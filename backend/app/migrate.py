"""DB の初期化と構造の更新。

- seed_settings      … 新しい DB（settings が空）に初期設定を入れる
- ensure_new_columns … 後から追加した列を既存の表に足す（create_all は既存の表を変えないため）
- upgrade            … 表の作り直し・データの移し替えなど、構造の変更（PRAGMA user_version で1回だけ。
                       実行前に backend/data/backups/ に DB を複製する）
- cleanup_legacy_todo / migrate_roulette_items … 2026-09 の統合の後始末（古い DB のときだけ動く）

旧版（Streamlit 版の settings.json / activity_log.csv / session_state.json）からの取り込みは
2026-11-06 に削除した（取り込みは済んでおり、元のファイルは C:\\Life_app_archive に移した）。
"""
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import crud, models
from .config import DEFAULT_SETTINGS


def normalize_settings(saved: dict) -> dict:
    """保存済み設定を初期設定に重ね、欠けているキーを補う"""
    s = DEFAULT_SETTINGS.copy()
    s.update(saved)
    s["study_dur_min"] = 30   # 下限は常に30分で固定
    s.setdefault("refresh_list_disabled", [])
    s.setdefault("block_process_list", [])
    s.setdefault("block_enabled", True)
    return s


def seed_settings(db: Session) -> None:
    """settings が空（新しい DB）なら初期設定を入れる"""
    if not crud.settings_is_empty(db):
        return
    for key, value in normalize_settings({}).items():
        crud.set_setting(db, key, value)
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
    add_if_missing("assignments", "focus", "focus BOOLEAN DEFAULT 0 NOT NULL")
    add_if_missing("assignments", "enabled", "enabled BOOLEAN DEFAULT 1 NOT NULL")
    # 2026-09-22：起動時の「今日の必須」画面（タグ・締切・ルーレット項目との紐づけ）
    add_if_missing("todo_items", "tag", "tag VARCHAR(30) DEFAULT '' NOT NULL")
    add_if_missing("todo_items", "due_date", "due_date VARCHAR(10) DEFAULT '' NOT NULL")
    add_if_missing("todo_items", "asg_id", "asg_id INTEGER")
    add_if_missing("schedule_blocks", "room", "room VARCHAR(100) DEFAULT '' NOT NULL")
    add_if_missing("life_events", "note", "note TEXT DEFAULT '' NOT NULL")
    add_if_missing("job_events", "choice", "choice INTEGER DEFAULT 0 NOT NULL")
    add_if_missing("life_events", "done", "done BOOLEAN DEFAULT 0 NOT NULL")
    # 2026-11-07：面接などの特例から「繰り返しの予定」「他人からの招待」を除くため（空＝不明＝特例にしない）
    add_if_missing("google_events", "recurring", "recurring BOOLEAN")
    add_if_missing("google_events", "owned_by_me", "owned_by_me BOOLEAN")


def cleanup_legacy_todo(db: Session, engine) -> None:
    """やること統合（2026-09）の後始末。1回だけ実行（settings todo_v1_cleanup_done）。

    - 旧テーブル habit_checks を削除（記録は todo_completions に移行済み）
    - 時間割の category="習慣" ブロックを削除（習慣は todo_items に移行済み）
    - 廃止した settings キーを削除
    """
    from sqlalchemy import inspect, text
    settings = crud.get_all_settings(db)
    if not settings.get("todo_v1_migrated"):
        return  # todo_items への移行（todo_v1_migrated）が済んでいないDBでは触らない
    legacy_keys = ("required_tasks", "required_tasks_min", "aux_tasks", "low_gear",
                   "mustdo_list", "mustdo_list_disabled", "periodic_tasks",
                   "habit_min_actions", "habit_started", "gate_v2_migrated")
    # 残骸があるときだけ動く（フラグ方式だと、旧コードが再生成した残骸を取りこぼすため）
    has_table = "habit_checks" in inspect(engine).get_table_names()
    old_blocks = db.execute(
        select(models.ScheduleBlock).where(models.ScheduleBlock.category == "習慣")
    ).scalars().all()
    old_keys = [k for k in legacy_keys if k in settings]
    if not has_table and not old_blocks and not old_keys:
        return
    if has_table:
        with engine.begin() as con:
            con.execute(text("DROP TABLE IF EXISTS habit_checks"))
    for r in old_blocks:
        db.delete(r)
    for key in old_keys:
        row = db.get(models.Setting, key)
        if row is not None:
            db.delete(row)
    crud.set_setting(db, "todo_v1_cleanup_done", True)
    db.commit()


