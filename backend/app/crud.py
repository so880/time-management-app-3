"""DB読み書き関数（CRUD層）。

main.py（API窓口）からはこの関数群だけを呼ぶ。
SQL の書き方がここに隔離されるので、将来のDB差し替えが容易。
"""
import json
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models
from .config import DEFAULT_SETTINGS


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
            note: str = "") -> None:
    """履歴を1行追加（既存 utils/logger.py の log_activity と同じ項目）"""
    db.add(models.ActivityLog(
        date=date_str, category=category, content=content, bgm=bgm,
        minutes=minutes, done_text=done_text, progress=progress,
        focus=focus, satisfaction=satisfaction, note=note,
    ))


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
    "target_value": 180,
    "study_time_total": 0,
    "refresh_time_total": 0,
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


def state_to_dict(row: models.DailyState) -> dict:
    """状態行を、既存 session_state.json と同じキー構成の dict にする"""
    return {
        "page": row.page,
        "current_task": _load_json(row.current_task),
        "start_time": row.start_time,
        "study_time_total": row.study_time_total,
        "refresh_time_total": row.refresh_time_total,
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
