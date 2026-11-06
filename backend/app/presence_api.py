"""📷 Webカメラ在席判定（F22）。

役割
  - webcam_worker.py（PC内の常駐ワーカー）が OpenCV の顔検出で「在席／不在」だけを判定し、
    約10秒ごとに POST /api/presence/ping で知らせてくる。画像はここには来ない（外部送信もしない）。
  - ここでは「分」単位にまとめて logs/presence/YYYY-MM-DD.json に残し、
    習慣の時間帯の在席率が基準（既定 70%）以上になったら、その習慣を完了にする
    （todo_completions に level="full" で記録。テーブル・列の追加はしない）。
  - 監視する時間帯は 07:00〜21:00 のうち授業以外（時間割の「大学」＋ Googleカレンダーの【大学】）。
    面接などの特例（gate_api.current_exemption）の間も監視しない。

設定（settings テーブル。key/JSON なのでスキーマ変更なし）
  presence_enabled        … 在席判定を使う（既定 False。カメラが無い PC では意味が無いため）
  presence_rate_min       … 完了とみなす在席率（%）。既定 70。下げる変更は翌日から有効（抜け道防止）
  webcam_log_enabled      … 30秒ごとの時刻入り静止画を logs/webcam/ に保存する（既定 False）
  webcam_log_interval_sec … 静止画の間隔（既定 30）
  webcam_log_keep_days    … 静止画を残す日数（既定 14。古い日のフォルダはワーカーが消す）
  camera_index            … 使うカメラの番号（既定 0。環境変数 FC_CAMERA_INDEX があればワーカーはそちらを優先）
  habit_options           … {習慣の番号(todo_items.id): {off_camera, min_minutes, record_only, camera_off, since, prev}}
                            （2026-11-06 に習慣名→番号へ。名前を変えても設定が消えない）
                            camera_off=True の習慣（AI面接の練習など）は、その時間帯はカメラを開かない
                            （面接アプリがカメラを使うため。2026-11-03）
                            off_camera=True の習慣（筋トレ等）は在席率では完了にせず、
                            小窓のタイマーで min_minutes 以上やったときだけ完了にする
                            record_only=True の習慣（F23・2026-11-02）は「記録だけ」：解放条件（tasks_done）に
                            入れず、全画面ロックも出さず、自己申告のチェックで完了にできる。
                            record_only にする変更は解放条件を減らすので翌日から有効（since/prev）

データの置き場所
  logs/presence/YYYY-MM-DD.json … {"minutes": {"HH:MM": "P"|"A"}, "completed": {習慣名: "HH:MM"}}
  （P=在席、A=不在。授業・時間外・特例の分は記録しない＝分母にも入れない）
"""
import json
import threading
import time
from datetime import date as date_cls, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import crud, models, policy
from .database import get_db

router = APIRouter()

ROOT = Path(__file__).resolve().parents[2]          # C:\Life_app
PRESENCE_DIR = ROOT / "logs" / "presence"
WEBCAM_DIR = ROOT / "logs" / "webcam"

MONITOR_START = policy.MONITOR_WINDOW["start"]   # 起きている時間（policy.py。ゲームの時間帯と同じ）
MONITOR_END = policy.MONITOR_WINDOW["end"]
DEFAULT_RATE_MIN = 70
RATE_MIN_FLOOR = 50       # これより下には下げられない
OFF_CAMERA_MIN_FLOOR = 10 # 画角外習慣の最低時間（分）はこれ未満にできない
CLASS_KEYWORDS = ("【大学】", "大学")   # Googleカレンダーの予定名でこれを含むものは授業扱い
# 💼 面接などの予定（Google＋アプリの単発予定）の前後はカメラを強制オフ（面接アプリに影響させない。2026-11-03）
CAMERA_OFF_MARGIN_MIN = 60

