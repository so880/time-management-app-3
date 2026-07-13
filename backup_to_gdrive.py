# -*- coding: utf-8 -*-
"""C:\\新しいフォルダー（最新版）→ Googleドライブへのバックアップ同期。

- ソースコード・バッチ・README・データ（記録DB含む）をコピーする
- node_modules / venv / __pycache__ は除外（数万ファイル・再生成可能なため）
- 記録DB（SQLite）は動作中でも安全な公式バックアップAPIでコピーする
- Gドラ側に残っている古い node_modules / venv は削除して軽量化する

実行: backup_to_gdrive.bat をダブルクリック（いつでも何度でもOK）
"""
import shutil
import sqlite3
from pathlib import Path

SRC = Path(__file__).resolve().parent
# Gドラのフォルダは「Life_Management_App」に改名済み（2026-07-07）
DST = Path(r"G:\マイドライブ\成果物\Life_Management_App")
IGNORE = shutil.ignore_patterns(
    "node_modules", "venv", "__pycache__", ".pytest_cache", "*.db")


def main():
    if not DST.parent.exists():
        print("Googleドライブ（G:）が見つかりません。同期アプリの起動を確認してください。")
        return

    # 1. Gドラ側の古い巨大フォルダを掃除（初期コピーの名残り）
    for p in (DST / "frontend" / "node_modules",
              DST / "backend" / "venv"):
        if p.exists():
            print(f"古い {p.name} を削除中…（数分かかることがあります）")
            shutil.rmtree(p, ignore_errors=True)

    # 2. ソース一式をコピー（上書き）
    print("ファイルをコピー中…")
    shutil.copytree(SRC, DST, ignore=IGNORE, dirs_exist_ok=True)

    # 3. 記録DBは安全なオンラインバックアップでコピー
    db = SRC / "backend" / "data" / "focus_cafe.db"
    if db.exists():
        (DST / "backend" / "data").mkdir(parents=True, exist_ok=True)
        src = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        dst = sqlite3.connect(str(DST / "backend" / "data" / "focus_cafe.db"))
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        print("記録DB（focus_cafe.db）もバックアップしました。")

    print()
    print("=" * 44)
    print(f" BACKUP COMPLETE → {DST}")
    print("=" * 44)
    print("※ Gドラ側は保管用です。別PCで動かすときはコピー後に setup.bat を実行してください。")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("エラーが発生しました:", e)
    input("Press Enter to close...")
