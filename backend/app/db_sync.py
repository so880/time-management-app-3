"""PC間のデータ共有（DBの自動プッシュ）。

仕組み（既存の C5 の仕組みを自動化したもの）：
- push（このモジュール）: 5分おきにDBが変わっていたら、SQLite公式の
  バックアップAPIで Gドライブ（Life_Management_App/backend/data）へコピーする。
  → 使い終わるたびに backup_to_gdrive.bat を手で実行しなくても、
    入力した内容が自動でGドライブに載る。
- pull（sync_db_pull.py・起動時）: もう一方のPCで start_all.bat を実行すると、
  Gドライブ側が新しければ確認のうえ取り込まれる。

前提：2台で「同時に」使わない（後から書いた方の内容が残る）。
Gドライブが無いPC（G: が繋がっていない等）では何もしない。
"""
import sqlite3
import time
from pathlib import Path

LOCAL_DB = Path(__file__).resolve().parent.parent / "data" / "focus_cafe.db"
REMOTE_DB = Path(r"G:\マイドライブ\成果物\Life_Management_App") / "backend" / "data" / "focus_cafe.db"
PUSH_SECONDS = 300  # チェック間隔（5分）


def push_once() -> bool:
    """ローカルDBをGドライブへコピーする（整合性を保つ公式バックアップAPI使用）"""
    if not LOCAL_DB.exists():
        return False
    REMOTE_DB.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(f"file:{LOCAL_DB.as_posix()}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(str(REMOTE_DB))
        try:
            with dst:
                src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return True


def push_loop() -> None:
    """バックグラウンド：DBが更新されていたら自動でGドライブへプッシュする"""
    time.sleep(60)  # 起動直後（pull直後）は落ち着くまで待つ
    last_pushed_mtime = 0.0
    while True:
        try:
            # Gドライブ自体が無い環境（未接続など）では静かに何もしない
            if REMOTE_DB.drive and not Path(REMOTE_DB.drive + "\\").exists():
                time.sleep(PUSH_SECONDS)
                continue
            if LOCAL_DB.exists():
                m = LOCAL_DB.stat().st_mtime
                if m > last_pushed_mtime:
                    push_once()
                    last_pushed_mtime = m
        except Exception as e:
            print("[db_sync] 自動プッシュに失敗（次回また試します）:", e)
        time.sleep(PUSH_SECONDS)
