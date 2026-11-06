"""制限の強化（F20）のテスト：設定ロック・AI審査つき解除。インメモリSQLite。"""
from datetime import date, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import crud, gate_api, models, policy


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    gate_api.ensure_gate_defaults(s)
    # 未完了の必須を1つ置く → 制限中
    s.add(models.TodoItem(kind="must", title="ES提出", date=date.today().isoformat(), enabled=True, created=""))
    s.commit()
    yield s
    s.close()


def test_locked_settings_cannot_be_weakened(db):
    crud.set_setting(db, "block_process_list", ["a.exe", "b.exe"])
    crud.set_setting(db, "site_block_list", ["YouTube"])
    db.commit()
    for chg in ({"block_enabled": False}, {"site_block_enabled": False},
                {"block_process_list": ["a.exe"]}, {"site_block_list": []}):
        with pytest.raises(HTTPException) as e:
            gate_api.check_settings_change(db, chg)
        assert e.value.status_code == 423
    # 強める方向（追加・オン）は通る
    gate_api.check_settings_change(db, {"block_process_list": ["a.exe", "b.exe", "c.exe"], "block_enabled": True})
    gate_api.check_settings_change(db, {"unrelated": 1})


def test_unlock_requires_long_reason(db):
    with pytest.raises(HTTPException) as e:
        gate_api.request_unlock(db, "短い", "game")
    assert e.value.status_code == 400


def _later():
    """今日中で、いまより後の時間帯（テストが深夜でも落ちないように 23:58〜23:59 を使う）"""
    return "23:58", "23:59"


def test_unlock_requires_valid_window(db):
    s_, e_ = _later()
    with pytest.raises(HTTPException) as e:
        gate_api.request_unlock(db, "あ" * 60, "game", "", "")
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        gate_api.request_unlock(db, "あ" * 60, "game", e_, s_)   # 終了が開始より前
    assert e.value.status_code == 400


def test_unlock_denied_without_ai(db):
    # Gemini キー無し → 審査できない → 却下。記録は残る。解放されない
    s_, e_ = _later()
    r = gate_api.request_unlock(db, "あ" * 60, "game", s_, e_)
    assert r["approved"] is False
    s = crud.get_all_settings(db)
    assert gate_api.unlock_request_dicts(db)[0]["approved"] is False   # 記録は表に残る（新しい順）
    assert (s.get("emergency_unlock_day") or {}).get("date") != date.today().isoformat()


def test_unlock_approved_by_ai(db, monkeypatch):
    monkeypatch.setattr(gate_api, "ai_judge_unlock", lambda db, reason, s="", e="": {"approve": True, "reason": "ok"})
    s_, e_ = _later()
    r = gate_api.request_unlock(db, "あ" * 60, "game", s_, e_)
    assert r["approved"] is True
    eu = crud.get_all_settings(db)["emergency_unlock_day"]
    assert eu["date"] == date.today().isoformat() and eu["start"] == s_ and eu["end"] == e_
    # 時間帯の外は解放されない。時間帯の中なら解放（23:58〜23:59 に実行しても落ちないよう、いまの時刻で期待値を決める）
    inside_now = policy.in_window(datetime.now().strftime("%H:%M"), s_, e_)
    assert gate_api.gate_state(db)["game_unlocked"] is inside_now
    assert policy.in_window("23:58", s_, e_) is True


def test_exemption_from_google_calendar(db, monkeypatch):
    from app import gcal_sync
    today = date.today().isoformat()
    now = datetime.now()
    # 予定は今日の中に収める（23:30 以降・0:05 前に実行しても日をまたがないように）
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = now.replace(hour=23, minute=59, second=0, microsecond=0)
    s_ = max(now - timedelta(minutes=5), day_start).strftime("%H:%M")
    e_ = min(now + timedelta(minutes=30), day_end).strftime("%H:%M")
    old = (now - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S")
    fresh = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
    events = [
        {"title": "A社 一次面接", "allday": False, "date": today, "start": s_, "end": e_, "created": old, "recurring": False, "ownedByMe": True},
        {"title": "B社 面接（いま作った）", "allday": False, "date": today, "start": s_, "end": e_, "created": fresh, "recurring": False, "ownedByMe": True},
        {"title": "ランチ", "allday": False, "date": today, "start": s_, "end": e_, "created": old, "recurring": False, "ownedByMe": True},
    ]
    monkeypatch.setattr(gcal_sync, "google_events_for", lambda db, d: events)
    ws = gate_api.exemption_windows(db, today)
    assert [w["title"] for w in ws] == ["A社 一次面接"]   # 24時間前に作られたものだけ
    st = gate_api.gate_state(db)
    assert st["exempt"]["title"] == "A社 一次面接"
    assert st["game_unlocked"] is True and st["site_unlocked"] is True


def test_habit_cannot_be_checked_manually(db):
    from app import todo_api
    h = models.TodoItem(kind="habit", title="英語", weekdays="0,1,2,3,4,5,6", start="08:00", end="08:30",
                        enabled=True, created="2026-01-01 00:00:00")
    db.add(h); db.commit()
    with pytest.raises(HTTPException) as e:
        todo_api.check_item(todo_api.CheckBody(item_id=h.id, done=True, level="full"), db)
    assert e.value.status_code == 423


def test_judge_parsing(db, monkeypatch):
    from app import money_api
    monkeypatch.setattr(money_api, "call_ai", lambda *a, **k: 'はい {"approve": "true", "reason": "x"}')
    assert gate_api.ai_judge_unlock(db, "r")["approve"] is False   # 文字列の "true" は承認扱いにしない
    monkeypatch.setattr(money_api, "call_ai", lambda *a, **k: '{"approve": true, "reason": "必要"}')
    assert gate_api.ai_judge_unlock(db, "r")["approve"] is True
    monkeypatch.setattr(money_api, "call_ai", lambda *a, **k: 'よくわからない')
    assert gate_api.ai_judge_unlock(db, "r")["approve"] is False
