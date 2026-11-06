"""ローカル日次バックアップ（外部送信なし）。

backend/data/backups/focus_cafe_YYYY-MM-DD.db を1日1回作り、直近 KEEP 世代だけ残す。
SQLite 公式のバックアップ API（Connection.backup）を使うので、使用中でも整合性が保たれる。
Gドライブへの同期は 2026-11 に廃止（デスクトップ1台・本人のみの利用）。
"""
import sqlite3
import time
from datetime import date
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
LOCAL_DB = DATA_DIR / "focus_cafe.db"
BACKUP_DIR = DATA_DIR / "backups"
KEEP = 7
CHECK_SECONDS = 3600


def backup_once() -> Path | None:
    """今日の分が無ければ作る。作ったファイルのパス（既にあれば None）"""
    if not LOCAL_DB.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    dst_path = BACKUP_DIR / f"focus_cafe_{date.today().isoformat()}.db"
    if dst_path.exists():
        return None
    src = sqlite3.connect(f"file:{LOCAL_DB.as_posix()}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(str(dst_path))
        try:
            with dst:
                src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    # 古い世代を消す
    files = sorted(BACKUP_DIR.glob("focus_cafe_*.db"))
    for old in files[:-KEEP]:
        try:
            old.unlink()
        except OSError:
            pass
    return dst_path


def backup_loop() -> None:
    time.sleep(120)
    while True:
        try:
            backup_once()
        except Exception as e:
            print("[local_backup] 失敗（次回また試します）:", e)
        time.sleep(CHECK_SECONDS)
