"""今日の状態（日付またぎのリセット）と、今日の勉強時間（activity_log の合計）のテスト。
インメモリSQLiteを使うので、実データには一切影響しない。
"""
import json
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import crud, models


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")  # インメモリ
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_first_access_creates_today_state(db):
    row = crud.get_or_create_state(db)
    assert row.target_date == date.today().isoformat()
    assert crud.state_to_dict(row)["study_time_total"] == 0
    assert row.target_value == 180
    assert row.target_locked is False


def test_date_rollover_resets_partial_keys(db):
    # 前日の状態：目標確定済み・抽選結果あり・ページは active
    db.add(models.DailyState(
        id=1, target_date="2020-01-01", page="active",
        current_task=json.dumps({"タスク": "残タスク"}, ensure_ascii=False),
        target_value=240, target_locked=True,
        last_was_refresh=True, force_study_only=True,
        rolled_options=json.dumps({"勉強": "A"}, ensure_ascii=False),
    ))
    db.commit()

    row = crud.get_or_create_state(db)

    assert row.target_date == date.today().isoformat()
    assert row.target_value == 180
    assert row.target_locked is False
    assert row.last_was_refresh is False
    assert row.force_study_only is False
    assert row.rolled_options is None
    # 保持されるもの（ページ・実行中タスクは復元される）
    assert row.page == "active"
    assert json.loads(row.current_task)["タスク"] == "残タスク"


def test_same_day_does_not_reset(db):
    today = date.today().isoformat()
    db.add(models.DailyState(id=1, target_date=today, target_value=200, target_locked=True))
    db.commit()
    row = crud.get_or_create_state(db)
    assert row.target_value == 200
    assert row.target_locked is True


def test_study_minutes_come_from_logs(db):
    today = date.today().isoformat()
    yday = (date.today() - timedelta(days=1)).isoformat()
    for when, cat, m in ((f"{today} 09:00:00", "勉強", 30), (f"{today} 10:00:00", "勉強(短縮修了)", 10),
                         (f"{today} 11:00:00", "中断", 5), (f"{today} 12:00:00", "気分転換", 20),
                         (f"{yday} 23:59:59", "勉強", 40)):
        crud.add_log(db, when, cat, "x", "", m)
    db.commit()
    assert crud.study_minutes(db) == 45          # 勉強・短縮修了・中断（集中切れまで）を数える
    assert crud.refresh_minutes(db) == 20
    assert crud.study_minutes(db, yday) == 40
    assert crud.study_minutes_by_day(db, yday, today) == {yday: 40, today: 45}
    st = crud.state_to_dict(crud.get_or_create_state(db))
    assert st["study_time_total"] == 45 and st["refresh_time_total"] == 20