_lock = threading.Lock()
_cache: dict = {"date": "", "data": None}   # 今日ぶんのメモリキャッシュ（ファイルは分が変わるたびに書く）
_last_check_minute = ""                      # 習慣の完了チェックを分に1回にするため
# 📷 カメラの状態（メモリのみ）。ワーカーが ping/camera_result で知らせ、画面の「カメラを確認」が読む
_cam: dict = {"test_requested": 0.0, "last": None}
DARK_BRIGHTNESS = 10   # 平均輝度（0〜255）がこれ未満なら「真っ暗」とみなす
CAMERA_INDEX_MAX = 9   # camera_index に入れられる上限（ワーカーの「確認」は 0〜4 を探す）


# ---------- 設定 ----------
def _settings(db: Session) -> dict:
    return crud.get_all_settings(db)


def presence_config(db: Session) -> dict:
    s = _settings(db)
    today = date_cls.today().isoformat()
    rate = s.get("presence_rate_min")
    if not isinstance(rate, dict):
        rate = {"value": int(rate) if isinstance(rate, (int, float)) else DEFAULT_RATE_MIN,
                "since": "", "prev": DEFAULT_RATE_MIN}
    eff_rate = int(rate.get("value", DEFAULT_RATE_MIN))
    if rate.get("since") and today < str(rate.get("since")):
        eff_rate = int(rate.get("prev", DEFAULT_RATE_MIN))
    return {
        "enabled": bool(s.get("presence_enabled", False)),
        "rate_min": eff_rate,
        "rate_min_pending": (int(rate.get("value")) if rate.get("since") and today < str(rate.get("since")) else None),
        "rate_min_since": rate.get("since") or "",
        "camera_index": _camera_index(s),
        "webcam_log": {
            "enabled": bool(s.get("webcam_log_enabled", False)),
            "interval_sec": max(10, int(s.get("webcam_log_interval_sec") or 30)),
            "keep_days": max(1, int(s.get("webcam_log_keep_days") or 14)),
        },
    }


def _camera_index(s: dict) -> int:
    try:
        return max(0, min(CAMERA_INDEX_MAX, int(s.get("camera_index") or 0)))
    except (TypeError, ValueError):
        return 0


def habit_option(db_or_settings, item, day: str | None = None) -> dict:
    """習慣ごとの設定（画角外・最低時間）。item は習慣の行（todo_items）。弱める変更は since（翌日）まで prev が有効"""
    s = db_or_settings if isinstance(db_or_settings, dict) else _settings(db_or_settings)
    day = day or date_cls.today().isoformat()
    opts = s.get("habit_options") or {}
    o = opts.get(str(item.id)) if isinstance(opts, dict) else None
    if not isinstance(o, dict):
        return {"off_camera": False, "min_minutes": 0, "record_only": False, "camera_off": False}
    camera_off = bool(o.get("camera_off", False))   # 弱める/強めるの対象外（即日有効）
    cur = {"off_camera": bool(o.get("off_camera", False)), "min_minutes": int(o.get("min_minutes") or 0),
           "record_only": bool(o.get("record_only", False)), "camera_off": camera_off}
    if o.get("since") and day < str(o.get("since")) and isinstance(o.get("prev"), dict):
        p = o["prev"]
        return {"off_camera": bool(p.get("off_camera", False)), "min_minutes": int(p.get("min_minutes") or 0),
                "record_only": bool(p.get("record_only", False)), "camera_off": camera_off,
                "pending": cur, "since": o.get("since")}
    return cur


def is_record_only(db_or_settings, item, day: str | None = None) -> bool:
    """「記録だけ」の習慣か（解放条件・全画面ロックの対象外。F23）。item は習慣の行"""
    try:
        return bool(habit_option(db_or_settings, item, day).get("record_only"))
    except Exception:
        return False


def _weaker(new: dict, old: dict) -> bool:
    """習慣設定が「完了しやすくなる方向」か（画角外にする／最低時間を短くする／記録だけにする）"""
    if new.get("record_only") and not old.get("record_only"):
        return True
    if new["off_camera"] and not old["off_camera"]:
        return True
    if new["off_camera"] and old["off_camera"] and 0 < new["min_minutes"] < (old["min_minutes"] or 10 ** 6):
        return True
    return False


