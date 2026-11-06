"""設定の初期値（migrate.normalize_settings）と DB の構造の更新（migrate.upgrade）のテスト"""
import json
import sqlite3

from sqlalchemy import create_engine

from app import migrate, models


def test_study_dur_min_is_always_30():
    s = migrate.normalize_settings({"study_dur_min": 10})
    assert s["study_dur_min"] == 30


def test_missing_keys_are_filled():
    s = migrate.normalize_settings({})
    assert s["block_enabled"] is True
    assert s["block_process_list"] == []
    assert "goals" in s
    for k in migrate.DEAD_SETTING_KEYS:
        assert k not in s   # 使われなくなった設定は初期値にも無い


def _old_db(path):
    """2026-11-06 より前の形の DB を作る（外部キーなし・settings に記録・勉強時間の列あり）"""
    con = sqlite3.connect(path)
    con.executescript("""
    CREATE TABLE settings (key VARCHAR(100) PRIMARY KEY, value TEXT);
    CREATE TABLE recurring_assignments (id INTEGER PRIMARY KEY, title VARCHAR(200), weekday INTEGER, enabled BOOLEAN);
    CREATE TABLE assignments (id INTEGER PRIMARY KEY, title VARCHAR(200), due_date VARCHAR(10), progress INTEGER,
        note TEXT, created VARCHAR(19), recurring_id INTEGER, category VARCHAR(20), focus BOOLEAN, enabled BOOLEAN);
    CREATE TABLE todo_items (id INTEGER PRIMARY KEY, kind VARCHAR(10), title VARCHAR(200), date VARCHAR(10),
        weekdays VARCHAR(20), every_days INTEGER, start VARCHAR(5), "end" VARCHAR(5), min_action TEXT,
        enabled BOOLEAN, created VARCHAR(19), sort INTEGER, tag VARCHAR(30), due_date VARCHAR(10), asg_id INTEGER);
    CREATE TABLE todo_completions (id INTEGER PRIMARY KEY, item_id INTEGER, date VARCHAR(10), at VARCHAR(5),
        level VARCHAR(10), CONSTRAINT uq_todo_completion UNIQUE (item_id, date));
    CREATE TABLE schedule_blocks (id INTEGER PRIMARY KEY, weekday INTEGER, start VARCHAR(5), "end" VARCHAR(5),
        title VARCHAR(100), category VARCHAR(30), enabled BOOLEAN, room VARCHAR(100));
    CREATE TABLE schedule_cancellations (id INTEGER PRIMARY KEY, date VARCHAR(10), block_id INTEGER);
    CREATE TABLE job_applications (id INTEGER PRIMARY KEY, company VARCHAR(100), title VARCHAR(200), kind VARCHAR(10),
        status VARCHAR(20), priority INTEGER, submitted TEXT, note TEXT, created VARCHAR(19));
    CREATE TABLE job_events (id INTEGER PRIMARY KEY, application_id INTEGER, label VARCHAR(100), date VARCHAR(10),
        end_date VARCHAR(10), start VARCHAR(5), "end" VARCHAR(5), choice INTEGER);
    CREATE TABLE job_docs (id INTEGER PRIMARY KEY, application_id INTEGER, title VARCHAR(100), body TEXT);
    CREATE TABLE daily_state (id INTEGER PRIMARY KEY, target_date VARCHAR(10), page VARCHAR(20), current_task TEXT,
        start_time FLOAT, study_time_total INTEGER, refresh_time_total INTEGER, target_value INTEGER,
        target_locked BOOLEAN, last_was_refresh BOOLEAN, force_study_only BOOLEAN, mock_exam_done BOOLEAN,
        pending_review TEXT, sos_task TEXT, rolled_options TEXT);
    INSERT INTO assignments VALUES (1, '課題', '', 0, '', '', 99, 'その他', 0, 1);      -- 存在しない毎週の項目
    INSERT INTO todo_items VALUES (1, 'habit', '筋トレ', NULL, '0', NULL, '05:30', '07:00', '', 1, '', 0, '', '', NULL);
    INSERT INTO todo_items VALUES (2, 'must', 'ES', '2026-11-06', NULL, NULL, '', '', '', 1, '', 0, '', '', 77);
    INSERT INTO todo_completions VALUES (1, 1, '2026-11-06', '07:00', 'full');
    INSERT INTO todo_completions VALUES (2, 55, '2026-11-06', '07:00', 'full');           -- 消えた項目の完了
    INSERT INTO job_events VALUES (1, 0, '合同説明会', '2026-11-20', '', '', '', 0);
    INSERT INTO daily_state VALUES (1, '2026-11-06', 'dashboard', NULL, NULL, 30, 0, 180, 0, 0, 0, 0, NULL, NULL, NULL);
    """)
    rows = {
        "emergency_unlocks": [{"ts": "2026-11-01 10:00:00", "reason": "r", "gates": "game", "start": "10:00",
                               "end": "11:00", "approved": False, "judge": "no"}, {"ts": "2026-10-01 09:00:00"}],
        "exemption_requests": [{"id": "ab12cd34", "created": "2026-11-01 10:00:00", "date": "2026-11-10",
                                "start": "10:00", "end": "11:00", "minutes": 60, "company": "テスト株式会社",
                                "kind": "面接", "evidence": "メール", "status": "approved",
                                "decision": {"reason": "ok", "at": "x", "by": "claude"}}],
        "gcal_google_events": {"fetched": "2026-11-06 10:00", "start": "2026-10-30", "end": "2027-01-06",
                               "calendar": "me", "events": [{"id": "g1", "title": "面接", "allday": False,
                                                             "date": "2026-11-10", "endDate": "2026-11-10",
                                                             "start": "10:00", "end": "11:00", "location": "",
                                                             "created": "2026-11-01T10:00:00"}]},
        "habit_options": {"筋トレ": {"record_only": True}, "消えた習慣": {"record_only": True}},
        "game_window": {"start": "10:00", "end": "03:00"},
        "toeic_date": "2026-05-24",
        "liquid_glass_enabled": True,
        "block_enabled": True,
    }
    con.executemany("INSERT INTO settings VALUES (?, ?)", [(k, json.dumps(v, ensure_ascii=False)) for k, v in rows.items()])
    con.commit()
    con.close()


