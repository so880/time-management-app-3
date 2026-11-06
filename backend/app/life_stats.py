"""集計の API：最近の傾向・平均勉強時間・日次サマリー・週次レポート。"""
from datetime import date as date_cls, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import crud, models
from .database import get_db
from .life_days import day_info, jpholiday
from .life_pc import pc_sessions_for_date

router = APIRouter()


# ---------- 📈 最近の傾向 ----------
def _gate_done_on(db: Session, d: date_cls, comp_by_day: dict) -> bool | None:
    """その日の「必須＋習慣」がすべて完了していたか（必須も習慣も無い日は None）"""
    from . import todo_api
    ds = d.isoformat()
    comp = comp_by_day.get(ds, {})
    must = todo_api.must_items_for_date(db, ds)
    habits = todo_api.habits_for_date(db, ds)
    if not must and not habits:
        return None
    return all(m.id in comp for m in must) and all(h.id in comp for h in habits)


@router.get("/api/stats/recent")
def stats_recent(days: int = 14, db: Session = Depends(get_db)):
    """📈 最近の傾向（ホームの折れ線グラフ用）。1日ごとに
    勉強分・習慣の達成率・ノルマ達成・stop_all（緊急解除）の有無を返す"""
    from . import todo_api
    days = max(1, min(days, 60))
    today = date_cls.today()
    since = (today - timedelta(days=days - 1)).isoformat()
    study = crud.study_minutes_by_day(db, since, today.isoformat())

    comp_by_day = todo_api.completions_since(db, since)
    from . import gate_api
    stop_days = {str(x["ts"])[:10] for x in gate_api.unlock_request_dicts(db, since)}
    day_names = "月火水木金土日"
    out = []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        ds = d.isoformat()
        due = todo_api.habits_for_date(db, ds)
        comp = comp_by_day.get(ds, {})
        done = sum(1 for h in due if h.id in comp)
        must = todo_api.must_items_for_date(db, ds)
        out.append({
            "date": ds,
            "label": f"{d.month}/{d.day}({day_names[d.weekday()]})",
            "study_min": study.get(ds, 0),
            "habit_rate": round(done / len(due) * 100) if due else None,
            "habit_done": done, "habit_due": len(due),
            "gate_done": _gate_done_on(db, d, comp_by_day),
            "gate_checked": sum(1 for m in must if m.id in comp),
            "gate_total": len(must),
            "stopped": ds in stop_days,
        })
    return out


# ---------- 📊 平均勉強時間（曜日別・平日/休日・月別） ----------
@router.get("/api/stats/study_averages")
def study_averages(days: int = 90, db: Session = Depends(get_db)):
    """直近days日間の勉強時間を、曜日別・平日/休日別・月別の「1日平均」で返す。

    平均は「勉強しなかった日も0分として含める」。
    休日 = 土日＋祝日（jpholiday）。月別は直近6ヶ月（今月は経過日数で割る）。
    """
    today = date_cls.today()
    since = today - timedelta(days=days - 1)

    # 日付ごとの勉強分数（数え方は crud.study_minutes_by_day に統一）
    per_day = crud.study_minutes_by_day(db, since.isoformat(), today.isoformat())

    def is_holiday(d) -> bool:
        if d.weekday() >= 5:
            return True
        return bool(jpholiday and jpholiday.is_holiday(d))

    day_names = "月火水木金土日"
    wd_total = [0] * 7
    wd_count = [0] * 7
    work_total = work_count = holi_total = holi_count = 0
    d = since
    while d <= today:
        m = per_day.get(d.isoformat(), 0)
        wd_total[d.weekday()] += m
        wd_count[d.weekday()] += 1
        if is_holiday(d):
            holi_total += m
            holi_count += 1
        else:
            work_total += m
            work_count += 1
        d += timedelta(days=1)

    # 月別（直近6ヶ月）：その月の経過日数で割った1日平均
    months = []
    y, mo = today.year, today.month
    for _ in range(6):
        ym = f"{y}-{mo:02d}"
        total = sum(v for k, v in per_day.items() if k.startswith(ym))
        # ただし per_day は直近days日ぶんしか無いため、古い月は全期間取り直す
        if ym < since.isoformat()[:7]:
            import calendar
            last = calendar.monthrange(y, mo)[1]
            total = sum(crud.study_minutes_by_day(db, f"{ym}-01", f"{ym}-{last:02d}").values())
        if ym == today.strftime("%Y-%m"):
            days_in = today.day
        else:
            nxt = date_cls(y + (1 if mo == 12 else 0), 1 if mo == 12 else mo + 1, 1)
            days_in = (nxt - date_cls(y, mo, 1)).days
        months.append({"ym": ym, "label": f"{mo}月",
                       "avg": round(total / days_in) if days_in else 0,
                       "total": total})
        mo -= 1
        if mo == 0:
            y, mo = y - 1, 12
    months.reverse()

    return {
        "days": days,
        "weekday": [
            {"weekday": i, "label": day_names[i],
             "avg": round(wd_total[i] / wd_count[i]) if wd_count[i] else 0}
            for i in range(7)
        ],
        "workday_avg": round(work_total / work_count) if work_count else 0,
        "holiday_avg": round(holi_total / holi_count) if holi_count else 0,
        "months": months,
    }


