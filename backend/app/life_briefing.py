"""☀️ 今日のブリーフィング（ホーム最上部の「今日の一枚」）・AI の今日のプラン・週間予定のコピペ用テキスト。

gcal_sync は life_api（→ このモジュール）を読み込むので、gcal_sync・jobs_api・todo_api・money_api は
関数の中で読み込む（import の循環を避ける）。
"""
from datetime import date as date_cls, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import crud, models
from .database import get_db
from .life_assignments import TAG_ICON, due_items, ensure_recurring_instances
from .life_days import HABIT_CAT, day_info
from .life_habits import habit_blocks_for

router = APIRouter()


# ---------- ☀️ 今日のブリーフィング（ホーム最上部の「今日の一枚」） ----------
@router.get("/api/briefing")
def briefing(db: Session = Depends(get_db)):
    """今日の授業・予定・期限が近い課題・直近の就活日程・勉強・お金を1回でまとめて返す"""
    today = date_cls.today()
    t = today.isoformat()
    info = day_info(db, t)

    # 🎓 今日の授業（実効曜日・休講を反映）＋今日の全時間割（「いまの予定」表示用）
    cancelled = {
        r.block_id for r in db.execute(
            select(models.ScheduleCancellation)
            .where(models.ScheduleCancellation.date == t)
        ).scalars().all()
    }
    timetable = sorted(
        [{"start": b.start, "end": b.end, "title": b.title,
          "category": b.category, "room": b.room or ""}
         for b in db.execute(
             select(models.ScheduleBlock)
             .where(models.ScheduleBlock.enabled == True,  # noqa: E712
                    models.ScheduleBlock.weekday == info["effective_weekday"],
                    models.ScheduleBlock.category != HABIT_CAT)  # 習慣は todo_items から
         ).scalars().all() if b.id not in cancelled]
        + [{"start": h["start"], "end": h["end"], "title": h["title"],
            "category": HABIT_CAT, "room": ""} for h in habit_blocks_for(db, t)],
        key=lambda x: x["start"],
    )
    classes = [b for b in timetable if b["category"] == "大学"]

    # 📌 今日の単発予定（done＝ホームでチェックできる）
    events = [
        {"id": e.id, "start": e.start, "end": e.end, "title": e.title,
         "done": bool(e.done)}
        for e in db.execute(
            select(models.LifeEvent).where(models.LifeEvent.date == t)
            .order_by(models.LifeEvent.start)
        ).scalars().all()
    ]

    # 🎲 期限3日以内の未完了ルーレット項目（期限つきのみ）
    ensure_recurring_instances(db)
    limit = (today + timedelta(days=3)).isoformat()
    assignments = []
    for a in due_items(db, end=limit):
        try:
            days_left = (datetime.strptime(a.due_date, "%Y-%m-%d").date() - today).days
        except ValueError:
            days_left = 0
        assignments.append({"id": a.id, "title": a.title, "due": a.due_date,
                            "progress": a.progress, "daysLeft": days_left,
                            "note": a.note or "", "category": a.category or "その他",
                            "focus": bool(a.focus), "enabled": bool(a.enabled)})

    # 💼 7日以内の就活日程＋被り件数
    from . import jobs_api
    jobs = sorted(
        jobs_api.events_between(db, t, (today + timedelta(days=7)).isoformat()),
        key=lambda j: (j["date"], j.get("start") or ""),
    )
    conflicts = len(jobs_api.find_conflicts(db))

    # ⏱ 勉強（今日ここまで／昨日／目標）
    st = crud.get_or_create_state(db)
    y = (today - timedelta(days=1)).isoformat()
    yesterday_min = crud.study_minutes(db, y)

    # 💰 今月の支出と残り（仕送り比）・今日の支出
    #    マネータブの「今月の収支」と同じ定義：残り = 仕送り −（今月の通常支出 ＋ 固定費・サブスクの月あたり合計）
    settings = crud.get_all_settings(db)
    allowance = settings.get("money_allowance")
    ym = t[:7]
    month_spent = 0.0
    today_spent = 0.0
    for e in db.execute(
        select(models.MoneyEntry)
        .where(models.MoneyEntry.kind == "spend",
               models.MoneyEntry.date.like(f"{ym}%"))
    ).scalars().all():
        month_spent += float(e.amount or 0)
        if e.date == t:
            today_spent += float(e.amount or 0)
    subs_monthly = 0.0  # 固定費・サブスクの月あたり（frontend logic.js の monthlyOf と同じ計算）
    for e in db.execute(
        select(models.MoneyEntry).where(models.MoneyEntry.kind == "sub")
    ).scalars().all():
        amount = float(e.amount or 0)
        subs_monthly += amount / e.plan_months if (e.plan_months or 0) > 0 else amount

    # 🔴 今日の必須（todo_items kind=must）。mustdo は互換用に「未完了のタイトル」
    from . import gcal_sync, todo_api
    td = todo_api.todo_today(db)
    must = td["must"]
    mustdo = [m["title"] for m in must if not m["checked"]]

    # 🤖 AIが作った今日のプラン（今日の分があれば返す）
    plan = settings.get("ai_day_plan") or {}
    ai_plan = plan.get("text") if plan.get("date") == t else None

    return {
        "date": t,
        "is_holiday": info["is_holiday"],
        "holiday_name": info["holiday_name"],
        "overridden": info["effective_weekday"] != info["weekday"],
        "classes": classes,
        "timetable": timetable,  # 今日の全時間割（生活・習慣なども含む。「いまの予定」表示用）
        "mustdo": mustdo,
        "must": must,                    # [{id,title,checked,level,at}]
        "todo_habits": td["habits"],     # 今日の習慣の状態
        "todo_periodic": td["periodic"],
        "tasks_done": td["tasks_done"],
        "ai_plan": ai_plan,
        "events": events,
        "google": gcal_sync.google_events_for(db, t),  # Googleメインカレンダーの今日の予定（表示専用）
        "assignments": assignments,
        "jobs": jobs[:5],
        "job_conflicts": conflicts,
        "study": {
            "today_min": crud.study_minutes(db, t),
            "yesterday_min": yesterday_min,
            "target_min": st.target_value,
        },
        "money": {
            "allowance": allowance,
            "month_spent": round(month_spent),
            "subs_monthly": round(subs_monthly),
            "remaining": (round(float(allowance) - month_spent - subs_monthly)
                          if allowance not in (None, "") else None),
            "today_spent": round(today_spent),
        },
    }