def set_habit_option(db: Session, item, off_camera: bool, min_minutes: int, window_minutes: int,
                     record_only: bool = False, camera_off: bool = False) -> dict:
    """画角外・最低時間・記録だけ を保存（item は習慣の行）。弱める変更は翌日から（since=明日、prev=今の有効値）。
    commit は呼び出し側"""
    min_minutes = int(min_minutes or 0)
    if off_camera:
        if min_minutes <= 0:
            min_minutes = window_minutes
        if min_minutes < OFF_CAMERA_MIN_FLOOR:
            raise HTTPException(status_code=400, detail=f"最低時間は {OFF_CAMERA_MIN_FLOOR} 分以上にしてください")
        if window_minutes and min_minutes > window_minutes:
            min_minutes = window_minutes
    else:
        min_minutes = 0
    s = _settings(db)
    today = date_cls.today().isoformat()
    cur_eff = habit_option(s, item, today)
    cur_eff = {"off_camera": cur_eff["off_camera"], "min_minutes": cur_eff["min_minutes"],
               "record_only": bool(cur_eff.get("record_only"))}
    new = {"off_camera": bool(off_camera), "min_minutes": min_minutes, "record_only": bool(record_only)}
    opts = dict(s.get("habit_options") or {})
    if _weaker(new, cur_eff):
        new.update({"since": (date_cls.today() + timedelta(days=1)).isoformat(), "prev": cur_eff})
    new["camera_off"] = bool(camera_off)   # カメラ停止は解放条件と無関係なので即日
    opts[str(item.id)] = new
    crud.set_setting(db, "habit_options", opts)
    return habit_option({"habit_options": opts}, item, today)


# ---------- 監視すべき時間帯か ----------
_hm_in = policy.in_window


def class_blocks(db: Session, day: str) -> list[dict]:
    """その日の授業の時間帯（時間割の「大学」＋ Googleカレンダーの【大学】。休講は除く）"""
    from . import life_api
    info = life_api.day_info(db, day)
    cancelled = {
        r.block_id for r in db.execute(
            select(models.ScheduleCancellation).where(models.ScheduleCancellation.date == day)
        ).scalars().all()
    }
    out = []
    for b in db.execute(
        select(models.ScheduleBlock).where(models.ScheduleBlock.enabled == True,  # noqa: E712
                                           models.ScheduleBlock.weekday == info["effective_weekday"],
                                           models.ScheduleBlock.category == "大学")
    ).scalars().all():
        if b.id in cancelled:
            continue
        out.append({"start": b.start, "end": b.end, "title": b.title, "source": "timetable"})
    try:
        from . import gcal_sync
        for g in gcal_sync.google_events_for(db, day) or []:
            if g.get("allday") or not g.get("start") or not g.get("end"):
                continue
            if any(k in str(g.get("title") or "") for k in CLASS_KEYWORDS):
                out.append({"start": g["start"], "end": g["end"], "title": g.get("title") or "", "source": "google"})
    except Exception:
        pass  # Google 連携が未設定・一時的な失敗は授業なし扱い
    return sorted(out, key=lambda x: x["start"])


def _shift_hm(hm: str, minutes: int) -> str:
    h, m = [int(x) for x in hm.split(":")]
    t = max(0, min(24 * 60, h * 60 + m + minutes))
    return f"{t // 60:02d}:{t % 60:02d}" if t < 24 * 60 else "24:00"


