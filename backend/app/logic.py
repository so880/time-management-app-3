"""抽選・所要時間・ゲーム解放の基本条件（旧版＝Streamlit 版のロジックを引き継いだもの）。

- 抽選（roll_once / get_pool / active_items）
- 所要時間の決定（模試120分／勉強はランダム／気分転換15〜30分）
- ゲーム解放の基本条件（今日のデータ・勉強≥目標・ゲームができる時間帯＝policy.GAME_WINDOW）
"""
import random
from datetime import datetime

from . import policy
from .config import DEFAULT_STUDY_TARGET_MIN, GAME_LIST


def active_items(settings: dict, key_name: str) -> list:
    """無効化されていない項目のみ返す（utils/helpers.py と同じ）"""
    disabled = set(settings.get(f"{key_name}_disabled") or [])
    return [t for t in (settings.get(key_name) or []) if t not in disabled]


def get_pool(settings: dict, mock_exam_done: bool, must: list | None = None,
             items: list | None = None) -> list:
    """勉強の抽選プール。

    今日の必須（todo_items kind=must）に未完了があればそこからのみ。
    無ければ ルーレット項目（assignments：未完了・有効。重点は3倍）＋（未実施なら）TOEIC模擬試験。
    must / items は呼び出し側（main.py）が DB から渡す。items は [(title, focus), ...]。
    """
    must = list(must or [])
    if must:
        return must
    pool = []
    for title, focus in (items or []):
        pool.extend([title] * (3 if focus else 1))
    if not mock_exam_done:
        pool.append("TOEIC模擬試験(2時間)")
    return pool or ["（勉強項目がありません・編集モードで追加/有効化してください）"]


def roll_once(settings: dict, last_was_refresh: bool, force_study_only: bool,
              mock_exam_done: bool, can_game: bool, must: list | None = None,
              items: list | None = None) -> dict:
    """ルーレット1回分の抽選。

    気分転換の次・SOS明け・短縮修了後は『勉強のみ』
    （気分転換は「なし(連続お休み)」になる）。
    must（今日の必須の未完了一覧）があれば勉強側はそこからのみ抽選する（気分転換側は通常どおり）。
    """
    study_only = last_was_refresh or force_study_only
    refresh_pool = active_items(settings, "refresh_list") + (GAME_LIST if can_game else [])
    refresh_pool = refresh_pool or ["（気分転換項目がありません）"]
    return {
        "勉強": random.choice(get_pool(settings, mock_exam_done, must, items)),
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


def is_unlock_time(now: datetime | None = None, window: dict | None = None) -> bool:
    """ゲームができる時間帯か（既定は policy.GAME_WINDOW＝07:00〜21:00 固定）"""
    now = now or datetime.now()
    w = window or policy.GAME_WINDOW
    return policy.in_window(now.strftime("%H:%M"), w["start"], w["end"])


def is_game_unlocked(target_date: str, study_time_total: int, target_value: int,
                     now: datetime | None = None, window: dict | None = None) -> bool:
    """ゲームの基本条件（ノルマ完了は gate_api が別に見る）。

    1. 日付ガード：今日のデータであること（古い日付なら必ずブロック）
    2. 今日の勉強時間 ≥ 今日の目標
    3. ゲームができる時間帯（policy.GAME_WINDOW。変更不可）

    now はテスト用に注入可能（未指定なら現在時刻）。
    """
    now = now or datetime.now()
    if target_date != now.date().isoformat():
        return False
    if int(study_time_total or 0) < int(target_value or DEFAULT_STUDY_TARGET_MIN):
        return False
    return is_unlock_time(now, window)