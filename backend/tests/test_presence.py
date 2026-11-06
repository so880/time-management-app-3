"""📷 Webカメラ在席判定（F22）のテスト。インメモリSQLite＋一時フォルダ。実データ・実カメラには触れない。"""
from datetime import date, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import crud, models, presence_api, todo_api


@pytest.fixture()
def db(tmp_path, monkeypatch):
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    # 記録ファイルは一時フォルダへ（logs/presence を汚さない）
    monkeypatch.setattr(presence_api, "PRESENCE_DIR", tmp_path / "presence")
    monkeypatch.setattr(presence_api, "WEBCAM_DIR", tmp_path / "webcam")
    presence_api._cache.update({"date": "", "data": None})
    yield s
    s.close()


def _today():
    return date.today().isoformat()


def _habit(db, title="SPI", start="10:00", end="11:00"):
    wd = ",".join(str(i) for i in range(7))
    it = models.TodoItem(kind="habit", title=title, weekdays=wd, start=start, end=end, enabled=True,
                         created=(date.today() - timedelta(days=3)).isoformat() + " 00:00:00")
    db.add(it)
    db.commit()
    return it


def _fill(day, start_hm, n, status="P"):
    data = presence_api.load_day(day)
    sh, sm = [int(x) for x in start_hm.split(":")]
    for i in range(n):
        m = sh * 60 + sm + i
        data["minutes"][f"{m // 60:02d}:{m % 60:02d}"] = status
    presence_api.save_day(day, data)


# ---------- 分の記録と統計 ----------
def test_record_sample_any_present_in_minute_wins(db):
    now = datetime(2026, 11, 2, 10, 5, 3)
    presence_api.record_sample(False, now)
    presence_api.record_sample(True, now.replace(second=40))
    presence_api.record_sample(False, now.replace(second=55))
    data = presence_api.load_day("2026-11-02")
    assert data["minutes"]["10:05"] == "P"


def test_window_stats_ignores_unmonitored_minutes(db):
    day = "2026-11-02"
    _fill(day, "10:00", 30, "P")
    _fill(day, "10:30", 10, "A")
    st = presence_api.window_stats(presence_api.load_day(day), "10:00", "11:00")
    assert st == {"total_min": 60, "monitored_min": 40, "present_min": 30, "absent_min": 10, "rate": 75}


def test_window_stats_across_midnight(db):
    day = "2026-11-02"
    _fill(day, "23:50", 10, "P")
    st = presence_api.window_stats(presence_api.load_day(day), "23:50", "00:10")
    assert st["total_min"] == 20 and st["present_min"] == 10


# ---------- 在席率で習慣が完了する ----------
def test_habit_completes_when_present_minutes_reach_threshold(db):
    it = _habit(db)
    crud.set_setting(db, "presence_enabled", True)
    db.commit()
    day = _today()
    _fill(day, "10:00", 41, "P")   # 70% of 60 = 42 が必要
    assert presence_api.complete_habits_by_presence(db) == []
    _fill(day, "10:41", 1, "P")
    assert presence_api.complete_habits_by_presence(db) == ["SPI"]
    db.commit()
    row = db.execute(select(models.TodoCompletion).where(models.TodoCompletion.item_id == it.id)).scalars().first()
    assert row is not None and row.level == "full" and row.date == day
    # 2回目は何もしない（二重登録なし）
    assert presence_api.complete_habits_by_presence(db) == []
    spi = [h for h in todo_api.todo_today(db)["habits"] if h["title"] == "SPI"][0]
    assert spi["done"] is True and spi["at"] != ""


def test_presence_disabled_never_completes(db):
    _habit(db)
    _fill(_today(), "10:00", 60, "P")
    assert presence_api.complete_habits_by_presence(db) == []


