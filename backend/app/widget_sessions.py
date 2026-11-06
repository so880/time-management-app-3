"""小窓（quick_widget）の計測を、本体が自分の時計で確かめるための記録（2026-11-06）。

小窓は計測中に20秒ごとに ping を送ってくる。本体は「ping が続いていた区間」を自分の時計で記録しておき、
小窓から届いた勉強の記録（POST /api/logs）は、その区間の長さまでしか受け付けない。
→ curl などで「600分やった」と1回送るだけで勉強目標・習慣を満たす抜け道を防ぐ
  （偽装するには、実際の時間ずっと ping を送り続ける必要がある）。

- 区間：ping が GAP_SEC 以上途切れたら別の区間にする
- 小窓の再起動（restart_all など）で途切れても、CHAIN_GAP_SEC 以内なら同じ計測の続きとして合計する
- 一度使った区間は「使用済み」にして、同じ時間を二度記録させない
- 本体の再起動で消えないよう settings["widget_sessions"] に保存する（SAVE_EVERY_SEC ごと・区間の始まり・使用時）
"""
import threading
import time

from sqlalchemy.orm import Session

from . import crud

SETTING_KEY = "widget_sessions"
GAP_SEC = 60            # ping（20秒ごと）がこれ以上途切れたら別の区間
CHAIN_GAP_SEC = 10 * 60  # 小窓の再起動による途切れはこれ以内なら続き（quick_widget.RESUME_LIMIT_SEC と同じ）
GRACE_SEC = 120         # 最後の ping から記録が届くまでの差・保存の間隔のぶんの余裕
KEEP = 30               # 保存しておく区間の数
SAVE_EVERY_SEC = 60

_lock = threading.Lock()
_cache: dict = {"loaded": False, "sessions": [], "saved_at": 0.0}


def _load(db: Session) -> list[dict]:
    if not _cache["loaded"]:
        raw = crud.get_all_settings(db).get(SETTING_KEY) or []
        _cache["sessions"] = [s for s in raw if isinstance(s, dict) and "start" in s and "last" in s] \
            if isinstance(raw, list) else []
        _cache["loaded"] = True
    return _cache["sessions"]


def _save(db: Session, now: float) -> None:
    crud.set_setting(db, SETTING_KEY, _cache["sessions"][-KEEP:])
    db.commit()
    _cache["saved_at"] = now


def reset_cache() -> None:
    """テスト用：メモリの記録を捨てる（次に DB から読み直す）"""
    _cache.update({"loaded": False, "sessions": [], "saved_at": 0.0})


def observe(db: Session, task: str, now: float | None = None) -> None:
    """計測中の ping を受け取ったときに呼ぶ。今の区間を延ばすか、新しい区間を始める"""
    now = time.time() if now is None else now
    with _lock:
        sessions = _load(db)
        last = sessions[-1] if sessions else None
        if last and not last.get("used") and 0 <= now - float(last["last"]) <= GAP_SEC:
            last["last"] = now
            last["task"] = task
            if now - _cache["saved_at"] >= SAVE_EVERY_SEC:
                _save(db, now)
            return
        sessions.append({"start": now, "last": now, "task": task, "used": False})
        del sessions[:-KEEP]
        _save(db, now)


def _chain(sessions: list[dict], end_ts: float) -> list[int]:
    """end_ts に終わった計測にあたる区間（未使用）の番号。直前の区間から、途切れが短いものをさかのぼる"""
    idx = None
    for i in range(len(sessions) - 1, -1, -1):
        s = sessions[i]
        if s.get("used"):
            continue
        if float(s["start"]) <= end_ts + GRACE_SEC and float(s["last"]) >= end_ts - GRACE_SEC:
            idx = i
            break
    if idx is None:
        return []
    out = [idx]
    for i in range(idx - 1, -1, -1):
        s, nxt = sessions[i], sessions[out[-1]]
        if s.get("used") or float(nxt["start"]) - float(s["last"]) > CHAIN_GAP_SEC:
            break
        out.append(i)
    return out


def observed_seconds(db: Session, now: float | None = None) -> int:
    """いま計測中の計測について、本体が確かめられた秒数（使用済みにはしない）"""
    now = time.time() if now is None else now
    with _lock:
        sessions = _load(db)
        return int(sum(float(sessions[i]["last"]) - float(sessions[i]["start"]) for i in _chain(sessions, now)))


def claim_minutes(db: Session, end_ts: float) -> int:
    """end_ts に終わった計測について、記録してよい分数を返し、その区間を使用済みにする"""
    with _lock:
        sessions = _load(db)
        ids = _chain(sessions, end_ts)
        if not ids:
            return 0
        sec = sum(float(sessions[i]["last"]) - float(sessions[i]["start"]) for i in ids)
        for i in ids:
            sessions[i]["used"] = True
        _save(db, time.time())
        return int((sec + GRACE_SEC) // 60)