def migrate_roulette_items(db: Session) -> None:
    """通常勉強／重点（settings のリスト）を assignments（ルーレット項目）へ移す。1回だけ。

    - study_list → 期限なし・タグ「その他」、focus_study_list → 重点
    - 各 _disabled に入っていたものは enabled=False
    - 旧タグ「私生活」→「私用」に読み替え
    - 移行後、settings の study_list / focus_study_list とその _disabled を削除
    """
    from datetime import datetime
    settings = crud.get_all_settings(db)
    if settings.get("roulette_v1_migrated"):
        return
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    have = {a.title for a in db.execute(select(models.Assignment)).scalars().all()}
    for key, focus in (("study_list", False), ("focus_study_list", True)):
        disabled = set(settings.get(f"{key}_disabled") or [])
        for t in settings.get(key) or []:
            t = str(t).strip()
            if not t or t in have:
                continue
            db.add(models.Assignment(title=t, due_date="", progress=0, note="", created=now,
                                     category="その他", focus=focus, enabled=t not in disabled))
            have.add(t)
    for a in db.execute(select(models.Assignment)
                        .where(models.Assignment.category == "私生活")).scalars().all():
        a.category = "私用"
    for key in ("study_list", "study_list_disabled", "focus_study_list", "focus_study_list_disabled"):
        row = db.get(models.Setting, key)
        if row is not None:
            db.delete(row)
    crud.set_setting(db, "roulette_v1_migrated", True)
    db.commit()


def run_all(db: Session) -> None:
    """起動時の初期データ（新しい DB のときだけ動く）"""
    seed_settings(db)


# =====================================================================
# DB の構造の更新（PRAGMA user_version で何回目まで済んだかを記録し、各段階を1回だけ実行する）
# =====================================================================
SCHEMA_VERSION = 1

# 使われなくなった設定（2026-11-06 依頼者の承認）。読むコードが無いことを確認済み
DEAD_SETTING_KEYS = (
    "game_window", "game_window_date",                       # ゲームの時間帯は policy.GAME_WINDOW に固定
    "toeic_date", "toeic_name", "intern_date", "intern_name",  # 目標は goals に移行済み
    "daily_hours_toeic", "daily_hours_intern",
    "daily_window",                                           # daily_routine に移行済み
    "phone_inbox_path",                                       # Gドライブ経由の取り込みは廃止
    "gate_seed_done",                                         # 初回シードは削除
    "liquid_glass_enabled",                                   # 旧レイアウトは削除
)

# 外部キーを付けるために作り直す表（親 → 子の順。SQLite は既存の表に外部キーを足せないため）
FK_TABLES = ("assignments", "todo_items", "todo_completions", "schedule_cancellations",
             "job_events", "job_docs")


def _backup_db(raw_path: str, label: str) -> str:
    """構造を変える前に DB を丸ごと複製する（SQLite のバックアップ API）。複製先を返す"""
    import sqlite3
    from datetime import datetime
    from .config import DATA_DIR
    dst_dir = DATA_DIR / "backups"
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / f"before_{label}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    src = sqlite3.connect(raw_path)
    try:
        out = sqlite3.connect(str(dst))
        try:
            src.backup(out)
        finally:
            out.close()
    finally:
        src.close()
    return str(dst)