# ---------- 📋 週間予定＋残課題のコピペ用テキスト ----------
@router.get("/api/export/week_text")
def export_week_text(db: Session = Depends(get_db)):
    """今日から7日分の予定と未完了課題を、そのまま貼れるテキストにして返す"""
    from . import jobs_api
    today = date_cls.today()
    day_names = "月火水木金土日"
    lines = [f"■ 週間予定（{today.isoformat()} から7日間）"]
    for i in range(7):
        d = today + timedelta(days=i)
        ds = d.isoformat()
        info = day_info(db, ds)
        head = f"{d.month}/{d.day}（{day_names[d.weekday()]}）"
        if info["holiday_name"]:
            head += f" 🎌{info['holiday_name']}"
        day_lines = []
        # 授業（実効曜日・休講反映）
        cancelled = {
            r.block_id for r in db.execute(
                select(models.ScheduleCancellation)
                .where(models.ScheduleCancellation.date == ds)
            ).scalars().all()
        }
        classes = [b for b in db.execute(
            select(models.ScheduleBlock)
            .where(models.ScheduleBlock.enabled == True,  # noqa: E712
                   models.ScheduleBlock.category == "大学",
                   models.ScheduleBlock.weekday == info["effective_weekday"])
            .order_by(models.ScheduleBlock.start)
        ).scalars().all() if b.id not in cancelled]
        if classes:
            day_lines.append("  授業: " + "、".join(
                f"{b.start} {b.title}" for b in classes))
        for ev in db.execute(
            select(models.LifeEvent).where(models.LifeEvent.date == ds)
            .order_by(models.LifeEvent.start)
        ).scalars().all():
            day_lines.append(f"  予定: {ev.start}〜{ev.end} {ev.title}"
                             + (f"（{ev.note}）" if (ev.note or "").strip() else ""))
        for je in jobs_api.events_between(db, ds, ds):
            choice = f"（第{je['choice']}希望）" if je.get("choice") else ""
            day_lines.append(f"  就活: {je.get('company', '')} {je['label']}{choice}".rstrip())
        lines.append(head + ("" if day_lines else "  予定なし"))
        lines.extend(day_lines)

    ensure_recurring_instances(db)
    undone = due_items(db)
    lines.append("")
    lines.append(f"■ 期限のある項目（{len(undone)}件）")
    for a in undone:
        lines.append(f"・{TAG_ICON.get(a.category or 'その他', '📌')} {a.title}"
                     f"｜期限 {a.due_date}｜進捗 {a.progress}%")
    if not undone:
        lines.append("なし 🎉")
    return {"text": "\n".join(lines)}


# ---------- 🤖 AIが今日の行動プランを作る ----------
@router.post("/api/briefing/ai_plan")
def briefing_ai_plan(db: Session = Depends(get_db)):
    """ブリーフィングの内容を AI（money_api.call_ai。今は Gemini）に渡し、今日の行動プラン（短い文章）を作る。

    マネータブで設定済みのAPIキーを使う（未設定なら400）。
    結果は settings の ai_day_plan に保存され、ホーム表示と
    Googleカレンダーの「📌 今日やること」イベントにも載る。
    """
    from . import money_api
    b = briefing(db)

    lines = []
    if b["mustdo"]:
        lines.append("【今日の必須（未完了）】" + "、".join(b["mustdo"][:8]))
    if b["assignments"]:
        lines.append("【期限が近い課題】" + "、".join(
            f"{a['title']}（あと{a['daysLeft']}日・{a['progress']}%）"
            for a in b["assignments"][:8]))
    if b["classes"]:
        lines.append("【今日の授業】" + "、".join(
            f"{c['start']} {c['title']}" for c in b["classes"]))
    if b["events"]:
        lines.append("【今日の予定】" + "、".join(
            f"{e['start']} {e['title']}" for e in b["events"]))
    if b["jobs"]:
        lines.append("【直近の就活】" + "、".join(
            f"{j['date'][5:]} {j.get('company', '')} {j['label']}".strip()
            for j in b["jobs"][:5]))
    st = b["study"]
    lines.append(f"【勉強】今日ここまで{st['today_min']}分／目標{st['target_min']}分"
                 f"（昨日{st['yesterday_min']}分）")
    if b["is_holiday"]:
        lines.append(f"【今日】祝日（{b['holiday_name']}）")

    system_text = (
        "あなたは大学生の学習コーチです。渡された今日の状況から、"
        "今日の行動プランを日本語で作ってください。"
        "・優先順位が分かる番号付きの箇条書きで4〜7行"
        "・授業や予定の合間のどの時間帯に何をやるかまで具体的に"
        "・最後に一言だけ励ましを添える"
        "・全体で350字以内。前置きや復唱はしない"
    )
    text = money_api.call_ai(db, system_text, "\n".join(lines), max_tokens=600)
    today = date_cls.today().isoformat()
    crud.set_setting(db, "ai_day_plan", {"date": today, "text": text})
    db.commit()
    return {"ok": True, "date": today, "text": text}
