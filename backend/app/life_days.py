"""祝日・曜日振替（その日に「どの曜日の時間割」を使うか）と、ライフ機能で共通の定数。

API（ルート）を持たないので、todo_api・gcal_sync・presence_api などどこから読み込んでも
import の循環が起きない。
"""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models

# 日本の祝日判定（pip install jpholiday。未導入でも動くフォールバック付き）
try:
    import jpholiday
except ImportError:
    jpholiday = None

HABIT_CAT = "習慣"   # 時間割・タイムライン・GCal 上での表示カテゴリ名（データは todo_items）


def day_info(db: Session, date: str) -> dict:
    """その日の 実効曜日（effective_weekday）と祝日・振替情報を返す。

    優先順位：
      1. 手動の振替（day_overrides）… holiday=土曜日程扱い / weekday=指定曜日の日程
      2. 祝日（jpholiday）… 平日でも土曜と同じ扱い（生活リズムのみ）
      3. 通常のカレンダー曜日
    """
    d = datetime.strptime(date, "%Y-%m-%d").date()
    real_wd = d.weekday()
    ov = db.execute(
        select(models.DayOverride).where(models.DayOverride.date == date)
    ).scalars().first()
    holiday_name = jpholiday.is_holiday_name(d) if jpholiday else None

    if ov is not None:
        eff = 5 if ov.mode == "holiday" else int(ov.weekday if ov.weekday is not None else real_wd)
        ov_dict = {"id": ov.id, "date": ov.date, "mode": ov.mode, "weekday": ov.weekday}
    elif holiday_name and real_wd < 5:
        eff = 5  # 祝日は土日と同じ扱い（土曜の時間割＝生活リズムのみ）
        ov_dict = None
    else:
        eff = real_wd
        ov_dict = None
    return {
        "weekday": real_wd,
        "effective_weekday": eff,
        "is_holiday": bool(holiday_name),
        "holiday_name": holiday_name,
        "override": ov_dict,
    }
