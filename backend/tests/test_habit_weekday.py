"""習慣は暦どおりの曜日で出る（祝日・振替で変わるのは時間割だけ。2026-11-03 依頼者の決定）"""
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import crud, life_api, models, todo_api


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    crud.set_setting(s, "todo_v1_migrated", True)
    s.commit()
    yield s
    s.close()


def test_habit_follows_real_weekday_even_on_override_holiday(db):
    # 2026-11-03（火・文化の日）に「月〜金」の習慣と「土日」の習慣
    day = "2026-11-03"
    created = (date(2026, 11, 3) - timedelta(days=3)).isoformat() + " 00:00:00"
    db.add(models.TodoItem(kind="habit", title="筋トレ", weekdays="0,1,2,3,4", start="05:30", end="07:00",
                           enabled=True, created=created))
    db.add(models.TodoItem(kind="habit", title="AI面接の練習(土日)", weekdays="5,6", start="05:00", end="05:30",
                           enabled=True, created=created))
    # 手動で「休み扱い（土曜日程）」にしても、習慣は火曜のまま
    db.add(models.DayOverride(date=day, mode="holiday", weekday=None))
    db.commit()
    assert life_api.day_info(db, day)["effective_weekday"] == 5   # 時間割は土曜日程
    titles = [it.title for it in todo_api.habits_for_date(db, day)]
    assert titles == ["筋トレ"]
    assert todo_api._habit_weekday(db, day) == 1
