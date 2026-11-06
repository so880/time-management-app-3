"""ルーレット項目（assignments。旧・課題＋通常勉強＋重点）と毎週の課題（テンプレート）の API。"""
from datetime import date as date_cls, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import crud, models
from .database import get_db

router = APIRouter()

ASSIGNMENT_PREFIX = "【課題】"  # 必須に課題を手で入れるときの目印（振り返り「終わった」で課題側も完了にする）


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
                category="大学", focus=False, enabled=True,
                created=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                recurring_id=r.id,
            ))
            added = True
    if added:
        db.commit()


# ---------- 課題 → 「今日絶対やる」自動同期 ----------
def sync_assignments_to_mustdo(db: Session) -> None:
    """毎週の課題インスタンス（今週分）を用意する。
    以前は期限2日以内の課題を「今日絶対やる」に自動追加していたが、2026-09 の統合の決定
    「課題は解放判定に含めない」により廃止した（課題を今日の必須へは足さない）。"""
    ensure_recurring_instances(db)  # 毎週の課題の今週分を先に用意する


def complete_assignment_by_label(db: Session, label: str) -> None:
    """振り返りで「終わった」と答えたとき、同名の期限つきルーレット項目を完了(100%)にする。
    旧「【課題】◯◯」の形も受け付ける。期限なしの項目（繰り返し使う勉強項目）は対象外"""
    title = label[len(ASSIGNMENT_PREFIX):] if label.startswith(ASSIGNMENT_PREFIX) else label
    # 同名の週次インスタンスが複数あり得るので「未完了で期限が近いもの」を対象にする
    row = db.execute(
        select(models.Assignment)
        .where(models.Assignment.title == title,
               models.Assignment.progress < 100,
               models.Assignment.due_date != "")
        .order_by(models.Assignment.due_date)
    ).scalars().first()
    if row is not None:
        row.progress = 100
        db.commit()
    ensure_recurring_instances(db)


# ---------- タグ ----------
ROULETTE_TAGS = ("就活", "大学", "私用", "その他")
TAG_ICON = {"就活": "💼", "大学": "🎓", "私用": "🏠", "その他": "📌"}
EXTRA_TAGS_KEY = "roulette_tags_extra"   # 起動画面で記入した追加タグ（settings にリストで保存）


def all_tags(db: Session) -> list[str]:
    """既定4タグ＋記入で追加されたタグ（重複なし・順序維持）"""
    out = list(ROULETTE_TAGS)
    extra = crud.get_all_settings(db).get(EXTRA_TAGS_KEY) or []
    for t in extra:
        t = str(t).strip()
        if t and t not in out:
            out.append(t)
    return out


def register_tags(db: Session, tags: list[str]) -> None:
    """新しいタグを追加タグの一覧に登録する（commit は呼び出し側）"""
    known = all_tags(db)
    extra = list(crud.get_all_settings(db).get(EXTRA_TAGS_KEY) or [])
    changed = False
    for t in tags:
        t = str(t).strip()
        if t and t not in known:
            extra.append(t)
            known.append(t)
            changed = True
    if changed:
        crud.set_setting(db, EXTRA_TAGS_KEY, extra)


# ---------- 入力の型 ----------
class AssignmentBody(BaseModel):
    """ルーレット項目（旧・課題）の入力"""
    title: str
    due_date: str = ""      # "YYYY-MM-DD"（空=期限なし）
    progress: int = 0       # 0〜100（100=完了。抽選から外れる）
    note: str = ""
    category: str = "その他"  # タグ：就活 / 大学 / 私用 / その他
    focus: bool = False     # 重点（抽選3倍）
    enabled: bool = True    # 抽選に出す


class RecurringAssignmentBody(BaseModel):
    title: str
    weekday: int            # 期限の曜日（月=0 ... 日=6）
    enabled: bool = True


