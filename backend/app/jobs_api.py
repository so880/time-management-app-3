"""就活（夏インターン・本選考）機能のAPI（FastAPI公式の APIRouter 方式）。

- 応募先（会社）の CRUD：選考状況・優先順位・提出した内容
- 日程（説明会・面接・インターン期間）の CRUD
- 日程の被り検知：重なっている日程を、応募先の優先順位つきで返す
"""
from datetime import date as date_cls, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models
from .database import get_db

router = APIRouter()

STATUSES = ["気になる", "ES提出", "Webテスト", "面接", "内定", "お見送り"]
PRIORITY_LABEL = {1: "高", 2: "中", 3: "低"}


# ---------- 変換 ----------
def app_dict(a: models.JobApplication) -> dict:
    return {
        "id": a.id, "company": a.company, "title": a.title, "kind": a.kind,
        "status": a.status, "priority": a.priority,
        "priorityLabel": PRIORITY_LABEL.get(a.priority, "中"),
        "submitted": a.submitted, "note": a.note, "created": a.created,
    }


def event_dict(e: models.JobEvent, apps: dict | None = None) -> dict:
    d = {
        "id": e.id, "applicationId": e.application_id, "label": e.label,
        "date": e.date, "endDate": e.end_date or "", "start": e.start or "",
        "end": e.end or "", "choice": e.choice or 0,
    }
    if apps is not None:
        if e.application_id in apps:
            a = apps[e.application_id]
            d["company"] = a.company
            d["priority"] = a.priority
            d["priorityLabel"] = PRIORITY_LABEL.get(a.priority, "中")
            d["status"] = a.status
        else:  # application_id=0：会社に紐づかない就活予定（合同説明会など）
            d["company"] = ""
            d["priority"] = 2
            d["priorityLabel"] = "中"
            d["status"] = ""
    return d


def _apps_by_id(db: Session) -> dict:
    rows = db.execute(select(models.JobApplication)).scalars().all()
    return {a.id: a for a in rows}


def _span(e: models.JobEvent) -> tuple:
    """イベントの (開始日, 最終日)。end_date が空なら1日だけ"""
    s = e.date
    t = e.end_date or e.date
    if t < s:
        s, t = t, s
    return s, t


def _overlap(a: models.JobEvent, b: models.JobEvent) -> bool:
    """日付の期間が重なるか（時間まで同じ日の重なりは日単位で判定する）"""
    a1, a2 = _span(a)
    b1, b2 = _span(b)
    return a1 <= b2 and b1 <= a2


def find_conflicts(db: Session) -> list[dict]:
    """今日以降の日程同士の被りを、優先順位つきで返す。

    返り値の events は応募先の priority 順（1=高 が先）に並ぶので、
    「どれを優先すべきか」がそのまま上から読める。
    """
    today = date_cls.today().isoformat()
    apps = _apps_by_id(db)
    events = [e for e in db.execute(select(models.JobEvent)).scalars().all()
              if _span(e)[1] >= today]
    conflicts = []
    used = set()
    for i, a in enumerate(events):
        if a.id in used:
            continue
        group = [a]
        for b in events[i + 1:]:
            if b.id in used:
                continue
            # 同じ会社の候補日（第N希望）同士は「選ぶための候補」なので被り扱いしない
            if any(_overlap(g, b) and not (
                    g.application_id and g.application_id == b.application_id)
                   for g in group):
                group.append(b)
        if len(group) > 1:
            for g in group:
                used.add(g.id)
            group.sort(key=lambda e: (
                apps[e.application_id].priority if e.application_id in apps else 2,
                e.choice or 0,
                e.date,
            ))
            conflicts.append({
                "dates": f"{min(_span(g)[0] for g in group)}〜{max(_span(g)[1] for g in group)}",
                "events": [event_dict(g, apps) for g in group],
            })
    return conflicts


# ---------- 応募先 ----------
class AppBody(BaseModel):
    company: str
    title: str = ""
    kind: str = "intern"           # intern / fulltime
    status: str = "気になる"
    priority: int = 2              # 1=高 2=中 3=低
    submitted: str = ""
    note: str = ""


