"""2026-11-06 の監査で見つかった抜け道・不具合の修正のテスト。インメモリSQLite。

- 振り返りの「終わった」で、同じ名前の習慣が完了にならない（必須だけ）
- 「今日を始める」の日付（day_setup_date）は /api/settings から書き換えられない
- Google 連携の URL は Apps Script の公式の場所だけ。制限中は URL・合言葉を変えられない
- 緊急解除の申請：1日2回まで・却下後30分は申請できない・1回3時間まで
- カレンダーの予定による特例は1日合計4時間まで
- ゲームの場所にある exe は、名前を変えても止める（NEVER_BLOCK より優先）
- PC のタイムゾーンが日本時間でないときは解放しない
- 秘密の設定（API キーなど）は画面に返さない。空で送られたら変更しない
- /api/logs：1件の分数の上限・送り直しは「終わった時刻」の日付で記録
- 他のサイトからの書き込み（CSRF）と、localhost 以外の宛先ホスト（DNS リバインディング）を拒否
"""
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import crud, exemption_api, gate_api, gcal_sync, main, models, policy, schemas, todo_api, widget_sessions

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import blocker  # noqa: E402

TODAY = date.today().isoformat()
WD = date.today().weekday()


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    gate_api.ensure_gate_defaults(s)
    crud.set_setting(s, "todo_v1_migrated", True)
    crud.set_setting(s, "todo_v1_cleanup_done", True)
    s.add(models.TodoItem(kind="must", title="英語", date=TODAY, enabled=True, created=""))
    s.add(models.TodoItem(kind="habit", title="英語", weekdays=str(WD), start="10:00", end="11:00",
                          enabled=True, created=""))
    crud.set_setting(s, todo_api.DAY_SETUP_KEY, TODAY)
    s.commit()
    gate_api.gate_state(s)   # 未完了＝制限中
    yield s
    s.close()


def _done_kinds(db):
    rows = db.execute(select(models.TodoCompletion, models.TodoItem)
                      .join(models.TodoItem, models.TodoItem.id == models.TodoCompletion.item_id)).all()
    return sorted(item.kind for _c, item in rows)


# ---------- 振り返りの「終わった」 ----------
def test_complete_by_title_does_not_complete_same_named_habit(db):
    assert todo_api.complete_by_title(db, "英語", "full") is True
    db.commit()
    assert _done_kinds(db) == ["must"]


def test_review_finish_ignores_remove_flag_when_task_was_not_must(db):
    crud.update_state(db, {"pending_review": {"task": "英語", "cat": "勉強", "em": 1, "log_id": None,
                                              "end": time.time(), "mustdo": False},
                           "page": "review"})
    db.commit()
    main.review_finish(schemas.ReviewBody(save_details=False, remove_mustdo=True), db)
    assert _done_kinds(db) == []


# ---------- 設定の保護 ----------
def test_day_setup_date_is_protected(db):
    with pytest.raises(HTTPException) as e:
        gate_api.check_settings_change(db, {"day_setup_date": "2000-01-01"})
    assert e.value.status_code == 423


def test_gas_url_must_be_apps_script(db):
    with pytest.raises(HTTPException) as e:
        gate_api.check_settings_change(db, {"gas_url": "http://127.0.0.1:9999/fake"})
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        gate_api.check_settings_change(db, {"gas_url": "file:///C:/fake.json"})
    assert e.value.status_code == 400


def test_gas_settings_locked_while_restricted(db):
    for chg in ({"gas_url": "https://script.google.com/macros/s/other/exec"}, {"gas_token": "new-token"}):
        with pytest.raises(HTTPException) as e:
            gate_api.check_settings_change(db, chg)
        assert e.value.status_code == 423


def test_gas_settings_same_value_is_allowed(db):
    crud.set_setting(db, "gas_url", "https://script.google.com/macros/s/abc/exec")
    db.commit()
    gate_api.check_settings_change(db, {"gas_url": "https://script.google.com/macros/s/abc/exec"})


# ---------- 緊急解除の上限 ----------
def _add_request(db, ts: datetime, approved: bool):
    db.add(models.UnlockRequest(ts=ts.strftime("%Y-%m-%d %H:%M:%S"), reason="x" * 60, gates="game+site",
                                start="10:00", end="11:00", approved=approved, judge=""))
    db.commit()


