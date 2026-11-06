"""制限ルール（backend/app/policy.py）のテスト。ワーカーと本体が同じ判定を使うことの確認"""
from datetime import datetime

from app import policy

NOW = datetime(2026, 11, 6, 14, 0, 0)
TODAY = "2026-11-06"


def test_in_window():
    assert policy.in_window("07:00", "07:00", "21:00") is True
    assert policy.in_window("21:00", "07:00", "21:00") is False
    assert policy.in_window("23:30", "23:00", "01:00") is True    # 日またぎ
    assert policy.in_window("12:00", "12:00", "12:00") is False   # 幅ゼロ


def test_shift_clamped_stays_in_day():
    # 00:30 の60分前は 00:00 で止まる（23:30 に回り込んで「夜通し」にならない）
    assert policy.shift_clamped(TODAY, "00:30", -60) == "00:00"
    assert policy.shift_clamped(TODAY, "23:30", 60) == "23:59"
    assert policy.shift_clamped(TODAY, "10:00", -60) == "09:00"


def test_norm_hm():
    assert policy.norm_hm("7:5") == "07:05"
    assert policy.norm_hm("24:00") is None
    assert policy.norm_hm("abc") is None


def _gate(updated, **kw):
    return {"date": TODAY, "tasks_done": True, "game_unlocked": True, "site_unlocked": True,
            "updated": updated, **kw}


def test_worker_follows_fresh_gate():
    s = {"gate_today": _gate("2026-11-06 13:59:00")}
    assert policy.worker_unlocked(s, "game", NOW) is True
    assert policy.worker_unlocked(s, "site", NOW) is True


def test_worker_blocks_on_stale_or_missing_gate():
    # 本体が止まって判定が古くなったら、解放のままにしない
    s = {"gate_today": _gate("2026-11-06 13:50:00")}
    assert policy.worker_unlocked(s, "game", NOW) is False
    assert policy.worker_unlocked({}, "site", NOW) is False
    s = {"gate_today": _gate("2026-11-05 13:59:00", date="2026-11-05")}
    assert policy.worker_unlocked(s, "site", NOW) is False


def test_worker_unlock_window_only_inside_time_and_gate():
    eu = {"date": TODAY, "gates": "site", "start": "13:00", "end": "15:00"}
    s = {"emergency_unlock_day": eu}
    assert policy.worker_unlocked(s, "site", NOW) is True
    assert policy.worker_unlocked(s, "game", NOW) is False          # 対象外
    assert policy.worker_unlocked(s, "site", datetime(2026, 11, 6, 15, 0)) is False   # 時間外


def test_block_off_is_only_for_that_day():
    s = {"block_enabled": False, "block_off_date": TODAY}
    assert policy.block_active(s, "game", NOW) is False                       # オフにした日はオフ
    assert policy.block_active(s, "game", datetime(2026, 11, 7, 0, 0)) is True  # 翌日は本体が止まっていてもオン
    assert policy.block_active({"block_enabled": False}, "game", NOW) is True   # 日付の無い古いオフはオン
    assert policy.block_active({}, "site", NOW) is True
