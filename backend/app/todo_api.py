"""📋 やること（todo_items / todo_completions）のAPI。2026-09 の統合決定に基づく。

種類:
- must     … 今日の必須。date を持ち、その日限り（翌日へ繰り越さない）
- habit    … 毎日の習慣。weekdays（"0,1,...,6"）と時刻。解放判定に含む
- periodic … 週単位・不定期。every_days（0=不定期）。記録のみ

完了記録は todo_completions（item_id × date、level=full/min）。
「2日連続未完了 → 翌日は必須扱い（level=min 不可）」は habit にのみ適用。

やることのデータはこのテーブルだけが正（settings のリストや habit_checks は廃止済み）。
新しいDBでは ensure_todo_migration() が既定のやることを1回だけ入れる。
"""
import json
from datetime import date as date_cls, datetime, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import crud, models
from .database import get_db

router = APIRouter()

KINDS = (models.KIND_MUST, models.KIND_HABIT, models.KIND_PERIODIC)


# ---------- 初期データ（新しいDBのときだけ1回） ----------
# 既定の習慣（タイトル, 開始, 終了）。全曜日に登録される
DEFAULT_HABITS = [
    ("筋トレ", "07:00", "07:30"),
    ("SPI", "09:00", "09:30"),
    ("TOEIC", "09:30", "10:00"),
    ("株価AI", "10:00", "11:00"),
    ("キーボード操作(今週の3つ)", "13:00", "13:15"),
    ("就活調査", "20:00", "20:30"),
]
DEFAULT_MUST = [
    "就活の返信・回答の未処理をゼロにする",
    "当日締切のES・申請の提出",
    "面接・面談の前日準備",
]
DEFAULT_PERIODIC = [  # every_days=0 は不定期（手動）
    ("就活メールの棚卸し", 3),
    ("秋冬インターン締切チェック", 7),
    ("GitHub app-3更新", 0),
]


def ensure_todo_migration(db: Session) -> None:
    """todo_items が空の新しいDBに既定のやることを入れる（settings todo_v1_migrated で1回だけ）。
    旧データ（settings のリスト・habit_checks・時間割の習慣ブロック）からの取り込みは
    2026-09 の統合時に済んでいるため、ここでは行わない（残骸の削除は migrate.cleanup_legacy_todo）。"""
    settings = crud.get_all_settings(db)
    if settings.get("todo_v1_migrated"):
        return
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today = date_cls.today().isoformat()
    sort = 0
    for title in DEFAULT_MUST:
        sort += 1
        db.add(models.TodoItem(kind=models.KIND_MUST, title=title, date=today, enabled=True,
                               created=now, sort=sort))
    for title, start, end in DEFAULT_HABITS:
        sort += 1
        db.add(models.TodoItem(kind=models.KIND_HABIT, title=title, weekdays="0,1,2,3,4,5,6",
                               start=start, end=end, enabled=True, created=now, sort=sort))
    for title, every in DEFAULT_PERIODIC:
        sort += 1
        db.add(models.TodoItem(kind=models.KIND_PERIODIC, title=title, every_days=every,
                               enabled=True, created=now, sort=sort))
    crud.set_setting(db, "todo_v1_migrated", True)
    db.commit()



# ---------- 参照用ヘルパー（解放判定・画面がこれを使う） ----------
def _weekday_set(item: models.TodoItem) -> set:
    return {int(x) for x in (item.weekdays or "").split(",") if x.strip().isdigit()}


def _completions(db: Session, date_str: str) -> dict[int, models.TodoCompletion]:
    return {
        c.item_id: c for c in db.execute(
            select(models.TodoCompletion).where(models.TodoCompletion.date == date_str)
        ).scalars().all()
    }


def _effective_weekday(db: Session, date_str: str) -> int:
    from . import life_api  # 実効曜日（祝日・振替）は life_api と同じ計算を使う
    return life_api.day_info(db, date_str)["effective_weekday"]


def _habit_weekday(db: Session, date_str: str) -> int:
    """習慣に使う曜日＝暦どおりの曜日（2026-11-03 依頼者の決定：祝日は「授業のない平日」。
    祝日・振替授業（月曜時間割など）で変わるのは授業の時間割だけで、筋トレ・AI面接などの習慣は変えない）"""
    return datetime.strptime(date_str, "%Y-%m-%d").date().weekday()