def test_off_camera_habit_ignores_presence_but_timer_min_minutes_works(db):
    it = _habit(db, title="筋トレ", start="07:00", end="08:00")
    crud.set_setting(db, "presence_enabled", True)
    db.commit()
    # 画角外・最低20分（初回設定＝弱める方向なので「翌日から」。prev は既定＝時間帯の長さ）
    res = presence_api.set_habit_option(db, _hitem(db, "筋トレ"), True, 20, 60)
    db.commit()
    assert res["off_camera"] is False and res["pending"] == {"off_camera": True, "min_minutes": 20, "record_only": False, "camera_off": False}
    # 今日はまだ時間帯の長さ（60分）が必要
    assert todo_api.habit_need_minutes(db, it) == 60
    assert todo_api.auto_complete_habit_by_study(db, "筋トレ", 20) == "min"
    # 翌日になった想定：since を今日にする
    opts = crud.get_all_settings(db)["habit_options"]
    opts[_hid(db, "筋トレ")]["since"] = _today()
    crud.set_setting(db, "habit_options", opts)
    db.commit()
    assert todo_api.habit_need_minutes(db, it) == 20
    _fill(_today(), "07:00", 60, "P")
    assert presence_api.complete_habits_by_presence(db) == []   # 画角外は在席率で完了しない
    assert todo_api.auto_complete_habit_by_study(db, "筋トレ", 20) == "full"


def test_off_camera_floor_and_stronger_change_is_immediate(db):
    _habit(db, title="筋トレ", start="07:00", end="08:00")
    with pytest.raises(HTTPException) as e:
        presence_api.set_habit_option(db, _hitem(db, "筋トレ"), True, 5, 60)
    assert e.value.status_code == 400
    presence_api.set_habit_option(db, _hitem(db, "筋トレ"), True, 30, 60)
    opts = crud.get_all_settings(db)["habit_options"]
    opts[_hid(db, "筋トレ")]["since"] = _today()
    crud.set_setting(db, "habit_options", opts)
    db.commit()
    # 長くする（強める）方向は即日
    res = presence_api.set_habit_option(db, _hitem(db, "筋トレ"), True, 45, 60)
    assert res == {"off_camera": True, "min_minutes": 45, "record_only": False, "camera_off": False}
    # 画角外をやめる（強める）も即日
    res = presence_api.set_habit_option(db, _hitem(db, "筋トレ"), False, 0, 60)
    assert res == {"off_camera": False, "min_minutes": 0, "record_only": False, "camera_off": False}


def test_rate_min_lowering_applies_tomorrow(db):
    assert presence_api.presence_config(db)["rate_min"] == 70
    presence_api.set_config(presence_api.ConfigBody(presence_rate_min=60), db)
    cfg = presence_api.presence_config(db)
    assert cfg["rate_min"] == 70 and cfg["rate_min_pending"] == 60
    presence_api.set_config(presence_api.ConfigBody(presence_rate_min=90), db)
    assert presence_api.presence_config(db)["rate_min"] == 90
    with pytest.raises(HTTPException):
        presence_api.set_config(presence_api.ConfigBody(presence_rate_min=30), db)


# ---------- 監視する時間帯 ----------
def test_monitor_state_respects_hours_class_and_enabled(db):
    crud.set_setting(db, "presence_enabled", True)
    db.commit()
    today = date.today()
    from app import life_api
    wd = life_api.day_info(db, today.isoformat())["effective_weekday"]  # 祝日・振替でも授業が出るように
    db.add(models.ScheduleBlock(weekday=wd, start="13:00", end="14:30", title="OS", category="大学", enabled=True))
    db.commit()
    mk = lambda h, m: datetime(today.year, today.month, today.day, h, m)  # noqa: E731
    assert presence_api.monitor_state(db, mk(6, 30))["reason"] == "outside"
    assert presence_api.monitor_state(db, mk(21, 0))["reason"] == "outside"
    st = presence_api.monitor_state(db, mk(13, 30))
    assert st["reason"] == "class" and st["camera_ok"] is False
    st = presence_api.monitor_state(db, mk(10, 0))
    assert st["monitor"] is True and st["camera_ok"] is True
    crud.set_setting(db, "presence_enabled", False)
    db.commit()
    st = presence_api.monitor_state(db, mk(10, 0))
    assert st["monitor"] is False and st["reason"] == "off" and st["camera_ok"] is True


