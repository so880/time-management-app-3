"""習慣（todo_items kind=habit ＋ todo_completions）の一覧・登録・削除・履歴の API（/api/habits）。

やることの判定そのもの（今日の習慣・完了状態）は todo_api にある。todo_api は life_api を
関数の中で読み込むため、ここでも todo_api は関数の中で読み込む（import の循環を避ける）。
"""
from datetime import date as date_cls, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models
from .database import get_db
from .life_days import HABIT_CAT

router = APIRouter()


class HabitBody(BaseModel):
    title: str
    start: str              # "HH:MM"
    end: str
    weekdays: list[int]     # 月=0 ... 日=6（複数選択）


class HabitMinActionBody(BaseModel):
    title: str
    text: str               # 「5分だけ着手」の最小単位の文言（空で削除）


def habit_blocks_for(db: Session, date_str: str) -> list[dict]:
    """その日に実施予定の習慣を「時間割ブロック風」の dict で返す
    （今日のまとめの timetable・1日分まとめの schedule に混ぜて表示するため）。
    id は時間割ブロックと衝突しないよう負の値（-item_id）にする"""
    from . import todo_api
    out = []
    for it in todo_api.habits_for_date(db, date_str):
        out.append({"id": -it.id, "weekday": todo_api._habit_weekday(db, date_str),
                    "start": it.start or "", "end": it.end or "", "title": it.title,
                    "category": HABIT_CAT, "enabled": True, "room": "", "cancelled": False})
    return [b for b in out if b["start"] and b["end"]]


def _habit_rate(db: Session, item, days: int) -> dict:
    """直近days日間の達成率（予定されていた日のうち何日やったか。着手も達成に数える）"""
    from . import todo_api
    today = date_cls.today()
    wds = todo_api._weekday_set(item)
    created_day = (item.created or "")[:10]
    expected = 0
    for i in range(days):
        d = today - timedelta(days=i)
        if d.weekday() in wds and d.isoformat() >= created_day:
            expected += 1
    if expected == 0:
        return {"done": 0, "expected": 0, "rate": None}
    since = (today - timedelta(days=days - 1)).isoformat()
    done = len(db.execute(
        select(models.TodoCompletion)
        .where(models.TodoCompletion.item_id == item.id, models.TodoCompletion.date >= since)
    ).scalars().all())
    return {"done": min(done, expected), "expected": expected,
            "rate": round(min(done, expected) / expected * 100)}


@router.get("/api/habits")
def list_habits(db: Session = Depends(get_db)):
    """習慣一覧（時間・曜日・7日/30日の達成率・今日の分のチェック状態）"""
    from . import todo_api, presence_api
    td = todo_api.todo_today(db)
    status = {h["id"]: h for h in td["habits"]}
    out = []
    for it in todo_api.habit_items(db):
        wds = sorted(todo_api._weekday_set(it))
        st = status.get(it.id, {})
        out.append({
            "id": it.id,
            "title": it.title,
            "weekdays": wds,
            "times": {str(w): f"{it.start}〜{it.end}" for w in wds},
            "dueToday": it.id in status,
            "checkedToday": bool(st.get("checked", False)),
            "level": st.get("level", ""),
            "forced": bool(st.get("forced", False)),
            "record_only": presence_api.is_record_only(db, it),   # 記録だけ（F23）
            "minAction": it.min_action or "",
            "rate7": _habit_rate(db, it, 7),
            "rate30": _habit_rate(db, it, 30),
        })
    return out


@router.post("/api/habits")
def create_habit(body: HabitBody, db: Session = Depends(get_db)):
    """習慣を登録（todo_items kind=habit）。曜日を追加登録すると既存の習慣に曜日が足される"""
    from . import todo_api
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="習慣の名前を入力してください")
    if not body.weekdays:
        raise HTTPException(status_code=400, detail="曜日を1つ以上選んでください")
    todo_api.upsert_habit(db, title, {int(w) for w in body.weekdays if 0 <= int(w) <= 6},
                          body.start, body.end)
    db.commit()
    return {"ok": True, "added": len(body.weekdays)}


