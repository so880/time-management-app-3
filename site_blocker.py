"""サイト閲覧制限ワーカー（blocker.py と同型：DBを読み取り専用で監視）。

「今日の必須タスク（🔒今日のノルマ）」が全部終わるまで、制限キーワードを
タイトルに含むウィンドウ（YouTube・マンガサイト等を開いたブラウザ）を
検知した瞬間に最小化し続ける。全部終わった時点で、その日は自由に閲覧できる。

- 解放条件は「今日の必須＋今日の習慣がすべて完了」。判定は本体（gate_api）が行い、
  結果 settings["gate_today"] をこのワーカーは読むだけ（読み方は backend/app/policy.py で本体と共通）
- DB が読めないときは前回読めた内容で続け、一度も読めていなければ制限する（安全側）
- 制限キーワードのON/OFF・編集はアプリの編集タブ「🔒 解放条件の設定」から
- 起動: start_all.bat が自動起動／停止: stop_all.bat（未達成時は理由入力が必要）

管理者権限は不要（hostsは触らない）。全ブラウザ・全アプリのウィンドウが対象。
"""
import ctypes
import re
import sys
import time
import unicodedata

import appctl

sys.path.insert(0, str(appctl.BACKEND_DIR))
from app import policy  # noqa: E402  本体と同じ解放判定（標準ライブラリだけのモジュール）

DB_FILE = appctl.DB_FILE
SETTING_KEYS = ("site_block_enabled", "site_block_off_date", "site_block_list", "emergency_unlock_day", "gate_today")
CHECK_INTERVAL_SEC = 2
# 設定に無くても常に対象にする（時間を溶かす定番。設定の一覧と合わせて判定）
BUILTIN_KEYWORDS = ["YouTube", "Prime Video", "プライム・ビデオ", "プライムビデオ", "Netflix", "Twitch",
                    "TikTok", "ニコニコ", "Abema", "Steam", "Shadowverse", "シャドウバース", "DMM GAMES"]
SW_MINIMIZE = 6
# 「YouTube」だけは部分一致にしない（2026-11-03 依頼者の指示）：
# NotebookLM などで「YouTube」を含む資料名・ノート名がウィンドウのタイトルに入ると最小化されてしまうため、
# 動画サイト本体のタブ（Chrome のタイトルが "〜 - YouTube" で終わる／"YouTube" で始まる＝トップ・YouTube Music・Studio）だけを対象にする。
# 他のキーワード（Prime Video・Netflix・設定の一覧）は従来どおり部分一致。
_YT_SEG = re.compile(r"^(\(\d+\)\s*)?youtube(\s|$)")   # "youtube" / "(3) youtube" / "youtube music" / "youtube studio"


def _is_youtube_tab(title: str) -> bool:
    # ウィンドウタイトルを " - " で区切った各部分が「YouTube」そのもの（または YouTube Music 等）なら動画サイト本体
    return any(_YT_SEG.match(seg.strip()) for seg in title.split(" - "))


def title_hits(title: str, keywords) -> bool:
    for k in keywords:
        if k == "youtube":
            if _is_youtube_tab(title):
                return True
        elif k in title:
            return True
    return False

user32 = ctypes.windll.user32


def foreground_title() -> str:
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ""
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def minimize_foreground():
    hwnd = user32.GetForegroundWindow()
    if hwnd:
        user32.ShowWindow(hwnd, SW_MINIMIZE)


def norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "").lower()


def main():
    print("サイト制限ワーカーを起動しました（必須タスク完了で解放）。")
    print(f"監視対象DB: {DB_FILE}")
    settings = {}   # 前回読めた設定（DB が一時的に読めないときに使う。最初は空＝制限する）
    while True:
        fresh = appctl.read_settings(SETTING_KEYS)
        if fresh is not None:
            settings = fresh
        try:
            if policy.block_active(settings, "site") and not policy.worker_unlocked(settings, "site"):
                custom = settings.get("site_block_list") or []
                if not isinstance(custom, list):
                    custom = []   # 設定が壊れていても既定のキーワードでは止め続ける
                keywords = [norm(str(k)) for k in list(custom) + BUILTIN_KEYWORDS if str(k).strip()]
                title = norm(foreground_title())
                if title and title_hits(title, keywords):
                    minimize_foreground()  # 見た瞬間に最小化（開けない）
        except Exception:
            # 想定外の値でワーカーごと落ちると、見守りタスクが起こすまで制限が外れるため、ループは止めない
            pass
        time.sleep(CHECK_INTERVAL_SEC)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nサイト制限ワーカーを停止しました。")