def todo_today(db: Session) -> dict:
    """今日のやること一覧（must / habit / periodic）と完了状態、解放判定に使う tasks_done"""
    ensure_todo_migration(db)
    today = date_cls.today()
    t = today.isoformat()
    items = db.execute(
        select(models.TodoItem).where(models.TodoItem.enabled == True)  # noqa: E712
        .order_by(models.TodoItem.sort, models.TodoItem.id)
    ).scalars().all()
    comp = _completions(db, t)
    y1, y2 = (today - timedelta(days=1)).isoformat(), (today - timedelta(days=2)).isoformat()
    comp_y1, comp_y2 = _completions(db, y1), _completions(db, y2)
    wd, wd1, wd2 = (_habit_weekday(db, t), _habit_weekday(db, y1),
                    _habit_weekday(db, y2))

    # F23：「記録だけ」の習慣（settings.habit_options[習慣の番号].record_only）は解放条件に入れない
    from . import presence_api
    try:
        settings_all = crud.get_all_settings(db)
    except Exception:
        settings_all = {}

    must, habits, periodic = [], [], []
    for it in items:
        c = comp.get(it.id)
        if it.kind == models.KIND_MUST:
            if it.date != t:
                continue
            must.append({"id": it.id, "title": it.title, "checked": c is not None,
                         "level": c.level if c else "", "at": c.at if c else "",
                         "tag": it.tag or "", "due": it.due_date or "", "asg_id": it.asg_id})
        elif it.kind == models.KIND_HABIT:
            wds = _weekday_set(it)
            if wd not in wds:
                continue
            created_day = (it.created or t)[:10]
            missed1 = wd1 in wds and it.id not in comp_y1 and y1 >= created_day
            missed2 = wd2 in wds and it.id not in comp_y2 and y2 >= created_day
            forced = missed1 and missed2
            checked = c is not None
            done = checked and (c.level == "full" or not forced)
            habits.append({"id": it.id, "title": it.title, "start": it.start, "end": it.end,
                           "checked": checked, "level": c.level if c else "", "at": c.at if c else "",
                           "forced": forced, "done": done, "minAction": it.min_action or "",
                           "record_only": presence_api.is_record_only(settings_all, it, t)})
        elif it.kind == models.KIND_PERIODIC:
            last = db.execute(
                select(models.TodoCompletion).where(models.TodoCompletion.item_id == it.id)
                .order_by(models.TodoCompletion.date.desc())
            ).scalars().first()
            days_since = None
            if last is not None:
                try:
                    days_since = (today - datetime.strptime(last.date, "%Y-%m-%d").date()).days
                except ValueError:
                    days_since = None
            every = int(it.every_days or 0)
            periodic.append({"id": it.id, "title": it.title, "everyDays": every,
                             "lastDone": last.date if last else "", "daysSince": days_since,
                             "due": bool(every > 0 and (days_since is None or days_since >= every)),
                             "checkedToday": c is not None})
    gate_habits = [h for h in habits if not h["record_only"]]   # 記録だけの習慣は解放条件に入れない
    tasks_done = all(m["checked"] for m in must) and all(h["done"] for h in gate_habits)
    return {"date": t, "must": must, "habits": habits, "periodic": periodic,
            "tasks_done": tasks_done,
            "remaining": [m["title"] for m in must if not m["checked"]]
                         + [h["title"] for h in gate_habits if not h["done"]]}


def habit_items(db: Session) -> list:
    """有効な習慣（todo_items kind=habit）を sort 順で"""
    return db.execute(
        select(models.TodoItem).where(models.TodoItem.kind == models.KIND_HABIT,
                                      models.TodoItem.enabled == True)  # noqa: E712
        .order_by(models.TodoItem.start, models.TodoItem.sort, models.TodoItem.id)
    ).scalars().all()


def habits_for_date(db: Session, date_str: str) -> list:
    """その日（暦どおりの曜日）に実施予定の習慣（登録日より前の日は対象外）"""
    wd = _habit_weekday(db, date_str)
    out = []
    for it in habit_items(db):
        if wd in _weekday_set(it) and date_str >= (it.created or "")[:10]:
            out.append(it)
    return out


def must_items_for_date(db: Session, date_str: str) -> list:
    return db.execute(
        select(models.TodoItem).where(models.TodoItem.kind == models.KIND_MUST,
                                      models.TodoItem.date == date_str,
                                      models.TodoItem.enabled == True)  # noqa: E712
        .order_by(models.TodoItem.sort, models.TodoItem.id)
    ).scalars().all()


def must_unfinished_titles(db: Session) -> list[str]:
    """今日の必須のうち未完了のタイトル（ルーレットの勉強抽選・小窓・GCal用）"""
    t = date_cls.today().isoformat()
    comp = _completions(db, t)
    return [m.title for m in must_items_for_date(db, t) if m.id not in comp]


MIN_ACTION_MINUTES = 5   # これ以上やれば「5分だけ着手」扱い


def habit_duration_minutes(item: models.TodoItem) -> int:
    """習慣の時間帯の長さ（分）。時刻が無い/不正なら 25 分"""
    try:
        sh, sm = [int(x) for x in (item.start or "").split(":")]
        eh, em = [int(x) for x in (item.end or "").split(":")]
    except ValueError:
        return 25
    d = (eh * 60 + em) - (sh * 60 + sm)
    if d <= 0:
        d += 24 * 60
    return d if d > 0 else 25


