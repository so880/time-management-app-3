"""Google連携（Apps Script中継）。

仕組み（docs/SETUP_GOOGLE_SYNC.md 参照）：
- ユーザーのGoogleアカウントに貼った Apps Script（gas/gas_bridge.gs）のURLへ
  バックエンドがPOSTし、専用カレンダー「FocusCafe」に予定を書き込む
  → Googleカレンダー公式アプリでスマホからも見られる。
- スマホのページ・iPhoneのショートカットは同じURLへ勉強記録を送り、Apps Script の受け取り箱にためる
  → このモジュールが Apps Script の phone_sync を定期的に呼んで受け取り箱を取り込み、
    勉強記録にする（Googleドライブのファイル経由の取り込みは 2026-11 に廃止）。

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

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from . import crud, models
from .database import SessionLocal, get_db
from .life_api import day_info

router = APIRouter()

SYNC_DAYS = 28          # 何日先まで同期するか
POLL_SECONDS = 300      # iPhone記録ファイルのチェック間隔
AUTO_SYNC_SECONDS = 6 * 3600  # カレンダー自動同期の間隔



def ensure_gcal_defaults(db: Session) -> None:
    settings = crud.get_all_settings(db)
    changed = False
    for key, default in (
        ("gas_url", ""),
        ("gas_token", ""),
        ("gcal_enabled", False),
        ("gcal_status", {}),
        ("phone_last_ts", 0),
        # --- 何をGoogleカレンダーへ送るか（アプリのGoogle連携設定で変更） ---
        ("gcal_class_mode", "summary"),   # summary=1日1件「○曜日課」/ detail=コマごと / none=送らない
        ("gcal_send_events", True),       # 📌単発予定
        ("gcal_send_assignments", True),  # 📚課題の期限（終日）
        ("gcal_send_jobs", True),         # 💼就活の日程
        ("gcal_send_board", True),        # 📋課題ボード（全課題の進捗一覧を今日の終日イベントに）
        ("gcal_send_today", True),        # 📌今日やること（mustdo・締切近課題・AIプランを今日の終日イベントに）
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
                   models.Assignment.due_date != "",
                   models.Assignment.due_date >= start,
                   models.Assignment.due_date <= end)
        ).scalars().all():
            events.append({
                "key": f"asg-{a.id}",
                "title": f"📌 期限: {a.title}",
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
            .where(models.Assignment.progress < 100, models.Assignment.due_date != "")
            .order_by(models.Assignment.due_date, models.Assignment.id)
        ).scalars().all()
        lines = []
        for a in rows:
            try:
                dleft = (datetime.strptime(a.due_date, "%Y-%m-%d").date() - today).days
                left = "今日締切！" if dleft <= 0 else f"あと{dleft}日"
            except ValueError:
                left = a.due_date
            icon = {"就活": "💼", "大学": "🎓", "私用": "🏠"}.get(a.category or "その他", "📌")
            line = f"・{icon} {a.title}｜{a.progress}%｜{left}（{a.due_date}）"
            if (a.note or "").strip():
                line += f"\n　　メモ: {a.note.strip()}"
            lines.append(line)
        events.append({
            "key": "asg-board",
            "title": f"📋 期限ボード（未完了{len(rows)}件）",
            "start": start,
            "end": start,
            "allday": True,
            "desc": ("\n".join(lines) if lines else "期限のある項目はありません 🎉")
                    + "\n\n（iPhoneのショートカット『課題メモ』で進捗・メモを更新できます）",
        })

    # 📌 今日やること（スマホからも「今日の全部」が見える終日イベント）
    if settings.get("gcal_send_today", True):
        from .life_api import briefing
        b = briefing(db)
        parts = []
        if b["mustdo"]:
            parts.append("🔴 今日の必須（未完了）:\n" + "\n".join(f"・{x}" for x in b["mustdo"]))
        if b["assignments"]:
            asg_lines = []
            for a in b["assignments"]:
                left = "今日締切！" if a["daysLeft"] <= 0 else f"あと{a['daysLeft']}日"
                asg_lines.append(f"・{a['title']}（{left}・{a['progress']}%）")
            parts.append("📌 期限が近い項目:\n" + "\n".join(asg_lines))
        if b["events"]:
            parts.append("📌 今日の予定:\n" + "\n".join(
                f"・{e['start']}〜{e['end']} {e['title']}" for e in b["events"]))
        today_jobs = [j for j in b["jobs"] if j["date"] == start
                      or (j.get("endDate") and j["date"] <= start <= j["endDate"])]
        if today_jobs:
            parts.append("💼 今日の就活:\n" + "\n".join(
                f"・{j.get('company', '')} {j['label']}".strip() for j in today_jobs))
        stx = b["study"]
        parts.append(f"⏱ 勉強: 目標{stx['target_min']}分（昨日{stx['yesterday_min']}分）")
        if b.get("ai_plan"):
            parts.append("🤖 今日のプラン:\n" + b["ai_plan"])
        events.append({
            "key": "today-plan",
            "title": "📌 今日やること",
            "start": start,
            "end": start,
            "allday": True,
            "desc": "\n\n".join(parts),
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


# ---------- Googleメインカレンダーの読み取り（表示専用） ----------
GOOGLE_PULL_BACK_DAYS = 7      # 何日前から
GOOGLE_PULL_AHEAD_DAYS = 62    # 何日先まで
GOOGLE_PULL_KEY = "gcal_google_pull"   # 最後に読み取った時刻・範囲・カレンダー名（settings）。予定は google_events テーブル


def _clean_google_event(raw: dict) -> dict | None:
    """Apps Script から来た1件を表示用の形に整える（不正なものは None）"""
    if not isinstance(raw, dict):
        return None
    date = _norm_date(raw.get("date"), "")
    if not date:
        return None
    end_date = _norm_date(raw.get("endDate"), date)
    if end_date < date:
        end_date = date
    allday = bool(raw.get("allday"))
    return {
        "id": str(raw.get("id") or ""),
        "title": str(raw.get("title") or "").strip() or "(無題)",
        "allday": allday,
        "date": date,
        "endDate": end_date,
        "start": "" if allday else _norm_time(raw.get("start"), ""),
        "end": "" if allday else _norm_time(raw.get("end"), ""),
        "location": str(raw.get("location") or "").strip(),
        # 作成日時（"YYYY-MM-DDTHH:MM:SS"）。面接などの特例は「開始24時間以上前に作成」が条件（gate_api）
        "created": str(raw.get("created") or "")[:19],
        # 繰り返しの予定か・自分が作った予定か（Apps Script 2026-11-07a 以降。古い版は None＝特例にしない）
        "recurring": raw["recurring"] if isinstance(raw.get("recurring"), bool) else None,
        "ownedByMe": raw["ownedByMe"] if isinstance(raw.get("ownedByMe"), bool) else None,
    }


def pull_google_events(db: Session) -> dict:
    """メインカレンダーの予定を Apps Script 経由で取り、settings に保存する（読み取り専用）"""
    ensure_gcal_defaults(db)
    settings = crud.get_all_settings(db)
    url = (settings.get("gas_url") or "").strip()
    token = (settings.get("gas_token") or "").strip()
    if not url or not token:
        raise HTTPException(status_code=400,
                            detail="Apps ScriptのURLとトークンを設定してください（docs/SETUP_GOOGLE_SYNC.md 参照）")
    today = datetime.now().date()
    start = (today - timedelta(days=GOOGLE_PULL_BACK_DAYS)).isoformat()
    end = (today + timedelta(days=GOOGLE_PULL_AHEAD_DAYS)).isoformat()
    try:
        r = _post_gas(url, {"token": token, "action": "list_events",
                            "range_start": start, "range_end": end})
    except Exception as e:
        _set_status(db, pull_error=f"取り込みに失敗: {e}")
        raise HTTPException(status_code=502, detail=f"Apps Scriptへの接続に失敗しました: {e}")
    if not r.get("ok"):
        err = str(r.get("error") or "")
        if err == "unknown action":
            err = "Apps Script が古いです。gas/gas_bridge.gs を貼り直して再デプロイしてください"
        _set_status(db, pull_error=f"Apps Script側エラー: {err}")
        raise HTTPException(status_code=502, detail=f"Apps Script側エラー: {err}")
    events = []
    for raw in r.get("events") or []:
        ev = _clean_google_event(raw)
        if ev is not None:
            events.append(ev)
    events.sort(key=lambda x: (x["date"], x["start"]))
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    # 読み取った範囲の予定をまるごと入れ替える（Google 側で消された予定を残さない）
    db.execute(delete(models.GoogleEvent))
    for ev in events:
        db.add(models.GoogleEvent(event_id=ev["id"], title=ev["title"], allday=ev["allday"], date=ev["date"],
                                  end_date=ev["endDate"], start=ev["start"], end=ev["end"],
                                  location=ev["location"], created=ev["created"],
                                  recurring=ev["recurring"], owned_by_me=ev["ownedByMe"]))
    crud.set_setting(db, GOOGLE_PULL_KEY, {"fetched": now_str, "start": start, "end": end,
                                           "calendar": str(r.get("calendar") or "")})
    db.commit()
    _set_status(db, last_pull=now_str, pulled=len(events), pull_error=None)
    return {"ok": True, "pulled": len(events), "range": f"{start}〜{end}",
            "calendar": str(r.get("calendar") or "")}


def google_events_between(db: Session, start: str, end: str) -> dict[str, list]:
    """保存済みのGoogle予定を {日付: [予定...]} で返す（期間ものは各日に展開）"""
    rows = db.execute(select(models.GoogleEvent).where(models.GoogleEvent.date <= end,
                                                       models.GoogleEvent.end_date >= start)).scalars().all()
    out: dict[str, list] = {}
    for r in rows:
        ev = {"id": r.event_id, "title": r.title, "allday": bool(r.allday), "date": r.date,
              "endDate": r.end_date, "start": r.start, "end": r.end, "location": r.location,
              "created": r.created, "recurring": r.recurring, "ownedByMe": r.owned_by_me}
        s = max(ev.get("date", ""), start)
        e = min(ev.get("endDate") or ev.get("date", ""), end)
        if not s or not e or e < s:
            continue
        try:
            dd = datetime.strptime(s, "%Y-%m-%d").date()
            end_d = datetime.strptime(e, "%Y-%m-%d").date()
        except ValueError:
            continue
        while dd <= end_d:
            out.setdefault(dd.isoformat(), []).append(ev)
            dd += timedelta(days=1)
    for lst in out.values():
        lst.sort(key=lambda x: (not x["allday"], x["start"]))  # 終日→時刻順
    return out


def google_events_for(db: Session, date: str) -> list:
    return google_events_between(db, date, date).get(date, [])


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
            category="その他", focus=False, enabled=True,
            created=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ))
    db.flush()  # commit は呼び出し側（1件ごとのセーブポイント内で呼ばれるため）
    return True


_phone_import_lock = threading.Lock()


def import_phone_items(db: Session, arr) -> int:
    """受け取り箱の配列（Apps Script の phone_sync の返事）から新しい記録を取り込む。
    phone_last_ts より新しい ts のものだけ処理するので、同じ記録が二重に入らない。
    30秒ごとの取り込みと画面の「今すぐ取り込む」が同時に動くと、同じ phone_last_ts を読んで
    同じ記録を両方が追加してしまうので、取り込みは1本ずつにする（2026-11-06）"""
    if not isinstance(arr, list):
        return 0
    with _phone_import_lock:
        # 前の取り込みが書いた phone_last_ts を確実に読むため、読み取り中のトランザクションを閉じてから始める
        db.commit()
        return _import_phone_items_locked(db, arr)


def _import_phone_items_locked(db: Session, arr: list) -> int:
    from . import gate_api
    settings = crud.get_all_settings(db)
    last_ts = float(settings.get("phone_last_ts") or 0)
    habit_touched = False
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
        try:
            with db.begin_nested():  # 1件ごとのセーブポイント：壊れた1件で全体を止めない
                if _import_one(db, item, ts, settings, today):
                    added += 1
        except Exception:
            continue
    if max_ts > last_ts:
        crud.set_setting(db, "phone_last_ts", max_ts)
        db.commit()
    if habit_touched:
        db.commit()
        gate_api.gate_state(db)
    if added:
        _set_status(db, phone_imported=datetime.now().strftime("%Y-%m-%d %H:%M"),
                    phone_added=added)
    return added


def _import_one(db: Session, item: dict, ts: float, settings: dict, today: str) -> bool:
    """受け取り箱の1件を取り込む。True=取り込んだ"""
    typ = str(item.get("type") or "study")

    if typ == "money":
        return _import_phone_money(db, item, ts, settings)
    if typ == "event":
        return _import_phone_event(db, item, ts)
    if typ == "asg_note":
        return _import_phone_asg_note(db, item, ts)
    if typ == "habit_done":
        # セキュリティ：スマホからの「習慣完了」は解放判定に使わない（合言葉が漏れても制限を外せないように）。
        # 習慣は PC 側のタイマー（規定時間）でのみ完了する。ここでは受け取った事実だけ記録する
        title = str(item.get("title") or "").strip()
        crud.add_log(db, datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S"), "メモ",
                     f"📱 習慣チェック（参考のみ）: {title}", "スマホ", 0)
        return bool(title)

    # 旧形式＝勉強タイマーの記録
    try:
        minutes = int(item.get("minutes") or 0)
        task = str(item.get("task") or "勉強")[:100]
    except (TypeError, ValueError, AttributeError):
        return False
    if minutes <= 0:
        return False
    # 0時をまたいだ計測は前日分と当日分に分ける（ts＝ストップした時刻）
    today_min = 0
    for when, mins, day in crud.split_minutes_by_day(ts, minutes):
        crud.add_log(db, when, "勉強", f"📱 {task}", "スマホ", mins)
        if day == today:
            today_min += mins
    # 今日の勉強時間は記録の合計から数える（crud.study_minutes）。
    # セキュリティ：スマホの勉強記録では習慣を完了にしない（PC 側のタイマーのみ）
    return True


# スマホ用ページに送る一覧の上限（Apps Script の ScriptProperties は1件 9KB までのため）
PHONE_LIST_LIMIT = {"roulette": 40, "due": 25, "events": 20}


def build_phone_choices(db: Session) -> dict:
    """スマホ用ページに渡す内容：スタートの選択肢（小窓と同じ）＋「予定・課題を見る」の中身。
    must / habits / roulette は従来の choices.json と同じ形（ショートカット互換）"""
    from . import todo_api
    td = todo_api.todo_today(db)
    today = datetime.now().date()
    t = today.isoformat()
    tomorrow = (today + timedelta(days=1)).isoformat()
    icon = {"就活": "💼", "大学": "🎓", "私用": "🏠"}

    roulette = [a.title for a in db.execute(
        select(models.Assignment)
        .where(models.Assignment.progress < 100, models.Assignment.enabled == True)  # noqa: E712
        .order_by(models.Assignment.focus.desc(), models.Assignment.id)
    ).scalars().all()][:PHONE_LIST_LIMIT["roulette"]]

    due = []
    for a in db.execute(
        select(models.Assignment)
        .where(models.Assignment.progress < 100, models.Assignment.due_date != "")
        .order_by(models.Assignment.due_date, models.Assignment.id)
    ).scalars().all()[:PHONE_LIST_LIMIT["due"]]:
        try:
            left = (datetime.strptime(a.due_date, "%Y-%m-%d").date() - today).days
        except ValueError:
            left = None
        due.append({"title": a.title, "due": a.due_date, "left": left, "progress": a.progress,
                    "icon": icon.get(a.category or "その他", "📌")})

    events = []
    for d in (t, tomorrow):
        for ev in db.execute(
            select(models.LifeEvent).where(models.LifeEvent.date == d)
            .order_by(models.LifeEvent.start)
        ).scalars().all():
            events.append({"date": d, "start": ev.start or "", "end": ev.end or "",
                           "title": ev.title, "google": False, "done": bool(ev.done)})
        for ev in google_events_for(db, d):
            events.append({"date": d, "start": ev.get("start") or "", "end": ev.get("end") or "",
                           "title": ev.get("title") or "", "google": True, "done": False})
    events.sort(key=lambda e: (e["date"], e["start"] or "00:00"))

    return {
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "date": t,
        "must": [m["title"] for m in td["must"] if not m["checked"]],
        "must_all": [{"title": m["title"], "done": bool(m["checked"]), "due": m["due"]}
                     for m in td["must"]],
        "habits": [{"title": h["title"], "start": h["start"], "end": h["end"],
                    "done": h["done"]} for h in td["habits"]],
        "roulette": roulette,
        "due": due,
        "events": events[:PHONE_LIST_LIMIT["events"]],
    }


# ---------- iPhone のタイマー（Apps Script に直接問い合わせ。約30秒ごと） ----------
PHONE_POLL_SECONDS = 30
_PHONE_TIMER = {"running": False, "task": "", "started_ms": 0, "checked": 0.0}
# main.py が起動時に差し込む：PC 側の計測状態（小窓/集中モード）と、スマホからの停止要求の処理
pc_timer_provider = None
pc_stop_handler = None


def phone_timer_state() -> dict:
    """iPhone で動いているタイマー（アプリの表示用）。elapsed は PC 側の時計で補正"""
    if not _PHONE_TIMER["running"]:
        return {"running": False, "task": "", "elapsed_sec": 0}
    elapsed = int(time.time() - _PHONE_TIMER["started_ms"] / 1000)
    return {"running": True, "task": _PHONE_TIMER["task"], "elapsed_sec": max(0, elapsed)}


def phone_sync_once(db: Session) -> dict:
    """Apps Script の phone_sync を1回呼び、タイマー状態の更新と受け取り箱の取り込みを行う"""
    settings = crud.get_all_settings(db)
    url = (settings.get("gas_url") or "").strip()
    token = (settings.get("gas_token") or "").strip()
    if not url or not token:
        raise HTTPException(status_code=400, detail="Apps ScriptのURLとトークンを設定してください")
    pc = {"running": False}
    if pc_timer_provider is not None:
        try:
            pc = pc_timer_provider()
        except Exception:
            pc = {"running": False}
    # スマホ用ページの選択肢・予定・課題も一緒に送る（スマホのページがいつ開かれても最新になるように）
    try:
        choices = build_phone_choices(db)
    except Exception:
        choices = None
    r = _post_gas(url, {"token": token, "action": "phone_sync", "pc_timer": pc, "choices": choices})
    if not r.get("ok"):
        raise HTTPException(status_code=502, detail=f"Apps Script側エラー: {r.get('error')}")
    # スマホから「PC の計測を止めて記録」が来ていたら実行
    if r.get("cmd") == "pc_stop" and pc_stop_handler is not None:
        try:
            pc_stop_handler()
        except Exception:
            pass
    t = r.get("timer") or {}
    _PHONE_TIMER.update({
        "running": bool(t.get("running")), "task": str(t.get("task") or ""),
        "started_ms": int(t.get("started") or 0), "checked": time.time(),
    })
    added = import_phone_items(db, r.get("inbox") or [])
    # スマホのタイマーは記録のみ（習慣の完了判定は PC 側のタイマーだけ。合言葉漏えい対策）
    st = phone_timer_state()
    return {"ok": True, "timer": st, "added": added}


def phone_poll_loop() -> None:
    """iPhone のスタート/ストップを即反映するための短い間隔のループ（失敗しても落とさない）"""
    time.sleep(20)
    while True:
        try:
            with SessionLocal() as db:
                settings = crud.get_all_settings(db)
                if settings.get("gcal_enabled") and settings.get("gas_url") and settings.get("gas_token"):
                    try:
                        phone_sync_once(db)
                    except HTTPException as e:
                        _set_status(db, phone_error=str(e.detail))
                    except Exception as e:  # 取り込み中の想定外エラーも画面で見えるようにする
                        db.rollback()
                        _set_status(db, phone_error=f"取り込みエラー: {type(e).__name__}: {str(e)[:160]}")
                    else:
                        if (crud.get_all_settings(db).get("gcal_status") or {}).get("phone_error"):
                            _set_status(db, phone_error=None)
        except Exception:
            pass
        time.sleep(PHONE_POLL_SECONDS)


# ---------- バックグラウンド（iPhone記録の取り込み＋カレンダー自動同期） ----------
def poll_loop() -> None:
    time.sleep(30)
    last_push = 0.0
    while True:
        try:
            with SessionLocal() as db:
                ensure_gcal_defaults(db)
                settings = crud.get_all_settings(db)
                configured = bool(settings.get("gcal_enabled")
                                  and settings.get("gas_url") and settings.get("gas_token"))
                if configured and time.time() - last_push > AUTO_SYNC_SECONDS:
                    try:
                        push_calendar(db)
                        last_push = time.time()
                    except HTTPException:
                        last_push = time.time()  # 失敗してもすぐ再試行しない
                if configured:
                    # メインカレンダーの読み取り（5分ごと。失敗は gcal_status.pull_error に残す）
                    try:
                        pull_google_events(db)
                    except HTTPException:
                        pass
        except Exception:
            pass  # ループは絶対に落とさない
        time.sleep(POLL_SECONDS)


# ---------- API ----------
@router.post("/api/gcal/sync")
def gcal_sync(db: Session = Depends(get_db)):
    """今すぐGoogleカレンダーへ同期"""
    return push_calendar(db)


@router.post("/api/gcal/pull")
def gcal_pull(db: Session = Depends(get_db)):
    """今すぐGoogleメインカレンダーの予定を読み取る（表示専用）"""
    return pull_google_events(db)


@router.get("/api/gcal/google_events")
def gcal_google_events(start: str, end: str, db: Session = Depends(get_db)):
    """保存済みのGoogle予定（{日付: [予定...]}）。取得時刻も返す"""
    box = crud.get_all_settings(db).get(GOOGLE_PULL_KEY) or {}
    return {"fetched": box.get("fetched") or "", "calendar": box.get("calendar") or "",
            "days": google_events_between(db, start, end)}


@router.post("/api/gcal/import_phone")
def gcal_import_phone(db: Session = Depends(get_db)):
    """今すぐiPhone記録を取り込む（Apps Script の phone_sync を1回呼ぶ）"""
    ensure_gcal_defaults(db)
    r = phone_sync_once(db)
    return {"ok": True, "added": r["added"], "timer": r["timer"]}


@router.get("/api/phone/timer")
def phone_timer(db: Session = Depends(get_db)):
    """iPhone で動いているタイマーの状態（約30秒ごとに更新）"""
    return phone_timer_state()


@router.get("/api/gcal/status")
def gcal_status(db: Session = Depends(get_db)):
    ensure_gcal_defaults(db)
    settings = crud.get_all_settings(db)
    return {
        "configured": bool((settings.get("gas_url") or "").strip()
                           and (settings.get("gas_token") or "").strip()),
        "enabled": bool(settings.get("gcal_enabled")),
        # 保存済みの URL がどれか画面で確認できるように末尾だけ返す（全体は返さない）
        "url_tail": (settings.get("gas_url") or "").strip()[-17:],
        "token_len": len((settings.get("gas_token") or "").strip()),
        "status": settings.get("gcal_status") or {},
    }