# ---------- 🎲 ルーレット項目（旧・課題＋通常勉強＋重点） ----------
def _assignment_dict(r: models.Assignment) -> dict:
    today = date_cls.today()
    days_left = None
    if r.due_date:
        try:
            days_left = (datetime.strptime(r.due_date, "%Y-%m-%d").date() - today).days
        except ValueError:
            days_left = None
    return {"id": r.id, "title": r.title, "due_date": r.due_date or "",
            "progress": r.progress, "note": r.note,
            "category": r.category or "その他",
            "focus": bool(r.focus), "enabled": bool(r.enabled),
            "days_left": days_left, "done": r.progress >= 100,
            "recurring": r.recurring_id is not None}


def roulette_pool_items(db: Session) -> list[tuple[str, bool]]:
    """抽選に出す項目 [(title, focus)]：未完了・有効。同名は1つに"""
    seen, out = set(), []
    for r in db.execute(
        select(models.Assignment)
        .where(models.Assignment.progress < 100, models.Assignment.enabled == True)  # noqa: E712
        .order_by(models.Assignment.id)
    ).scalars().all():
        if r.title in seen:
            continue
        seen.add(r.title)
        out.append((r.title, bool(r.focus)))
    return out


def due_items(db: Session, start: str = "", end: str = "", include_done: bool = False) -> list:
    """期限つきの項目（カレンダー・GCal・今日やること用）"""
    q = select(models.Assignment).where(models.Assignment.due_date != "")
    if not include_done:
        q = q.where(models.Assignment.progress < 100)
    if start:
        q = q.where(models.Assignment.due_date >= start)
    if end:
        q = q.where(models.Assignment.due_date <= end)
    return db.execute(q.order_by(models.Assignment.due_date, models.Assignment.id)).scalars().all()


@router.get("/api/assignments")
def list_assignments(db: Session = Depends(get_db)):
    """ルーレット項目の一覧（未完了→期限が近い順→期限なし、完了は後ろ）"""
    ensure_recurring_instances(db)  # 表示時にも週次インスタンスを最新化
    rows = db.execute(
        select(models.Assignment)
        .order_by(models.Assignment.progress >= 100,
                  models.Assignment.due_date == "",
                  models.Assignment.due_date, models.Assignment.id)
    ).scalars().all()
    return [_assignment_dict(r) for r in rows]


@router.get("/api/assignments/tags")
def list_tags(db: Session = Depends(get_db)):
    """使えるタグ一覧（既定4つ＋起動画面で記入した追加タグ）。アイコンは無いものは 🏷"""
    return [{"name": t, "icon": TAG_ICON.get(t, "🏷")} for t in all_tags(db)]


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
            db.delete(inst)
        db.delete(row)
        db.commit()
    return {"ok": True}


def _check_asg_body(body: AssignmentBody, db: Session) -> None:
    if not body.title.strip():
        raise HTTPException(status_code=400, detail="項目名を入力してください")
    if body.category not in all_tags(db):
        raise HTTPException(status_code=400,
                            detail="タグは 就活/大学/私用/その他 か、起動画面で追加したタグのいずれか")
    if body.due_date:
        try:
            datetime.strptime(body.due_date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="期限は YYYY-MM-DD で指定してください")


@router.post("/api/assignments")
def create_assignment(body: AssignmentBody, db: Session = Depends(get_db)):
    _check_asg_body(body, db)
    row = models.Assignment(
        title=body.title.strip(), due_date=body.due_date or "",
        progress=max(0, min(100, body.progress)), note=body.note,
        category=body.category, focus=body.focus, enabled=body.enabled,
        created=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    db.add(row)
    db.commit()
    return _assignment_dict(row)


@router.put("/api/assignments/{assignment_id}")
def update_assignment(assignment_id: int, body: AssignmentBody, db: Session = Depends(get_db)):
    _check_asg_body(body, db)
    row = db.get(models.Assignment, assignment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="項目が見つかりません")
    row.title = body.title.strip()
    row.due_date = body.due_date or ""
    row.progress = max(0, min(100, body.progress))
    row.note = body.note
    row.category = body.category
    row.focus = body.focus
    row.enabled = body.enabled
    db.commit()
    return _assignment_dict(row)


@router.delete("/api/assignments/{assignment_id}")
def delete_assignment(assignment_id: int, db: Session = Depends(get_db)):
    row = db.get(models.Assignment, assignment_id)
    if row is not None:
        db.delete(row)
        db.commit()
    return {"ok": True}