def test_unlock_too_long_is_rejected(db):
    with pytest.raises(HTTPException) as e:
        gate_api.check_unlock_limits(db, "09:00", "12:01")
    assert e.value.status_code == 400
    gate_api.check_unlock_limits(db, "09:00", "12:00")   # ちょうど3時間はよい


def test_unlock_daily_max(db):
    now = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
    _add_request(db, now - timedelta(hours=3), approved=True)
    _add_request(db, now - timedelta(hours=2), approved=True)
    with pytest.raises(HTTPException) as e:
        gate_api.check_unlock_limits(db, "13:00", "14:00", now=now)
    assert e.value.status_code == 429


def test_unlock_wait_after_rejection(db):
    now = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
    _add_request(db, now - timedelta(minutes=10), approved=False)
    with pytest.raises(HTTPException) as e:
        gate_api.check_unlock_limits(db, "13:00", "14:00", now=now)
    assert e.value.status_code == 429
    gate_api.check_unlock_limits(db, "13:00", "14:00", now=now + timedelta(minutes=21))


def test_unlock_requests_of_other_days_do_not_count(db):
    now = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
    _add_request(db, now - timedelta(days=1), approved=False)
    _add_request(db, now - timedelta(days=1, minutes=1), approved=False)
    gate_api.check_unlock_limits(db, "13:00", "14:00", now=now)


# ---------- カレンダーの特例の1日の上限 ----------
def test_calendar_exemptions_capped_per_day(db, monkeypatch):
    created = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S")
    events = [{"title": f"面接{i}", "allday": False, "start": f"{s}:00", "end": f"{s + 2}:00", "created": created,
               "recurring": False, "ownedByMe": True}
              for i, s in enumerate((9, 12, 15))]   # 2時間 × 3件 = 6時間
    monkeypatch.setattr(gcal_sync, "google_events_for", lambda _db, _day: events)
    monkeypatch.setattr(exemption_api, "approved_windows", lambda _db, _day: [])
    wins = gate_api.exemption_windows(db, TODAY)
    assert [w["title"] for w in wins] == ["面接0", "面接1"]   # 4時間まで（開始の早い順）


def test_calendar_exemption_excludes_recurring_invited_and_unknown(db, monkeypatch):
    created = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S")
    base = {"allday": False, "start": "10:00", "end": "11:00", "created": created}
    events = [dict(base, title="面接 毎日", recurring=True, ownedByMe=True),
              dict(base, title="面接 招待", recurring=False, ownedByMe=False),
              dict(base, title="面接 不明", recurring=None, ownedByMe=None),
              dict(base, title="面接 自分の1回", recurring=False, ownedByMe=True)]
    monkeypatch.setattr(gcal_sync, "google_events_for", lambda _db, _day: events)
    monkeypatch.setattr(exemption_api, "approved_windows", lambda _db, _day: [])
    assert [w["title"] for w in gate_api.exemption_windows(db, TODAY)] == ["面接 自分の1回"]


def test_pulled_event_keeps_recurring_and_owner():
    ev = gcal_sync._clean_google_event({"date": TODAY, "title": "面接", "start": "10:00", "end": "11:00",
                                        "recurring": False, "ownedByMe": True})
    assert ev["recurring"] is False and ev["ownedByMe"] is True
    old = gcal_sync._clean_google_event({"date": TODAY, "title": "面接", "start": "10:00", "end": "11:00"})
    assert old["recurring"] is None and old["ownedByMe"] is None


# ---------- ゲームの exe の改名 ----------
def test_renamed_game_exe_is_detected_by_location():
    assert blocker.game_by_location(r"C:\Program Files (x86)\Steam\steamapps\common\SomeGame\code.exe")
    assert not blocker.game_by_location(r"C:\Users\me\AppData\Local\Programs\Microsoft VS Code\Code.exe")


