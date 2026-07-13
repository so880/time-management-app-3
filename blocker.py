"""ゲームブロッカー（React + FastAPI 版に接続した独立ワーカー）。

「ゲーム解放条件」を満たしていない間、設定に登録されたプロセス
（ゲームの .exe）を検知して終了させ続ける。条件を満たすと自動で解除。

旧版（settings.json / session_state.json を読む）との違いは読み取り先だけで、
判定ロジック・監視方式は同じ。SQLite（backend/data/focus_cafe.db）を
読み取り専用で2秒ごとに読み直すので、設定変更はワーカー再起動なしで反映される。

- 起動: python blocker.py（通常は start_all.bat が自動で起動する）
- 停止: Ctrl + C（またはウィンドウを閉じる）
"""
import json
import sqlite3
import time
from datetime import date, datetime, time as dtime
from pathlib import Path

import psutil

DB_FILE = Path(__file__).resolve().parent / "backend" / "data" / "focus_cafe.db"
CHECK_INTERVAL_SEC = 2  # 監視間隔


def read_db():
    """SQLite から設定と今日の状態を読む。失敗時は None（＝何もしない側に倒す）。

    読み取り専用モード（mode=ro）で開くので、本体の書き込みを妨げない。
    """
    try:
        con = sqlite3.connect(f"file:{DB_FILE.as_posix()}?mode=ro", uri=True, timeout=1)
        try:
            cur = con.execute(
                "SELECT key, value FROM settings WHERE key IN ('block_enabled', 'block_process_list')"
            )
            settings = {k: json.loads(v) for k, v in cur.fetchall()}
            row = con.execute(
                "SELECT target_date, study_time_total, target_value FROM daily_state WHERE id = 1"
            ).fetchone()
            return settings, row
        finally:
            con.close()
    except Exception:
        return None


def is_game_unlocked(row):
    """ゲーム解放条件（すべて満たすと解放）。1つでも欠ければ未解放=ブロック対象。

    backend/app/logic.py の is_game_unlocked と同じ3条件（20:00〜翌2:59）。
    """
    if row is None:
        return False
    target_date, study, target = row
    # 1. 日付ガード：古い進捗データでは解放しない（必ずブロック側）
    if target_date != date.today().isoformat():
        return False
    # 2. 今日の勉強が今日の目標以上
    if int(study or 0) < int(target or 180):
        return False
    # 3. 20:00〜翌2:59 の時間帯（日またぎ）
    now = datetime.now().time()
    return now >= dtime(20, 0) or now < dtime(3, 0)


def kill_blocked(blocked_names_lower):
    """ブロック対象プロセスを終了させる。名前は大文字小文字を無視して比較。"""
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            name = proc.info.get("name")
            if name and name.lower() in blocked_names_lower:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except psutil.TimeoutExpired:
                    proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        except Exception:
            # 想定外でもループは絶対に落とさない
            continue


def main():
    print("ゲームブロッカーを起動しました（React版DBを監視）。停止は Ctrl + C。")
    print(f"監視対象DB: {DB_FILE}")
    while True:
        data = read_db()
        if data is not None:
            settings, row = data
            if settings.get("block_enabled", True) and not is_game_unlocked(row):
                names = settings.get("block_process_list", []) or []
                blocked = {str(n).strip().lower() for n in names if str(n).strip()}
                if blocked:
                    kill_blocked(blocked)
        time.sleep(CHECK_INTERVAL_SEC)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nゲームブロッカーを停止しました。")
