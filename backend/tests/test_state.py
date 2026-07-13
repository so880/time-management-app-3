"""日付またぎリセット（既存 init_session の挙動）のテスト。

インメモリSQLiteを使うので、実データには一切影響しない。
"""
import json
from datetime import date

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
    assert row.study_time_total == 0
    assert row.target_value == 180
    assert row.target_locked is False


def test_date_rollover_resets_partial_keys(db):
    # 前日の状態：勉強済み・目標確定済み・抽選結果あり・ページは active
    db.add(models.DailyState(
        id=1, target_date="2020-01-01", page="active",
        current_task=json.dumps({"タスク": "残タスク"}, ensure_ascii=False),
        study_time_total=100, refresh_time_total=50,
        target_value=240, target_locked=True,
        last_was_refresh=True, force_study_only=True,
        rolled_options=json.dumps({"勉強": "A"}, ensure_ascii=False),
    ))
    db.commit()

    row = crud.get_or_create_state(db)

    # リセットされるもの（既存 state.py init_session と同じ）
    assert row.target_date == date.today().isoformat()
    assert row.study_time_total == 0
    assert row.refresh_time_total == 0
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
    db.add(models.DailyState(
        id=1, target_date=today, study_time_total=90,
        target_value=200, target_locked=True,
    ))
    db.commit()

    row = crud.get_or_create_state(db)
    assert row.study_time_total == 90
    assert row.target_value == 200
    assert row.target_locked is True
