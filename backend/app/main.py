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

from fastapi import Depends, FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from . import crud, db_sync, gcal_sync, jobs_api, life_api, logic, mail_import, migrate, models, money_api, schemas
from .config import SOS_LIST
from .database import SessionLocal, engine, get_db

import random

# アップロード背景画像の保存先（既存 bg_images/ に相当）
BG_DIR = Path(__file__).resolve().parent.parent / "bg_images"
BG_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """起動時の初期化（FastAPI公式の lifespan 方式）"""
    models.Base.metadata.create_all(bind=engine)
    migrate.ensure_new_columns(engine)  # 既存テーブルへの列追加（簡易マイグレーション）
    with SessionLocal() as db:
        migrate.run_all(db)
        money_api.ensure_money_defaults(db)  # マネー設定の初期化
        mail_import.ensure_mail_defaults(db)  # メール取り込み設定の初期化
    # 利用通知メールの自動チェック（有効時のみ動く。デーモンなので終了処理は不要）
    threading.Thread(target=mail_import.poll_loop, daemon=True).start()
    # iPhone記録の取り込み＋Googleカレンダー自動同期
    threading.Thread(target=gcal_sync.poll_loop, daemon=True).start()
    # PC間共有：DBをGドライブへ自動プッシュ（もう一方のPCは起動時に取り込む）
    threading.Thread(target=db_sync.push_loop, daemon=True).start()
    yield


app = FastAPI(title="Focus & Cafe Roulette API", lifespan=lifespan)

# CORS設定：React開発サーバー（別ポート 5173）からの呼び出しを許可
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# アップロードした背景画像を配信（http://127.0.0.1:8000/bg/ファイル名）
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


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _can_game(db: Session) -> bool:
    """現在のゲーム解放状態（state の日付ガード込み）"""
    row = crud.get_or_create_state(db)
    return logic.is_game_unlocked(row.target_date, row.study_time_total, row.target_value)


def _elapsed_minutes(row) -> int:
    """経過分（views/active.py と同じ：0以上・duration以下に丸める）"""
    task = crud.state_to_dict(row).get("current_task") or {}
    duration = int(task.get("duration", 0))
    start = row.start_time or time.time()
    return max(0, min(int((time.time() - start) / 60), duration))


# ---------- 基本 ----------
@app.get("/api/health")
def health_check():
    return {"status": "ok"}


# ---------- 設定 ----------
@app.get("/api/settings")
def read_settings(db: Session = Depends(get_db)):
    return crud.get_all_settings(db)


@app.put("/api/settings")
def update_settings(changes: dict, db: Session = Depends(get_db)):
    """設定の更新（渡されたキーだけ上書き。即保存＝既存 save_settings 相当）"""
    for key, value in changes.items():
        crud.set_setting(db, key, value)
    db.commit()
    return crud.get_all_settings(db)


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
    """状態の部分更新（ページ遷移・目標の確定など）"""
    row = crud.update_state(db, changes)
    return crud.state_to_dict(row)


# ---------- 履歴 ----------
@app.get("/api/logs")
def read_logs(db: Session = Depends(get_db)):
    return crud.get_logs(db)


@app.post("/api/logs")
def create_log(body: schemas.LogBody, db: Session = Depends(get_db)):
    """履歴の追加（クイックスタート小窓の連携入口でもある）。

    add_to_today=True かつカテゴリが勉強/気分転換なら今日の合計にも加算
    （日付ガードは get_or_create_state が行う）。
    """
    crud.add_log(db, _now_str(), body.category, body.content, body.bgm,
                 body.minutes, body.done_text, body.progress, body.focus,
                 body.satisfaction, body.note)
    if body.add_to_today:
        row = crud.get_or_create_state(db)
        if "勉強" in body.category:
            row.study_time_total += int(body.minutes)
        elif "気分転換" in body.category:
            row.refresh_time_total += int(body.minutes)
    db.commit()
    return {"ok": True}


