# -*- coding: utf-8 -*-
"""起動時のDB同期（PC間の受け渡し・pull側）。

Gドライブ（Life_Management_App）の focus_cafe.db が、このPCのものより
新しければ、確認のうえ取り込む。ノートPC⇄デスクトップで課題や記録を
引き継ぐための仕組み（push側は backup_to_gdrive.bat）。

前提：2台で同時にアプリを使わない（同時に使うと後からバックアップした方が勝つ）。
start_all.bat の先頭から自動で呼ばれる。
"""
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

LOCAL = Path(__file__).resolve().parent / "backend" / "data" / "focus_cafe.db"
REMOTE = Path(r"G:\マイドライブ\成果物\Life_Management_App") / "backend" / "data" / "focus_cafe.db"
MARGIN_SEC = 60  # この差以内なら「同じ」とみなす


def fmt(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%m/%d %H:%M")


def main():
    if not REMOTE.exists():
        return  # Gドラにまだ無ければ何もしない
    if not LOCAL.exists():
        print(f"ローカルにDBが無いため、Gドラの記録（{fmt(REMOTE.stat().st_mtime)}）を取り込みます。")
        LOCAL.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REMOTE, LOCAL)
        return

    r_m, l_m = REMOTE.stat().st_mtime, LOCAL.stat().st_mtime
    if r_m <= l_m + MARGIN_SEC:
        return  # ローカルが最新（または同等）→そのまま起動

    print("=" * 56)
    print(" Gドライブに、このPCより新しい記録があります。")
    print(f"   Gドラ側    : {fmt(r_m)} （別のPCで使った分と思われます）")
    print(f"   このPC側   : {fmt(l_m)}")
    print(" 取り込むと、このPCの記録はGドラの内容に置き換わります。")
    print(" （現在のDBは focus_cafe.db.bak として残します）")
    print("=" * 56)
    ans = input(" Gドラの記録を取り込みますか？ [y/N] > ").strip().lower()
    if ans != "y":
        print(" 取り込まずにこのPCの記録のまま起動します。")
        return
    shutil.copy2(LOCAL, LOCAL.with_suffix(".db.bak"))
    # コピーはSQLiteの整合性を保つ公式バックアップAPIで行う
    src = sqlite3.connect(f"file:{REMOTE.as_posix()}?mode=ro", uri=True)
    dst = sqlite3.connect(str(LOCAL))
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    print(" 取り込みました。")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("DB同期チェックでエラー（そのまま起動します）:", e)