def _is_record_only(db: Session, item) -> bool:
    """「記録だけ」の習慣か（presence_api.habit_options の record_only。F23）。item は習慣の行"""
    try:
        from . import presence_api
        return presence_api.is_record_only(db, item)
    except Exception:
        return False


def habit_need_minutes(db: Session, item: models.TodoItem) -> int:
    """タイマーでその習慣を完了にするのに必要な分数。
    既定は時間帯の長さ。画角外の習慣（筋トレ等。settings habit_options で off_camera=True）は
    依頼者が決めた最低時間（min_minutes。10分以上・時間帯の長さ以下）。F22（2026-11-01 夜）で追加"""
    need = habit_duration_minutes(item)
    try:
        from . import presence_api
        opt = presence_api.habit_option(db, item)
        if opt.get("off_camera") and int(opt.get("min_minutes") or 0) > 0:
            need = min(need, max(presence_api.OFF_CAMERA_MIN_FLOOR, int(opt["min_minutes"])))
    except Exception:
        pass
    return need


def auto_complete_habit_by_study(db: Session, title: str, minutes: int) -> str:
    """小窓・iPhone のタイマーで習慣を「規定時間」やったら自動で完了にする。
    規定時間＝その習慣の時間帯の長さ（画角外の習慣は最低時間。habit_need_minutes）。
    それ未満でも5分以上なら着手（min）。返り値: "full" / "min" / ""（対象外）。commit は呼び出し側"""
    t = date_cls.today().isoformat()
    name = title.strip()
    for prefix in ("📱 ", "📱"):
        if name.startswith(prefix):
            name = name[len(prefix):].strip()
    for it in habits_for_date(db, t):
        if it.title != name:
            continue
        need = habit_need_minutes(db, it)
        if minutes >= need:
            level = "full"
        elif minutes >= MIN_ACTION_MINUTES:
            level = "min"
        else:
            return ""
        row = db.execute(
            select(models.TodoCompletion).where(models.TodoCompletion.item_id == it.id,
                                                models.TodoCompletion.date == t)
        ).scalars().first()
        if row is None:
            db.add(models.TodoCompletion(item_id=it.id, date=t,
                                         at=datetime.now().strftime("%H:%M"), level=level))
            db.flush()
        elif row.level != "full" and level == "full":
            row.level = "full"
        return level
    return ""


def complete_by_title(db: Session, title: str, level: str = "full") -> bool:
    """タイトル一致で「今日の必須」を完了にする（振り返り「消す」用。commit は呼び出し側）。
    習慣（habit）は対象にしない：習慣の完了は PC のタイマーで時間帯の長さ以上やったときだけ
    （同じ名前の必須と習慣があると、自己申告で習慣が完了になる抜け道だったため。2026-11-06）"""
    t = date_cls.today().isoformat()
    hit = False
    for it in db.execute(
        select(models.TodoItem).where(models.TodoItem.title == title,
                                      models.TodoItem.kind == models.KIND_MUST,
                                      models.TodoItem.date == t,
                                      models.TodoItem.enabled == True)  # noqa: E712
    ).scalars().all():
        row = db.execute(
            select(models.TodoCompletion).where(models.TodoCompletion.item_id == it.id,
                                                models.TodoCompletion.date == t)
        ).scalars().first()
        if row is None:
            db.add(models.TodoCompletion(item_id=it.id, date=t,
                                         at=datetime.now().strftime("%H:%M"), level=level))
            db.flush()  # 同じ一括処理内で同じ習慣が2回来ても二重登録にならないように
        elif row.level != "full" and level == "full":
            row.level = "full"
        hit = True
    return hit


# ---------- 制限中は「解放条件を減らす変更」をさせない（2026-11-06） ----------
# 必須・習慣は解放条件そのもの。制限中に消す／無効にする／短くすると、AI 審査を通さずに解除できてしまう。
# 追加・名前の変更・時間を延ばす変更はいつでもできる。今日のノルマが全部終わっていれば自由に変えられる。
def quota_done_now(db: Session) -> bool:
    """今日のノルマ（必須＋今日の習慣）が全部終わっているか。本体が書いた最新の判定（gate_today）を読むだけ
    （ここで再計算すると途中の変更を commit してしまうため）。判定が古い・無いときは「終わっていない」"""
    from . import policy
    gt = crud.get_all_settings(db).get("gate_today") or {}
    return policy.gate_fresh(gt) and bool(gt.get("tasks_done"))


def deny_if_locked(db: Session, what: str) -> None:
    if not quota_done_now(db):
        raise HTTPException(status_code=423,
                            detail=f"制限中は{what}できません（解放条件が減るため）。"
                                   "今日のノルマが全部終わってから変更してください")


def _completed_today(db: Session, item_id: int) -> bool:
    t = date_cls.today().isoformat()
    return db.execute(select(models.TodoCompletion).where(models.TodoCompletion.item_id == item_id,
                                                          models.TodoCompletion.date == t)).scalars().first() is not None


