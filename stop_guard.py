# -*- coding: utf-8 -*-
"""stop_all のゲート：制限中は本人の一存では解除できない（AI 審査）。

- ゲーム制限（目標未達 or 時間帯外）とサイト制限（必須タスク未完了）を確認
- どちらかが「まだ制限中」なら、60文字以上の理由と時間帯を本体（/api/gate/emergency_unlock）へ送り、
  Gemini の審査官が「事実かつ必要」と判断した場合だけ、その時間帯だけ解除される
- 本体が止まっている／Gemini キーが無いときは申請できない＝解除されない
- DB が読めない・本体の判定が古いときは「制限中」として扱う（判定は backend/app/policy.py で共通）
- 申請と結果は本体の設定 emergency_unlocks と logs/emergency_unlock.log の両方に残る
- すべて解放済み／制限オフの日は、そのまますぐ止まる

stop_all.bat から呼ばれる。単独実行も可。
"""
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

import appctl

sys.path.insert(0, str(appctl.BACKEND_DIR))
from app import policy  # noqa: E402  ワーカーと同じ解放判定

LOG_FILE = appctl.LOGS / "emergency_unlock.log"
SETTING_KEYS = ("block_enabled", "block_off_date", "site_block_enabled", "site_block_off_date",
                "emergency_unlock_day", "gate_today")


def read_state():
    """(ゲームが制限中か, サイトが制限中か)。DB が読めないときは両方「制限中」（安全側）"""
    s = appctl.read_settings(SETTING_KEYS)
    if s is None:
        return True, True
    game_blocked = policy.block_active(s, "game") and not policy.worker_unlocked(s, "game")
    site_blocked = policy.block_active(s, "site") and not policy.worker_unlocked(s, "site")
    return game_blocked, site_blocked


def request_unlock(reason, gates, start, end):
    """解除申請を本体（AI審査）に送る。戻り値 (approved, message)。
    本体が止まっている・Geminiキーが無い → 申請できない（＝解除されない）"""
    try:
        body = json.dumps({"reason": reason, "gates": gates, "start": start, "end": end}).encode("utf-8")
        req = urllib.request.Request(appctl.backend_url() + "/api/gate/emergency_unlock", data=body,
                                     headers={"Content-Type": "application/json"},
                                     method="POST")
        with urllib.request.urlopen(req, timeout=60) as r:
            res = json.loads(r.read().decode("utf-8"))
        return bool(res.get("approved")), str(res.get("judge") or "")
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8")).get("detail", "")
        except Exception:
            detail = str(e)
        return False, f"受け付けられません：{detail}"
    except Exception as e:
        return False, f"本体に接続できません（本体が動いていないと解除申請はできません）: {type(e).__name__}"


def write_log(line_text):
    """申請の結果をファイルにも残す（本体側の記録とは別に、自分で見返す用）"""
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {line_text}\n"
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


def kill_all(everything=False, keep_locks=False):
    """止める対象を選んで停止する（Life_app のプロセスだけ。判定は appctl で launcher と共通）。

    - 既定（everything=False）：ロックだけ＝ blocker.py と site_blocker.py。
      小窓・バックエンド・画面・PCトラッカーはそのまま動き続ける。
    - everything=True（stop_all.bat all）：本体・画面・小窓・記録ワーカーも止める。
      見守りタスクが本体を起こし直さないよう、runtime.json に「本人が止めた」と残す（start_all で消える）
    - keep_locks=True：制限中なので blocker / site_blocker は残す
    """
    log = "launcher.log"
    if everything:
        appctl.write_runtime(stopped_by_user=True)
        appctl.stop_scripts((appctl.WIDGET, "pc_tracker.py", "webcam_worker.py"), log)
        appctl.stop_frontend(log)
        appctl.stop_backend(log)
    if not keep_locks:
        appctl.stop_scripts(appctl.LOCK_WORKERS, log)


def main():
    args = [a.lower() for a in sys.argv[1:]]
    if "check_only" in args:
        # uninstall_guard_task.bat 用：制限中なら終了コード1（何も止めない）
        g, s_ = read_state()
        sys.exit(1 if (g or s_) else 0)
    everything = "all" in args
    what = "アプリ全体" if everything else "ゲーム・サイトのロック（小窓や画面は残ります）"
    game_blocked, site_blocked = read_state()
    if not game_blocked and not site_blocked:
        print(f"制限はすべて解放済み（またはオフ）です。{what}を停止します...")
        kill_all(everything)
        print("停止しました。ゲーム・サイトの制限もありません。")
        time.sleep(2)
        return

    gates = "+".join(x for x, b in (("game", game_blocked), ("site", site_blocked)) if b)
    print("=" * 60)
    if game_blocked:
        print(" 🎮 ゲーム制限がまだ有効です（ノルマ未完了・勉強目標未達・時間帯外のいずれか）")
    if site_blocked:
        print(" 🔒 サイト制限がまだ有効です（今日の必須タスク・習慣が未完了）")
    print("")
    print(" 制限中は、あなた一人の判断では解除できません。")
    print(" 解除が本当に必要なら、何時から何時まで・何のために必要かを60文字以上で書いて申請してください。")
    print(" AI の審査官が審査し、事実かつ必要と判断した場合だけ、その時間帯だけ解除されます。")
    print(" （申請内容と結果はすべて記録され、アプリの「制限」タブで見られます）")
    print(" 申請せずにロック以外だけ止める場合は s、やめる場合は q を入力してください。")
    print("=" * 60)
    while True:
        try:
            reason = input(" 解除理由 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n 中止しました。制限はそのまま動き続けます。")
            time.sleep(2)
            return
        if reason.lower() == "q":
            print(" 中止しました。制限はそのまま動き続けます。")
            time.sleep(2)
            return
        if reason.lower() == "s":
            if everything:
                print(" ロック（ゲーム・サイト制限）以外を停止します...")
                kill_all(True, keep_locks=True)
                print(" 停止しました。制限は動き続けています。")
            else:
                print(" ロック以外に止めるものがありません。")
            time.sleep(2)
            return
        if len(reason) < 60:
            print(f" !! 短すぎます（{len(reason)}文字）。60文字以上で、何が・いつ・なぜ必要かを書いてください。")
            continue
        break
    def ask_time(label):
        while True:
            try:
                v = input(f" {label}（HH:MM）> ").strip()
            except (EOFError, KeyboardInterrupt):
                return None
            if v.lower() == "q":
                return None
            try:
                h, m = v.split(":")
                if 0 <= int(h) <= 23 and 0 <= int(m) <= 59:
                    return f"{int(h):02d}:{int(m):02d}"
            except ValueError:
                pass
            print(" !! 例：14:00 のように入力してください")
    start = ask_time("解除の開始時刻")
    end = ask_time("解除の終了時刻") if start else None
    if not start or not end:
        print(" 中止しました。制限はそのまま動き続けます。")
        time.sleep(2)
        return
    print(" 審査中です…（最大1分）")
    approved, msg = request_unlock(reason, gates, start, end)
    write_log(f"gates={gates} {start}-{end} approved={approved} judge={msg} reason={reason}")
    if not approved:
        print(f" ✖ 却下されました：{msg}")
        print(" 制限はそのまま動き続けます。")
        time.sleep(4)
        return
    print(f" ✔ 承認されました：{msg}")
    print(f" {start}〜{end} の間だけ解除されます（ワーカーは動いたまま、その時間帯は見送ります）。")
    if everything:
        kill_all(True, keep_locks=True)
    print(" 停止しました。明日はやろう。")
    time.sleep(2)


if __name__ == "__main__":
    main()