def test_upgrade_v1_moves_data_and_adds_foreign_keys(tmp_path, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)   # バックアップの置き場所
    path = tmp_path / "old.db"
    _old_db(path)
    engine = create_engine("sqlite:///" + path.as_posix())
    models.Base.metadata.create_all(engine)   # 起動時と同じ順（新しい表を作ってから upgrade）
    assert migrate.upgrade(engine) == migrate.SCHEMA_VERSION
    assert list((tmp_path / "backups").glob("before_schema_v1_*.db"))   # 実行前の複製
    con = sqlite3.connect(path)
    q = lambda sql: con.execute(sql).fetchall()   # noqa: E731
    assert q("PRAGMA user_version")[0][0] == migrate.SCHEMA_VERSION
    assert q("PRAGMA foreign_key_check") == []
    # 外部キーが付いている
    assert {r[2] for r in q("PRAGMA foreign_key_list(todo_completions)")} == {"todo_items"}
    assert {r[2] for r in q("PRAGMA foreign_key_list(todo_items)")} == {"assignments"}
    # 参照先の無い行の片づけ
    assert q("SELECT recurring_id FROM assignments") == [(None,)]
    assert q("SELECT asg_id FROM todo_items WHERE id = 2") == [(None,)]
    assert q("SELECT item_id FROM todo_completions") == [(1,)]
    assert q("SELECT application_id FROM job_events") == [(None,)]
    # 記録の移し替え
    assert len(q("SELECT * FROM unlock_requests")) == 2
    assert q("SELECT approved FROM unlock_requests ORDER BY ts") == [(None,), (0,)]
    assert q("SELECT id, status, decision_reason FROM exemption_requests") == [("ab12cd34", "approved", "ok")]
    assert q("SELECT event_id, created FROM google_events") == [("g1", "2026-11-01T10:00:00")]
    keys = {r[0] for r in q("SELECT key FROM settings")}
    assert not keys & {"emergency_unlocks", "exemption_requests", "gcal_google_events", "game_window",
                       "toeic_date", "liquid_glass_enabled"}
    assert "gcal_google_pull" in keys and "block_enabled" in keys
    # 習慣ごとの設定は習慣の番号で（消えた習慣の分は持ち越さない）
    assert json.loads(q("SELECT value FROM settings WHERE key = 'habit_options'")[0][0]) == {"1": {"record_only": True}}
    # 勉強時間の列は無い
    cols = {r[1] for r in q("PRAGMA table_info(daily_state)")}
    assert "study_time_total" not in cols and "refresh_time_total" not in cols
    con.close()
    # 2回目は何もしない
    assert migrate.upgrade(engine) == migrate.SCHEMA_VERSION


def test_upgrade_on_new_db_only_sets_version(tmp_path):
    path = tmp_path / "new.db"
    engine = create_engine("sqlite:///" + path.as_posix())
    models.Base.metadata.create_all(engine)
    assert migrate.upgrade(engine) == migrate.SCHEMA_VERSION
    assert not (tmp_path / "backups").exists()