def camera_off_windows(db: Session, day: str) -> list[dict]:
    """カメラを強制オフにする時間帯 [{start, end, title, source}]（2026-11-03）：
    1. camera_off=True の習慣（AI面接の練習など）の時間帯
    2. 面接などの予定（名前に policy.EXEMPT_KINDS を含む。Google＋アプリの単発予定）の前後 CAMERA_OFF_MARGIN_MIN 分
       ※ こちらは「24時間前に作成」の条件を付けない（カメラを止めるだけで制限は緩まないため）"""
    from . import todo_api
    s = _settings(db)
    out = []
    for it in todo_api.habits_for_date(db, day):
        if it.start and it.end and habit_option(s, it, day).get("camera_off"):
            out.append({"start": it.start, "end": it.end, "title": it.title, "source": "habit"})
    events = []
    for ev in db.execute(select(models.LifeEvent).where(models.LifeEvent.date == day)).scalars().all():
        events.append({"title": ev.title or "", "start": ev.start, "end": ev.end})
    try:
        from . import gcal_sync
        for g in gcal_sync.google_events_for(db, day) or []:
            if not g.get("allday"):
                events.append({"title": str(g.get("title") or ""), "start": g.get("start"), "end": g.get("end")})
    except Exception:
        pass
    for ev in events:
        if not ev["start"] or not ev["end"]:
            continue
        if any(k.lower() in ev["title"].lower() for k in policy.EXEMPT_KINDS):
            out.append({"start": _shift_hm(ev["start"], -CAMERA_OFF_MARGIN_MIN),
                        "end": _shift_hm(ev["end"], CAMERA_OFF_MARGIN_MIN),
                        "title": ev["title"], "source": "event"})
    return sorted(out, key=lambda x: x["start"])


def monitor_state(db: Session, now: datetime | None = None) -> dict:
    """いま監視すべきか（ワーカーが約20秒ごとに聞く）。理由も返す（画面の表示用）"""
    now = now or datetime.now()
    hm = now.strftime("%H:%M")
    cfg = presence_config(db)
    # camera_ok：カメラを使ってよい時間か（在席判定・静止画の両方に共通。授業・特例・時間外は使わない）
    base = {"in_hours": _hm_in(hm, MONITOR_START, MONITOR_END), "camera_ok": False}
    # 💼 面接の前後・AI面接の練習中はカメラを絶対に開かない（監視時間外でも同じ結果だが、理由を先に返す）
    for w in camera_off_windows(db, now.date().isoformat()):
        if _hm_in(hm, w["start"], w["end"]):
            lab = "AI面接の練習中" if w["source"] == "habit" else f"面接の前後{CAMERA_OFF_MARGIN_MIN}分"
            return {**base, "monitor": False, "reason": "camera_off",
                    "label": f"カメラ停止（{lab}：{w['title']}）"}
    if not base["in_hours"]:
        return {**base, "monitor": False, "reason": "outside",
                "label": f"監視時間外（{MONITOR_START}〜{MONITOR_END}）"}
    from . import gate_api
    ex = gate_api.current_exemption(db, now)
    if ex:
        return {**base, "monitor": False, "reason": "exempt", "label": f"特例中：{ex.get('title', '')}"}
    for c in class_blocks(db, now.date().isoformat()):
        if _hm_in(hm, c["start"], c["end"]):
            return {**base, "monitor": False, "reason": "class", "label": f"授業中：{c['title']}"}
    base["camera_ok"] = True
    if not cfg["enabled"]:
        return {**base, "monitor": False, "reason": "off", "label": "在席判定はオフ"}
    return {**base, "monitor": True, "reason": "work", "label": "監視中"}


# ---------- 日ごとの記録（ファイル） ----------
def _day_path(day: str) -> Path:
    return PRESENCE_DIR / f"{day}.json"


def load_day(day: str) -> dict:
    with _lock:
        if _cache["date"] == day and _cache["data"] is not None:
            return _cache["data"]
    p = _day_path(day)
    data = {"minutes": {}, "completed": {}}
    if p.exists():
        try:
            loaded = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data["minutes"] = dict(loaded.get("minutes") or {})
                data["completed"] = dict(loaded.get("completed") or {})
        except (OSError, ValueError):
            pass
    with _lock:
        if day == date_cls.today().isoformat():
            _cache.update({"date": day, "data": data})
    return data


def save_day(day: str, data: dict) -> None:
    try:
        PRESENCE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _day_path(day).with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_day_path(day))
    except OSError:
        pass


def record_sample(present: bool, now: datetime | None = None) -> str:
    """1サンプル（在席/不在）を今の分に反映。その分に1回でも在席があれば P。返り値は "HH:MM" """
    now = now or datetime.now()
    day = now.date().isoformat()
    hm = now.strftime("%H:%M")
    data = load_day(day)
    with _lock:
        prev = data["minutes"].get(hm)
        data["minutes"][hm] = "P" if (present or prev == "P") else "A"
    save_day(day, data)
    return hm