# ---------- タイムゾーン ----------
def test_worker_locks_when_timezone_is_not_japan(monkeypatch):
    settings = {"gate_today": {"date": TODAY, "tasks_done": True, "game_unlocked": True, "site_unlocked": True,
                               "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}}
    monkeypatch.setattr(policy, "clock_ok", lambda: True)
    assert policy.worker_unlocked(settings, "site") is True
    monkeypatch.setattr(policy, "clock_ok", lambda: False)
    assert policy.worker_unlocked(settings, "site") is False


# ---------- 秘密の設定 ----------
def test_secrets_are_not_returned_and_blank_does_not_overwrite(db):
    crud.set_setting(db, "money_api_key", "AIza-secret")
    db.commit()
    out = main.read_settings(db)
    assert out["money_api_key"] == ""
    assert out["secrets_set"]["money_api_key"] is True
    main.update_settings({"money_api_key": "", "secrets_set": {"money_api_key": True}}, db)
    assert crud.get_all_settings(db)["money_api_key"] == "AIza-secret"
    assert "secrets_set" not in crud.get_all_settings(db)


# ---------- /api/logs ----------
def _log_rows(db):
    return db.execute(select(models.ActivityLog)).scalars().all()


def _ping_for(db, minutes: int, end_ts: float, task: str = "数学"):
    """小窓が end_ts まで minutes 分、20秒ごとに ping を送っていたことにする"""
    t = end_ts - minutes * 60
    while t <= end_ts:
        widget_sessions.observe(db, task, now=t)
        t += 20


@pytest.fixture(autouse=True)
def _fresh_sessions():
    widget_sessions.reset_cache()
    yield
    widget_sessions.reset_cache()


def test_log_without_observed_widget_is_not_recorded(db):
    """curl などで分数だけ送っても記録されない（本体が ping を見ていない）"""
    r = main.create_log(schemas.LogBody(content="数学", minutes=600), db)
    assert r["recorded_minutes"] == 0 and _log_rows(db) == []


def test_log_is_limited_to_observed_minutes(db):
    now = time.time()
    _ping_for(db, 30, now)
    r = main.create_log(schemas.LogBody(content="数学", minutes=300), db)
    assert 30 <= r["recorded_minutes"] <= 32
    # 同じ区間はもう使えない（同じ時間を二度記録させない）
    assert main.create_log(schemas.LogBody(content="数学", minutes=30), db)["recorded_minutes"] == 0


def test_log_honest_record_is_kept(db):
    now = time.time()
    _ping_for(db, 45, now)
    assert main.create_log(schemas.LogBody(content="数学", minutes=45), db)["recorded_minutes"] == 45


def test_widget_restart_gap_is_chained(db):
    """小窓の再起動（数分の途切れ）をはさんでも、前後の区間を合計する"""
    now = time.time()
    _ping_for(db, 20, now - 25 * 60)     # 再起動前の20分
    _ping_for(db, 20, now)               # 5分止まって、再起動後の20分
    assert main.create_log(schemas.LogBody(content="数学", minutes=40), db)["recorded_minutes"] == 40


def test_log_minutes_are_capped(db):
    now = time.time()
    _ping_for(db, 600, now)
    main.create_log(schemas.LogBody(content="数学", minutes=100000), db)
    assert sum(r.minutes for r in _log_rows(db)) == main.MAX_LOG_MINUTES


def test_log_resend_uses_end_time_date(db):
    yesterday_noon = datetime.combine(date.today() - timedelta(days=1), datetime.min.time()) + timedelta(hours=12)
    _ping_for(db, 30, yesterday_noon.timestamp())
    main.create_log(schemas.LogBody(content="数学", minutes=30, end_at=yesterday_noon.timestamp()), db)
    rows = _log_rows(db)
    assert len(rows) == 1 and str(rows[0].date).startswith((date.today() - timedelta(days=1)).isoformat())


def test_widget_sessions_cannot_be_written_from_settings(db):
    with pytest.raises(HTTPException) as e:
        gate_api.check_settings_change(db, {"widget_sessions": [{"start": 0, "last": 99999, "used": False}]})
    assert e.value.status_code == 423

def test_log_rejects_future_end_time(db):
    with pytest.raises(HTTPException) as e:
        main.create_log(schemas.LogBody(content="数学", minutes=30, end_at=time.time() + 3600), db)
    assert e.value.status_code == 400


# ---------- 宛先ホスト・他のサイトからの書き込み ----------
def test_rejects_unknown_host():
    client = TestClient(main.app, base_url="http://evil.example")
    assert client.get("/api/health").status_code == 400


def test_rejects_cross_site_write_but_allows_local():
    client = TestClient(main.app, base_url="http://127.0.0.1")
    assert client.get("/api/health").status_code == 200
    r = client.post("/api/widget/bye", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert client.post("/api/widget/bye", headers={"Origin": "http://localhost:5173"}).status_code == 200
    assert client.post("/api/widget/bye").status_code == 200   # 小窓・ワーカー（Origin なし）