@router.delete("/api/habits/{title}")
def delete_habit(title: str, db: Session = Depends(get_db)):
    """習慣を削除（達成記録も一緒に消える）。制限中は不可（解放条件が減るため）"""
    from . import todo_api
    todo_api.deny_if_locked(db, "習慣を削除すること")
    for it in db.execute(
        select(models.TodoItem).where(models.TodoItem.kind == models.KIND_HABIT, models.TodoItem.title == title)
    ).scalars().all():
        for c in db.execute(select(models.TodoCompletion)
                            .where(models.TodoCompletion.item_id == it.id)).scalars().all():
            db.delete(c)
        db.delete(it)
    # 古い DB に旧の時間割ブロック（category=習慣）が残っていれば一緒に消す
    # （通常は migrate.cleanup_legacy_todo で削除済み。残っていても消し残さないための念のため）
    for r in db.execute(
        select(models.ScheduleBlock)
        .where(models.ScheduleBlock.category == HABIT_CAT, models.ScheduleBlock.title == title)
    ).scalars().all():
        db.delete(r)
    db.commit()
    return {"ok": True}


@router.put("/api/habits/min_action")
def set_habit_min_action(body: HabitMinActionBody, db: Session = Depends(get_db)):
    """習慣ごとの「5分だけ着手」の最小単位の文言を保存（todo_items.min_action）"""
    rows = db.execute(
        select(models.TodoItem).where(models.TodoItem.kind == models.KIND_HABIT,
                                      models.TodoItem.title == body.title)
    ).scalars().all()
    if not rows:
        raise HTTPException(status_code=404, detail="習慣が見つかりません")
    for it in rows:
        it.min_action = body.text.strip()
    db.commit()
    return {"ok": True}


@router.get("/api/habits/history")
def habits_history(days: int = 14, db: Session = Depends(get_db)):
    """完了時刻の履歴：習慣ごとに「予定時刻 → 実際に完了した時刻（ずれ）」を返す"""
    from . import todo_api
    since = (date_cls.today() - timedelta(days=days - 1)).isoformat()
    items = {it.id: it for it in todo_api.habit_items(db)}
    out: dict[str, list] = {}
    for c in db.execute(
        select(models.TodoCompletion).where(models.TodoCompletion.date >= since)
        .order_by(models.TodoCompletion.date.desc())
    ).scalars().all():
        it = items.get(c.item_id)
        if it is None:
            continue
        plan = it.start or ""
        diff = None
        if plan and c.at:
            try:
                ph, pm = map(int, plan.split(":"))
                ah, am = map(int, c.at.split(":"))
                diff = (ah * 60 + am) - (ph * 60 + pm)
            except ValueError:
                diff = None
        out.setdefault(it.title, []).append(
            {"date": c.date, "at": c.at or "", "planned": plan, "diffMin": diff,
             "level": c.level or "full"})
    return out


@router.get("/api/habits/daily_rates")
def habits_daily_rates(days: int = 7, db: Session = Depends(get_db)):
    """直近days日間の「その日やる予定だった習慣のうち何個やったか」（完了割合の推移）"""
    from . import todo_api
    today = date_cls.today()
    since = (today - timedelta(days=days - 1)).isoformat()
    comp_by_day = todo_api.completions_since(db, since)
    day_names = "月火水木金土日"
    out = []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        ds = d.isoformat()
        due = todo_api.habits_for_date(db, ds)
        comp = comp_by_day.get(ds, {})
        done = sum(1 for h in due if h.id in comp)
        out.append({
            "date": ds,
            "label": f"{d.month}/{d.day}({day_names[d.weekday()]})",
            "due": len(due), "done": done,
            "rate": round(done / len(due) * 100) if due else None,
        })
    return out
