"""時間割（曜日別の繰り返し予定）・休講・曜日振替の API。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models
from .database import get_db
from .life_days import day_info

router = APIRouter()


# ---------- 入力の型 ----------
class ScheduleBlockBody(BaseModel):
    weekday: int            # 月=0 ... 日=6
    start: str              # "HH:MM"
    end: str
    title: str
    category: str = "大学"
    enabled: bool = True
    room: str = ""          # 教室などのメモ


class CancelToggleBody(BaseModel):
    date: str               # "YYYY-MM-DD"
    block_id: int


class OverrideBody(BaseModel):
    date: str               # "YYYY-MM-DD"
    mode: str               # "holiday" / "weekday" / "clear"（clear=振替を取り消す）
    weekday: int | None = None


# ---------- 変換 ----------
def schedule_dict(r: models.ScheduleBlock) -> dict:
    return {"id": r.id, "weekday": r.weekday, "start": r.start, "end": r.end,
            "title": r.title, "category": r.category, "enabled": r.enabled,
            "room": r.room or ""}


# ---------- 時間割（繰り返し予定） ----------
@router.get("/api/life/schedule")
def list_schedule(db: Session = Depends(get_db)):
    rows = db.execute(
        select(models.ScheduleBlock)
        .order_by(models.ScheduleBlock.weekday, models.ScheduleBlock.start)
    ).scalars().all()
    return [schedule_dict(r) for r in rows]


@router.post("/api/life/schedule")
def create_schedule(body: ScheduleBlockBody, db: Session = Depends(get_db)):
    row = models.ScheduleBlock(**body.model_dump())
    db.add(row)
    db.commit()
    return schedule_dict(row)


@router.put("/api/life/schedule/{block_id}")
def update_schedule(block_id: int, body: ScheduleBlockBody, db: Session = Depends(get_db)):
    row = db.get(models.ScheduleBlock, block_id)
    if row is None:
        raise HTTPException(status_code=404, detail="時間割が見つかりません")
    for k, v in body.model_dump().items():
        setattr(row, k, v)
    db.commit()
    return schedule_dict(row)


@router.delete("/api/life/schedule/{block_id}")
def delete_schedule(block_id: int, db: Session = Depends(get_db)):
    row = db.get(models.ScheduleBlock, block_id)
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


# ---------- 曜日振替の登録・削除 ----------
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
