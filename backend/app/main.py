"""FastAPI 入口（API窓口）。

起動: backend フォルダで `fastapi dev app/main.py`
  → http://127.0.0.1:8000
  → 自動ドキュメント http://127.0.0.1:8000/docs
"""
import re
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy.orm import Session

from . import (crud, exemption_api, gate_api, local_backup, gcal_sync, jobs_api, life_api, logic, mail_import,
               migrate, models, money_api, policy, presence_api, schemas, todo_api, widget_sessions)
from .config import SOS_LIST
from .database import SessionLocal, engine, get_db

import logging
import random

# アップロード背景画像の保存先（既存 bg_images/ に相当）
BG_DIR = Path(__file__).resolve().parent.parent / "bg_images"
BG_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger(__name__)

# この本体に接続してよいホスト名（本人の PC の中だけ）
LOCAL_HOSTS = ("127.0.0.1", "localhost")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """起動時の初期化（FastAPI公式の lifespan 方式）"""
    models.Base.metadata.create_all(bind=engine)
    migrate.ensure_new_columns(engine)  # 既存テーブルへの列追加（簡易マイグレーション）
    migrate.upgrade(engine)             # 構造の変更（外部キー・記録の表など。版ごとに1回だけ。実行前に複製を取る）
    with SessionLocal() as db:
        migrate.run_all(db)
        money_api.ensure_money_defaults(db)  # マネー設定の初期化
        mail_import.ensure_mail_defaults(db)  # メール取り込み設定の初期化
        gate_api.ensure_gate_defaults(db)     # サイト制限の初期化＋単発タスクのシード
        todo_api.ensure_todo_migration(db)    # やること（todo_items）の初期データ（新しいDBのみ）
        migrate.cleanup_legacy_todo(db, engine)  # 旧 habit_checks・旧キーの後始末（1回だけ）
        migrate.migrate_roulette_items(db)    # 通常勉強／重点 → ルーレット項目（assignments）へ（1回だけ）
    # 利用通知メールの自動チェック（有効時のみ動く。デーモンなので終了処理は不要）
    threading.Thread(target=mail_import.poll_loop, daemon=True).start()
    # iPhone記録の取り込み＋Googleカレンダー自動同期
    threading.Thread(target=gcal_sync.poll_loop, daemon=True).start()
    # iPhone のタイマー（スタート/ストップ）を約30秒ごとに Apps Script から取り込む
    gcal_sync.pc_timer_provider = pc_timer_state   # スマホ用ページに PC の計測状態を見せる
    gcal_sync.pc_stop_handler = pc_timer_stop      # スマホから PC の計測を止める
    threading.Thread(target=gcal_sync.phone_poll_loop, daemon=True).start()
    # ローカル日次バックアップ（backend/data/backups、7世代。外部送信なし）
    threading.Thread(target=local_backup.backup_loop, daemon=True).start()
    # 解放判定（gate_today）を60秒ごとに再計算（ワーカーはこの結果を読む）
    with SessionLocal() as db:
        gate_api.gate_state(db)
    gate_api.start_refresh_thread()
    yield


app = FastAPI(title="Focus & Cafe Roulette API", lifespan=lifespan)

# 画面（Vite）は自分の proxy（frontend/vite.config.js）で /api /bg /webcam をここへ中継するので、
# ブラウザから見ると同じオリジン。CORS の許可は置かない（他のサイトから API を読ませないため。2026-11-06）

# 宛先のホスト名は 127.0.0.1 / localhost だけ受け付ける（Starlette 公式の TrustedHostMiddleware）。
# 悪意のあるサイトが自分のドメイン名を 127.0.0.1 に向け直して（DNS リバインディング）API を読むのを防ぐ
app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(LOCAL_HOSTS))


@app.middleware("http")
async def reject_cross_site_writes(request: Request, call_next):
    """他のサイトから送られた書き込み（CSRF）を拒否する。
    ブラウザは別のサイトからの POST などに Origin ヘッダーを付けるので、それが localhost の画面以外なら 403。
    Origin の無い要求（小窓・ワーカー・ツール）はそのまま通す"""
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if origin is not None and (urlsplit(origin).hostname or "") not in LOCAL_HOSTS:
            return JSONResponse(status_code=403, content={"detail": "このサイトからの操作は受け付けません"})
    return await call_next(request)


