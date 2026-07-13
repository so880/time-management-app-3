"""ライフ（生活ログ）機能のAPI（FastAPI公式の APIRouter 方式）。

- 時間割（曜日別の繰り返し予定）・単発予定・手入力実績の CRUD
- PC使用セッションの受け取り（pc_tracker.py から）
- 1日分まとめ取得（/api/life/day）：予定＋実績＋勉強記録＋PC使用
"""
from datetime import date as date_cls, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import crud, models
from .database import get_db

# 日本の祝日判定（pip install jpholiday。未導入でも動くフォールバック付き）
try:
    import jpholiday
except ImportError:
    jpholiday = None

router = APIRouter()


# ---------- 祝日・曜日振替（その日に「どの曜日の時間割」を使うか） ----------
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

ASSIGNMENT_PREFIX = "【課題】"  # mustdo に自動追加するときの目印
DUE_SOON_DAYS = 2              # この日数以内の期限で「今日絶対やる」へ自動追加


# ---------- 毎週の課題 → 週ごとのインスタンス自動生成 ----------
def next_due_date(weekday: int) -> str:
    """次にその曜日が来る日付（今日がその曜日なら今日）を返す"""
    today = date_cls.today()
    delta = (weekday - today.weekday()) % 7
    return (today + timedelta(days=delta)).isoformat()


