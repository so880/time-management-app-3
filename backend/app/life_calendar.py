"""月カレンダー（/api/life/calendar）と1日分まとめ（/api/life/day、タイムライン用）の API。

gcal_sync・jobs_api は関数の中で読み込む（gcal_sync が life_api を読み込むため、import の循環を避ける）。
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models
from .database import get_db
from .life_days import HABIT_CAT, day_info
from .life_events import event_dict, list_entries, list_events
from .life_habits import habit_blocks_for
from .life_pc import pc_sessions_for_date
from .life_schedule import schedule_dict

router = APIRouter()


# ---------- 月カレンダー ----------
@router.get("/api/life/calendar")
def calendar_month(month: str, db: Session = Depends(get_db)):
    """月カレンダー用：各日の 祝日/振替・単発予定・課題期限・授業コマ数 をまとめて返す"""
    try:
        first = datetime.strptime(month + "-01", "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="month は YYYY-MM 形式で指定してください")
    if first.month == 12:
        next_first = first.replace(year=first.year + 1, month=1)
    else:
        next_first = first.replace(month=first.month + 1)
    n_days = (next_first - first).days

    # 月内の単発予定・課題・休講をまとめて取得
    m_start = first.isoformat()
    m_end = (next_first - timedelta(days=1)).isoformat()
    events_by_day: dict[str, list] = {}
    for ev in db.execute(
        select(models.LifeEvent)
        .where(models.LifeEvent.date >= m_start, models.LifeEvent.date <= m_end)
        .order_by(models.LifeEvent.start)
    ).scalars().all():
        events_by_day.setdefault(ev.date, []).append(event_dict(ev))
    asg_by_day: dict[str, list] = {}
    for a in db.execute(
        select(models.Assignment)
        .where(models.Assignment.due_date >= m_start, models.Assignment.due_date <= m_end)
        .order_by(models.Assignment.id)
    ).scalars().all():
        asg_by_day.setdefault(a.due_date, []).append(
            {"id": a.id, "title": a.title, "progress": a.progress,
             "done": a.progress >= 100, "recurring": a.recurring_id is not None,
             "category": a.category or "その他"})
    cancelled_by_day: dict[str, set] = {}
    for c in db.execute(
        select(models.ScheduleCancellation)
        .where(models.ScheduleCancellation.date >= m_start,
               models.ScheduleCancellation.date <= m_end)
    ).scalars().all():
        cancelled_by_day.setdefault(c.date, set()).add(c.block_id)

    # 曜日別の授業（大学カテゴリ）ブロック
    uni_by_wd: dict[int, list] = {}
    for b in db.execute(
        select(models.ScheduleBlock)
        .where(models.ScheduleBlock.enabled == True,  # noqa: E712
               models.ScheduleBlock.category == "大学")
    ).scalars().all():
        uni_by_wd.setdefault(b.weekday, []).append(b)

    # 就活の日程（期間ものは各日に展開する）
    from . import jobs_api
    jobs_by_day: dict[str, list] = {}
    for je in jobs_api.events_between(db, m_start, m_end):
        j_start = je["date"]
        j_end = je["endDate"] or je["date"]
        if j_end < j_start:
            j_start, j_end = j_end, j_start
        cur = max(j_start, m_start)
        last = min(j_end, m_end)
        dd = datetime.strptime(cur, "%Y-%m-%d").date()
        end_d = datetime.strptime(last, "%Y-%m-%d").date()
        while dd <= end_d:
            jobs_by_day.setdefault(dd.isoformat(), []).append(je)
            dd += timedelta(days=1)

    # Googleメインカレンダーの予定（読み取り専用。5分ごとに取り込んだもの）
    from . import gcal_sync
    google_by_day = gcal_sync.google_events_between(db, m_start, m_end)

    days = []
    for i in range(n_days):
        d = (first + timedelta(days=i)).isoformat()
        info = day_info(db, d)
        cancelled = cancelled_by_day.get(d, set())
        classes = [b for b in uni_by_wd.get(info["effective_weekday"], [])
                   if b.id not in cancelled]
        days.append({
            "date": d,
            **info,
            "events": events_by_day.get(d, []),
            "assignments": asg_by_day.get(d, []),
            "jobs": jobs_by_day.get(d, []),
            "google": google_by_day.get(d, []),
            "class_count": len(classes),
            "class_titles": [b.title for b in classes][:4],
        })
    return {"month": month, "days": days}


# ---------- 1日分まとめ ----------
@router.get("/api/life/day")
def get_day(date: str, db: Session = Depends(get_db)):
    """タイムライン用：その日の予定・実績・勉強記録・PC使用をまとめて返す。

    時間割は 実効曜日（祝日・振替を反映）で選ぶ。
    """
    info = day_info(db, date)
    weekday = info["effective_weekday"]  # 祝日・振替を反映した曜日

    cancelled_ids = {
        r.block_id for r in db.execute(
            select(models.ScheduleCancellation)
            .where(models.ScheduleCancellation.date == date)
        ).scalars().all()
    }
    schedule = []
    for r in db.execute(
        select(models.ScheduleBlock)
        .where(models.ScheduleBlock.weekday == weekday,
               models.ScheduleBlock.enabled == True,  # noqa: E712
               models.ScheduleBlock.category != HABIT_CAT)  # 習慣は todo_items から
        .order_by(models.ScheduleBlock.start)
    ).scalars().all():
        d = schedule_dict(r)
        d["cancelled"] = r.id in cancelled_ids  # 休講フラグ
        schedule.append(d)
    schedule.extend(habit_blocks_for(db, date))  # 習慣（id は負の値）
    schedule.sort(key=lambda x: x["start"])
    events = list_events(date, db)
    entries = list_entries(date, db)

    # 勉強アプリの記録（activity_log）→ 「日付」列は終了時刻なので開始を逆算
    study = []
    logs = db.execute(
        select(models.ActivityLog).where(models.ActivityLog.date.like(date + "%"))
        .order_by(models.ActivityLog.id)
    ).scalars().all()
    for r in logs:
        if r.minutes <= 0:
            continue
        try:
            end_dt = datetime.strptime(r.date, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        start_dt = end_dt - timedelta(minutes=r.minutes)
        study.append({
            "start": start_dt.strftime("%H:%M"),
            "end": end_dt.strftime("%H:%M"),
            "title": r.content,
            "category": r.category,
            "minutes": r.minutes,
        })

    from . import gcal_sync
    return {
        "date": date,
        **info,  # weekday / effective_weekday / is_holiday / holiday_name / override
        "schedule": schedule,
        "events": events,
        "google": gcal_sync.google_events_for(db, date),  # Googleメインカレンダー（表示専用）
        "entries": entries,
        "study": study,
        "pc": pc_sessions_for_date(db, date),
    }