# アップロードした背景画像を配信（/bg/ファイル名）
app.mount("/bg", StaticFiles(directory=str(BG_DIR)), name="bg")

# ライフ（生活ログ）機能のAPI（life_api.py に分離）
app.include_router(life_api.router)

# 金銭管理（旧 ikaseru）のAPI（money_api.py に分離）
app.include_router(money_api.router)

# 利用通知メールの自動取り込みAPI（mail_import.py に分離）
app.include_router(mail_import.router)

# Google連携（カレンダー同期・iPhone記録取り込み）API
app.include_router(gcal_sync.router)

# 就活（夏インターン・本選考）API（jobs_api.py に分離）
app.include_router(jobs_api.router)

# 🔒 サイト制限ゲート（必須タスク完了で解放）API（gate_api.py に分離）
app.include_router(gate_api.router)

# 📋 やること統合（must / habit / periodic）API（todo_api.py に分離）
app.include_router(todo_api.router)

# 📷 Webカメラ在席判定・静止画記録（presence_api.py。F22）
app.include_router(presence_api.router)
app.include_router(exemption_api.router)   # 💼 面接などの特例（Claude 審査。2026-11-03）
# 静止画のまとめ画像を画面に出すための配信（logs/webcam。127.0.0.1 のみ。外部送信なし）
presence_api.WEBCAM_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/webcam", StaticFiles(directory=str(presence_api.WEBCAM_DIR)), name="webcam")


# ---------- 小窓（quick_widget）の生存確認と再表示 ----------
# 小窓は20秒ごとに ping を送ってくる。60秒来なければ「閉じられた」とみなし、
# ホームに「🪟 小窓を表示」ボタンが現れる → 押すとここから pythonw で起動する。
_WIDGET_STATE = {"last_ping": 0.0, "running": False, "task": "", "elapsed_sec": 0}
# アプリ → 小窓への指示（「この習慣でタイマー開始」）。次の ping の返事で渡す。90秒で失効
_WIDGET_COMMAND = {"start": "", "stop": False, "at": 0.0}


def pc_timer_state() -> dict:
    """PC 側で動いている計測（小窓 or アプリの集中モード）。スマホ用ページに見せるため gcal_sync が使う"""
    since = time.time() - _WIDGET_STATE["last_ping"]
    if since < 60 and _WIDGET_STATE["running"]:
        elapsed = int(_WIDGET_STATE["elapsed_sec"] + since)
        return {"running": True, "task": _WIDGET_STATE["task"] or "（タスク未選択）",
                "started": int((time.time() - elapsed) * 1000), "source": "widget"}
    try:
        with SessionLocal() as db:
            row = crud.get_or_create_state(db)
            st = crud.state_to_dict(row)
            task = st.get("current_task")
            if st.get("page") == "active" and task and row.start_time:
                return {"running": True, "task": task.get("タスク") or "", 
                        "started": int(float(row.start_time) * 1000), "source": "app"}
    except Exception:
        pass
    return {"running": False}


def pc_timer_stop() -> str:
    """スマホからの「PC の計測を止めて記録」。小窓なら次の ping で止める、アプリの集中モードなら記録して終了"""
    since = time.time() - _WIDGET_STATE["last_ping"]
    if since < 60 and _WIDGET_STATE["running"]:
        _WIDGET_COMMAND.update({"stop": True, "at": time.time()})
        return "widget"
    with SessionLocal() as db:
        row = crud.get_or_create_state(db)
        st = crud.state_to_dict(row)
        task = st.get("current_task")
        if st.get("page") == "active" and task:
            em = _elapsed_minutes(row)
            today = datetime.now().date().isoformat()
            today_min = 0
            for when, mins, day in crud.split_minutes_by_day(time.time(), em):
                crud.add_log(db, when, task["カテゴリ"], task["タスク"], "設定BGM", mins,
                             note="📱 スマホから終了")
                if day == today:
                    today_min += mins
            changes = {"pending_review": None, "current_task": None, "start_time": None,
                       "page": "dashboard"}
            if task["カテゴリ"] == "勉強" and today_min > 0:
                todo_api.auto_complete_habit_by_study(db, task["タスク"], today_min)
            crud.update_state(db, changes)
            db.commit()
            gate_api.gate_state(db)
            return "app"
    return ""


