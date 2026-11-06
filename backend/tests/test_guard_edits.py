"""制限中に「解放条件を減らす」操作ができないことのテスト（2026-11-06）。インメモリSQLite。

- /api/settings から本体専用のキー（gate_today・承認された解除など）を書けない
- /api/state から勉強時間・確定済みの目標を書き換えられない
- 制限中は 習慣の削除・無効化・曜日を減らす・時間帯を短くする・まだ終わっていない今日の必須の削除 ができない
- 追加・延長・名前の変更はいつでもできる。ノルマが全部終わっていれば自由
"""
from datetime import date, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import crud, gate_api, main, models, todo_api

TODAY = date.today().isoformat()
WD = date.today().weekday()


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    gate_api.ensure_gate_defaults(s)
    crud.set_setting(s, "todo_v1_migrated", True)       # 既定のやることを入れない（このテストの項目だけにする）
    crud.set_setting(s, "todo_v1_cleanup_done", True)
    s.add(models.TodoItem(kind="must", title="ES提出", date=TODAY, enabled=True, created=""))
    s.add(models.TodoItem(kind="habit", title="英語", weekdays=f"{WD},{(WD + 1) % 7}", start="10:00", end="11:00",
                          enabled=True, created=""))
    crud.set_setting(s, todo_api.DAY_SETUP_KEY, TODAY)   # 「今日を始める」は済み
    s.commit()
    gate_api.gate_state(s)   # gate_today を書く（未完了＝制限中）
    yield s
    s.close()


def _habit(db):
    return db.query(models.TodoItem).filter_by(kind="habit").one()


def _must(db):
    return db.query(models.TodoItem).filter_by(kind="must").one()


def _body(item, **over):
    d = dict(kind=item.kind, title=item.title, weekdays=[int(w) for w in (item.weekdays or "").split(",") if w],
             start=item.start or "", end=item.end or "", every_days=0, min_action="", enabled=True)
    d.update(over)
    return todo_api.ItemBody(**d)


def _locked(fn, *a):
    with pytest.raises(HTTPException) as e:
        fn(*a)
    assert e.value.status_code == 423


# ---------- 設定 ----------
def test_protected_settings_cannot_be_written(db):
    forged = {"date": TODAY, "tasks_done": True, "game_unlocked": True, "site_unlocked": True,
              "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    for chg in ({"gate_today": forged},
                {"emergency_unlock_day": {"date": TODAY, "gates": "game+site", "start": "00:00", "end": "23:59"}},
                {"block_off_date": TODAY},
                {"habit_options": {"英語": {"record_only": True}}},
                {"presence_rate_min": {"value": 0}}):
        _locked(gate_api.check_settings_change, db, chg)
    # 今と同じ値を送り返すのは問題ない（画面が設定を丸ごと送る場合）
    cur = crud.get_all_settings(db)
    gate_api.check_settings_change(db, {"gate_today": cur.get("gate_today")})


# ---------- 今日の状態 ----------
def test_state_patch_only_page_and_target(db):
    with pytest.raises(HTTPException) as e:
        main.patch_state({"study_time_total": 999}, db)
    assert e.value.status_code == 400
    main.patch_state({"target_value": 120, "target_locked": True}, db)
    _locked(main.patch_state, {"target_value": 0}, db)          # 確定後は変えられない
    _locked(main.patch_state, {"target_locked": False}, db)     # 確定の取り消し不可
    assert main.patch_state({"page": "dashboard"}, db)["page"] == "dashboard"


# ---------- やること ----------
def test_locked_habit_cannot_be_weakened(db):
    h = _habit(db)
    _locked(todo_api.update_item, h.id, _body(h, enabled=False), db)
    _locked(todo_api.update_item, h.id, _body(h, end="10:30"), db)            # 短くする
    _locked(todo_api.update_item, h.id, _body(h, weekdays=[WD]), db)          # 曜日を減らす
    _locked(todo_api.update_item, h.id, _body(h, kind="periodic"), db)        # 種類を変える
    _locked(todo_api.delete_item, h.id, db)
    from app import life_api
    _locked(life_api.delete_habit, "英語", db)
    # 延ばす・名前を変えるのは通る
    todo_api.update_item(h.id, _body(h, end="11:30"), db)
    todo_api.update_item(h.id, _body(h, title="英語（リスニング）", end="11:30"), db)


def test_locked_must_cannot_be_removed(db):
    m = _must(db)
    _locked(todo_api.delete_item, m.id, db)
    _locked(todo_api.replace_must_titles, db, [])
    _locked(todo_api.update_item, m.id, _body(m, enabled=False), db)
    # 追加はできる（既存を残したまま）
    todo_api.replace_must_titles(db, ["ES提出", "面接準備"])
    db.commit()
    assert {x.title for x in db.query(models.TodoItem).filter_by(kind="must")} == {"ES提出", "面接準備"}


def test_first_day_setup_can_replace_must(db):
    crud.set_setting(db, todo_api.DAY_SETUP_KEY, "2000-01-01")   # 今日はまだ「今日を始める」前
    db.commit()
    todo_api.replace_must_titles(db, [])
    db.commit()
    assert db.query(models.TodoItem).filter_by(kind="must").count() == 0


def test_free_when_quota_done(db, monkeypatch):
    monkeypatch.setattr(todo_api, "quota_done_now", lambda db: True)
    h = _habit(db)
    todo_api.update_item(h.id, _body(h, enabled=False), db)
    todo_api.delete_item(h.id, db)
    todo_api.replace_must_titles(db, [])


def test_stale_gate_counts_as_locked(db):
    gt = dict(crud.get_all_settings(db)["gate_today"], tasks_done=True, updated="2000-01-01 00:00:00")
    crud.set_setting(db, "gate_today", gt)
    db.commit()
    assert todo_api.quota_done_now(db) is False


def test_switch_off_stamps_today_and_resets_next_day(db, monkeypatch):
    from app import policy
    chg = gate_api.stamp_switches({"block_enabled": False})
    assert chg == {"block_enabled": False, "block_off_date": TODAY}
    assert gate_api.stamp_switches({"site_block_enabled": True})["site_block_off_date"] == ""
    # 前の日にオフにしたもの → gate_state がオンに戻す
    crud.set_setting(db, "block_enabled", False)
    crud.set_setting(db, "block_off_date", "2000-01-01")
    db.commit()
    gate_api.gate_state(db)
    s = crud.get_all_settings(db)
    assert s["block_enabled"] is True and policy.block_active(s, "game")


def test_calendar_exemption_caps_length_but_not_count(db, monkeypatch):
    from app import gcal_sync
    created = "2000-01-01T00:00:00"
    events = [{"title": f"株式会社テスト 面接{i}", "allday": False, "start": f"{9 + i}:00", "end": f"{9 + i}:30",
               "created": created, "recurring": False, "ownedByMe": True} for i in range(5)]                       # 同じ週に5件でも全部対象
    events.append({"title": "インターン（終日相当）", "allday": False, "start": "09:00", "end": "18:00",
                   "created": created, "recurring": False, "ownedByMe": True})                                     # 180分を超えるものは対象外
    monkeypatch.setattr(gcal_sync, "google_events_for", lambda db, d: events)
    ws = gate_api.exemption_windows(db, TODAY)
    assert len([w for w in ws if "面接" in w["title"]]) == 5
    assert not any("インターン" in w["title"] for w in ws)