def _hm_minutes(hm: str | None) -> int | None:
    try:
        h, m = [int(x) for x in str(hm).split(":")[:2]]
        return h * 60 + m
    except (ValueError, AttributeError):
        return None


def _slot_len(start, end) -> int:
    s, e = _hm_minutes(start), _hm_minutes(end)
    if s is None or e is None:
        return 0
    return (e - s) % (24 * 60)


def replace_must_titles(db: Session, titles: list[str]) -> None:
    """今日の必須をタイトルだけで丸ごと差し替え（貼り付け欄用。タグ・締切なし）。commit は呼び出し側"""
    replace_must_rows(db, [{"title": x} for x in titles])


def sync_periodic(db: Session, tasks: list[dict]) -> None:
    """週単位・不定期の一覧を todo_items に同期（タイトルで突き合わせ。無いものは削除）"""
    wanted = {str(p.get("title", "")).strip(): max(0, int(p.get("every_days") or 0))
              for p in tasks if str(p.get("title", "")).strip()}
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    existing = {
        it.title: it for it in db.execute(
            select(models.TodoItem).where(models.TodoItem.kind == models.KIND_PERIODIC)
        ).scalars().all()
    }
    for title, it in existing.items():
        if title not in wanted:
            for c in db.execute(select(models.TodoCompletion)
                                .where(models.TodoCompletion.item_id == it.id)).scalars().all():
                db.delete(c)
            db.delete(it)
    for i, (title, every) in enumerate(wanted.items()):
        it = existing.get(title)
        if it is None:
            db.add(models.TodoItem(kind=models.KIND_PERIODIC, title=title, every_days=every,
                                   enabled=True, created=now, sort=i))
        else:
            it.every_days = every
            it.enabled = True
            it.sort = i


def completions_since(db: Session, since: str) -> dict[str, dict[int, str]]:
    """{date: {item_id: level}} を since 以降で"""
    out: dict[str, dict[int, str]] = {}
    for c in db.execute(
        select(models.TodoCompletion).where(models.TodoCompletion.date >= since)
    ).scalars().all():
        out.setdefault(c.date, {})[c.item_id] = c.level or "full"
    return out


def _refresh_gate(db: Session) -> None:
    """やることを変えたあとに解放判定をやり直し、gate_today を最新にする（ワーカーが読む値のため）"""
    from . import gate_api
    gate_api.gate_state(db)