def _upgrade_v1(con, engine) -> None:
    """2026-11-06（依頼者の承認済み）：
    1. 参照先の無い行の片づけ（存在しない「毎週の項目」への紐づけ 等）
    2. 外部キー付きで6つの表を作り直す（SQLite 公式の手順：新しい表を作って写し、古い表を消して名前を戻す）
    3. 索引の追加（PC記録・履歴・やること・完了記録）
    4. settings に入れていた記録を専用の表へ（解除申請・特例の申請・Google の予定）
    5. 習慣ごとの設定（habit_options）を「習慣名」ではなく「習慣の番号」で持つ
    6. 今日の勉強時間・気分転換時間の列を削除（activity_log の合計に一本化）
    7. 使われなくなった設定の削除
    con は sqlite3 の接続（autocommit。呼び出し側が BEGIN/COMMIT する）"""
    from sqlalchemy.schema import CreateIndex, CreateTable

    def setting(key):
        row = con.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        try:
            return json.loads(row[0])
        except ValueError:
            return None

    def drop_setting(key):
        con.execute("DELETE FROM settings WHERE key = ?", (key,))

    # ---- 1. 参照先の無い行 ----
    con.execute("UPDATE assignments SET recurring_id = NULL WHERE recurring_id IS NOT NULL "
                "AND recurring_id NOT IN (SELECT id FROM recurring_assignments)")
    con.execute("UPDATE todo_items SET asg_id = NULL WHERE asg_id IS NOT NULL "
                "AND asg_id NOT IN (SELECT id FROM assignments)")
    con.execute("DELETE FROM todo_completions WHERE item_id NOT IN (SELECT id FROM todo_items)")
    con.execute("DELETE FROM schedule_cancellations WHERE block_id NOT IN (SELECT id FROM schedule_blocks)")
    # 就活：0 は「会社に紐づかない予定」の意味だった → NULL で表す
    con.execute("UPDATE job_events SET application_id = NULL WHERE application_id = 0 "
                "OR application_id NOT IN (SELECT id FROM job_applications)")
    con.execute("DELETE FROM job_docs WHERE application_id NOT IN (SELECT id FROM job_applications)")

    # ---- 2. 外部キー付きで作り直す ----
    dialect = engine.dialect
    for name in FK_TABLES:
        table = models.Base.metadata.tables[name]
        old_cols = [r[1] for r in con.execute(f'PRAGMA table_info("{name}")').fetchall()]
        cols = [c.name for c in table.columns if c.name in old_cols]
        ddl = str(CreateTable(table).compile(dialect=dialect)).strip()
        prefix = f"CREATE TABLE {name} "
        assert ddl.startswith(prefix), ddl[:60]
        con.execute(f"CREATE TABLE {name}__new " + ddl[len(prefix):])
        col_list = ", ".join(f'"{c}"' for c in cols)
        con.execute(f'INSERT INTO {name}__new ({col_list}) SELECT {col_list} FROM "{name}"')
        con.execute(f'DROP TABLE "{name}"')
        con.execute(f'ALTER TABLE {name}__new RENAME TO "{name}"')

    # ---- 3. 索引（作り直した表の索引と、既存の表への追加） ----
    have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'index'").fetchall()}
    for table in models.Base.metadata.sorted_tables:
        for idx in table.indexes:
            if idx.name not in have:
                con.execute(str(CreateIndex(idx).compile(dialect=dialect)))

    # ---- 4. settings の記録 → 専用の表 ----
    # 過去の移行（版を上げる処理）なので、gates の既定値は policy.ALL_GATES ではなく当時の値を直接書く
    # （後で定数を変えても、過去の移行の結果が変わらないように）
    for e in setting("emergency_unlocks") or []:
        if not isinstance(e, dict):
            continue
        appr = e.get("approved")
        con.execute("INSERT INTO unlock_requests (ts, reason, gates, start, \"end\", approved, judge) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (str(e.get("ts") or "")[:19], str(e.get("reason") or ""), str(e.get("gates") or "game+site"),
                     str(e.get("start") or ""), str(e.get("end") or ""),
                     None if appr is None else bool(appr), str(e.get("judge") or "")))
    drop_setting("emergency_unlocks")
    for r in setting("exemption_requests") or []:
        if not isinstance(r, dict) or not r.get("id"):
            continue
        d = r.get("decision") or {}
        con.execute("INSERT OR IGNORE INTO exemption_requests (id, created, date, start, \"end\", minutes, company, "
                    "kind, evidence, status, decision_reason, decision_at, decision_by, over_cap) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (str(r["id"]), str(r.get("created") or ""), str(r.get("date") or ""),
                     str(r.get("start") or ""), str(r.get("end") or ""), int(r.get("minutes") or 0),
                     str(r.get("company") or ""), str(r.get("kind") or ""), str(r.get("evidence") or ""),
                     str(r.get("status") or "pending"), str(d.get("reason") or ""), str(d.get("at") or ""),
                     str(d.get("by") or ""), bool(r.get("over_cap"))))
    drop_setting("exemption_requests")
    box = setting("gcal_google_events")
    if isinstance(box, dict):
        for ev in box.get("events") or []:
            if not isinstance(ev, dict) or not ev.get("date"):
                continue
            con.execute("INSERT INTO google_events (event_id, title, allday, date, end_date, start, \"end\", "
                        "location, created) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (str(ev.get("id") or ""), str(ev.get("title") or ""), bool(ev.get("allday")),
                         str(ev["date"]), str(ev.get("endDate") or ev["date"]), str(ev.get("start") or ""),
                         str(ev.get("end") or ""), str(ev.get("location") or ""), str(ev.get("created") or "")))
        meta = {k: box.get(k) or "" for k in ("fetched", "start", "end", "calendar")}
        con.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                    ("gcal_google_pull", json.dumps(meta, ensure_ascii=False)))
    drop_setting("gcal_google_events")

    # ---- 5. 習慣ごとの設定：習慣名 → 習慣の番号 ----
    opts = setting("habit_options")
    if isinstance(opts, dict):
        ids = {t: i for i, t in con.execute("SELECT id, title FROM todo_items WHERE kind = 'habit'").fetchall()}
        new = {}
        for k, v in opts.items():
            if str(k).isdigit():
                new[str(k)] = v
            elif k in ids:
                new[str(ids[k])] = v
            # 消えた習慣の設定は持ち越さない
        con.execute("UPDATE settings SET value = ? WHERE key = 'habit_options'",
                    (json.dumps(new, ensure_ascii=False),))

    # ---- 6. 勉強時間・気分転換時間の列（activity_log の合計に一本化） ----
    cols = [r[1] for r in con.execute('PRAGMA table_info("daily_state")').fetchall()]
    for c in ("study_time_total", "refresh_time_total"):
        if c in cols:
            con.execute(f'ALTER TABLE daily_state DROP COLUMN "{c}"')

    # ---- 7. 使われなくなった設定 ----
    for k in DEAD_SETTING_KEYS:
        drop_setting(k)


