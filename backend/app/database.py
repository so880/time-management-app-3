"""DBアクセス層（接続部分）。

FastAPI公式ドキュメントの「SQL (Relational) Databases」の構成に準拠。
ここだけを書き換えれば、将来 SQLite → PostgreSQL に差し替えられる
（DATABASE_URL を postgresql:// に変え、engine の connect_args を外すだけ）。
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import DB_FILE

# SQLite のデータベースURL（ファイル1個）
SQLALCHEMY_DATABASE_URL = "sqlite:///" + DB_FILE.as_posix()

# check_same_thread=False は SQLite + FastAPI の公式推奨設定
# （複数リクエストから同じ接続を使えるようにする。SQLite のみ必要）
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
)

# セッション（DBとの会話1回分）の工場
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """全テーブル定義（models.py）の親クラス"""
    pass


def get_db():
    """FastAPI の Depends で使う、リクエストごとのDBセッション"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