def test_day_summary_and_week(db):
    _habit(db)
    crud.set_setting(db, "presence_enabled", True)
    db.commit()
    day = _today()
    _fill(day, "10:00", 20, "P")
    _fill(day, "10:20", 20, "A")
    s = presence_api.day_summary(db, day)
    assert s["rate"] == 50 and s["present_min"] == 20
    assert s["habits"][0]["title"] == "SPI" and s["habits"][0]["need_min"] == 42
    assert s["blocks"][0] == {"status": "P", "start": "10:00", "end": "10:20", "minutes": 20}
    w = presence_api.week_summary(db, day)
    assert len(w) == 7 and w[-1]["date"] == day and w[-1]["rate"] == 50


# ---------- 📷 カメラ確認（画面の「カメラを確認する」） ----------
def test_camera_test_roundtrip(db):
    presence_api._cam.update({"test_requested": 0.0, "last": None})
    assert presence_api.get_config(db)["camera"]["test_pending"] is False
    presence_api.camera_test()
    assert presence_api.get_config(db)["camera"]["test_pending"] is True
    presence_api.camera_result(presence_api.CameraResultBody(ok=True, brightness=2.0, faces=0, width=640, height=480, backend="DSHOW"))
    c = presence_api.get_config(db)["camera"]
    assert c["test_pending"] is False and c["last"]["brightness"] == 2.0
    assert "真っ暗" in c["note"]
    presence_api.camera_result(presence_api.CameraResultBody(ok=True, brightness=90.0, faces=1))
    assert "正常" in presence_api.get_config(db)["camera"]["note"]
    presence_api.camera_result(presence_api.CameraResultBody(ok=False, error="x"))
    assert "開けません" in presence_api.get_config(db)["camera"]["note"]


# ---------- 「記録だけ」の習慣（F23・2026-11-02） ----------
def _no_defaults(db):
    """テスト用：todo_today が既定のやることを入れないようにする"""
    crud.set_setting(db, "todo_v1_migrated", True)
    db.commit()


def _hid(db, title):
    """習慣の番号（habit_options のキー）"""
    return str(db.query(models.TodoItem).filter_by(kind="habit", title=title).one().id)


def _hitem(db, title):
    return db.query(models.TodoItem).filter_by(kind="habit", title=title).one()


def _set_record_only(db, title, value=True):
    """テスト用：since を使わず即日で record_only を入れる"""
    opts = dict(crud.get_all_settings(db).get("habit_options") or {})
    opts[_hid(db, title)] = {"off_camera": False, "min_minutes": 0, "record_only": value}
    crud.set_setting(db, "habit_options", opts)
    db.commit()


def test_record_only_habit_not_in_tasks_done(db):
    _no_defaults(db)
    _habit(db, title="筋トレ", start="05:30", end="07:00")
    spi = _habit(db, title="SPI", start="", end="")
    td = todo_api.todo_today(db)
    assert td["tasks_done"] is False and set(td["remaining"]) == {"筋トレ", "SPI"}
    _set_record_only(db, "筋トレ")
    td = todo_api.todo_today(db)
    h = {x["title"]: x for x in td["habits"]}
    assert h["筋トレ"]["record_only"] is True and h["SPI"]["record_only"] is False
    assert td["remaining"] == ["SPI"]          # 記録だけの習慣は残りに入らない
    assert td["tasks_done"] is False           # SPI が未完了
    # SPI を完了にすると、筋トレが未完了でも tasks_done は True
    db.add(models.TodoCompletion(item_id=spi.id, date=_today(), at="10:00", level="full"))
    db.commit()
    assert todo_api.todo_today(db)["tasks_done"] is True


def test_record_only_habit_can_be_checked_but_normal_habit_is_423(db):
    _no_defaults(db)
    kin = _habit(db, title="筋トレ", start="05:30", end="07:00")
    spi = _habit(db, title="SPI", start="", end="")
    _set_record_only(db, "筋トレ")
    td = todo_api.check_item(todo_api.CheckBody(item_id=kin.id, done=True), db)
    assert {x["title"]: x["checked"] for x in td["habits"]}["筋トレ"] is True
    with pytest.raises(HTTPException) as e:
        todo_api.check_item(todo_api.CheckBody(item_id=spi.id, done=True), db)
    assert e.value.status_code == 423
    # 取り消しは従来どおり誰でも可
    td = todo_api.check_item(todo_api.CheckBody(item_id=kin.id, done=False), db)
    assert {x["title"]: x["checked"] for x in td["habits"]}["筋トレ"] is False