@router.get("/api/jobs")
def list_apps(db: Session = Depends(get_db)):
    apps = db.execute(
        select(models.JobApplication).order_by(models.JobApplication.priority,
                                               models.JobApplication.id)
    ).scalars().all()
    events = db.execute(
        select(models.JobEvent).order_by(models.JobEvent.date)
    ).scalars().all()
    by_app: dict[int, list] = {}
    for e in events:
        by_app.setdefault(e.application_id, []).append(event_dict(e))
    out = []
    for a in apps:
        d = app_dict(a)
        evs = by_app.get(a.id, [])
        evs.sort(key=lambda x: (x["choice"], x["date"]))  # 確定→第1希望→第2希望…の順
        d["events"] = evs
        out.append(d)
    standalone = by_app.get(0, [])  # 会社に紐づかない就活予定
    for e in standalone:
        e["company"] = ""
    return {"applications": out, "statuses": STATUSES,
            "standalone": standalone,
            "conflicts": find_conflicts(db)}


@router.post("/api/jobs")
def create_app(body: AppBody, db: Session = Depends(get_db)):
    if not body.company.strip():
        raise HTTPException(status_code=400, detail="会社名を入力してください")
    row = models.JobApplication(
        company=body.company.strip(), title=body.title.strip(), kind=body.kind,
        status=body.status, priority=int(body.priority),
        submitted=body.submitted, note=body.note,
        created=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    db.add(row)
    db.commit()
    return app_dict(row)


@router.put("/api/jobs/{app_id}")
def update_app(app_id: int, body: AppBody, db: Session = Depends(get_db)):
    row = db.get(models.JobApplication, app_id)
    if row is None:
        raise HTTPException(status_code=404, detail="応募先が見つかりません")
    row.company = body.company.strip() or row.company
    row.title = body.title.strip()
    row.kind = body.kind
    row.status = body.status
    row.priority = int(body.priority)
    row.submitted = body.submitted
    row.note = body.note
    db.commit()
    return app_dict(row)


@router.delete("/api/jobs/{app_id}")
def delete_app(app_id: int, db: Session = Depends(get_db)):
    row = db.get(models.JobApplication, app_id)
    if row is not None:
        for e in db.execute(
            select(models.JobEvent).where(models.JobEvent.application_id == app_id)
        ).scalars().all():
            db.delete(e)
        db.delete(row)
        db.commit()
    return {"ok": True}


# ---------- 日程 ----------
class EventBody(BaseModel):
    applicationId: int = 0   # 0=会社に紐づかない就活予定（合同説明会など）
    label: str = ""
    date: str
    endDate: str = ""
    start: str = ""
    end: str = ""
    choice: int = 0          # 0=確定 / 1〜=第N希望（候補日）


@router.post("/api/jobs/events")
def create_event(body: EventBody, db: Session = Depends(get_db)):
    if body.applicationId and db.get(models.JobApplication, body.applicationId) is None:
        raise HTTPException(status_code=404, detail="応募先が見つかりません")
    try:
        datetime.strptime(body.date, "%Y-%m-%d")
        if body.endDate:
            datetime.strptime(body.endDate, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="日付の形式が正しくありません")
    row = models.JobEvent(
        application_id=body.applicationId, label=body.label.strip(),
        date=body.date, end_date=body.endDate, start=body.start, end=body.end,
        choice=max(0, min(9, int(body.choice or 0))),
    )
    db.add(row)
    db.commit()
    return event_dict(row, _apps_by_id(db))


@router.delete("/api/jobs/events/{event_id}")
def delete_event(event_id: int, db: Session = Depends(get_db)):
    row = db.get(models.JobEvent, event_id)
    if row is not None:
        db.delete(row)
        db.commit()
    return {"ok": True}


@router.get("/api/jobs/conflicts")
def get_conflicts(db: Session = Depends(get_db)):
    return {"conflicts": find_conflicts(db)}


def events_between(db: Session, start: str, end: str) -> list[dict]:
    """期間内の就活日程（カレンダー・Googleカレンダー連携用）"""
    apps = _apps_by_id(db)
    out = []
    for e in db.execute(select(models.JobEvent)).scalars().all():
        s, t = _span(e)
        if s <= end and t >= start:
            out.append(event_dict(e, apps))
    return out
