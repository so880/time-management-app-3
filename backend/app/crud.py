"""DB読み書き関数（CRUD層）。

settings（key/JSON）・daily_state・activity_log など、複数のモジュールが共通で使う
読み書きをここにまとめている。各機能のモジュール（todo_api・life_api など）は、
自分のテーブルについては db.execute / db.get で直接読み書きする（SQLAlchemy の標準の書き方）。
"""
import json
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models
from .config import DEFAULT_SETTINGS, DEFAULT_STUDY_TARGET_MIN


# ---------- settings ----------
def get_all_settings(db: Session) -> dict:
    """settings テーブル全行を dict にして返す（値はJSON文字列→Pythonの値に戻す）"""
    rows = db.execute(select(models.Setting)).scalars().all()
    return {row.key: json.loads(row.value) for row in rows}


def set_setting(db: Session, key: str, value) -> None:
    """1キーぶんの設定を保存（あれば更新、なければ追加）"""
    text = json.dumps(value, ensure_ascii=False)
    row = db.get(models.Setting, key)
    if row is None:
        db.add(models.Setting(key=key, value=text))
    else:
        row.value = text


def settings_is_empty(db: Session) -> bool:
    """settings テーブルが空かどうか（初回起動判定）"""
    first = db.execute(select(models.Setting).limit(1)).scalars().first()
    return first is None


def init_settings_with_defaults(db: Session) -> None:
    """DEFAULT_SETTINGS を投入する（テーブルが空のときだけ呼ぶこと）"""
    for key, value in DEFAULT_SETTINGS.items():
        set_setting(db, key, value)


# ---------- activity_log ----------
def logs_is_empty(db: Session) -> bool:
    first = db.execute(select(models.ActivityLog).limit(1)).scalars().first()
    return first is None


def add_log(db: Session, date_str: str, category: str, content: str,
            bgm: str = "", minutes: int = 0, done_text: str = "",
            progress: str = "", focus: str = "", satisfaction: str = "",
            note: str = "") -> models.ActivityLog:
    """履歴を1行追加して、その行を返す（commit は呼び出し側）"""
    row = models.ActivityLog(
        date=date_str, category=category, content=content, bgm=bgm,
        minutes=minutes, done_text=done_text, progress=progress,
        focus=focus, satisfaction=satisfaction, note=note,
    )
    db.add(row)
    return row