def test_record_only_change_applies_tomorrow_and_put_accepts_it(db):
    _no_defaults(db)
    _habit(db, title="筋トレ", start="05:30", end="07:00")
    res = presence_api.set_habit_option(db, _hitem(db, "筋トレ"), False, 0, 90, record_only=True)
    db.commit()
    # 解放条件を減らす方向なので翌日から（今日はまだ record_only=False）
    assert res["record_only"] is False and res["pending"]["record_only"] is True
    assert todo_api.todo_today(db)["tasks_done"] is False
    opts = crud.get_all_settings(db)["habit_options"]
    opts[_hid(db, "筋トレ")]["since"] = _today()
    crud.set_setting(db, "habit_options", opts)
    db.commit()
    assert presence_api.is_record_only(db, _hitem(db, "筋トレ")) is True
    assert todo_api.todo_today(db)["tasks_done"] is True
    # 記録だけ をやめる（強める）は即日
    res = presence_api.set_habit_option(db, _hitem(db, "筋トレ"), False, 0, 90, record_only=False)
    assert res == {"off_camera": False, "min_minutes": 0, "record_only": False, "camera_off": False}


def test_record_only_habit_has_no_habit_lock(db, monkeypatch):
    _no_defaults(db)
    _habit(db, title="筋トレ", start="00:00", end="23:59")
    _set_record_only(db, "筋トレ")
    from app import gate_api
    monkeypatch.setattr(gate_api, "current_exemption", lambda db, now: None)
    assert todo_api.current_habit(db)["habit"] is None
    _set_record_only(db, "筋トレ", False)
    assert todo_api.current_habit(db)["habit"]["title"] == "筋トレ"


# ---------- カメラ強制オフ（AI面接の練習・面接の前後60分。2026-11-03） ----------
def test_camera_off_for_habit_and_around_interview_event(db, monkeypatch):
    _no_defaults(db)
    crud.set_setting(db, "presence_enabled", True)
    _habit(db, title="AI面接の練習", start="07:30", end="08:00")
    presence_api.set_habit_option(db, _hitem(db, "AI面接の練習"), False, 0, 30, camera_off=True)
    _habit(db, title="SPI", start="09:00", end="10:00")
    db.add(models.LifeEvent(date="2026-11-04", start="14:00", end="15:00", title="A社 二次面接", category="就活"))
    db.commit()
    from app import gate_api
    monkeypatch.setattr(gate_api, "current_exemption", lambda db, now: None)
    monkeypatch.setattr(presence_api, "class_blocks", lambda db, day: [])
    wins = presence_api.camera_off_windows(db, "2026-11-04")
    assert [(w["start"], w["end"], w["source"]) for w in wins] == [("07:30", "08:00", "habit"), ("13:00", "16:00", "event")]
    st = presence_api.monitor_state(db, datetime(2026, 11, 4, 7, 45))
    assert st["camera_ok"] is False and st["monitor"] is False and st["reason"] == "camera_off"
    st = presence_api.monitor_state(db, datetime(2026, 11, 4, 13, 10))
    assert st["reason"] == "camera_off" and "面接" in st["label"]
    st = presence_api.monitor_state(db, datetime(2026, 11, 4, 9, 30))
    assert st["camera_ok"] is True and st["monitor"] is True
    # camera_off は即日有効（弱める扱いではない）
    assert presence_api.habit_option(db, _hitem(db, "AI面接の練習"))["camera_off"] is True
    # カメラを止めても在席率の必要分は時間帯の長さで計算される＝ただで完了にはならない
    assert presence_api.complete_habits_by_presence(db, datetime(2026, 11, 4, 8, 0)) == []