def ensure_recurring_instances(db: Session) -> None:
    """有効な「毎週の課題」それぞれについて、次の期限日のインスタンスが
    無ければ作る（週ごとに1つ・完了済みでも同じ期限日には作り直さない）。

    → 今週分を完了・削除しても、期限日が過ぎれば翌週分が自動生成される。
    """
    recs = db.execute(
        select(models.RecurringAssignment)
        .where(models.RecurringAssignment.enabled == True)  # noqa: E712
    ).scalars().all()
    added = False
    for r in recs:
        due = next_due_date(r.weekday)
        exists = db.execute(
            select(models.Assignment)
            .where(models.Assignment.recurring_id == r.id,
                   models.Assignment.due_date == due)
        ).scalars().first()
        if exists is None:
            db.add(models.Assignment(
                title=r.title, due_date=due, progress=0, note="",
                created=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                recurring_id=r.id,
            ))
            added = True
    if added:
        db.commit()


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
        ({"start": b.start, "end": b.end, "title": b.title,
          "category": b.category, "room": b.room or ""}
         for b in db.execute(
             select(models.ScheduleBlock)
             .where(models.ScheduleBlock.enabled == True,  # noqa: E712
                    models.ScheduleBlock.weekday == info["effective_weekday"])
         ).scalars().all() if b.id not in cancelled),
        key=lambda x: x["start"],
    )
    classes = [b for b in timetable if b["category"] == "大学"]

    # 📌 今日の単発予定
    events = [
        {"start": e.start, "end": e.end, "title": e.title}
        for e in db.execute(
            select(models.LifeEvent).where(models.LifeEvent.date == t)
            .order_by(models.LifeEvent.start)
        ).scalars().all()
    ]

    # 📚 期限3日以内の未完了課題
    ensure_recurring_instances(db)
    limit = (today + timedelta(days=3)).isoformat()
    assignments = []
    for a in db.execute(
        select(models.Assignment)
        .where(models.Assignment.progress < 100,
               models.Assignment.due_date <= limit)
        .order_by(models.Assignment.due_date, models.Assignment.id)
    ).scalars().all():
        try:
            days_left = (datetime.strptime(a.due_date, "%Y-%m-%d").date() - today).days
        except ValueError:
            days_left = 0
        assignments.append({"title": a.title, "due": a.due_date,
                            "progress": a.progress, "daysLeft": days_left})

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
    yesterday_min = sum(
        int(r.minutes or 0) for r in db.execute(
            select(models.ActivityLog)
            .where(models.ActivityLog.category == "勉強",
                   models.ActivityLog.date.like(f"{y}%"))
        ).scalars().all()
    )

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

    return {
        "date": t,
        "is_holiday": info["is_holiday"],
        "holiday_name": info["holiday_name"],
        "overridden": info["effective_weekday"] != info["weekday"],
        "classes": classes,
        "timetable": timetable,  # 今日の全時間割（生活・習慣なども含む。「いまの予定」表示用）
        "events": events,
        "assignments": assignments,
        "jobs": jobs[:5],
        "job_conflicts": conflicts,
        "study": {
            "today_min": st.study_time_total,
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


# ---------- 課題 → 「今日絶対やる」自動同期 ----------
def sync_assignments_to_mustdo(db: Session) -> None:
    """期限が2日以内の未完了課題を、期限が近い順で mustdo_list の先頭に置く。

    - 目印（【課題】）付きの項目だけを自動管理する（手入力の項目には触らない）
    - 期限が遠のいた/完了した課題の項目は自動で取り除く
    """
    ensure_recurring_instances(db)  # 毎週の課題の今週分を先に用意する
    limit = (date_cls.today() + timedelta(days=DUE_SOON_DAYS)).isoformat()
    rows = db.execute(
        select(models.Assignment)
        .where(models.Assignment.progress < 100,
               models.Assignment.due_date <= limit)
        .order_by(models.Assignment.due_date, models.Assignment.id)
    ).scalars().all()
    labels = [f"{ASSIGNMENT_PREFIX}{r.title}" for r in rows]

    settings = crud.get_all_settings(db)
    current = settings.get("mustdo_list") or []
    manual = [x for x in current if not str(x).startswith(ASSIGNMENT_PREFIX)]
    new_list = labels + manual
    if new_list != current:
        crud.set_setting(db, "mustdo_list", new_list)
        # 無効リストからも消えた課題項目を掃除
        disabled = settings.get("mustdo_list_disabled") or []
        new_disabled = [x for x in disabled
                        if not str(x).startswith(ASSIGNMENT_PREFIX) or x in labels]
        if new_disabled != disabled:
            crud.set_setting(db, "mustdo_list_disabled", new_disabled)
        db.commit()


def complete_assignment_by_label(db: Session, label: str) -> None:
    """「【課題】◯◯は終わった」と答えたとき、対応する課題を完了(100%)にする"""
    if not label.startswith(ASSIGNMENT_PREFIX):
        return
    title = label[len(ASSIGNMENT_PREFIX):]
    # 同名の週次インスタンスが複数あり得るので「未完了で期限が近いもの」を対象にする
    row = db.execute(
        select(models.Assignment)
        .where(models.Assignment.title == title,
               models.Assignment.progress < 100)
        .order_by(models.Assignment.due_date)
    ).scalars().first()
    if row is not None:
        row.progress = 100
        db.commit()
    sync_assignments_to_mustdo(db)


# ---------- 入力の型 ----------
class ScheduleBlockBody(BaseModel):
    weekday: int            # 月=0 ... 日=6
    start: str              # "HH:MM"
    end: str
    title: str
    category: str = "大学"
    enabled: bool = True
    room: str = ""          # 教室などのメモ


class LifeEventBody(BaseModel):
    date: str               # "YYYY-MM-DD"
    start: str
    end: str
    title: str
    category: str = "予定"
    note: str = ""          # 場所などのメモ


class LifeEntryBody(BaseModel):
    date: str
    start: str
    end: str
    title: str
    category: str = "生活"
    note: str = ""


class CancelToggleBody(BaseModel):
    date: str               # "YYYY-MM-DD"
    block_id: int


class AssignmentBody(BaseModel):
    title: str
    due_date: str           # "YYYY-MM-DD"
    progress: int = 0       # 0〜100
    note: str = ""
    category: str = "大学"  # 大学 / 私生活 / 就活


class RecurringAssignmentBody(BaseModel):
    title: str
    weekday: int            # 期限の曜日（月=0 ... 日=6）
    enabled: bool = True


class PcSessionBody(BaseModel):
    start_ts: float
    end_ts: float
    app: str
    title: str = ""


class PcSessionsBatch(BaseModel):
    sessions: list[PcSessionBody]


# ---------- 変換 ----------
def _sched_dict(r: models.ScheduleBlock) -> dict:
    return {"id": r.id, "weekday": r.weekday, "start": r.start, "end": r.end,
            "title": r.title, "category": r.category, "enabled": r.enabled,
            "room": r.room or ""}


def _event_dict(r: models.LifeEvent) -> dict:
    return {"id": r.id, "date": r.date, "start": r.start, "end": r.end,
            "title": r.title, "category": r.category, "note": r.note or ""}


def _entry_dict(r: models.LifeEntry) -> dict:
    return {"id": r.id, "date": r.date, "start": r.start, "end": r.end,
            "title": r.title, "category": r.category, "note": r.note}


# ---------- 時間割（繰り返し予定） ----------
@router.get("/api/life/schedule")
def list_schedule(db: Session = Depends(get_db)):
    rows = db.execute(
        select(models.ScheduleBlock)
        .order_by(models.ScheduleBlock.weekday, models.ScheduleBlock.start)
    ).scalars().all()
    return [_sched_dict(r) for r in rows]


@router.post("/api/life/schedule")
def create_schedule(body: ScheduleBlockBody, db: Session = Depends(get_db)):
    row = models.ScheduleBlock(**body.model_dump())
    db.add(row)
    db.commit()
    return _sched_dict(row)


@router.put("/api/life/schedule/{block_id}")
def update_schedule(block_id: int, body: ScheduleBlockBody, db: Session = Depends(get_db)):
    row = db.get(models.ScheduleBlock, block_id)
    if row is None:
        raise HTTPException(status_code=404, detail="時間割が見つかりません")
    for k, v in body.model_dump().items():
        setattr(row, k, v)
    db.commit()
    return _sched_dict(row)


@router.delete("/api/life/schedule/{block_id}")
def delete_schedule(block_id: int, db: Session = Depends(get_db)):
    row = db.get(models.ScheduleBlock, block_id)
    if row is not None:
        db.delete(row)
        db.commit()
    return {"ok": True}


# ---------- 単発予定 ----------
@router.get("/api/life/events")
def list_events(date: str, db: Session = Depends(get_db)):
    rows = db.execute(
        select(models.LifeEvent).where(models.LifeEvent.date == date)
        .order_by(models.LifeEvent.start)
    ).scalars().all()
    return [_event_dict(r) for r in rows]


@router.post("/api/life/events")
def create_event(body: LifeEventBody, db: Session = Depends(get_db)):
    row = models.LifeEvent(**body.model_dump())
    db.add(row)
    db.commit()
    return _event_dict(row)


@router.delete("/api/life/events/{event_id}")
def delete_event(event_id: int, db: Session = Depends(get_db)):
    row = db.get(models.LifeEvent, event_id)
    if row is not None:
        db.delete(row)
        db.commit()
    return {"ok": True}


# ---------- 手入力の実績 ----------
@router.get("/api/life/entries")
def list_entries(date: str, db: Session = Depends(get_db)):
    rows = db.execute(
        select(models.LifeEntry).where(models.LifeEntry.date == date)
        .order_by(models.LifeEntry.start)
    ).scalars().all()
    return [_entry_dict(r) for r in rows]


@router.post("/api/life/entries")
def create_entry(body: LifeEntryBody, db: Session = Depends(get_db)):
    row = models.LifeEntry(**body.model_dump())
    db.add(row)
    db.commit()
    return _entry_dict(row)


@router.put("/api/life/entries/{entry_id}")
def update_entry(entry_id: int, body: LifeEntryBody, db: Session = Depends(get_db)):
    row = db.get(models.LifeEntry, entry_id)
    if row is None:
        raise HTTPException(status_code=404, detail="実績が見つかりません")
    for k, v in body.model_dump().items():
        setattr(row, k, v)
    db.commit()
    return _entry_dict(row)


@router.delete("/api/life/entries/{entry_id}")
def delete_entry(entry_id: int, db: Session = Depends(get_db)):
    row = db.get(models.LifeEntry, entry_id)
    if row is not None:
        db.delete(row)
        db.commit()
    return {"ok": True}


# ---------- 休講 ----------
@router.post("/api/life/cancel_toggle")
def toggle_cancellation(body: CancelToggleBody, db: Session = Depends(get_db)):
    """その日のその授業の休講を切り替える（あれば解除・なければ登録）"""
    row = db.execute(
        select(models.ScheduleCancellation)
        .where(models.ScheduleCancellation.date == body.date,
               models.ScheduleCancellation.block_id == body.block_id)
    ).scalars().first()
    if row is None:
        db.add(models.ScheduleCancellation(date=body.date, block_id=body.block_id))
        cancelled = True
    else:
        db.delete(row)
        cancelled = False
    db.commit()
    return {"cancelled": cancelled}


# ---------- 課題（Notion風） ----------
def _assignment_dict(r: models.Assignment) -> dict:
    today = date_cls.today()
    try:
        due = datetime.strptime(r.due_date, "%Y-%m-%d").date()
        days_left = (due - today).days
    except ValueError:
        days_left = None
    return {"id": r.id, "title": r.title, "due_date": r.due_date,
            "progress": r.progress, "note": r.note,
            "category": r.category or "大学",
            "days_left": days_left, "done": r.progress >= 100,
            "recurring": r.recurring_id is not None}


@router.get("/api/assignments")
def list_assignments(db: Session = Depends(get_db)):
    """課題一覧（未完了を期限が近い順に、完了は後ろに）"""
    ensure_recurring_instances(db)  # 表示時にも週次インスタンスを最新化
    rows = db.execute(
        select(models.Assignment)
        .order_by(models.Assignment.progress >= 100,
                  models.Assignment.due_date, models.Assignment.id)
    ).scalars().all()
    return [_assignment_dict(r) for r in rows]


# ---------- 毎週の課題（テンプレート） ----------
# 注意：/api/assignments/{assignment_id} より先に定義すること（ルート解決順）
def _recurring_dict(r: models.RecurringAssignment) -> dict:
    return {"id": r.id, "title": r.title, "weekday": r.weekday, "enabled": r.enabled}


@router.get("/api/assignments/recurring")
def list_recurring(db: Session = Depends(get_db)):
    rows = db.execute(
        select(models.RecurringAssignment)
        .order_by(models.RecurringAssignment.weekday, models.RecurringAssignment.id)
    ).scalars().all()
    return [_recurring_dict(r) for r in rows]


@router.post("/api/assignments/recurring")
def create_recurring(body: RecurringAssignmentBody, db: Session = Depends(get_db)):
    row = models.RecurringAssignment(**body.model_dump())
    db.add(row)
    db.commit()
    sync_assignments_to_mustdo(db)  # 今週分のインスタンスも即生成
    return _recurring_dict(row)


@router.put("/api/assignments/recurring/{recurring_id}")
def update_recurring(recurring_id: int, body: RecurringAssignmentBody,
                     db: Session = Depends(get_db)):
    row = db.get(models.RecurringAssignment, recurring_id)
    if row is None:
        raise HTTPException(status_code=404, detail="毎週の課題が見つかりません")
    row.title = body.title
    row.weekday = body.weekday
    row.enabled = body.enabled
    db.commit()
    sync_assignments_to_mustdo(db)
    return _recurring_dict(row)


@router.delete("/api/assignments/recurring/{recurring_id}")
def delete_recurring(recurring_id: int, db: Session = Depends(get_db)):
    """テンプレートを削除（未完了の今週分インスタンスも一緒に片付ける）"""
    row = db.get(models.RecurringAssignment, recurring_id)
    if row is not None:
        for inst in db.execute(
            select(models.Assignment)
            .where(models.Assignment.recurring_id == recurring_id,
                   models.Assignment.progress < 100)
        ).scalars().all():
            label = f"{ASSIGNMENT_PREFIX}{inst.title}"
            settings = crud.get_all_settings(db)
            current = settings.get("mustdo_list") or []
            if label in current:
                crud.set_setting(db, "mustdo_list", [x for x in current if x != label])
            db.delete(inst)
        db.delete(row)
        db.commit()
        sync_assignments_to_mustdo(db)
    return {"ok": True}


@router.post("/api/assignments")
def create_assignment(body: AssignmentBody, db: Session = Depends(get_db)):
    row = models.Assignment(
        title=body.title, due_date=body.due_date,
        progress=max(0, min(100, body.progress)), note=body.note,
        category=body.category or "大学",
        created=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    db.add(row)
    db.commit()
    sync_assignments_to_mustdo(db)
    return _assignment_dict(row)


@router.put("/api/assignments/{assignment_id}")
def update_assignment(assignment_id: int, body: AssignmentBody, db: Session = Depends(get_db)):
    row = db.get(models.Assignment, assignment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="課題が見つかりません")
    old_label = f"{ASSIGNMENT_PREFIX}{row.title}"
    row.title = body.title
    row.due_date = body.due_date
    row.progress = max(0, min(100, body.progress))
    row.note = body.note
    row.category = body.category or "大学"
    db.commit()
    # 題名が変わった場合、mustdo の古い項目を掃除してから同期
    settings = crud.get_all_settings(db)
    current = settings.get("mustdo_list") or []
    if old_label in current and old_label != f"{ASSIGNMENT_PREFIX}{row.title}":
        crud.set_setting(db, "mustdo_list", [x for x in current if x != old_label])
        db.commit()
    sync_assignments_to_mustdo(db)
    return _assignment_dict(row)


@router.delete("/api/assignments/{assignment_id}")
def delete_assignment(assignment_id: int, db: Session = Depends(get_db)):
    row = db.get(models.Assignment, assignment_id)
    if row is not None:
        label = f"{ASSIGNMENT_PREFIX}{row.title}"
        db.delete(row)
        # mustdo からも取り除く
        settings = crud.get_all_settings(db)
        current = settings.get("mustdo_list") or []
        if label in current:
            crud.set_setting(db, "mustdo_list", [x for x in current if x != label])
        db.commit()
        sync_assignments_to_mustdo(db)
    return {"ok": True}


# ---------- PC使用セッション ----------
@router.post("/api/pc/sessions")
def add_pc_sessions(body: PcSessionsBatch, db: Session = Depends(get_db)):
    """pc_tracker.py からのまとめ書き込み"""
    for s in body.sessions:
        if s.end_ts > s.start_ts:
            db.add(models.PcSession(**s.model_dump()))
    db.commit()
    return {"ok": True, "count": len(body.sessions)}


def _pc_sessions_for_date(db: Session, date: str) -> list[dict]:
    """その日に重なるPCセッションを返す（日をまたぐものは切り詰める）"""
    day_start = datetime.strptime(date, "%Y-%m-%d")
    day_end = day_start + timedelta(days=1)
    s0, e0 = day_start.timestamp(), day_end.timestamp()
    rows = db.execute(
        select(models.PcSession)
        .where(models.PcSession.end_ts > s0, models.PcSession.start_ts < e0)
        .order_by(models.PcSession.start_ts)
    ).scalars().all()
    return [
        {"id": r.id, "start_ts": max(r.start_ts, s0), "end_ts": min(r.end_ts, e0),
         "app": r.app, "title": r.title}
        for r in rows
    ]


@router.get("/api/pc/sessions")
def list_pc_sessions(date: str, db: Session = Depends(get_db)):
    return _pc_sessions_for_date(db, date)


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
        if "勉強" in r.category or r.category == "中断":
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
    for s in _pc_sessions_for_date(db, date):
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


# ---------- 曜日振替の登録・削除 ----------
class OverrideBody(BaseModel):
    date: str               # "YYYY-MM-DD"
    mode: str               # "holiday" / "weekday" / "clear"（clear=振替を取り消す）
    weekday: int | None = None


@router.post("/api/life/override")
def set_override(body: OverrideBody, db: Session = Depends(get_db)):
    """日付単位の曜日振替を設定（例：祝日の振替で月曜日程／臨時休講日）"""
    row = db.execute(
        select(models.DayOverride).where(models.DayOverride.date == body.date)
    ).scalars().first()
    if body.mode == "clear":
        if row is not None:
            db.delete(row)
            db.commit()
    else:
        if body.mode not in ("holiday", "weekday"):
            raise HTTPException(status_code=400, detail="mode は holiday / weekday / clear")
        if body.mode == "weekday" and (body.weekday is None or not 0 <= body.weekday <= 6):
            raise HTTPException(status_code=400, detail="weekday（月=0〜日=6）を指定してください")
        if row is None:
            db.add(models.DayOverride(date=body.date, mode=body.mode, weekday=body.weekday))
        else:
            row.mode = body.mode
            row.weekday = body.weekday
        db.commit()
    return day_info(db, body.date)


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
        events_by_day.setdefault(ev.date, []).append(_event_dict(ev))
    asg_by_day: dict[str, list] = {}
    for a in db.execute(
        select(models.Assignment)
        .where(models.Assignment.due_date >= m_start, models.Assignment.due_date <= m_end)
        .order_by(models.Assignment.id)
    ).scalars().all():
        asg_by_day.setdefault(a.due_date, []).append(
            {"id": a.id, "title": a.title, "progress": a.progress,
             "done": a.progress >= 100, "recurring": a.recurring_id is not None})
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
               models.ScheduleBlock.enabled == True)  # noqa: E712
        .order_by(models.ScheduleBlock.start)
    ).scalars().all():
        d = _sched_dict(r)
        d["cancelled"] = r.id in cancelled_ids  # 休講フラグ
        schedule.append(d)
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

    return {
        "date": date,
        **info,  # weekday / effective_weekday / is_holiday / holiday_name / override
        "schedule": schedule,
        "events": events,
        "entries": entries,
        "study": study,
        "pc": _pc_sessions_for_date(db, date),
    }