def upsert_habit(db: Session, title: str, weekdays: set, start: str, end: str) -> None:
    """習慣の登録（POST /api/habits）：同名の習慣がなければ作り、あれば曜日を足して有効にする。
    既にある習慣の開始・終了時刻は変えない"""
    item = db.execute(
        select(models.TodoItem).where(models.TodoItem.kind == models.KIND_HABIT, models.TodoItem.title == title)
    ).scalars().first()
    wds = ",".join(str(x) for x in sorted({int(w) for w in weekdays}))
    if item is None:
        db.add(models.TodoItem(kind=models.KIND_HABIT, title=title, weekdays=wds, start=start, end=end,
                               enabled=True, created=datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    else:
        merged = sorted(_weekday_set(item) | {int(w) for w in weekdays})
        item.weekdays = ",".join(str(x) for x in merged)
        item.enabled = True


# ---------- API ----------
@router.get("/api/todo/today")
def get_today(db: Session = Depends(get_db)):
    return todo_today(db)


class CheckBody(BaseModel):
    item_id: int
    done: bool = True
    level: str = "full"


@router.post("/api/todo/check")
def check_item(body: CheckBody, db: Session = Depends(get_db)):
    """完了記録（done=False で取り消し）。既にあれば level だけ更新（着手→通常完了の格上げ）"""
    if body.level not in ("full", "min"):
        raise HTTPException(status_code=400, detail="level は full か min を指定してください")
    item = db.get(models.TodoItem, body.item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="やることが見つかりません")
    if item.kind == models.KIND_HABIT and body.done and not _is_record_only(db, item):
        # 習慣はチェックでは完了にならない：時間帯の長さ以上タイマーで計測したときだけ自動完了
        # （「記録だけ」の習慣は解放条件に入らないので自己申告のチェックを許す。F23）
        raise HTTPException(status_code=423,
                            detail="習慣はチェックでは完了になりません。小窓か「選んで始める」でタイマーを回し、"
                                   "時間帯の長さ以上やると自動で完了します")
    t = date_cls.today().isoformat()
    row = db.execute(
        select(models.TodoCompletion).where(models.TodoCompletion.item_id == item.id,
                                            models.TodoCompletion.date == t)
    ).scalars().first()
    if body.done:
        if row is None:
            db.add(models.TodoCompletion(item_id=item.id, date=t,
                                         at=datetime.now().strftime("%H:%M"), level=body.level))
        else:
            row.level = body.level
    elif row is not None:
        db.delete(row)
    # 格上げ元のルーレット項目があれば進捗も連動（完了=100%／取り消し=0%に戻す）
    if item.kind == models.KIND_MUST and item.asg_id:
        asg = db.get(models.Assignment, item.asg_id)
        if asg is not None:
            asg.progress = 100 if body.done else 0
    db.commit()
    _refresh_gate(db)
    return todo_today(db)


@router.post("/api/todo/must/replace")
def replace_must(text: str = Body(..., media_type="text/plain"), db: Session = Depends(get_db)):
    """今日の必須を丸ごと差し替える。本文はプレーンテキスト（1行1件、先頭に記号なし）。

    当日の must を全削除→再登録。同じタイトルの当日完了記録は引き継ぐ。
    """
    titles = []
    for line in text.splitlines():
        s = line.strip()
        if s and s not in titles:
            titles.append(s)
    replace_must_titles(db, titles)
    db.commit()
    _refresh_gate(db)
    return todo_today(db)


# ---------- 起動時の「今日の必須」入力画面 ----------
DAY_SETUP_KEY = "day_setup_date"   # 「今日を始める」を押した日（YYYY-MM-DD）
CARRY_OVER_DAYS = 14                # 未完了の必須をさかのぼる日数
PROMOTE_DAYS = 1                    # 締切が「今日＋この日数」以内（期限切れ含む）→ 必須に格上げ（固定）


def _setting_str(db: Session, key: str) -> str:
    """settings の1キーを文字列で（値は JSON 文字列で保存されている）"""
    row = db.get(models.Setting, key)
    if row is None or row.value is None:
        return ""
    try:
        v = json.loads(row.value)
    except ValueError:
        return ""
    return v if isinstance(v, str) else ""


def promote_limit(today: str) -> str:
    """この日付以前の締切は必須に格上げ（今日・明日・期限切れ）"""
    return (date_cls.fromisoformat(today) + timedelta(days=PROMOTE_DAYS)).isoformat()


def _must_row(it: models.TodoItem, source: str, today: str) -> dict:
    due = it.due_date or ""
    return {"key": f"m{it.id}", "source": source, "title": it.title, "tag": it.tag or "",
            "due": due, "asg_id": it.asg_id, "must": True,
            "forced": bool(due and due <= promote_limit(today)),
            "from_date": it.date or ""}


def carry_over_rows(db: Session, today: str) -> list[dict]:
    """昨日までの未完了（必須＋期限つきルーレット項目）を行にして返す。
    今日の必須に同じ内容（asg_id か タイトル）があるものは除く"""
    from . import life_api
    since = (date_cls.fromisoformat(today) - timedelta(days=CARRY_OVER_DAYS)).isoformat()
    today_items = must_items_for_date(db, today)
    today_titles = {m.title for m in today_items}
    today_asg = {m.asg_id for m in today_items if m.asg_id}
    rows: list[dict] = []
    seen_titles: set = set()

    # 1) 過去の必須（未完了）。新しい日付順
    items = db.execute(
        select(models.TodoItem).where(models.TodoItem.kind == models.KIND_MUST,
                                      models.TodoItem.enabled == True,  # noqa: E712
                                      models.TodoItem.date >= since,
                                      models.TodoItem.date < today)
        .order_by(models.TodoItem.date.desc(), models.TodoItem.sort, models.TodoItem.id)
    ).scalars().all()
    done_ids = {
        c.item_id for c in db.execute(
            select(models.TodoCompletion).where(models.TodoCompletion.date >= since)
        ).scalars().all()
    }
    # 同じタイトルの必須が「その日以降のどこかで」完了していれば、もう終わったものとして出さない。
    # （必須は毎日作り直すので、繰り越した先の日で完了しても、元の日の行は未完了のまま残るため）
    last_done_by_title: dict[str, str] = {}
    for c, it2 in db.execute(
        select(models.TodoCompletion, models.TodoItem)
        .join(models.TodoItem, models.TodoItem.id == models.TodoCompletion.item_id)
        .where(models.TodoItem.kind == models.KIND_MUST, models.TodoCompletion.date >= since)
    ).all():
        if c.date > last_done_by_title.get(it2.title, ""):
            last_done_by_title[it2.title] = c.date
    for it in items:
        if it.id in done_ids or it.title in today_titles or it.title in seen_titles:
            continue
        if last_done_by_title.get(it.title, "") >= (it.date or ""):
            continue
        if it.asg_id and it.asg_id in today_asg:
            continue
        seen_titles.add(it.title)
        rows.append(_must_row(it, "past_must", today))

    # 2) 期限つきで未完了のルーレット項目（期限切れ含む・期限順）
    covered_asg = today_asg | {r["asg_id"] for r in rows if r.get("asg_id")}
    for a in life_api.due_items(db):
        if not a.enabled or a.id in covered_asg or a.title in today_titles or a.title in seen_titles:
            continue
        seen_titles.add(a.title)
        forced = a.due_date <= promote_limit(today)
        rows.append({"key": f"a{a.id}", "source": "asg", "title": a.title,
                     "tag": a.category or "その他", "due": a.due_date, "asg_id": a.id,
                     "must": forced, "forced": forced, "from_date": ""})
    # 締切が近い順（期限なしは後ろ）→ 必須優先
    rows.sort(key=lambda r: (not r["forced"], r["due"] or "9999-99-99", not r["must"]))
    return rows


def day_setup_state(db: Session) -> dict:
    from . import life_api
    t = date_cls.today().isoformat()
    data = todo_today(db)
    today_rows = [_must_row(it, "today", t) for it in must_items_for_date(db, t)]
    carry = carry_over_rows(db, t)
    return {
        "date": t,
        "tomorrow": promote_limit(t),
        "done": _setting_str(db, DAY_SETUP_KEY) == t,
        "tags": [{"name": x, "icon": life_api.TAG_ICON.get(x, "🏷")} for x in life_api.all_tags(db)],
        # 入力画面の初期行：昨日までの未完了（締切が近い順）→ 今日すでに登録済みの必須
        "rows": carry + today_rows,
        "carry_count": len(carry),
        "habits": data["habits"],
        "periodic": data["periodic"],
    }


class SetupRow(BaseModel):
    title: str
    tag: str = ""
    due: str = ""            # "YYYY-MM-DD" か空
    must: bool = True        # 今日の必須に入れる（締切が近いものは True に固定される）
    asg_id: int | None = None


class DaySetupBody(BaseModel):
    rows: list[SetupRow] = []
    done: list[str] = []     # 起動画面で「✓ 終わった」を押した繰り越し行の key（"m12"＝必須 / "a5"＝ルーレット項目）


def mark_carried_done(db: Session, keys: list[str]) -> int:
    """繰り越し行を「もう終わった」にする。必須は元の日付で完了記録、ルーレット項目は進捗100%。
    commit は呼び出し側。戻り値＝処理した件数"""
    n = 0
    now = datetime.now().strftime("%H:%M")
    for key in keys:
        key = str(key or "")
        if len(key) < 2 or not key[1:].isdigit():
            continue
        rid = int(key[1:])
        if key[0] == "m":
            it = db.get(models.TodoItem, rid)
            if it is None or it.kind != models.KIND_MUST:
                continue
            d = it.date or date_cls.today().isoformat()
            exists = db.execute(
                select(models.TodoCompletion).where(models.TodoCompletion.item_id == it.id,
                                                    models.TodoCompletion.date == d)
            ).scalars().first()
            if exists is None:
                db.add(models.TodoCompletion(item_id=it.id, date=d, at=now, level="full"))
                db.flush()
            if it.asg_id:
                asg = db.get(models.Assignment, it.asg_id)
                if asg is not None and asg.due_date:
                    asg.progress = 100
            n += 1
        elif key[0] == "a":
            asg = db.get(models.Assignment, rid)
            if asg is not None:
                asg.progress = 100
                n += 1
    return n


def _norm_due(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    try:
        return datetime.strptime(s, "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise HTTPException(status_code=400, detail=f"締切は YYYY-MM-DD で指定してください（{s}）")


def apply_day_setup(db: Session, rows: list[SetupRow]) -> dict:
    """行の内容を反映：締切が近いもの／必須チェックのものは今日の必須へ、
    締切つきはルーレット項目（作成/更新）へ。空でも可。commit は呼び出し側"""
    from . import life_api
    t = date_cls.today().isoformat()
    limit = promote_limit(t)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    must_rows: list[dict] = []
    new_tags: list[str] = []
    n_asg = 0
    seen: set = set()
    for r in rows:
        title = r.title.strip()
        if not title or title in seen:
            continue
        seen.add(title)
        tag = r.tag.strip()
        due = _norm_due(r.due)
        if tag:
            new_tags.append(tag)
        asg = db.get(models.Assignment, r.asg_id) if r.asg_id else None
        if due:
            # 締切つき → ルーレット項目として持つ（既存があれば更新、無ければ作成）
            if asg is None:
                asg = models.Assignment(title=title, due_date=due, progress=0, note="",
                                        category=tag or "その他", focus=False, enabled=True,
                                        created=now)
                db.add(asg)
                db.flush()
            else:
                asg.title = title
                asg.due_date = due
                if tag:
                    asg.category = tag
            n_asg += 1
        elif asg is not None:
            # 締切を消した → ルーレット項目は期限なしに戻す
            asg.title = title
            asg.due_date = ""
            if tag:
                asg.category = tag
        is_must = bool(r.must) or bool(due and due <= limit)
        if is_must:
            must_rows.append({"title": title, "tag": tag or (asg.category if asg else ""),
                              "due_date": due, "asg_id": asg.id if asg else None})
    life_api.register_tags(db, new_tags)
    replace_must_rows(db, must_rows)
    crud.set_setting(db, DAY_SETUP_KEY, t)
    return {"must": len(must_rows), "roulette": n_asg}


def replace_must_rows(db: Session, rows: list[dict]) -> None:
    """今日の必須を丸ごと差し替え（タグ・締切・紐づけ付き）。
    同名の当日完了記録は引き継ぐ。行にタグ・締切・紐づけが無ければ同名の旧項目から引き継ぐ
    （貼り付け欄からの差し替えで起動画面の設定が消えないように）"""
    t = date_cls.today().isoformat()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # 制限中に、まだ終わっていない今日の必須を消すことはできない（「今日を始める」の最初の確定は除く）
    if _setting_str(db, DAY_SETUP_KEY) == t:
        new_titles = {r["title"] for r in rows}
        removed = [it.title for it in must_items_for_date(db, t)
                   if it.title not in new_titles and not _completed_today(db, it.id)]
        if removed:
            deny_if_locked(db, f"まだ終わっていない必須（{'、'.join(removed)[:60]}）を消すこと")
    old_comp = {}
    old_meta = {}
    for it in must_items_for_date(db, t):
        old_meta[it.title] = (it.tag or "", it.due_date or "", it.asg_id)
        c = db.execute(
            select(models.TodoCompletion).where(models.TodoCompletion.item_id == it.id,
                                                models.TodoCompletion.date == t)
        ).scalars().first()
        if c is not None:
            old_comp[it.title] = (c.at, c.level)
            db.delete(c)
        db.delete(it)
    db.flush()
    for i, r in enumerate(rows):
        m_tag, m_due, m_asg = old_meta.get(r["title"], ("", "", None))
        item = models.TodoItem(kind=models.KIND_MUST, title=r["title"], date=t, enabled=True, created=now,
                               sort=i, tag=r.get("tag") or m_tag, due_date=r.get("due_date") or m_due,
                               asg_id=r.get("asg_id") or m_asg)
        db.add(item)
        db.flush()
        if r["title"] in old_comp:
            at, level = old_comp[r["title"]]
            db.add(models.TodoCompletion(item_id=item.id, date=t, at=at, level=level))


@router.get("/api/todo/day_setup")
def get_day_setup(db: Session = Depends(get_db)):
    """その日に初めて開いたときの入力画面用。done=True なら画面は出さない"""
    return day_setup_state(db)


@router.post("/api/todo/day_setup")
def confirm_day_setup(body: DaySetupBody, db: Session = Depends(get_db)):
    """「今日を始める」：行の内容を反映して今日を確定する。空でも可"""
    n_done = mark_carried_done(db, body.done)
    result = apply_day_setup(db, body.rows)
    result["done"] = n_done
    db.commit()
    _refresh_gate(db)
    out = day_setup_state(db)
    out["result"] = result
    return out


# ---------- いまが習慣の時間帯か（ホームの全画面ロック用） ----------
def current_habit(db: Session) -> dict:
    """今の時刻が今日の習慣の時間帯に入っていて、その習慣が未完了なら返す（完了済みなら None）。
    複数重なるときは開始が早いもの。日またぎ（23:00〜01:00）にも対応"""
    now = datetime.now()
    t = now.date().isoformat()
    hm = now.strftime("%H:%M")
    # 面接などの特例の時間帯は全画面ロックを出さない（支障を出さないため）
    from . import gate_api
    if gate_api.current_exemption(db, now):
        return {"date": t, "now": hm, "habit": None, "exempt": True}
    data = todo_today(db)
    hits = []
    for h in data["habits"]:
        if h["done"] or not h["start"] or not h["end"] or h.get("record_only"):
            continue   # 記録だけの習慣は全画面ロックを出さない（F23）
        s, e = h["start"], h["end"]
        inside = (s <= hm < e) if s <= e else (hm >= s or hm < e)
        if inside:
            hits.append(h)
    if not hits:
        return {"date": t, "now": hm, "habit": None}
    hits.sort(key=lambda x: x["start"])
    h = hits[0]
    item = db.get(models.TodoItem, h["id"])
    out = {"date": t, "now": hm, "habit": h,
           "minutes": habit_need_minutes(db, item),          # タイマーで完了に必要な分数
           "window_minutes": habit_duration_minutes(item)}   # 時間帯の長さ
    # 📷 在席判定（F22）：画角外の習慣か／在席率で完了する習慣なら現在の在席分も返す（ロック画面の表示用）
    try:
        from . import presence_api
        opt = presence_api.habit_option(db, item, t)
        cfg = presence_api.presence_config(db)
        out["off_camera"] = bool(opt.get("off_camera"))
        if cfg["enabled"] and not out["off_camera"]:
            st = presence_api.window_stats(presence_api.load_day(t), item.start, item.end)
            out["presence"] = {**st, "need_min": -(-st["total_min"] * cfg["rate_min"] // 100),
                               "rate_min": cfg["rate_min"],
                               "monitor": presence_api.monitor_state(db, now)}
    except Exception:
        pass
    return out


@router.get("/api/todo/current_habit")
def get_current_habit(db: Session = Depends(get_db)):
    """いま取り組むべき習慣（時間帯内・未完了）。無ければ habit=None"""
    return current_habit(db)


class ItemBody(BaseModel):
    kind: str
    title: str
    weekdays: list[int] | None = None   # habit
    start: str = ""                     # habit
    end: str = ""                       # habit
    every_days: int | None = None       # periodic
    min_action: str = ""                # habit
    enabled: bool = True


def _validate(body: ItemBody) -> None:
    if body.kind not in KINDS:
        raise HTTPException(status_code=400, detail="kind は must / habit / periodic")
    if not body.title.strip():
        raise HTTPException(status_code=400, detail="タイトルを入力してください")
    if body.kind == models.KIND_HABIT and not body.weekdays:
        raise HTTPException(status_code=400, detail="習慣は曜日を1つ以上選んでください")


@router.get("/api/todo/items")
def list_items(db: Session = Depends(get_db)):
    ensure_todo_migration(db)
    rows = db.execute(select(models.TodoItem).order_by(models.TodoItem.kind, models.TodoItem.sort,
                                                       models.TodoItem.id)).scalars().all()
    return [{"id": r.id, "kind": r.kind, "title": r.title, "date": r.date,
             "weekdays": sorted(_weekday_set(r)), "start": r.start, "end": r.end,
             "everyDays": r.every_days, "minAction": r.min_action or "", "enabled": r.enabled,
             "created": r.created} for r in rows]


@router.post("/api/todo/items")
def create_item(body: ItemBody, db: Session = Depends(get_db)):
    _validate(body)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    item = models.TodoItem(
        kind=body.kind, title=body.title.strip(),
        date=date_cls.today().isoformat() if body.kind == models.KIND_MUST else None,
        weekdays=",".join(str(int(w)) for w in sorted(set(body.weekdays or []))) or None,
        start=body.start if body.kind == models.KIND_HABIT else "", end=body.end if body.kind == models.KIND_HABIT else "",
        every_days=max(0, int(body.every_days or 0)) if body.kind == models.KIND_PERIODIC else None,
        min_action=body.min_action.strip(), enabled=body.enabled, created=now)
    db.add(item)
    db.commit()
    return {"ok": True, "id": item.id}


@router.put("/api/todo/items/{item_id}")
def update_item(item_id: int, body: ItemBody, db: Session = Depends(get_db)):
    _validate(body)
    item = db.get(models.TodoItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="やることが見つかりません")
    _deny_weakening_update(db, item, body)
    item.kind = body.kind
    item.title = body.title.strip()
    item.weekdays = ",".join(str(int(w)) for w in sorted(set(body.weekdays or []))) or None
    item.start = body.start if body.kind == models.KIND_HABIT else ""
    item.end = body.end if body.kind == models.KIND_HABIT else ""
    item.every_days = max(0, int(body.every_days or 0)) if body.kind == models.KIND_PERIODIC else None
    item.min_action = body.min_action.strip()
    item.enabled = body.enabled
    db.commit()
    return {"ok": True}


def _counts_for_gate(db: Session, item) -> bool:
    """解放条件に入っている項目か（習慣、または今日のまだ終わっていない必須）"""
    if item.kind == models.KIND_HABIT:
        return bool(item.enabled)
    if item.kind == models.KIND_MUST:
        return item.date == date_cls.today().isoformat() and bool(item.enabled) \
            and not _completed_today(db, item.id)
    return False


def _deny_weakening_update(db: Session, item, body) -> None:
    """制限中の更新のうち、解放条件を減らすもの（無効化・種類の変更・曜日を減らす・時間帯を短くする）を拒否"""
    if not _counts_for_gate(db, item):
        return
    weak = []
    if body.kind != item.kind:
        weak.append("種類を変えること")
    if item.enabled and not body.enabled:
        weak.append("無効にすること")
    if item.kind == models.KIND_HABIT and body.kind == models.KIND_HABIT:
        if _weekday_set(item) - {int(w) for w in (body.weekdays or [])}:
            weak.append("曜日を減らすこと")
        if _slot_len(body.start, body.end) < _slot_len(item.start, item.end):
            weak.append("時間帯を短くすること")
    if weak:
        deny_if_locked(db, "／".join(weak))


@router.delete("/api/todo/items/{item_id}")
def delete_item(item_id: int, db: Session = Depends(get_db)):
    item = db.get(models.TodoItem, item_id)
    if item is not None and _counts_for_gate(db, item):
        deny_if_locked(db, "解放条件に入っている項目を削除すること")
    if item is not None:
        for c in db.execute(select(models.TodoCompletion)
                            .where(models.TodoCompletion.item_id == item.id)).scalars().all():
            db.delete(c)
        db.delete(item)
        db.commit()
    return {"ok": True}
