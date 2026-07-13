"""既存アプリのコアロジック移植（utils/helpers.py・views/dashboard.py・blocker.py より）。

- 抽選（roll_once / get_pool / active_items）
- 所要時間の決定（模試120分／勉強はランダム／気分転換15〜30分）
- ゲーム解放判定（今日のデータ・勉強≥目標・20:00〜翌2:59）
"""
import random
from datetime import date, datetime

from .config import (
    GAME_LIST,
    GAME_UNLOCK_END_HOUR,
    GAME_UNLOCK_START_HOUR,
)


def active_items(settings: dict, key_name: str) -> list:
    """無効化されていない項目のみ返す（utils/helpers.py と同じ）"""
    disabled = set(settings.get(f"{key_name}_disabled") or [])
    return [t for t in (settings.get(key_name) or []) if t not in disabled]


def get_pool(settings: dict, mock_exam_done: bool) -> list:
    """勉強の抽選プール（utils/helpers.py と同じ）。

    「今日絶対やる」に項目があればそこからのみ。空なら
    通常勉強＋重点(3倍)＋（未実施なら）TOEIC模擬試験。
    """
    must = list(active_items(settings, "mustdo_list"))
    if must:
        return must
    pool = list(active_items(settings, "study_list"))
    for t in active_items(settings, "focus_study_list"):
        pool.extend([t] * 3)
    if not mock_exam_done:
        pool.append("TOEIC模擬試験(2時間)")
    return pool or ["（勉強項目がありません・編集モードで追加/有効化してください）"]


def roll_once(settings: dict, last_was_refresh: bool, force_study_only: bool,
              mock_exam_done: bool, can_game: bool) -> dict:
    """ルーレット1回分の抽選（utils/helpers.py と同じ）。

    気分転換の次・SOS明け・短縮修了後は『勉強のみ』
    （気分転換は「なし(連続お休み)」になる）。
    """
    study_only = last_was_refresh or force_study_only
    refresh_pool = active_items(settings, "refresh_list") + (GAME_LIST if can_game else [])
    refresh_pool = refresh_pool or ["（気分転換項目がありません）"]
    return {
        "勉強": random.choice(get_pool(settings, mock_exam_done)),
        "気分転換": "なし(連続お休み)" if study_only else random.choice(refresh_pool),
    }


def pick_duration(settings: dict, category: str, task_name: str) -> tuple[int, bool]:
    """タスクの所要時間（分）を決める（views/dashboard.py と同じ）。

    戻り値: (duration, is_mock_exam)
    """
    if "模試" in task_name or "模擬" in task_name:
        return 120, True
    if category == "勉強":
        dmin = int(settings.get("study_dur_min", 30))
        dmax = int(settings.get("study_dur_max", 60))
        if dmin > dmax:
            dmin, dmax = dmax, dmin
        return random.randint(dmin, dmax), False
    return random.randint(15, 30), False


def is_unlock_time(now: datetime | None = None) -> bool:
    """ゲーム解放の時間帯か（20:00〜翌2:59。2:59に統一済み）"""
    now = now or datetime.now()
    return now.hour >= GAME_UNLOCK_START_HOUR or now.hour < GAME_UNLOCK_END_HOUR


def is_game_unlocked(target_date: str, study_time_total: int, target_value: int,
                     now: datetime | None = None) -> bool:
    """ゲーム解放判定（blocker.py と同じ3条件）。

    1. 日付ガード：今日のデータであること（古い日付なら必ずブロック）
    2. 今日の勉強時間 ≥ 今日の目標
    3. 20:00〜翌2:59 の時間帯

    now はテスト用に注入可能（未指定なら現在時刻）。
    """
    now = now or datetime.now()
    if target_date != now.date().isoformat():
        return False
    if int(study_time_total or 0) < int(target_value or 180):
        return False
    return is_unlock_time(now)
