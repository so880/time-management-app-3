"""コアロジックのテスト（ゲーム解放判定・抽選プール・所要時間）。

実行: backend フォルダで `pytest -v`（scripts\run_tests.bat でも可）
"""
from datetime import datetime

from app import logic


# ---------- ゲーム解放：時間帯（policy.GAME_WINDOW＝07:00〜21:00 固定） ----------
def test_unlock_time_boundaries():
    assert logic.is_unlock_time(datetime(2026, 7, 6, 6, 59)) is False
    assert logic.is_unlock_time(datetime(2026, 7, 6, 7, 0)) is True
    assert logic.is_unlock_time(datetime(2026, 7, 6, 20, 59)) is True
    assert logic.is_unlock_time(datetime(2026, 7, 6, 21, 0)) is False   # 21:00 で終了
    assert logic.is_unlock_time(datetime(2026, 7, 7, 2, 0)) is False


# ---------- ゲーム解放：3条件 ----------
def test_game_unlocked_all_conditions_met():
    now = datetime(2026, 7, 6, 15, 0)
    assert logic.is_game_unlocked("2026-07-06", 180, 180, now) is True


def test_game_unlocked_date_guard_blocks_old_data():
    # 古い日付の進捗データでは、勉強量・時間帯を満たしていても解放しない
    now = datetime(2026, 7, 6, 15, 0)
    assert logic.is_game_unlocked("2026-07-05", 999, 180, now) is False


def test_game_unlocked_study_below_target():
    now = datetime(2026, 7, 6, 15, 0)
    assert logic.is_game_unlocked("2026-07-06", 179, 180, now) is False


def test_game_unlocked_outside_time_window():
    now = datetime(2026, 7, 6, 21, 30)
    assert logic.is_game_unlocked("2026-07-06", 300, 180, now) is False


# ---------- 抽選プール ----------
def _settings(**over):
    s = {
        "refresh_list": ["R1"], "refresh_list_disabled": [],
        "study_dur_min": 30, "study_dur_max": 60,
    }
    s.update(over)
    return s


def test_pool_must_has_priority():
    # 今日の必須（未完了）があれば、勉強の抽選はそこからのみ（todo_items から呼び出し側が渡す）
    s = _settings()
    assert logic.get_pool(s, mock_exam_done=True, must=["必須1", "必須2"]) == ["必須1", "必須2"]


ITEMS = [("A", False), ("B", False)]  # ルーレット項目（title, focus）は呼び出し側が渡す


def test_pool_no_unfinished_must_falls_back_to_items():
    # 必須がすべて完了（空）ならルーレット項目から抽選
    s = _settings()
    pool = logic.get_pool(s, mock_exam_done=True, must=[], items=ITEMS)
    assert "A" in pool and "B" in pool


def test_pool_focus_items_are_tripled():
    s = _settings()
    pool = logic.get_pool(s, mock_exam_done=True, items=[("重点X", True)])
    assert pool.count("重点X") == 3


def test_pool_mock_exam_only_when_not_done():
    s = _settings()
    assert "TOEIC模擬試験(2時間)" in logic.get_pool(s, mock_exam_done=False, items=ITEMS)
    assert "TOEIC模擬試験(2時間)" not in logic.get_pool(s, mock_exam_done=True, items=ITEMS)


def test_pool_empty_items_gives_placeholder():
    s = _settings()
    pool = logic.get_pool(s, mock_exam_done=True, items=[])
    assert len(pool) == 1 and "勉強項目がありません" in pool[0]


# ---------- 抽選（roll_once） ----------
def test_roll_normal_gives_both_options():
    s = _settings()
    r = logic.roll_once(s, last_was_refresh=False, force_study_only=False,
                        mock_exam_done=True, can_game=False, must=[], items=[("A", False)])
    assert r["勉強"] == "A"
    assert r["気分転換"] == "R1"


def test_roll_after_refresh_forces_study_only():
    # 気分転換の直後は連続で気分転換できない
    s = _settings()
    r = logic.roll_once(s, last_was_refresh=True, force_study_only=False,
                        mock_exam_done=True, can_game=False)
    assert r["気分転換"] == "なし(連続お休み)"


def test_roll_force_study_only():
    # SOS明け・短縮修了後も勉強のみ
    s = _settings()
    r = logic.roll_once(s, last_was_refresh=False, force_study_only=True,
                        mock_exam_done=True, can_game=False)
    assert r["気分転換"] == "なし(連続お休み)"


def test_roll_can_game_adds_real_games():
    # 解放中は気分転換プールに本物のゲームが追加される
    s = _settings(refresh_list=[])  # 通常の気分転換を空にしてゲームだけにする
    r = logic.roll_once(s, last_was_refresh=False, force_study_only=False,
                        mock_exam_done=True, can_game=True)
    assert r["気分転換"] in logic.GAME_LIST


# ---------- 所要時間 ----------
def test_duration_mock_exam_is_120():
    s = _settings()
    dur, is_mock = logic.pick_duration(s, "勉強", "TOEIC模擬試験(2時間)")
    assert dur == 120 and is_mock is True


def test_duration_study_within_range():
    s = _settings(study_dur_min=30, study_dur_max=60)
    for _ in range(50):
        dur, is_mock = logic.pick_duration(s, "勉強", "普通のタスク")
        assert 30 <= dur <= 60 and is_mock is False


def test_duration_refresh_within_15_30():
    s = _settings()
    for _ in range(50):
        dur, _ = logic.pick_duration(s, "気分転換", "読書")
        assert 15 <= dur <= 30