# ---------- 集計（日次サマリー・週次レポート） ----------
def _to_min(hhmm: str) -> int:
    try:
        h, m = str(hhmm).split(":")[:2]
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return 0


def _day_stats(db: Session, date: str) -> dict:
    """1日分のカテゴリ別合計（分）などを計算する。

    - 予定（時間割・単発）：日またぎ（睡眠23:00〜6:30等）は日ごとに分割して計上
      （前日の日またぎブロックの朝側も当日に含める）
    - 実績（手入力）・勉強アプリの記録・PC使用も合算
    - 時間割は実効曜日（祝日・振替を反映）で選ぶ
    """
    weekday = day_info(db, date)["effective_weekday"]
    prev_date = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    prev_weekday = day_info(db, prev_date)["effective_weekday"]
    cat: dict[str, int] = {}
    planned = 0  # 睡眠を除く「予定で埋まっている時間」

    def add(category: str, minutes: int):
        if minutes > 0:
            cat[category] = cat.get(category, 0) + minutes

    cancelled_ids = {
        r.block_id for r in db.execute(
            select(models.ScheduleCancellation)
            .where(models.ScheduleCancellation.date == date)
        ).scalars().all()
    }

    def block_minutes(start: str, end: str, morning_part: bool) -> int:
        s, e = _to_min(start), _to_min(end)
        if morning_part:              # 前日ブロックの 0:00〜end 部分
            return e if e <= s else 0
        return (e - s) if e > s else (1440 - s)  # 日またぎは当日は start〜24:00

    # 時間割（当日ぶん＋前日の日またぎの朝側）
    for wd, morning in ((weekday, False), (prev_weekday, True)):
        for b in db.execute(
            select(models.ScheduleBlock)
            .where(models.ScheduleBlock.weekday == wd,
                   models.ScheduleBlock.enabled == True)  # noqa: E712
        ).scalars().all():
            if morning and _to_min(b.end) > _to_min(b.start):
                continue  # 日またぎでない前日ブロックは無関係
            if not morning and b.id in cancelled_ids:
                continue  # 休講
            m = block_minutes(b.start, b.end, morning)
            add(b.category, m)
            if b.category != "睡眠":
                planned += m

    # 単発予定
    for ev in db.execute(
        select(models.LifeEvent).where(models.LifeEvent.date == date)
    ).scalars().all():
        m = block_minutes(ev.start, ev.end, False)
        add(ev.category, m)
        if ev.category != "睡眠":
            planned += m

    # 手入力の実績
    recorded_free = 0
    for en in db.execute(
        select(models.LifeEntry).where(models.LifeEntry.date == date)
    ).scalars().all():
        m = block_minutes(en.start, en.end, False)
        add(en.category, m)
        recorded_free += m

    # 勉強アプリの記録
    study_minutes = 0
    refresh_minutes = 0
    for r in db.execute(
        select(models.ActivityLog).where(models.ActivityLog.date.like(date + "%"))
    ).scalars().all():
        if r.minutes <= 0:
            continue
        if crud.is_study_category(r.category):
            add("勉強", r.minutes)
            study_minutes += r.minutes
            recorded_free += r.minutes
        elif "気分転換" in r.category:
            add("気分転換", r.minutes)
            refresh_minutes += r.minutes
            recorded_free += r.minutes

    # PC使用（アプリ別・カテゴリ集計とは別枠）
    pc_apps: dict[str, int] = {}
    pc_total = 0
    for s in pc_sessions_for_date(db, date):
        m = int((s["end_ts"] - s["start_ts"]) / 60)
        if m <= 0:
            continue
        app = s["app"].lower().removesuffix(".exe")
        pc_apps[app] = pc_apps.get(app, 0) + m
        pc_total += m

    sleep = cat.get("睡眠", 0)
    free = max(0, 1440 - sleep - planned)
    unrecorded = max(0, free - recorded_free)

    return {
        "date": date,
        "categories": cat,
        "planned_minutes": planned,
        "sleep_minutes": sleep,
        "free_minutes": free,
        "recorded_free_minutes": min(recorded_free, free) if free else recorded_free,
        "unrecorded_minutes": unrecorded,
        "study_minutes": study_minutes,
        "refresh_minutes": refresh_minutes,
        "pc_total_minutes": pc_total,
        "pc_apps": sorted(
            [{"app": a, "minutes": m} for a, m in pc_apps.items()],
            key=lambda x: -x["minutes"])[:8],
    }


