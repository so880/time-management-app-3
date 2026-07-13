"""Google連携（Apps Script中継）。

仕組み（docs/SETUP_GOOGLE_SYNC.md 参照）：
- ユーザーのGoogleアカウントに貼った Apps Script（gas/gas_bridge.gs）のURLへ
  バックエンドがPOSTし、専用カレンダー「FocusCafe」に予定を書き込む
  → Googleカレンダー公式アプリでスマホからも見られる。
- iPhoneのショートカットも同じURLへ勉強記録をPOSTし、Apps Scriptが
  Googleドライブの FocusCafeSync/phone_inbox.json に追記する
  → デスクトップのGoogleドライブ（G:）に同期されたファイルをこのモジュールが
    5分おきに読み、勉強記録として取り込む（結果はGドラ経由で反映）。

同期対象（今日から28日ぶん）：大学の授業（祝日・振替・休講を反映）／単発予定／
未完了課題の期限（終日イベント）。イベントは説明欄の fcid: タグで管理し、
同期のたびに範囲内を入れ替えるので二重登録されない。
"""
import json
import re
import threading
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import crud, models
from .database import SessionLocal, get_db
from .life_api import day_info

router = APIRouter()

SYNC_DAYS = 28          # 何日先まで同期するか
POLL_SECONDS = 300      # iPhone記録ファイルのチェック間隔
AUTO_SYNC_SECONDS = 6 * 3600  # カレンダー自動同期の間隔

DEFAULT_PHONE_INBOX = r"G:\マイドライブ\FocusCafeSync\phone_inbox.json"


def ensure_gcal_defaults(db: Session) -> None:
    settings = crud.get_all_settings(db)
    changed = False
    for key, default in (
        ("gas_url", ""),
        ("gas_token", ""),
        ("gcal_enabled", False),
        ("gcal_status", {}),
        ("phone_inbox_path", DEFAULT_PHONE_INBOX),
        ("phone_last_ts", 0),
        # --- 何をGoogleカレンダーへ送るか（アプリのGoogle連携設定で変更） ---
        ("gcal_class_mode", "summary"),   # summary=1日1件「○曜日課」/ detail=コマごと / none=送らない
        ("gcal_send_events", True),       # 📌単発予定
        ("gcal_send_assignments", True),  # 📚課題の期限（終日）
        ("gcal_send_jobs", True),         # 💼就活の日程
        ("gcal_send_board", True),        # 📋課題ボード（全課題の進捗一覧を今日の終日イベントに）
    ):
        if key not in settings:
            crud.set_setting(db, key, default)
            changed = True
    if changed:
        db.commit()


def _set_status(db: Session, **kw) -> None:
    st = crud.get_all_settings(db).get("gcal_status") or {}
    st.update(kw)
    crud.set_setting(db, "gcal_status", st)
    db.commit()


# ---------- 同期するイベントの組み立て ----------
DAY_NAMES = ["月", "火", "水", "木", "金", "土", "日"]