def _auto_complete_habit(task: str, minutes: int) -> None:
    """計測中のタスクが今日の習慣なら、規定時間で自動完了（5分以上なら着手）。失敗は無視"""
    if minutes < todo_api.MIN_ACTION_MINUTES:
        return
    try:
        with SessionLocal() as db:
            if todo_api.auto_complete_habit_by_study(db, task, minutes):
                db.commit()
                gate_api.gate_state(db)
    except Exception:
        pass


@app.post("/api/widget/ping")
def widget_ping(body: schemas.WidgetPing | None = None):
    """小窓からの生存通知。計測中なら task / elapsed_sec も届く（アプリのリアルタイム表示用）。
    返事に start（タスク名）が入っていたら、小窓はそれを選んでタイマーを開始する"""
    body = body or schemas.WidgetPing()   # 中身のない ping も受け付ける
    _WIDGET_STATE["last_ping"] = time.time()
    _WIDGET_STATE["running"] = body.running
    _WIDGET_STATE["task"] = body.task
    _WIDGET_STATE["elapsed_sec"] = max(0, min(body.elapsed_sec, MAX_LOG_MINUTES * 60))
    if _WIDGET_STATE["running"]:
        # 本体の時計で「ping が続いていた区間」を記録する（記録の分数を確かめるため：widget_sessions）
        observed = 0
        try:
            with SessionLocal() as db:
                widget_sessions.observe(db, _WIDGET_STATE["task"])
                observed = widget_sessions.observed_seconds(db) + widget_sessions.GRACE_SEC
        except Exception:
            logger.exception("小窓の計測区間の記録に失敗しました")
        # 習慣を計測中で規定時間（時間帯の長さ）に達したら、止める前でも自動で完了にする。
        # 数えるのは「小窓の経過時間」「本体が確かめた時間」「今日の 0時以降」のいちばん短いもの
        # （23:30 に始めた計測で今日の習慣を前日分込みで完了にしない・経過時間の偽装を数えない）
        if _WIDGET_STATE["task"]:
            now = datetime.now()
            since_midnight = int((now - now.replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds())
            counted = min(_WIDGET_STATE["elapsed_sec"], observed, since_midnight)
            _auto_complete_habit(_WIDGET_STATE["task"], counted // 60)
    out = {"ok": True}
    if time.time() - _WIDGET_COMMAND["at"] < 90:
        if _WIDGET_COMMAND["start"] and not _WIDGET_STATE["running"]:
            out["start"] = _WIDGET_COMMAND["start"]
        if _WIDGET_COMMAND["stop"] and _WIDGET_STATE["running"]:
            out["stop"] = True  # スマホからの「止めて記録」
    if _WIDGET_COMMAND["start"] or _WIDGET_COMMAND["stop"]:
        _WIDGET_COMMAND.update({"start": "", "stop": False, "at": 0.0})
    return out


@app.post("/api/widget/start")
def widget_start(body: schemas.WidgetStart | None = None):
    """アプリから小窓のタイマーを開始させる（習慣の全画面ロックの「小窓で開始」）。
    小窓が閉じていれば起動し、最初の ping で指示を渡す"""
    task = (body.task if body else "").strip()
    if not task:
        raise HTTPException(status_code=400, detail="task を指定してください")
    if _WIDGET_STATE["running"] and (time.time() - _WIDGET_STATE["last_ping"]) < 60:
        raise HTTPException(status_code=409, detail=f"小窓は「{_WIDGET_STATE['task']}」を計測中です")
    _WIDGET_COMMAND.update({"start": task, "at": time.time()})
    launched = widget_show()
    return {"ok": True, "task": task, "launched": not launched.get("already")}


@app.post("/api/widget/stop")
def widget_stop():
    """アプリから小窓のタイマーを止めて記録させる（画角外の習慣「終了」ボタン用。F22）。
    小窓は次の ping（最長20秒）で stop を受け取り、通常の終了と同じ記録処理を行う"""
    if not (_WIDGET_STATE["running"] and (time.time() - _WIDGET_STATE["last_ping"]) < 60):
        raise HTTPException(status_code=409, detail="小窓は計測していません")
    _WIDGET_COMMAND.update({"stop": True, "at": time.time()})
    return {"ok": True, "task": _WIDGET_STATE["task"]}


@app.post("/api/widget/bye")
def widget_bye():
    _WIDGET_STATE.update({"last_ping": 0.0, "running": False, "task": "", "elapsed_sec": 0})
    return {"ok": True}


@app.get("/api/widget/status")
def widget_status():
    """alive に加えて、計測中なら「今この瞬間の経過秒」を返す（最終pingからの経過を足す）"""
    since = time.time() - _WIDGET_STATE["last_ping"]
    alive = since < 60
    running = alive and _WIDGET_STATE["running"]
    out = {
        "alive": alive,
        "running": running,
        "task": _WIDGET_STATE["task"] if running else "",
        "elapsed_sec": int(_WIDGET_STATE["elapsed_sec"] + since) if running else 0,
        "source": "widget" if running else "",
    }
    # 小窓が動いていなければ、iPhone のタイマー（Apps Script 経由・約30秒ごと更新）を表示に使う
    if not running:
        ph = gcal_sync.phone_timer_state()
        if ph["running"]:
            out.update({"running": True, "task": "📱 " + ph["task"],
                        "elapsed_sec": ph["elapsed_sec"], "source": "phone"})
    return out


@app.post("/api/widget/show")
def widget_show():
    if (time.time() - _WIDGET_STATE["last_ping"]) < 60:
        return {"ok": True, "already": True}
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[2]
    widget = root / "quick_widget.py"
    if not widget.exists():
        raise HTTPException(status_code=404, detail="quick_widget.py が見つかりません")
    # Python の選び方は launcher と同じ（appctl.widget_python：venv に PySide6 があれば venv、無ければ PATH の pythonw）
    if str(root) not in sys.path:
        sys.path.append(str(root))   # 末尾に足す（標準ライブラリなどを上書きしないように）
    import appctl
    subprocess.Popen([appctl.widget_python(), str(widget)], cwd=str(root))
    return {"ok": True, "already": False}


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


MIN_STUDY_TARGET = 30   # 今日の勉強目標の下限（分）。ホームの入力欄と同じ
MAX_LOG_MINUTES = 480   # 1件の記録の上限（分）。集中モードの消し忘れ対策（_elapsed_minutes）と同じ8時間
LOG_END_AT_MAX_AGE_SEC = 7 * 24 * 3600   # 送り直しで受け付ける「終わった時刻」の古さの上限（7日）


def _game_window(db: Session) -> dict:
    """ゲームができる時間帯（policy.GAME_WINDOW に固定）。設定からは読まない"""
    return dict(policy.GAME_WINDOW)


def _can_game(db: Session) -> bool:
    """現在のゲーム解放状態（勉強時間・時間帯・日付ガード ＋ ノルマ完了。判定は gate_api に集約）"""
    return bool(gate_api.gate_state(db)["game_unlocked"])


def _elapsed_minutes(row) -> int:
    """経過分。規定時間を過ぎても「終了を押すまで」の実時間を数える。

    （以前は duration で頭打ちにしていたが、タイマー終了後に続けた分も
      勉強時間として記録する仕様に変更。消し忘れ対策として8時間で頭打ち）
    """
    start = row.start_time or time.time()
    return max(0, min(int((time.time() - start) / 60), 480))


# ---------- 基本 ----------
@app.get("/api/health")
def health_check():
    # app：起動役（appctl.backend_alive）が「他のアプリの同じ番号」と区別するための名前
    return {"status": "ok", "app": "focus-cafe"}


# ---------- 設定 ----------
# 画面には中身を返さない設定（API キー・パスワード・合言葉）。画面には「設定済みかどうか」だけを
# secrets_set で返し、保存は「新しい値を入力したときだけ」上書きする（空のまま送られたら変更しない）
SECRET_SETTING_KEYS = ("gas_token", "money_api_key", "mail_app_password")


def _settings_for_screen(settings: dict) -> dict:
    out = dict(settings)
    out.pop(widget_sessions.SETTING_KEY, None)   # 本体の内部の記録（画面では使わない。60秒ごとに変わる）
    out["secrets_set"] = {k: bool(str(settings.get(k) or "").strip()) for k in SECRET_SETTING_KEYS}
    for k in SECRET_SETTING_KEYS:
        if k in out:
            out[k] = ""
    return out


@app.get("/api/settings")
def read_settings(db: Session = Depends(get_db)):
    return _settings_for_screen(crud.get_all_settings(db))


@app.put("/api/settings")
def update_settings(changes: dict, db: Session = Depends(get_db)):
    """設定の更新（渡されたキーだけ上書き。即保存＝既存 save_settings 相当）"""
    changes.pop("secrets_set", None)   # 画面向けの表示用の項目は保存しない
    for k in SECRET_SETTING_KEYS:      # 秘密の項目は空なら「変更しない」
        if k in changes and not str(changes[k] or "").strip():
            changes.pop(k)
    gate_api.check_settings_change(db, changes)  # 制限中はブロック設定を弱められない（423）
    gate_api.stamp_switches(changes)             # 制限のオフはその日だけ有効
    for key, value in changes.items():
        crud.set_setting(db, key, value)
    db.commit()
    return _settings_for_screen(crud.get_all_settings(db))


# ---------- 今日の状態 ----------
@app.get("/api/state")
def read_state(db: Session = Depends(get_db)):
    """今日の状態（日付またぎリセット込み＝既存 init_session 相当）。

    あわせて課題→「今日絶対やる」の自動同期も行う
    （期限2日以内の課題が期限順で mustdo に反映される）。
    """
    row = crud.get_or_create_state(db)
    life_api.sync_assignments_to_mustdo(db)
    return crud.state_to_dict(row)


@app.patch("/api/state")
def patch_state(changes: dict, db: Session = Depends(get_db)):
    """状態の部分更新（画面から変えてよいのは ページ と 今日の勉強目標の確定 だけ。2026-11-06）。

    勉強時間（study_time_total）・実行中のタスクなどは本体の処理だけが書く。
    目標は1日1回だけ確定でき（target_locked）、確定後は下げられない（ゲームの解放条件になるため）"""
    row = crud.get_or_create_state(db)
    allowed = {}
    for key, value in changes.items():
        if key == "page":
            allowed["page"] = str(value)
        elif key == "target_value":
            v = int(value)
            if row.target_locked and v != row.target_value:
                raise HTTPException(status_code=423, detail="今日の勉強目標はすでに確定しています（変更は明日から）")
            if v < MIN_STUDY_TARGET:
                raise HTTPException(status_code=400, detail=f"勉強目標は {MIN_STUDY_TARGET} 分以上にしてください")
            allowed["target_value"] = v
        elif key == "target_locked":
            if not value and row.target_locked:
                raise HTTPException(status_code=423, detail="確定した目標は取り消せません")
            allowed["target_locked"] = bool(value) or bool(row.target_locked)
        else:
            raise HTTPException(status_code=400, detail=f"{key} は画面からは変更できません")
    row = crud.update_state(db, allowed)
    return crud.state_to_dict(row)


# ---------- 履歴 ----------
@app.get("/api/logs")
def read_logs(db: Session = Depends(get_db)):
    return crud.get_logs(db)


@app.post("/api/logs")
def create_log(body: schemas.LogBody, db: Session = Depends(get_db)):
    """履歴の追加（クイックスタート小窓の連携入口でもある）。
    今日の勉強・気分転換の合計は記録から数える（crud.study_minutes）ので、ここで足し込む必要はない。
    """
    # 1件の分数は 1〜MAX_LOG_MINUTES に収める（大きな値を送って勉強目標・習慣を一気に満たす抜け道を防ぐ）
    minutes = max(0, min(int(body.minutes), MAX_LOG_MINUTES))
    # 終わった時刻：送り直し（pending）は「やった時刻」で記録する。未来や古すぎる時刻は受け付けない
    now_ts = time.time()
    end_ts = now_ts
    if body.end_at is not None:
        if not (now_ts - LOG_END_AT_MAX_AGE_SEC <= body.end_at <= now_ts + 60):
            raise HTTPException(status_code=400, detail="end_at（終わった時刻）が範囲外です")
        end_ts = min(float(body.end_at), now_ts)
    # 本体が ping で確かめられた計測時間までしか記録しない（curl などで分数だけ送る抜け道を防ぐ。widget_sessions）
    note = body.note
    allowed = widget_sessions.claim_minutes(db, end_ts)
    if minutes > allowed:
        note = (note + f"（届いた{minutes}分のうち、本体が計測を確認できた{allowed}分を記録）").strip()
        minutes = allowed
    if minutes <= 0:
        return {"ok": True, "habit_level": "", "recorded_minutes": 0}
    # 計測が0時をまたいでいたら、前日分と今日分に分けて記録する（全部が翌日扱いになるのを防ぐ）
    today = datetime.now().date().isoformat()
    parts = crud.split_minutes_by_day(end_ts, minutes)
    today_min = 0
    for i, (when, mins, day) in enumerate(parts):
        last = (i == len(parts) - 1)
        crud.add_log(db, when, body.category, body.content, body.bgm, mins,
                     body.done_text if last else "", body.progress if last else "",
                     body.focus if last else "", body.satisfaction if last else "",
                     note if len(parts) == 1 else (note + "（日付をまたいだため分割）").strip())
        if day == today:
            today_min += mins
    # 小窓で「習慣」を選んで規定時間やった → 今日の習慣を自動で完了（5分以上なら着手）
    habit_level = ""
    if "勉強" in body.category and today_min > 0:
        habit_level = todo_api.auto_complete_habit_by_study(db, body.content, today_min)
    db.commit()
    if habit_level:
        gate_api.gate_state(db)  # 解放判定を更新
    return {"ok": True, "habit_level": habit_level, "recorded_minutes": minutes}


# ---------- ゲーム解放 ----------
@app.get("/api/game/status")
def game_status(db: Session = Depends(get_db)):
    """ゲーム解放状態（画面表示・blocker 連携用）"""
    row = crud.get_or_create_state(db)
    w = _game_window(db)
    gate = gate_api.gate_state(db)
    return {
        "unlocked": gate["game_unlocked"],
        "study_ok": gate["game_base"],       # 勉強時間・時間帯・日付の条件
        "tasks_done": gate["tasks_done"],    # 必須タスク＋今日の習慣の条件
        "study_time_total": crud.study_minutes(db),
        "target_value": row.target_value,
        "is_unlock_time": logic.is_unlock_time(window=w),
        "window": w,
        # 解放時間帯は固定（変更不可）
        "window_changeable": False,
    }


# ---------- ルーレット ----------
@app.post("/api/roulette/roll")
def roulette_roll(db: Session = Depends(get_db)):
    """ルーレットを回す（views/dashboard.py の roll_once 呼び出しと同じ）"""
    row = crud.get_or_create_state(db)
    settings = crud.get_all_settings(db)
    can_game = _can_game(db)
    options = logic.roll_once(
        settings,
        last_was_refresh=row.last_was_refresh,
        force_study_only=row.force_study_only,
        mock_exam_done=row.mock_exam_done,
        can_game=can_game,
        must=todo_api.must_unfinished_titles(db),  # 未完了の必須があれば勉強はそこから
        items=life_api.roulette_pool_items(db),    # ルーレット項目（未完了・有効。重点は3倍）
    )
    crud.update_state(db, {"rolled_options": options})
    return {
        "options": options,
        "study_only": row.last_was_refresh or row.force_study_only,
        "can_game": can_game,
    }


@app.post("/api/roulette/choose")
def roulette_choose(body: schemas.ChooseBody, db: Session = Depends(get_db)):
    """実行タスクを選んで集中モードを開始（views/dashboard.py と同じ手順）"""
    row = crud.get_or_create_state(db)
    settings = crud.get_all_settings(db)
    duration, is_mock = logic.pick_duration(settings, body.category, body.task)
    # 振り返りで「終わった？」を聞く対象：今日の必須、または期限つきのルーレット項目
    is_mustdo = body.category == "勉強" and (
        body.task in todo_api.must_unfinished_titles(db)
        or any(a.title == body.task for a in life_api.due_items(db)))
    changes = {
        "current_task": {"カテゴリ": body.category, "タスク": body.task,
                         "duration": duration, "mustdo": is_mustdo},
        "start_time": time.time(),
        "force_study_only": False,
        "last_was_refresh": (body.category == "気分転換"),
        "rolled_options": None,
        "page": "active",
    }
    if is_mock:
        changes["mock_exam_done"] = True
    row = crud.update_state(db, changes)
    return crud.state_to_dict(row)


# ---------- 集中モード ----------
@app.post("/api/task/finish")
def task_finish(db: Session = Depends(get_db)):
    """■終了して記録する：この時点で履歴に記録し、ふりかえりへ。
    ふりかえりは記録に「やったこと・満足度など」を書き足すだけ（ふりかえりを閉じても時間は消えない。2026-11-06）"""
    row = crud.get_or_create_state(db)
    task = crud.state_to_dict(row).get("current_task")
    if not task:
        raise HTTPException(status_code=400, detail="実行中のタスクがありません")
    em = _elapsed_minutes(row)
    end_ts = time.time()
    # 0時をまたいでいれば前日分と今日分に分けて記録する
    today = datetime.now().date().isoformat()
    parts = crud.split_minutes_by_day(end_ts, em)
    logs = [crud.add_log(db, when, task["カテゴリ"], task["タスク"], "設定BGM", mins,
                         note=("" if len(parts) == 1 else "日付をまたいだため分割"))
            for when, mins, _day in parts]
    db.flush()
    today_min = sum(m for _, m, d in parts if d == today)
    changes = {
        "pending_review": {"task": task["タスク"], "cat": task["カテゴリ"],
                           "em": em, "end": end_ts, "mustdo": task.get("mustdo", False),
                           "log_id": logs[-1].id, "today_min": today_min},
        "page": "review",
    }
    row = crud.update_state(db, changes)
    return crud.state_to_dict(row)


@app.post("/api/task/shorten")
def task_shorten(db: Session = Depends(get_db)):
    """🔁短い課題の早期修了→勉強のみで再抽選（views/active.py と同じ）"""
    row = crud.get_or_create_state(db)
    task = crud.state_to_dict(row).get("current_task")
    if not task:
        raise HTTPException(status_code=400, detail="実行中のタスクがありません")
    em = _elapsed_minutes(row)
    crud.add_log(db, _now_str(), "勉強(短縮修了)", task["タスク"], "設定BGM",
                 em, note="短い課題のため早期修了→再抽選")
    db.flush()   # いま書いた記録を合計に含める
    settings = crud.get_all_settings(db)
    can_game = (logic.is_game_unlocked(row.target_date, crud.study_minutes(db), row.target_value,
                                       window=_game_window(db))
                and gate_api.gate_state(db)["tasks_done"])
    options = logic.roll_once(settings, last_was_refresh=False,
                              force_study_only=True,
                              mock_exam_done=row.mock_exam_done,
                              can_game=can_game,
                              must=todo_api.must_unfinished_titles(db),
                              items=life_api.roulette_pool_items(db))
    row = crud.update_state(db, {
        "last_was_refresh": False,
        "force_study_only": True,   # 再抽選は勉強のみ表示
        "rolled_options": options,
        "current_task": None,
        "start_time": None,
        "page": "dashboard",
    })
    return crud.state_to_dict(row)


@app.post("/api/task/sos")
def task_sos(db: Session = Depends(get_db)):
    """🚨集中切れ！(SOS)：中断を記録してSOSページへ（views/active.py と同じ）"""
    row = crud.get_or_create_state(db)
    task = crud.state_to_dict(row).get("current_task")
    if not task:
        raise HTTPException(status_code=400, detail="実行中のタスクがありません")
    em = _elapsed_minutes(row)
    crud.add_log(db, _now_str(), "中断", task["タスク"], "設定BGM",
                 em, note="集中切れ")
    row = crud.update_state(db, {
        "sos_task": random.choice(SOS_LIST),
        "current_task": None,
        "start_time": None,
        "page": "sos",
    })
    return crud.state_to_dict(row)


@app.post("/api/sos/done")
def sos_done(db: Session = Depends(get_db)):
    """SOS明け：ダッシュボードへ戻る。次の抽選は勉強のみ（views/sos.py と同じ趣旨）"""
    row = crud.update_state(db, {
        "page": "dashboard",
        "force_study_only": True,  # SOS明けの次の抽選は勉強のみ
    })
    return crud.state_to_dict(row)


# ---------- ふりかえり ----------
@app.post("/api/review/finish")
def review_finish(body: schemas.ReviewBody, db: Session = Depends(get_db)):
    """ふりかえりの確定（views/review.py の _finish_review と同じ）"""
    row = crud.get_or_create_state(db)
    pr = crud.state_to_dict(row).get("pending_review") or {}
    # 記録は「終了」を押したときに書いてある（task_finish）。ここでは詳細を書き足すだけ
    if pr.get("log_id"):
        log = db.get(models.ActivityLog, pr["log_id"])
        if log is not None and body.save_details:
            log.done_text, log.progress = body.done_text, body.progress
            log.focus, log.satisfaction = body.focus, body.satisfaction
        today_min = int(pr.get("today_min") or 0)
    else:
        # 2026-11-06 より前の「終了」で、まだ記録していないもの：ここで記録する（時間を失わないため）
        parts = crud.split_minutes_by_day(float(pr.get("end") or time.time()), int(pr.get("em", 0)))
        for i, (when, mins, _day) in enumerate(parts):
            last = i == len(parts) - 1
            crud.add_log(db, when, pr.get("cat", ""), pr.get("task", ""), "設定BGM", mins,
                         done_text=body.done_text if body.save_details and last else "",
                         progress=body.progress if body.save_details and last else "",
                         focus=body.focus if body.save_details and last else "",
                         satisfaction=body.satisfaction if body.save_details and last else "",
                         note="" if len(parts) == 1 else "日付をまたいだため分割")
        today = datetime.now().date().isoformat()
        today_min = sum(m for _, m, d in parts if d == today)
    # 集中モードで習慣を規定時間やっていたら自動で完了（5分以上なら着手）
    if pr.get("cat") == "勉強" and pr.get("task") and today_min > 0:
        if todo_api.auto_complete_habit_by_study(db, pr["task"], today_min):
            db.commit()
            gate_api.gate_state(db)
    # 「終わった」と答えていたら、今日の必須（todo_items）に完了記録を付ける
    # 本体が記録した「必須だったか」（pr["mustdo"]）も確認する（画面から送られる値だけを信用しない）
    if body.remove_mustdo and pr.get("mustdo") and pr.get("task"):
        todo_api.complete_by_title(db, pr["task"], "full")
        db.commit()
        gate_api.gate_state(db)  # 解放判定を即時更新
        # 同名の期限つきルーレット項目（旧・課題）も完了(100%)にする
        life_api.complete_assignment_by_label(db, pr["task"])
    row = crud.update_state(db, {
        "pending_review": None,
        "current_task": None,
        "start_time": None,
        "page": "dashboard",
    })
    return crud.state_to_dict(row)


# ---------- 背景画像 ----------
@app.post("/api/background/upload")
def upload_background(file: UploadFile, db: Session = Depends(get_db)):
    """背景画像のアップロード（components/background.py と同じ命名規則）"""
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ("png", "jpg", "jpeg"):
        raise HTTPException(status_code=400, detail="png / jpg / jpeg のみ対応です")
    safe = re.sub(r"[^A-Za-z0-9._-]", "", file.filename or "bg")
    fname = datetime.now().strftime("%Y%m%d_%H%M%S_") + safe
    if not fname.lower().endswith("." + ext):
        fname = fname + "." + ext
    (BG_DIR / fname).write_bytes(file.file.read())
    settings = crud.get_all_settings(db)
    hist = settings.get("bg_history") or []
    if fname not in hist:
        hist.insert(0, fname)
    crud.set_setting(db, "bg_history", hist)
    crud.set_setting(db, "bg_current_file", fname)
    db.commit()
    return {"filename": fname, "url": f"/bg/{fname}"}


@app.delete("/api/background/{fname}")
def delete_background(fname: str, db: Session = Depends(get_db)):
    """背景画像を履歴から削除（ファイルも削除）"""
    settings = crud.get_all_settings(db)
    hist = [h for h in (settings.get("bg_history") or []) if h != fname]
    crud.set_setting(db, "bg_history", hist)
    if settings.get("bg_current_file") == fname:
        crud.set_setting(db, "bg_current_file", hist[0] if hist else "")
    db.commit()
    try:
        (BG_DIR / Path(fname).name).unlink(missing_ok=True)
    except OSError:
        pass
    return {"ok": True, "bg_history": hist}


# ---------- 全データリセット ----------
@app.post("/api/reset")
def reset_all(db: Session = Depends(get_db)):
    """全データリセット：履歴と今日の状態（実行中のタスク等）を消す。
    今日確定した勉強目標はそのまま（解除すると目標を下げてゲームを解放できてしまうため。2026-11-06）"""
    crud.delete_all_logs(db)
    row = crud.update_state(db, {
        "page": "dashboard", "current_task": None, "start_time": None,
        "rolled_options": None, "pending_review": None,
    })
    return crud.state_to_dict(row)
