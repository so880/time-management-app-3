"""PC使用セッション（pc_tracker.py から受け取る）の API。"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models
from .database import get_db

router = APIRouter()


class PcSessionBody(BaseModel):
    start_ts: float
    end_ts: float
    app: str
    title: str = ""


class PcSessionsBatch(BaseModel):
    sessions: list[PcSessionBody]


# ---------- PC使用セッション ----------
@router.post("/api/pc/sessions")
def add_pc_sessions(body: PcSessionsBatch, db: Session = Depends(get_db)):
    """pc_tracker.py からのまとめ書き込み"""
    for s in body.sessions:
        if s.end_ts > s.start_ts:
            db.add(models.PcSession(**s.model_dump()))
    db.commit()
    return {"ok": True, "count": len(body.sessions)}


def pc_sessions_for_date(db: Session, date: str) -> list[dict]:
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
    return pc_sessions_for_date(db, date)
