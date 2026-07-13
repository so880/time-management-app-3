"""設定の正規化（既存 load_settings 相当）のテスト"""
from app import migrate


def test_daily_window_migrates_to_routine_when_missing():
    saved = {
        "daily_window": [{"start": "08:00", "end": "20:00"}] * 7,
    }
    s = migrate.normalize_settings(saved)
    assert s["daily_routine"][0] == [{"start": "08:00", "end": "20:00"}]
    assert len(s["daily_routine"]) == 7


def test_existing_routine_is_kept():
    routine = [[{"start": "10:00", "end": "12:00"}]] * 7
    saved = {
        "daily_routine": routine,
        "daily_window": [{"start": "08:00", "end": "20:00"}] * 7,
    }
    s = migrate.normalize_settings(saved)
    assert s["daily_routine"] == routine  # daily_window では上書きされない


def test_goals_fallback_from_legacy_keys():
    saved = {
        "goals": [],
        "toeic_name": "英検", "toeic_date": "2027-01-01", "daily_hours_toeic": 4,
        "intern_name": "本選考", "intern_date": "2027-02-01", "daily_hours_intern": 1,
    }
    s = migrate.normalize_settings(saved)
    assert s["goals"][0] == {"name": "英検", "date": "2027-01-01", "hours": 4}
    assert s["goals"][1] == {"name": "本選考", "date": "2027-02-01", "hours": 1}


def test_study_dur_min_is_always_30():
    s = migrate.normalize_settings({"study_dur_min": 10})
    assert s["study_dur_min"] == 30


def test_missing_keys_are_filled():
    s = migrate.normalize_settings({})
    assert s["block_enabled"] is True
    assert s["block_process_list"] == []
    assert s["liquid_glass_enabled"] is False
    assert s["mustdo_list"] == []