def _minutes_between(start: str, end: str) -> list[str]:
    """start〜end（end は含まない）の "HH:MM" 一覧。日またぎ対応"""
    sh, sm = [int(x) for x in start.split(":")]
    eh, em = [int(x) for x in end.split(":")]
    s = sh * 60 + sm
    e = eh * 60 + em
    if e <= s:
        e += 24 * 60
    return [f"{(m // 60) % 24:02d}:{m % 60:02d}" for m in range(s, e)]


def window_stats(data: dict, start: str, end: str) -> dict:
    """時間帯の在席統計。監視対象外の分（記録なし）は分母に入れない"""
    mins = _minutes_between(start, end)
    present = sum(1 for m in mins if data["minutes"].get(m) == "P")
    absent = sum(1 for m in mins if data["minutes"].get(m) == "A")
    total = len(mins)
    monitored = present + absent
    rate = round(present / monitored * 100) if monitored else None
    return {"total_min": total, "monitored_min": monitored, "present_min": present,
            "absent_min": absent, "rate": rate}


# ---------- 習慣の完了（在席率） ----------
def complete_habits_by_presence(db: Session, now: datetime | None = None) -> list[str]:
    """今日の未完了の習慣（画角外でないもの）について、時間帯の在席分が
    「時間帯の長さ × 基準％」以上になった時点で完了にする。commit は呼び出し側。返り値＝完了にした習慣名"""
    from . import todo_api
    now = now or datetime.now()
    day = now.date().isoformat()
    cfg = presence_config(db)
    if not cfg["enabled"]:
        return []
    s = _settings(db)
    data = load_day(day)
    done = []
    for it in todo_api.habits_for_date(db, day):
        if not it.start or not it.end:
            continue
        opt = habit_option(s, it, day)
        if opt["off_camera"]:
            continue
        row = db.execute(
            select(models.TodoCompletion).where(models.TodoCompletion.item_id == it.id,
                                                models.TodoCompletion.date == day)
        ).scalars().first()
        if row is not None and row.level == "full":
            continue
        st = window_stats(data, it.start, it.end)
        need = -(-st["total_min"] * cfg["rate_min"] // 100)   # 切り上げ
        if need <= 0 or st["present_min"] < need:
            continue
        at = now.strftime("%H:%M")
        if row is None:
            db.add(models.TodoCompletion(item_id=it.id, date=day, at=at, level="full"))
            db.flush()
        else:
            row.level = "full"
        with _lock:
            data["completed"][it.title] = at
        done.append(it.title)
    if done:
        save_day(day, data)
    return done


# ---------- 画面用のまとめ ----------
def _fmt(idx: int) -> str:
    return f"{(idx // 60) % 24:02d}:{idx % 60:02d}"


def blocks_from_minutes(data: dict) -> list[dict]:
    """分の並びを「同じ状態が続く区間」にまとめる（タイムライン表示用）"""
    out = []
    cur = None
    for hm in sorted(data["minutes"]):
        st = data["minutes"][hm]
        h, m = [int(x) for x in hm.split(":")]
        idx = h * 60 + m
        if cur and cur["status"] == st and cur["end_idx"] == idx:
            cur["end_idx"] = idx + 1
        else:
            if cur:
                out.append(cur)
            cur = {"status": st, "start_idx": idx, "end_idx": idx + 1}
    if cur:
        out.append(cur)
    return [{"status": b["status"], "start": _fmt(b["start_idx"]), "end": _fmt(b["end_idx"]),
             "minutes": b["end_idx"] - b["start_idx"]} for b in out]


def day_summary(db: Session, day: str) -> dict:
    from . import todo_api
    data = load_day(day)
    cfg = presence_config(db)
    s = _settings(db)
    present = sum(1 for v in data["minutes"].values() if v == "P")
    absent = sum(1 for v in data["minutes"].values() if v == "A")
    monitored = present + absent
    habits = []
    comp = {c.item_id: c for c in db.execute(
        select(models.TodoCompletion).where(models.TodoCompletion.date == day)).scalars().all()}
    for it in todo_api.habits_for_date(db, day):
        if not it.start or not it.end:
            continue
        opt = habit_option(s, it, day)
        st = window_stats(data, it.start, it.end)
        c = comp.get(it.id)
        habits.append({
            "title": it.title, "start": it.start, "end": it.end,
            "off_camera": opt["off_camera"], "min_minutes": opt["min_minutes"],
            "record_only": bool(opt.get("record_only")),
            "done": bool(c and c.level == "full"), "done_at": c.at if c else "",
            "by_presence": it.title in data["completed"],
            "need_min": -(-st["total_min"] * cfg["rate_min"] // 100) if not opt["off_camera"] else None,
            **st,
        })
    return {
        "date": day, "enabled": cfg["enabled"], "rate_min": cfg["rate_min"],
        "monitored_min": monitored, "present_min": present, "absent_min": absent,
        "rate": (round(present / monitored * 100) if monitored else None),
        "blocks": blocks_from_minutes(data),
        "classes": class_blocks(db, day),
        "habits": habits,
        "completed": data["completed"],
    }


def week_summary(db: Session, end_day: str) -> list[dict]:
    end = datetime.strptime(end_day, "%Y-%m-%d").date()
    out = []
    for i in range(6, -1, -1):
        d = (end - timedelta(days=i)).isoformat()
        data = load_day(d)
        present = sum(1 for v in data["minutes"].values() if v == "P")
        absent = sum(1 for v in data["minutes"].values() if v == "A")
        mon = present + absent
        out.append({"date": d, "label": "月火水木金土日"[(end - timedelta(days=i)).weekday()],
                    "monitored_min": mon, "present_min": present,
                    "rate": (round(present / mon * 100) if mon else None),
                    "completed": len(data["completed"])})
    return out


# ---------- API ----------
class PingBody(BaseModel):
    present: bool
    faces: int = 0
    brightness: float | None = None   # フレームの平均輝度（0〜255）。真っ暗の検知用


class CameraResultBody(BaseModel):
    ok: bool
    brightness: float | None = None
    faces: int = 0
    width: int = 0
    height: int = 0
    backend: str = ""
    error: str = ""
    index: int = 0              # 確認に使ったカメラ番号
    found: list[dict] = []      # 見つかったカメラ（index 0〜4 のうち開けたもの：{index, width, height, backend}）


def _camera_note(r: dict | None) -> str:
    if not r:
        return ""
    found = r.get("found") or []
    if not r.get("ok"):
        if found:
            nums = "・".join(str(f.get("index")) for f in found)
            return (f"カメラ番号 {r.get('index', 0)} を開けません。見つかったカメラは番号 {nums} です。"
                    "下の「使うカメラ」で選び直してください")
        return "カメラを開けません。他のアプリが使用中か、Windows の設定 › プライバシー › カメラ で「デスクトップ アプリにカメラへのアクセスを許可」がオフになっていないか確認してください"
    b = r.get("brightness")
    if b is not None and b < DARK_BRIGHTNESS:
        return ("映像が真っ暗です。カメラにカバー（プライバシーシャッター）が掛かっている可能性があります。"
                "カバーを外しても暗いときは、別のカメラ番号（下の「使うカメラ」）か、仮想カメラ（NVIDIA Broadcast 等）が選ばれていないかを確認してください")
    if r.get("faces", 0) == 0:
        return "カメラは映っていますが顔が検出されていません。正面を向いて明るい場所で試してください"
    return "カメラ・顔検出とも正常です"


def _camera_state() -> dict:
    last = _cam.get("last")
    pending = (time.time() - _cam["test_requested"]) < 90 if _cam["test_requested"] else False
    return {"test_pending": pending, "last": last, "note": _camera_note(last)}


class ConfigBody(BaseModel):
    presence_enabled: bool | None = None
    presence_rate_min: int | None = None
    camera_index: int | None = None
    webcam_log_enabled: bool | None = None
    webcam_log_interval_sec: int | None = None
    webcam_log_keep_days: int | None = None


class HabitOptionBody(BaseModel):
    title: str
    off_camera: bool = False
    min_minutes: int = 0
    record_only: bool = False   # 記録だけ（解放条件に入れない。F23）
    camera_off: bool = False    # この習慣の時間帯はカメラを開かない（AI面接の練習など）


@router.get("/api/presence/config")
def get_config(db: Session = Depends(get_db)):
    """ワーカー（約20秒ごと）と画面が読む。monitor が False のときワーカーはカメラを開かない"""
    cfg = presence_config(db)
    st = monitor_state(db)
    return {**cfg, "monitor": st["monitor"], "reason": st["reason"], "label": st["label"],
            "camera_ok": st["camera_ok"], "in_hours": st["in_hours"],
            "camera": _camera_state(),
            "camera_off_windows": camera_off_windows(db, date_cls.today().isoformat()),
            "now": datetime.now().strftime("%H:%M"),
            "window": {"start": MONITOR_START, "end": MONITOR_END}}


@router.post("/api/presence/config")
def set_config(body: ConfigBody, db: Session = Depends(get_db)):
    """在席判定・静止画記録の設定。在席率の基準を下げる変更だけは翌日から有効（当日の抜け道にしない）"""
    if body.presence_enabled is not None:
        crud.set_setting(db, "presence_enabled", bool(body.presence_enabled))
    if body.presence_rate_min is not None:
        v = int(body.presence_rate_min)
        if not (RATE_MIN_FLOOR <= v <= 100):
            raise HTTPException(status_code=400, detail=f"在席率の基準は {RATE_MIN_FLOOR}〜100% にしてください")
        cur = presence_config(db)
        if v < cur["rate_min"]:
            crud.set_setting(db, "presence_rate_min",
                             {"value": v, "since": (date_cls.today() + timedelta(days=1)).isoformat(),
                              "prev": cur["rate_min"]})
        else:
            crud.set_setting(db, "presence_rate_min", {"value": v, "since": "", "prev": v})
    if body.camera_index is not None:
        v = int(body.camera_index)
        if not (0 <= v <= CAMERA_INDEX_MAX):
            raise HTTPException(status_code=400, detail=f"カメラ番号は 0〜{CAMERA_INDEX_MAX} にしてください")
        crud.set_setting(db, "camera_index", v)
    if body.webcam_log_enabled is not None:
        crud.set_setting(db, "webcam_log_enabled", bool(body.webcam_log_enabled))
    if body.webcam_log_interval_sec is not None:
        crud.set_setting(db, "webcam_log_interval_sec", max(10, int(body.webcam_log_interval_sec)))
    if body.webcam_log_keep_days is not None:
        crud.set_setting(db, "webcam_log_keep_days", max(1, int(body.webcam_log_keep_days)))
    db.commit()
    return get_config(db)


@router.post("/api/presence/camera_test")
def camera_test():
    """画面の「カメラを確認」：ワーカーに1回だけ撮って報告させる（結果は /api/presence/config の camera.last）"""
    _cam["test_requested"] = time.time()
    _cam["last"] = None
    return {"ok": True, "note": "ワーカーが次の確認（最長20秒）でカメラを開き、結果を報告します"}


@router.post("/api/presence/camera_result")
def camera_result(body: CameraResultBody):
    """ワーカーからのカメラ確認の結果"""
    _cam["last"] = {**body.model_dump(), "at": datetime.now().strftime("%H:%M:%S")}
    _cam["test_requested"] = 0.0
    return {"ok": True, "note": _camera_note(_cam["last"])}


@router.post("/api/presence/ping")
def ping(body: PingBody, db: Session = Depends(get_db)):
    """ワーカーからの在席サンプル（約10秒ごと）。監視対象の時間だけ記録する"""
    global _last_check_minute
    _cam["last"] = {"ok": True, "brightness": body.brightness, "faces": int(body.faces),
                    "width": 0, "height": 0, "backend": "", "error": "",
                    "at": datetime.now().strftime("%H:%M:%S")}
    st = monitor_state(db)
    if not st["monitor"]:
        return {"ok": True, "recorded": False, "reason": st["reason"]}
    hm = record_sample(bool(body.present))
    done = []
    if hm != _last_check_minute:
        _last_check_minute = hm
        done = complete_habits_by_presence(db)
        if done:
            db.commit()
            from . import gate_api
            gate_api.gate_state(db)
    return {"ok": True, "recorded": True, "minute": hm, "completed": done}


@router.get("/api/presence/day")
def get_day(date: str = "", db: Session = Depends(get_db)):
    day = date or date_cls.today().isoformat()
    try:
        datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="date は YYYY-MM-DD")
    return day_summary(db, day)


@router.get("/api/presence/week")
def get_week(date: str = "", db: Session = Depends(get_db)):
    day = date or date_cls.today().isoformat()
    try:
        datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="date は YYYY-MM-DD")
    return {"end": day, "rate_min": presence_config(db)["rate_min"], "days": week_summary(db, day)}