def build_events(db: Session, days: int = SYNC_DAYS) -> tuple[list, str, str]:
    today = datetime.now().date()
    start = today.isoformat()
    end = (today + timedelta(days=days)).isoformat()
    settings = crud.get_all_settings(db)
    class_mode = settings.get("gcal_class_mode") or "summary"

    # 曜日別の授業（大学カテゴリ・有効のみ）
    uni_by_wd: dict[int, list] = {}
    for b in db.execute(
        select(models.ScheduleBlock)
        .where(models.ScheduleBlock.enabled == True,  # noqa: E712
               models.ScheduleBlock.category == "大学")
    ).scalars().all():
        uni_by_wd.setdefault(b.weekday, []).append(b)

    cancelled: dict[str, set] = {}
    for c in db.execute(
        select(models.ScheduleCancellation)
        .where(models.ScheduleCancellation.date >= start,
               models.ScheduleCancellation.date <= end)
    ).scalars().all():
        cancelled.setdefault(c.date, set()).add(c.block_id)

    events = []
    # 🎓 授業：summary=1日1件「○曜日課」/ detail=コマごと / none=送らない
    if class_mode != "none":
        for i in range(days + 1):
            d = (today + timedelta(days=i)).isoformat()
            info = day_info(db, d)
            blocks = sorted(
                (b for b in uni_by_wd.get(info["effective_weekday"], [])
                 if b.id not in cancelled.get(d, set())),
                key=lambda b: b.start,
            )
            if not blocks:
                continue
            if class_mode == "detail":
                for b in blocks:
                    events.append({
                        "key": f"sch-{b.id}-{d}",
                        "title": f"🎓 {b.title}",
                        "start": f"{d}T{b.start}:00",
                        "end": f"{d}T{b.end}:00",
                        "allday": False,
                        "desc": ("時間割" + ("（振替）" if info["override"] else "")
                                 + (f"\n教室: {b.room}" if b.room else "")),
                    })
            else:  # summary：その日の授業をまとめて1件の終日イベントに
                wd = DAY_NAMES[info["effective_weekday"]]
                lines = [f"{b.start}〜{b.end} {b.title}"
                         + (f"（{b.room}）" if b.room else "") for b in blocks]
                events.append({
                    "key": f"schday-{d}",
                    "title": f"🎓 {wd}曜日課（{len(blocks)}コマ）"
                             + ("・振替" if info["override"] else ""),
                    "start": d,
                    "end": d,
                    "allday": True,
                    "desc": "\n".join(lines),
                })

    # 📌 単発予定（全カテゴリ）
    if settings.get("gcal_send_events", True):
        for ev in db.execute(
            select(models.LifeEvent)
            .where(models.LifeEvent.date >= start, models.LifeEvent.date <= end)
        ).scalars().all():
            events.append({
                "key": f"ev-{ev.id}",
                "title": f"📌 {ev.title}",
                "start": f"{ev.date}T{ev.start}:00",
                "end": f"{ev.date}T{ev.end}:00",
                "allday": False,
                "desc": f"単発予定（{ev.category}）"
                        + (f"\nメモ: {ev.note}" if (ev.note or "").strip() else ""),
            })

    # 📚 未完了課題の期限（終日）
    if settings.get("gcal_send_assignments", True):
        for a in db.execute(
            select(models.Assignment)
            .where(models.Assignment.progress < 100,
                   models.Assignment.due_date >= start,
                   models.Assignment.due_date <= end)
        ).scalars().all():
            events.append({
                "key": f"asg-{a.id}",
                "title": f"📚 課題: {a.title}",
                "start": a.due_date,
                "end": a.due_date,
                "allday": True,
                "desc": f"進捗 {a.progress}%"
                        + (f"\nメモ: {a.note}" if (a.note or "").strip() else ""),
            })

    # 📋 課題ボード（全未完了課題の状態を「今日」の終日イベント1件に集約。
    #     スマホのGoogleカレンダーを開けば課題の進捗・メモがいつでも見られる）
    if settings.get("gcal_send_board", True):
        rows = db.execute(
            select(models.Assignment)
            .where(models.Assignment.progress < 100)
            .order_by(models.Assignment.due_date, models.Assignment.id)
        ).scalars().all()
        lines = []
        for a in rows:
            try:
                dleft = (datetime.strptime(a.due_date, "%Y-%m-%d").date() - today).days
                left = "今日締切！" if dleft <= 0 else f"あと{dleft}日"
            except ValueError:
                left = a.due_date
            icon = {"大学": "🎓", "私生活": "🏠", "就活": "💼"}.get(a.category or "大学", "🎓")
            line = f"・{icon} {a.title}｜{a.progress}%｜{left}（{a.due_date}）"
            if (a.note or "").strip():
                line += f"\n　　メモ: {a.note.strip()}"
            lines.append(line)
        events.append({
            "key": "asg-board",
            "title": f"📋 課題ボード（未完了{len(rows)}件）",
            "start": start,
            "end": start,
            "allday": True,
            "desc": ("\n".join(lines) if lines else "未完了の課題はありません 🎉")
                    + "\n\n（iPhoneのショートカット『課題メモ』で進捗・メモを更新できます）",
        })

    # 💼 就活の日程（説明会・面接・インターン期間）
    from . import jobs_api
    if not settings.get("gcal_send_jobs", True):
        return events, start, end
    for je in jobs_api.events_between(db, start, end):
        title = f"💼 {je.get('company', '')} {je['label']}".strip()
        if je.get("choice"):
            title += f"（第{je['choice']}希望）"
        if je.get("company"):
            desc = (f"就活（優先度: {je.get('priorityLabel', '中')}"
                    f" / 状況: {je.get('status', '')}）")
        else:
            desc = "就活（会社に紐づかない予定）"
        if je["start"] and je["end"] and not je["endDate"]:
            events.append({
                "key": f"job-{je['id']}",
                "title": title,
                "start": f"{je['date']}T{je['start']}:00",
                "end": f"{je['date']}T{je['end']}:00",
                "allday": False,
                "desc": desc,
            })
        else:
            events.append({
                "key": f"job-{je['id']}",
                "title": title,
                "start": je["date"],
                "end": je["endDate"] or je["date"],
                "allday": True,
                "desc": desc,
            })
    return events, start, end


