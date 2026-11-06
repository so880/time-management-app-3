"""単発予定（life_events）と手入力の実績（life_entries）の API。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models
from .database import get_db

router = APIRouter()


# ---------- 入力の型 ----------
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


# ---------- 変換 ----------
def event_dict(r: models.LifeEvent) -> dict:
    return {"id": r.id, "date": r.date, "start": r.start, "end": r.end,
            "title": r.title, "category": r.category, "note": r.note or "",
            "done": bool(r.done)}


def _entry_dict(r: models.LifeEntry) -> dict:
    return {"id": r.id, "date": r.date, "start": r.start, "end": r.end,
            "title": r.title, "category": r.category, "note": r.note}


# ---------- 単発予定 ----------
@router.get("/api/life/events")
def list_events(date: str, db: Session = Depends(get_db)):
    rows = db.execute(
        select(models.LifeEvent).where(models.LifeEvent.date == date)
        .order_by(models.LifeEvent.start)
    ).scalars().all()
    return [event_dict(r) for r in rows]


@router.post("/api/life/events")
def create_event(body: LifeEventBody, db: Session = Depends(get_db)):
    row = models.LifeEvent(**body.model_dump())
    db.add(row)
    db.commit()
    return event_dict(row)


@router.delete("/api/life/events/{event_id}")
def delete_event(event_id: int, db: Session = Depends(get_db)):
    row = db.get(models.LifeEvent, event_id)
    if row is not None:
        db.delete(row)
        db.commit()
    return {"ok": True}


class EventDoneBody(BaseModel):
    done: bool = True


@router.post("/api/life/events/{event_id}/done")
def toggle_event_done(event_id: int, body: EventDoneBody, db: Session = Depends(get_db)):
    """予定の完了チェック（ホーム・ライフから）"""
    row = db.get(models.LifeEvent, event_id)
    if row is None:
        raise HTTPException(status_code=404, detail="予定が見つかりません")
    row.done = body.done
    db.commit()
    return event_dict(row)


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
