"""ライフ（生活ログ）機能の API の入り口（FastAPI公式の APIRouter 方式）。

機能ごとのモジュールに分けてあり、ここではそれぞれの router をまとめて main.py に渡す。
- life_days        … 祝日・曜日振替（day_info）と共通の定数（API なし）
- life_briefing    … 今日のブリーフィング・AI の今日のプラン・週間予定のコピペ用テキスト
- life_habits      … 習慣の一覧・登録・削除・履歴（/api/habits）
- life_stats       … 最近の傾向・平均勉強時間・日次サマリー・週次レポート
- life_schedule    … 時間割・休講・曜日振替
- life_events      … 単発予定・手入力の実績
- life_assignments … ルーレット項目（assignments）・毎週の課題
- life_pc          … PC使用セッション（pc_tracker.py から）
- life_calendar    … 月カレンダー・1日分まとめ（/api/life/day）

他のモジュール（main・todo_api・gcal_sync・presence_api など）やテストは、これまでどおり
life_api.day_info などの名前で使えるように、ここから読み込み直して公開している。
"""
from fastapi import APIRouter

from . import (life_assignments, life_briefing, life_calendar, life_events, life_habits, life_pc,
               life_schedule, life_stats)
from .life_assignments import (ASSIGNMENT_PREFIX, ROULETTE_TAGS, TAG_ICON, all_tags,
                               complete_assignment_by_label, due_items, ensure_recurring_instances,
                               register_tags, roulette_pool_items, sync_assignments_to_mustdo)
from .life_briefing import briefing
from .life_days import HABIT_CAT, day_info
from .life_habits import delete_habit, habit_blocks_for

__all__ = [
    "router",
    "ASSIGNMENT_PREFIX", "ROULETTE_TAGS", "TAG_ICON", "all_tags", "complete_assignment_by_label",
    "due_items", "ensure_recurring_instances", "register_tags", "roulette_pool_items",
    "sync_assignments_to_mustdo",
    "briefing",
    "HABIT_CAT", "day_info",
    "delete_habit", "habit_blocks_for",
]

router = APIRouter()
# 登録の順番は分ける前の life_api.py で最初に出てくる順に合わせている
# （同じ URL・同じメソッドのルートは無いので、順番で動きは変わらない）
for _module in (life_briefing, life_habits, life_stats, life_schedule, life_events,
                life_assignments, life_pc, life_calendar):
    router.include_router(_module.router)