def _post_gas(url: str, payload: dict) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as res:
        return json.load(res)


def push_calendar(db: Session) -> dict:
    """予定をGoogleカレンダー（FocusCafeカレンダー）へ反映する"""
    ensure_gcal_defaults(db)
    settings = crud.get_all_settings(db)
    url = (settings.get("gas_url") or "").strip()
    token = (settings.get("gas_token") or "").strip()
    if not url or not token:
        raise HTTPException(status_code=400,
                            detail="Apps ScriptのURLとトークンを設定してください（docs/SETUP_GOOGLE_SYNC.md 参照）")
    events, start, end = build_events(db)
    try:
        r = _post_gas(url, {"token": token, "action": "sync_events",
                            "range_start": start, "range_end": end, "events": events})
    except Exception as e:
        _set_status(db, error=f"同期に失敗: {e}")
        raise HTTPException(status_code=502, detail=f"Apps Scriptへの接続に失敗しました: {e}")
    if not r.get("ok"):
        _set_status(db, error=f"Apps Script側エラー: {r.get('error')}")
        raise HTTPException(status_code=502, detail=f"Apps Script側エラー: {r.get('error')}")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    _set_status(db, last_sync=now_str, pushed=len(events), error=None)
    return {"ok": True, "pushed": len(events), "range": f"{start}〜{end}"}


# ---------- iPhoneからの取り込み（勉強記録・支出・単発予定） ----------
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
_DATE_RE = re.compile(r"^(20\d{2})-(\d{1,2})-(\d{1,2})")


def _norm_time(s, default="00:00") -> str:
    """'9:00' → '09:00'。読めなければ default"""
    m = _TIME_RE.match(str(s or "").strip())
    if not m:
        return default
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return default
    return f"{h:02d}:{mi:02d}"


def _norm_date(s, default) -> str:
    m = _DATE_RE.match(str(s or "").strip())
    if not m:
        return default
    return f"{int(m.group(1))}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


def _import_phone_money(db: Session, item: dict, ts: float, settings: dict) -> bool:
    """iPhoneからの支出記録 → MoneyEntry（アプリで手入力したのと同じ形）"""
    from . import money_api
    try:
        amount = float(item.get("amount") or 0)
    except (TypeError, ValueError):
        return False
    if amount <= 0:
        return False
    cats = settings.get("money_categories") or ["その他"]
    category = str(item.get("category") or "").strip()
    if category not in cats:
        category = "その他" if "その他" in cats else cats[0]
    date = _norm_date(item.get("date"),
                      datetime.fromtimestamp(ts).strftime("%Y-%m-%d"))
    row = models.MoneyEntry(
        kind="spend", date=date, amount=amount, category=category,
        detail=str(item.get("detail") or "").strip()[:100],
        created_at=time.time() * 1000, source="phone",
    )
    money_api.apply_judgement(db, row)
    db.add(row)
    return True