def split_minutes_by_day(end_ts: float, minutes: int) -> list[tuple[str, int, str]]:
    """計測が日付をまたいだとき、日ごとに分ける。

    end_ts（終了時刻の epoch 秒）から minutes 分さかのぼった区間を、0時で区切って
    [(履歴の日時 "YYYY-MM-DD HH:MM:SS", その日の分数, その日 "YYYY-MM-DD"), ...] で返す（古い日が先）。
    履歴の日時は「その区間の終わり」（前日分は 23:59:59）。日付をまたがなければ1件だけ。
    """
    from datetime import datetime, timedelta
    minutes = max(0, int(minutes))
    end = datetime.fromtimestamp(end_ts)
    if minutes == 0:
        return [(end.strftime("%Y-%m-%d %H:%M:%S"), 0, end.date().isoformat())]
    start = end - timedelta(minutes=minutes)
    parts: list[tuple[str, int, str]] = []
    cur = start
    left = minutes
    while cur.date() < end.date():
        midnight = datetime.combine(cur.date() + timedelta(days=1), datetime.min.time())
        m = min(left, int((midnight - cur).total_seconds() // 60))
        if m > 0:
            last_sec = midnight - timedelta(seconds=1)
            parts.append((last_sec.strftime("%Y-%m-%d %H:%M:%S"), m, cur.date().isoformat()))
            left -= m
        cur = midnight
    parts.append((end.strftime("%Y-%m-%d %H:%M:%S"), left, end.date().isoformat()))
    return [p for p in parts if p[1] > 0] or [parts[-1]]


def delete_all_logs(db: Session) -> None:
    """履歴を全削除（全データリセット用）"""
    for row in db.execute(select(models.ActivityLog)).scalars().all():
        db.delete(row)
    db.commit()


def get_logs(db: Session) -> list[dict]:
    """履歴全件を、既存CSVと同じ日本語キーの dict のリストで返す"""
    rows = db.execute(
        select(models.ActivityLog).order_by(models.ActivityLog.id)
    ).scalars().all()
    return [
        {
            "日付": r.date, "カテゴリ": r.category, "内容": r.content,
            "BGM": r.bgm, "経過時間(分)": r.minutes,
            "やったこと": r.done_text, "進捗度合い": r.progress,
            "集中度": r.focus, "満足度": r.satisfaction, "メモ": r.note,
        }
        for r in rows
    ]


# ---------- daily_state ----------
# JSONとして保存している列（読むときに Python の値へ戻す）
_STATE_JSON_FIELDS = ("current_task", "pending_review", "sos_task", "rolled_options")

# 日付が変わったときにリセットするキーと初期値（既存 state.py init_session と同じ）
_DATE_RESET_VALUES = {
    "target_locked": False,
    "target_value": DEFAULT_STUDY_TARGET_MIN,
    "last_was_refresh": False,
    "force_study_only": False,
}


def _dump_json(value) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False)


def _load_json(text: str | None):
    return None if text is None else json.loads(text)


def get_or_create_state(db: Session) -> models.DailyState:
    """id=1 の状態行を取得（無ければ今日の初期値で作成）し、
    日付またぎリセット（既存 init_session と同じ挙動）を適用して返す。"""
    today = date.today().isoformat()
    row = db.get(models.DailyState, 1)
    if row is None:
        row = models.DailyState(id=1, target_date=today)
        db.add(row)
        db.commit()
        return row
    # 日付またぎ：一部だけリセットし他（page・current_task等）は保持
    if row.target_date != today:
        for key, value in _DATE_RESET_VALUES.items():
            setattr(row, key, value)
        row.rolled_options = None  # 前日の抽選結果は持ち越さない
        row.target_date = today
        db.commit()
    return row


# ---------- 今日の勉強時間・気分転換時間（activity_log の合計が唯一の元データ。2026-11-06） ----------
# 以前は daily_state に足し込んでいたが、加算する場所が5か所あり扱いがずれていたため、記録から毎回数える。
# 勉強に数えるカテゴリ：「勉強」を含むもの（勉強・勉強(短縮修了)）と「中断」（集中切れまでの時間。従来どおり）
STUDY_CATEGORIES_LIKE = ("%勉強%",)
STUDY_CATEGORIES_EXACT = ("中断",)
REFRESH_CATEGORIES_LIKE = ("%気分転換%",)


def is_study_category(category: str) -> bool:
    """そのカテゴリを勉強時間に数えるか（Python 側で1件ずつ判定するとき用。SQL の条件と同じ）"""
    c = category or ""
    return any(x.strip("%") in c for x in STUDY_CATEGORIES_LIKE) or c in STUDY_CATEGORIES_EXACT


def _minutes_by_day(db: Session, start: str, end: str, like: tuple, exact: tuple = ()) -> dict[str, int]:
    """start〜end（両端を含む "YYYY-MM-DD"）の日ごとの合計分数 {日付: 分}"""
    from datetime import date as _date, timedelta as _td
    from sqlalchemy import func, or_
    nxt = (_date.fromisoformat(end) + _td(days=1)).isoformat()
    day = func.substr(models.ActivityLog.date, 1, 10)
    cond = [models.ActivityLog.category.like(x) for x in like] + \
           [models.ActivityLog.category == x for x in exact]
    rows = db.execute(
        select(day, func.sum(models.ActivityLog.minutes))
        .where(models.ActivityLog.date >= start, models.ActivityLog.date < nxt, or_(*cond))
        .group_by(day)
    ).all()
    return {d: int(m or 0) for d, m in rows}


def study_minutes_by_day(db: Session, start: str, end: str) -> dict[str, int]:
    """start〜end の日ごとの勉強時間（分）。記録の無い日はキーが無い"""
    return _minutes_by_day(db, start, end, STUDY_CATEGORIES_LIKE, STUDY_CATEGORIES_EXACT)


def study_minutes(db: Session, day: str | None = None) -> int:
    """その日（既定は今日）の勉強時間（分）"""
    day = day or date.today().isoformat()
    return study_minutes_by_day(db, day, day).get(day, 0)


def refresh_minutes(db: Session, day: str | None = None) -> int:
    """その日（既定は今日）の気分転換の時間（分）"""
    day = day or date.today().isoformat()
    return _minutes_by_day(db, day, day, REFRESH_CATEGORIES_LIKE).get(day, 0)


def state_to_dict(row: models.DailyState) -> dict:
    """状態行を画面に返す形の dict にする（勉強・気分転換の合計は記録から数える）"""
    from sqlalchemy.orm import object_session
    db = object_session(row)
    return {
        "page": row.page,
        "current_task": _load_json(row.current_task),
        "start_time": row.start_time,
        "study_time_total": study_minutes(db) if db is not None else 0,
        "refresh_time_total": refresh_minutes(db) if db is not None else 0,
        "target_value": row.target_value,
        "target_locked": row.target_locked,
        "target_date": row.target_date,
        "last_was_refresh": row.last_was_refresh,
        "force_study_only": row.force_study_only,
        "mock_exam_done": row.mock_exam_done,
        "pending_review": _load_json(row.pending_review),
        "sos_task": _load_json(row.sos_task),
        "rolled_options": _load_json(row.rolled_options),
    }


def update_state(db: Session, changes: dict) -> models.DailyState:
    """状態の部分更新（渡されたキーだけ書き換える）。
    target_date はサーバー側で管理するため外から変更させない。"""
    row = get_or_create_state(db)
    for key, value in changes.items():
        if key == "target_date":
            continue
        if key in _STATE_JSON_FIELDS:
            setattr(row, key, _dump_json(value))
        elif hasattr(row, key) and key != "id":
            setattr(row, key, value)
    db.commit()
    return row