def _money_day(db: Session, date: str) -> dict:
    """その日の支出（金銭管理・通常支出のみ）"""
    rows = db.execute(
        select(models.MoneyEntry)
        .where(models.MoneyEntry.kind == "spend", models.MoneyEntry.date == date)
        .order_by(models.MoneyEntry.amount.desc())
    ).scalars().all()
    return {
        "total": sum(r.amount for r in rows),
        "count": len(rows),
        "items": [{"detail": r.detail or r.category, "category": r.category,
                   "amount": r.amount} for r in rows[:5]],
    }


@router.get("/api/life/summary")
def day_summary(date: str, db: Session = Depends(get_db)):
    """日次サマリー（当日＋比較用に前日も返す。今日の支出も含む）"""
    prev = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    today = _day_stats(db, date)
    yesterday = _day_stats(db, prev)
    today["money"] = _money_day(db, date)
    yesterday["money"] = _money_day(db, prev)
    return {"today": today, "yesterday": yesterday}


@router.get("/api/life/week")
def week_summary(date: str, db: Session = Depends(get_db)):
    """週次レポート（その日付を含む月曜はじまりの1週間）"""
    d = datetime.strptime(date, "%Y-%m-%d")
    monday = d - timedelta(days=d.weekday())
    days = []
    pc_apps: dict[str, int] = {}
    for i in range(7):
        day = (monday + timedelta(days=i)).strftime("%Y-%m-%d")
        st = _day_stats(db, day)
        days.append(st)
        for a in st["pc_apps"]:
            pc_apps[a["app"]] = pc_apps.get(a["app"], 0) + a["minutes"]

    # 課題：今週期限のもの
    week_start = monday.strftime("%Y-%m-%d")
    week_end = (monday + timedelta(days=6)).strftime("%Y-%m-%d")
    asg = db.execute(
        select(models.Assignment)
        .where(models.Assignment.due_date >= week_start,
               models.Assignment.due_date <= week_end)
    ).scalars().all()
    today = date_cls.today().isoformat()
    # 今週の支出（金銭管理・通常支出）
    money_rows = db.execute(
        select(models.MoneyEntry)
        .where(models.MoneyEntry.kind == "spend",
               models.MoneyEntry.date >= week_start,
               models.MoneyEntry.date <= week_end)
    ).scalars().all()
    money_by_cat: dict[str, float] = {}
    for r in money_rows:
        money_by_cat[r.category] = money_by_cat.get(r.category, 0) + r.amount

    return {
        "week_start": week_start,
        "week_end": week_end,
        "days": days,
        "money_total": sum(r.amount for r in money_rows),
        "money_by_category": sorted(
            [{"category": c, "amount": a} for c, a in money_by_cat.items()],
            key=lambda x: -x["amount"])[:6],
        "study_total": sum(x["study_minutes"] for x in days),
        "pc_apps": sorted(
            [{"app": a, "minutes": m} for a, m in pc_apps.items()],
            key=lambda x: -x["minutes"])[:8],
        "assignments": {
            "total": len(asg),
            "done": sum(1 for a in asg if a.progress >= 100),
            "overdue": sum(1 for a in asg if a.progress < 100 and a.due_date < today),
        },
    }