@router.get("/api/presence/habit_options")
def list_habit_options(db: Session = Depends(get_db)):
    """習慣ごとの画角外・最低時間の設定（有効値と、翌日から有効になる予定の値）"""
    from . import todo_api
    s = _settings(db)
    today = date_cls.today().isoformat()
    out = []
    for it in todo_api.habit_items(db):
        opt = habit_option(s, it, today)
        out.append({"title": it.title, "start": it.start, "end": it.end,
                    "window_minutes": todo_api.habit_duration_minutes(it), **opt})
    return out


@router.put("/api/presence/habit_options")
def put_habit_option(body: HabitOptionBody, db: Session = Depends(get_db)):
    from . import todo_api
    item = next((it for it in todo_api.habit_items(db) if it.title == body.title.strip()), None)
    if item is None:
        raise HTTPException(status_code=404, detail="その習慣が見つかりません")
    res = set_habit_option(db, item, body.off_camera, body.min_minutes,
                           todo_api.habit_duration_minutes(item), record_only=body.record_only,
                           camera_off=body.camera_off)
    db.commit()
    return {"title": item.title, **res}


# ---------- 📷 静止画の記録（webcam_log 相当）と1日分のまとめ画像 ----------
@router.get("/api/webcam/days")
def webcam_days():
    """静止画がある日の一覧（枚数・まとめ画像の有無）"""
    out = []
    if WEBCAM_DIR.exists():
        for d in sorted(WEBCAM_DIR.iterdir(), reverse=True):
            if d.is_dir() and len(d.name) == 10:
                n = sum(1 for _ in d.glob("*.jpg"))
                summary = WEBCAM_DIR / f"summary_{d.name}.jpg"
                out.append({"date": d.name, "count": n,
                            "summary": f"/webcam/summary_{d.name}.jpg" if summary.exists() else ""})
    return out


class SummaryBody(BaseModel):
    date: str = ""


@router.post("/api/webcam/summary")
def make_summary(body: SummaryBody, db: Session = Depends(get_db)):
    """その日の静止画から一覧画像を作る（webcam_summary.py を venv の python で実行。OpenCV 必須）"""
    import subprocess
    import sys
    day = body.date or date_cls.today().isoformat()
    try:
        datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="date は YYYY-MM-DD")
    script = ROOT / "webcam_summary.py"
    if not script.exists():
        raise HTTPException(status_code=404, detail="webcam_summary.py が見つかりません")
    if not (WEBCAM_DIR / day).exists():
        raise HTTPException(status_code=404, detail=f"{day} の静止画がありません")
    try:
        r = subprocess.run([sys.executable, str(script), "--date", day], capture_output=True, text=True,
                           timeout=120, cwd=str(ROOT),
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="まとめ画像の作成がタイムアウトしました")
    if r.returncode != 0:
        raise HTTPException(status_code=500, detail=(r.stderr or r.stdout or "作成に失敗しました")[-400:])
    out = WEBCAM_DIR / f"summary_{day}.jpg"
    return {"ok": out.exists(), "date": day, "url": f"/webcam/summary_{day}.jpg" if out.exists() else ""}