def _import_phone_event(db: Session, item: dict, ts: float) -> bool:
    """iPhoneからの単発予定 → LifeEvent（アプリで手入力したのと同じ形）。

    endDate が入っていれば複数日の予定：date〜endDate の毎日に同じ予定を作る
    （タイムライン・カレンダー・Google同期がそのまま全日に効く方式）。
    """
    title = str(item.get("title") or "").strip()[:100]
    if not title:
        return False
    date = _norm_date(item.get("date"),
                      datetime.fromtimestamp(ts).strftime("%Y-%m-%d"))
    end_date = _norm_date(item.get("endDate"), date)
    if end_date < date:
        date, end_date = end_date, date
    start = _norm_time(item.get("start"), "00:00")
    end = _norm_time(item.get("end"), start)
    category = str(item.get("category") or "予定").strip()[:30]

    d = datetime.strptime(date, "%Y-%m-%d").date()
    last = datetime.strptime(end_date, "%Y-%m-%d").date()
    if (last - d).days > 30:
        last = d + timedelta(days=30)  # 入力ミス対策：最長31日まで
    while d <= last:
        db.add(models.LifeEvent(date=d.isoformat(), start=start, end=end,
                                title=title, category=category))
        d += timedelta(days=1)
    return True


def _import_phone_asg_note(db: Session, item: dict, ts: float) -> bool:
    """iPhoneからの課題メモ・進捗更新。

    title（部分一致・全半角/大小文字を吸収）で未完了課題を探し、
    - 見つかれば：メモを時刻付きで追記し、progress が送られていれば進捗も更新
    - 見つからなければ：新しい課題として作成（期限=7日後）→ スマホから課題も足せる
    """
    import unicodedata
    title = str(item.get("title") or "").strip()
    if not title:
        return False
    note = str(item.get("note") or "").strip()
    progress = None
    p_raw = str(item.get("progress") or "").strip()
    if p_raw:
        try:
            progress = max(0, min(100, int(float(p_raw))))
        except (TypeError, ValueError):
            progress = None
    if not note and progress is None:
        return False  # 変更内容が何もない

    def norm(s):
        return unicodedata.normalize("NFKC", str(s or "")).lower().replace(" ", "")

    key = norm(title)
    cands = [a for a in db.execute(
        select(models.Assignment)
        .where(models.Assignment.progress < 100)
        .order_by(models.Assignment.due_date, models.Assignment.id)
    ).scalars().all() if key in norm(a.title) or norm(a.title) in key]

    stamp = datetime.fromtimestamp(ts).strftime("%m/%d %H:%M")
    if cands:
        a = cands[0]  # 期限が最も近いものを更新
        if note:
            a.note = (a.note + "\n" if (a.note or "").strip() else "") + f"[📱{stamp}] {note}"
        if progress is not None:
            a.progress = progress
    else:
        due = (datetime.fromtimestamp(ts).date() + timedelta(days=7)).isoformat()
        db.add(models.Assignment(
            title=title[:200], due_date=due,
            progress=progress or 0,
            note=f"[📱{stamp}] {note}" if note else "",
            created=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ))
    from .life_api import sync_assignments_to_mustdo
    db.commit()
    sync_assignments_to_mustdo(db)  # 期限2日以内なら「今日絶対やる」へも反映
    return True