# ---------- ゲーム解放 ----------
@app.get("/api/game/status")
def game_status(db: Session = Depends(get_db)):
    """ゲーム解放状態（画面表示・将来の blocker 連携用）"""
    row = crud.get_or_create_state(db)
    return {
        "unlocked": logic.is_game_unlocked(row.target_date, row.study_time_total, row.target_value),
        "study_time_total": row.study_time_total,
        "target_value": row.target_value,
        "is_unlock_time": logic.is_unlock_time(),
    }


# ---------- ルーレット ----------
@app.post("/api/roulette/roll")
def roulette_roll(db: Session = Depends(get_db)):
    """ルーレットを回す（views/dashboard.py の roll_once 呼び出しと同じ）"""
    row = crud.get_or_create_state(db)
    settings = crud.get_all_settings(db)
    can_game = logic.is_game_unlocked(row.target_date, row.study_time_total, row.target_value)
    options = logic.roll_once(
        settings,
        last_was_refresh=row.last_was_refresh,
        force_study_only=row.force_study_only,
        mock_exam_done=row.mock_exam_done,
        can_game=can_game,
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
    is_mustdo = (body.category == "勉強"
                 and body.task in (settings.get("mustdo_list") or []))
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
    """■終了して記録する：合計に加算し、ふりかえりへ（views/active.py と同じ）"""
    row = crud.get_or_create_state(db)
    task = crud.state_to_dict(row).get("current_task")
    if not task:
        raise HTTPException(status_code=400, detail="実行中のタスクがありません")
    em = _elapsed_minutes(row)
    changes = {
        "pending_review": {"task": task["タスク"], "cat": task["カテゴリ"],
                           "em": em, "mustdo": task.get("mustdo", False)},
        "page": "review",
    }
    if task["カテゴリ"] == "勉強":
        changes["study_time_total"] = row.study_time_total + em
    else:
        changes["refresh_time_total"] = row.refresh_time_total + em
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
    settings = crud.get_all_settings(db)
    new_study_total = row.study_time_total + em
    can_game = logic.is_game_unlocked(row.target_date, new_study_total, row.target_value)
    options = logic.roll_once(settings, last_was_refresh=False,
                              force_study_only=True,
                              mock_exam_done=row.mock_exam_done,
                              can_game=can_game)
    row = crud.update_state(db, {
        "study_time_total": new_study_total,
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
        "study_time_total": row.study_time_total + em,
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
    crud.add_log(
        db, _now_str(), pr.get("cat", ""), pr.get("task", ""), "設定BGM",
        int(pr.get("em", 0)),
        done_text=(body.done_text if body.save_details else ""),
        progress=(body.progress if body.save_details else ""),
        focus=(body.focus if body.save_details else ""),
        satisfaction=(body.satisfaction if body.save_details else ""),
    )
    # 「終わった」と答えていたら『今日絶対やる』から自動削除
    if body.remove_mustdo and pr.get("task"):
        settings = crud.get_all_settings(db)
        ml = settings.get("mustdo_list") or []
        md = settings.get("mustdo_list_disabled") or []
        if pr["task"] in ml:
            ml.remove(pr["task"])
            crud.set_setting(db, "mustdo_list", ml)
        if pr["task"] in md:
            md.remove(pr["task"])
            crud.set_setting(db, "mustdo_list_disabled", md)
        # 【課題】項目なら、課題管理側も完了(100%)にする（再追加されないように）
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
    """全データリセット（app.py サイドバーの機能と同じ：履歴と今日の状態を初期化）"""
    crud.delete_all_logs(db)
    row = crud.update_state(db, {
        "study_time_total": 0, "refresh_time_total": 0,
        "page": "dashboard", "current_task": None, "start_time": None,
        "rolled_options": None, "pending_review": None,
        "target_locked": False,
    })
    return crud.state_to_dict(row)