UPGRADES = {1: _upgrade_v1}


def upgrade(engine) -> int:
    """DB の構造を最新にする（起動時に create_all の後で呼ぶ）。新しい DB は create_all で最新の形に
    なっているので、版番号だけ進める。既存の DB は、構造を変える前に backups/ に複製してから実行する。
    各段階は1つのトランザクション（途中で失敗したら元のまま）。戻り値は実行後の版"""
    import sqlite3
    raw_path = engine.url.database
    con = sqlite3.connect(raw_path, isolation_level=None)   # 自分で BEGIN / COMMIT する
    try:
        ver = con.execute("PRAGMA user_version").fetchone()[0]
        if ver >= SCHEMA_VERSION:
            return ver
        fresh = con.execute("SELECT COUNT(*) FROM settings").fetchone()[0] == 0
        if fresh:
            con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            return SCHEMA_VERSION
        backup = _backup_db(raw_path, f"schema_v{SCHEMA_VERSION}")
        # 表の作り直しの間は外部キーの確認を止める（SQLite 公式の手順。トランザクションの外で切り替える）
        con.execute("PRAGMA foreign_keys = OFF")
        for v in range(ver + 1, SCHEMA_VERSION + 1):
            con.execute("BEGIN")
            try:
                UPGRADES[v](con, engine)
                bad = con.execute("PRAGMA foreign_key_check").fetchall()
                if bad:
                    raise RuntimeError(f"外部キーの不整合が残っています: {bad[:5]}")
                con.execute(f"PRAGMA user_version = {v}")
                con.execute("COMMIT")
            except Exception as e:
                con.execute("ROLLBACK")
                raise RuntimeError(f"DB の更新（版 {v}）に失敗しました。DB は元のままです（複製: {backup}）") from e
        con.execute("PRAGMA foreign_keys = ON")
        return SCHEMA_VERSION
    finally:
        con.close()
