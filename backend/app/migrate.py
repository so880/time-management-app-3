"""既存データ（JSON / CSV）→ SQLite への初回移行処理。

起動時（lifespan）に呼ばれる。各テーブルが「空のときだけ」取り込むので、
2回目以降の起動では何もしない（安全に何度でも呼べる）。

- settings.json      → settings テーブル（既存 state.py load_settings と同じ正規化）
- activity_log.csv   → activity_log テーブル
- session_state.json → daily_state テーブル（日付またぎリセットは読み出し時に適用）
"""
import csv
import json

from sqlalchemy.orm import Session

from . import crud, models
from .config import (
    DEFAULT_SETTINGS,
    LEGACY_LOG_FILE,
    LEGACY_SESSION_FILE,
    LEGACY_SETTINGS_FILE,
)


def _load_json_file(path) -> dict:
    """JSONを安全に読む。無い・壊れている場合は空dict（既存 blocker.py と同じ方針）"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def normalize_settings(saved: dict) -> dict:
    """既存 state.py の load_settings() の正規化処理を移植。

    保存済み設定を DEFAULT_SETTINGS に重ねた上で、
    欠損キーの補完・旧形式からの移行を行う。
    """
    s = DEFAULT_SETTINGS.copy()
    s.update(saved)
    # 旧形式(toeic/intern固定)から可変goalsへ移行
    if not s.get("goals"):
        s["goals"] = [
            {"name": s.get("toeic_name", "TOEIC"),
             "date": s.get("toeic_date", "2026-05-24"),
             "hours": int(s.get("daily_hours_toeic", 3))},
            {"name": s.get("intern_name", "インターン"),
             "date": s.get("intern_date", "2026-06-01"),
             "hours": int(s.get("daily_hours_intern", 2))},
        ]
    # 下限は常に30分で固定
    s["study_dur_min"] = 30
    for k in ("study_list_disabled", "focus_study_list_disabled",
              "refresh_list_disabled", "mustdo_list_disabled"):
        s.setdefault(k, [])
    s.setdefault("mustdo_list", [])
    # ゲームブロック機能のキー（欠損時も確実に埋める）
    s.setdefault("block_process_list", [])
    s.setdefault("block_enabled", True)
    # リキッドグラス風UI（欠損補完）
    s.setdefault("liquid_glass_enabled", False)
    # 旧 daily_window(単一) -> daily_routine(複数) へ移行
    if not saved.get("daily_routine") and saved.get("daily_window"):
        dw = saved["daily_window"]
        s["daily_routine"] = [
            [{"start": d.get("start", "09:00"), "end": d.get("end", "22:00")}]
            for d in dw
        ]
    return s


def migrate_settings(db: Session) -> None:
    """settings テーブルが空なら、settings.json（無ければ初期値）を取り込む"""
    if not crud.settings_is_empty(db):
        return
    saved = _load_json_file(LEGACY_SETTINGS_FILE)
    s = normalize_settings(saved)
    for key, value in s.items():
        crud.set_setting(db, key, value)
    db.commit()


def migrate_logs(db: Session) -> None:
    """activity_log テーブルが空なら、activity_log.csv を取り込む"""
    if not crud.logs_is_empty(db):
        return
    if not LEGACY_LOG_FILE.exists():
        return
    # utf-8-sig：既存CSVはBOM付きで保存されているため（BOM無しでも読める）
    with open(LEGACY_LOG_FILE, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                minutes = int(float(row.get("経過時間(分)") or 0))
            except (TypeError, ValueError):
                minutes = 0
            crud.add_log(
                db,
                date_str=(row.get("日付") or "").strip(),
                category=(row.get("カテゴリ") or "").strip(),
                content=row.get("内容") or "",
                bgm=row.get("BGM") or "",
                minutes=minutes,
                done_text=row.get("やったこと") or "",
                progress=row.get("進捗度合い") or "",
                focus=row.get("集中度") or "",
                satisfaction=row.get("満足度") or "",
                note=row.get("メモ") or "",
            )
    db.commit()


def migrate_state(db: Session) -> None:
    """daily_state が無ければ、session_state.json を取り込む。

    日付が古い場合のリセットは crud.get_or_create_state() が
    読み出しのたびに行うので、ここでは値をそのまま保存してよい。
    """
    if db.get(models.DailyState, 1) is not None:
        return
    saved = _load_json_file(LEGACY_SESSION_FILE)
    if not saved:
        return  # ファイルが無ければ何もしない（初回アクセス時に初期値で作られる）

    def _j(key):
        v = saved.get(key)
        return None if v is None else json.dumps(v, ensure_ascii=False)

    db.add(models.DailyState(
        id=1,
        target_date=str(saved.get("target_date") or ""),
        page=str(saved.get("page") or "dashboard"),
        current_task=_j("current_task"),
        start_time=saved.get("start_time"),
        study_time_total=int(saved.get("study_time_total") or 0),
        refresh_time_total=int(saved.get("refresh_time_total") or 0),
        target_value=int(saved.get("target_value") or 180),
        target_locked=bool(saved.get("target_locked", False)),
        last_was_refresh=bool(saved.get("last_was_refresh", False)),
        force_study_only=bool(saved.get("force_study_only", False)),
        mock_exam_done=bool(saved.get("mock_exam_done", False)),
        pending_review=_j("pending_review"),
        sos_task=_j("sos_task"),
        rolled_options=_j("rolled_options"),
    ))
    db.commit()


def ensure_new_columns(engine) -> None:
    """後から追加した列を既存テーブルに足す（簡易マイグレーション）。

    SQLAlchemy の create_all は「既存テーブルへの列追加」をしないため、
    ここで不足列を ALTER TABLE で補う。
    """
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    tables = insp.get_table_names()

    def add_if_missing(table, column, ddl):
        if table not in tables:
            return
        cols = [c["name"] for c in insp.get_columns(table)]
        if column not in cols:
            with engine.begin() as con:
                con.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))

    add_if_missing("assignments", "recurring_id", "recurring_id INTEGER")
    add_if_missing("assignments", "category", "category VARCHAR(20) DEFAULT '大学' NOT NULL")
    add_if_missing("schedule_blocks", "room", "room VARCHAR(100) DEFAULT '' NOT NULL")
    add_if_missing("life_events", "note", "note TEXT DEFAULT '' NOT NULL")
    add_if_missing("job_events", "choice", "choice INTEGER DEFAULT 0 NOT NULL")


def run_all(db: Session) -> None:
    """全移行処理を実行（各処理は空テーブルのときだけ動く）"""
    migrate_settings(db)
    migrate_logs(db)
    migrate_state(db)