def import_phone_logs(db: Session) -> int:
    """GドラのFocusCafeSync/phone_inbox.json から新しい記録を取り込む。

    type なし（旧形式）= 勉強タイマーの記録 / type="money" = 支出 /
    type="event" = 単発予定 / type="asg_note" = 課題のメモ・進捗更新（無ければ新規作成）
    """
    settings = crud.get_all_settings(db)
    path = Path(settings.get("phone_inbox_path") or DEFAULT_PHONE_INBOX)
    if not path.exists():
        return 0
    try:
        arr = json.loads(path.read_text(encoding="utf-8") or "[]")
    except (OSError, json.JSONDecodeError):
        return 0
    if not isinstance(arr, list):
        return 0
    last_ts = float(settings.get("phone_last_ts") or 0)
    today = datetime.now().strftime("%Y-%m-%d")
    added = 0
    max_ts = last_ts
    for item in arr:
        try:
            ts = float(item.get("ts") or 0)
        except (TypeError, ValueError, AttributeError):
            continue
        if ts <= last_ts:
            continue
        max_ts = max(max_ts, ts)
        typ = str(item.get("type") or "study")

        if typ == "money":
            if _import_phone_money(db, item, ts, settings):
                added += 1
            continue
        if typ == "event":
            if _import_phone_event(db, item, ts):
                added += 1
            continue
        if typ == "asg_note":
            if _import_phone_asg_note(db, item, ts):
                added += 1
            continue

        # 旧形式＝勉強タイマーの記録
        try:
            minutes = int(item.get("minutes") or 0)
            task = str(item.get("task") or "勉強")[:100]
            date = str(item.get("date") or today)[:10]
        except (TypeError, ValueError, AttributeError):
            continue
        if minutes <= 0:
            continue
        crud.add_log(db, f"{date} {datetime.fromtimestamp(ts).strftime('%H:%M:%S')}",
                     "勉強", f"📱 {task}", "スマホ", minutes)
        if date == today:
            row = crud.get_or_create_state(db)
            row.study_time_total += minutes
        added += 1
    if max_ts > last_ts:
        crud.set_setting(db, "phone_last_ts", max_ts)
        db.commit()
    if added:
        _set_status(db, phone_imported=datetime.now().strftime("%Y-%m-%d %H:%M"),
                    phone_added=added)
    return added


# ---------- バックグラウンド（iPhone記録の取り込み＋カレンダー自動同期） ----------
def poll_loop() -> None:
    time.sleep(30)
    last_push = 0.0
    while True:
        try:
            with SessionLocal() as db:
                ensure_gcal_defaults(db)
                import_phone_logs(db)
                settings = crud.get_all_settings(db)
                if (settings.get("gcal_enabled")
                        and settings.get("gas_url") and settings.get("gas_token")
                        and time.time() - last_push > AUTO_SYNC_SECONDS):
                    try:
                        push_calendar(db)
                        last_push = time.time()
                    except HTTPException:
                        last_push = time.time()  # 失敗してもすぐ再試行しない
        except Exception:
            pass  # ループは絶対に落とさない
        time.sleep(POLL_SECONDS)


# ---------- API ----------
@router.post("/api/gcal/sync")
def gcal_sync(db: Session = Depends(get_db)):
    """今すぐGoogleカレンダーへ同期"""
    return push_calendar(db)


@router.post("/api/gcal/import_phone")
def gcal_import_phone(db: Session = Depends(get_db)):
    """今すぐiPhone記録を取り込む"""
    ensure_gcal_defaults(db)
    return {"ok": True, "added": import_phone_logs(db)}


@router.get("/api/gcal/status")
def gcal_status(db: Session = Depends(get_db)):
    ensure_gcal_defaults(db)
    settings = crud.get_all_settings(db)
    return {
        "configured": bool((settings.get("gas_url") or "").strip()
                           and (settings.get("gas_token") or "").strip()),
        "enabled": bool(settings.get("gcal_enabled")),
        "status": settings.get("gcal_status") or {},
        "phone_inbox_path": settings.get("phone_inbox_path") or DEFAULT_PHONE_INBOX,
    }
