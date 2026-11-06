"""F19 のテスト：日付またぎの分割／完了済み必須の再出現防止／起動画面の「終わった」／スマホ用一覧。

インメモリSQLiteを使うので、実データには一切影響しない。
"""
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import crud, gcal_sync, models, todo_api


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")  # インメモリ
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


# ---------- 日付またぎの分割 ----------
def test_split_same_day_is_single_part():
    end = datetime(2026, 9, 30, 15, 0).timestamp()
    parts = crud.split_minutes_by_day(end, 60)
    assert parts == [("2026-09-30 15:00:00", 60, "2026-09-30")]


def test_split_across_midnight():
    # 23:30 開始 → 0:45 終了（75分）＝ 前日30分＋当日45分
    end = datetime(2026, 10, 1, 0, 45).timestamp()
    parts = crud.split_minutes_by_day(end, 75)
    assert parts == [("2026-09-30 23:59:59", 30, "2026-09-30"),
                     ("2026-10-01 00:45:00", 45, "2026-10-01")]
    assert sum(p[1] for p in parts) == 75


def test_split_zero_minutes():
    end = datetime(2026, 10, 1, 0, 5).timestamp()
    parts = crud.split_minutes_by_day(end, 0)
    assert len(parts) == 1 and parts[0][1] == 0


# ---------- 完了済み必須の再出現防止 ----------
def _must(db, title, d):
    it = models.TodoItem(kind="must", title=title, date=d, enabled=True, created=d + " 00:00:00")
    db.add(it)
    db.flush()
    return it


def test_carry_over_skips_title_completed_later(db):
    today = date.today()
    d3 = (today - timedelta(days=3)).isoformat()
    d2 = (today - timedelta(days=2)).isoformat()
    d1 = (today - timedelta(days=1)).isoformat()
    _must(db, "面接の準備", d3)               # 元の日：未完了のまま
    later = _must(db, "面接の準備", d2)       # 繰り越した日：完了
    db.add(models.TodoCompletion(item_id=later.id, date=d2, at="10:00", level="full"))
    _must(db, "ES提出", d1)                   # 本当に未完了
    db.commit()
    titles = [r["title"] for r in todo_api.carry_over_rows(db, today.isoformat())]
    assert "面接の準備" not in titles
    assert "ES提出" in titles


def test_mark_carried_done_stops_carry_over(db):
    today = date.today()
    d1 = (today - timedelta(days=1)).isoformat()
    it = _must(db, "年金の手続き", d1)
    db.commit()
    assert "年金の手続き" in [r["title"] for r in todo_api.carry_over_rows(db, today.isoformat())]
    assert todo_api.mark_carried_done(db, [f"m{it.id}", "x", "m999"]) == 1
    todo_api.mark_carried_done(db, [f"m{it.id}"])  # 2回押しても一意制約で落ちない
    db.commit()
    comps = db.execute(select(models.TodoCompletion)
                       .where(models.TodoCompletion.item_id == it.id)).scalars().all()
    assert len(comps) == 1 and comps[0].date == d1
    assert "年金の手続き" not in [r["title"] for r in todo_api.carry_over_rows(db, today.isoformat())]


def test_mark_carried_done_assignment(db):
    a = models.Assignment(title="レポート", due_date=date.today().isoformat(), progress=0,
                          note="", category="大学", focus=False, enabled=True, created="")
    db.add(a)
    db.flush()
    assert todo_api.mark_carried_done(db, [f"a{a.id}"]) == 1
    assert a.progress == 100


# ---------- スマホ用ページの一覧 ----------
def test_build_phone_choices_shape(db):
    t = date.today().isoformat()
    m1 = _must(db, "必須A", t)
    _must(db, "必須B", t)
    db.add(models.TodoCompletion(item_id=m1.id, date=t, at="09:00", level="full"))
    db.add(models.Assignment(title="課題X", due_date=t, progress=10, note="", category="大学",
                             focus=False, enabled=True, created=""))
    db.add(models.LifeEvent(date=t, start="13:00", end="14:00", title="面談", category="予定"))
    db.commit()
    c = gcal_sync.build_phone_choices(db)
    assert c["date"] == t
    # （初回の移行で既定の必須が入ることがあるので、自分で入れた2件だけを見る）
    assert "必須B" in c["must"] and "必須A" not in c["must"]      # 未完了だけ（スタートの選択肢）
    done = {m["title"]: m["done"] for m in c["must_all"]}         # 一覧は完了も含む
    assert done["必須A"] is True and done["必須B"] is False
    assert c["due"][0]["title"] == "課題X" and c["due"][0]["left"] == 0
    assert c["events"][0]["title"] == "面談"
    assert "課題X" in c["roulette"]
