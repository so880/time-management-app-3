"""💼 面接などの特例（Claude 審査版。2026-11-03 依頼者の指示）

目的：面接・面談・選考などの「本当に必要な用事」のときだけ、Gemini に頼らずに制限を止められる手段。
ただし本人の一存では通らない（事前登録＋Claude の審査）。

流れ
  1. 申請（制限タブ）：開始の MIN_LEAD_HOURS（24）時間以上前に、日付・開始/終了・会社名・種類・根拠を登録
     → exemption_requests テーブルに status="pending" で保存し、logs/exemption_requests.json に書き出す（Claude が読む）
  2. 審査（Claude）：Claude（このチャット or 定期タスク）が logs/exemption_requests.json を読み、
     docs/EXEMPTION_REVIEW.md の基準で判断して logs/claude_exemptions.json に承認／却下を書く
  3. 反映：本体は claude_exemptions.json の決定だけを有効にする。承認された申請は
     その時間帯（前後 MARGIN_MIN 分）に gate_api.exemption_windows → 全制限解除・HabitLock なし・カメラ停止
  4. 制限：1件 MAX_MINUTES（180）分まで、承認は週 WEEK_CAP（3）件まで（超えた分は無効）。全件を記録

抜け道にならないために
  - 申請は24時間以上前のものだけ（当日の思いつきは不可）。作成日時は本体が付ける
  - 承認の権限はファイル（claude_exemptions.json）にあり、画面からは承認できない
  - 週3件・1件3時間の上限は本体側でも数える（Claude が間違えても超えない）
  - 管理者権限でファイルを直接書く抜け道は、DB を直接書く抜け道と同じ扱い（依頼者了承の範囲）
"""
import json
import uuid
from datetime import date as date_cls, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models, policy
from .database import get_db

router = APIRouter()

ROOT = Path(__file__).resolve().parents[2]
LOGS = ROOT / "logs"
REQ_FILE = LOGS / "exemption_requests.json"     # 本体が書く（Claude が読む）
DEC_FILE = LOGS / "claude_exemptions.json"      # Claude が書く（本体が読む）
UNLOCK_LOG = LOGS / "emergency_unlock.log"

# 種類・事前登録の時間・前後の余白は Google カレンダーの特例と共通（policy.py）
KINDS = policy.EXEMPT_KINDS
MIN_LEAD_HOURS = policy.EXEMPT_MIN_LEAD_HOURS   # 申請は開始の24時間以上前
MAX_MINUTES = policy.EXEMPT_MAX_MINUTES       # 1件の長さ（前後の余白は別）
MARGIN_MIN = policy.EXEMPT_MARGIN_MIN           # 前後の余白（準備・移動）
WEEK_CAP = policy.EXEMPT_WEEK_CAP             # 承認は週3件まで（月曜はじまり）
MIN_COMPANY = 2
MIN_EVIDENCE = 5
KEEP_DAYS = 60           # 履歴を残す日数

CRITERIA = (
    "承認するのは『実在の企業・団体の、具体的な選考（面接・面談・説明会・試験など）で、"
    "日時が確定していて、根拠（案内メールの件名・予約ページ・担当者名など）がある』申請だけ。"
    "『準備したい』『勉強のため』『気分転換』『念のため』は却下。会社名が曖昧（A社・某社）も却下。"
    f"1件 {MAX_MINUTES} 分以内、週 {WEEK_CAP} 件以内。迷ったら却下し、理由を書く。"
)


def _log(line: str) -> None:
    try:
        LOGS.mkdir(parents=True, exist_ok=True)
        with open(UNLOCK_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [exemption] {line}\n")
    except OSError:
        pass


def _norm_hm(v: str) -> str:
    hm = policy.norm_hm(v)
    if hm is None:
        raise HTTPException(status_code=400, detail="時刻は 00:00〜23:59 の HH:MM で入力してください")
    return hm


def _to_dict(r: models.ExemptionRequest) -> dict:
    """画面・決定ファイルに出す形"""
    return {"id": r.id, "created": r.created, "date": r.date, "start": r.start, "end": r.end,
            "minutes": r.minutes, "company": r.company, "kind": r.kind, "evidence": r.evidence,
            "status": r.status, "over_cap": bool(r.over_cap),
            "decision": ({"reason": r.decision_reason, "at": r.decision_at, "by": r.decision_by}
                         if r.status in ("approved", "rejected") else None)}


def _rows(db: Session) -> list[models.ExemptionRequest]:
    """保持期間（KEEP_DAYS）より古い申請は消してから、作成順に返す"""
    limit = (date_cls.today() - timedelta(days=KEEP_DAYS)).isoformat()
    for r in db.execute(select(models.ExemptionRequest)
                        .where(models.ExemptionRequest.date < limit)).scalars().all():
        db.delete(r)
    return list(db.execute(select(models.ExemptionRequest)
                           .order_by(models.ExemptionRequest.created)).scalars().all())


def load_decisions() -> dict[str, dict]:
    """Claude が書いた決定ファイル。壊れていれば空（＝承認なし）"""
    try:
        data = json.loads(DEC_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for d in data.get("decisions", []) if isinstance(data, dict) else []:
        if isinstance(d, dict) and d.get("request_id"):
            out[str(d["request_id"])] = d
    return out


def write_requests_file(reqs: list[dict]) -> None:
    """Claude が読む用（審査待ちを先頭に、直近のものだけ）"""
    try:
        LOGS.mkdir(parents=True, exist_ok=True)
        pending = [r for r in reqs if r.get("status") == "pending"]
        others = [r for r in reqs if r.get("status") != "pending"][-20:]
        REQ_FILE.write_text(json.dumps({
            "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "how_to_decide": CRITERIA,
            "decision_file": str(DEC_FILE),
            "decision_format": {"decisions": [{"request_id": "<id>", "approved": True, "reason": "<理由>",
                                               "at": "YYYY-MM-DD HH:MM", "by": "claude"}]},
            "pending": pending, "recent": others,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def _week_key(day: str) -> str:
    d = datetime.strptime(day, "%Y-%m-%d").date()
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def merged_requests(db: Session) -> list[dict]:
    """申請に Claude の決定を反映した一覧（反映したら保存し、記録に残す）"""
    rows = _rows(db)
    decs = load_decisions()
    changed = False
    for r in rows:
        d = decs.get(str(r.id))
        if d is None or r.status == "cancelled":
            continue
        new_status = "approved" if d.get("approved") else "rejected"
        reason = str(d.get("reason") or "")[:300]
        if r.status != new_status or r.decision_reason != reason:
            r.status, r.decision_reason = new_status, reason
            r.decision_at, r.decision_by = str(d.get("at") or ""), str(d.get("by") or "claude")
            changed = True
            _log(f"{new_status}: {r.date} {r.start}-{r.end} {r.company} {r.kind} id={r.id} / {reason}")
    # 週の上限：承認済みを作成順に数え、WEEK_CAP 件目までだけ有効（over_cap=True は無効）
    per_week: dict[str, int] = {}
    for r in rows:
        over = False
        if r.status == "approved":
            wk = _week_key(r.date)
            per_week[wk] = per_week.get(wk, 0) + 1
            over = per_week[wk] > WEEK_CAP
        if bool(r.over_cap) != over:
            r.over_cap = over
            changed = True
    out = [_to_dict(r) for r in rows]
    if changed or db.dirty or db.deleted:
        db.commit()
        write_requests_file(out)
    return out


def approved_windows(db: Session, day: str) -> list[dict]:
    """その日に有効な特例（Claude 承認済み・週上限内）。前後 MARGIN_MIN 分を含めた時間帯。
    有効かどうかは **いまの決定ファイル** で決める（表の status は履歴用。表だけ書き換えても効かない）"""
    out = []
    decs = load_decisions()
    for r in merged_requests(db):
        if r.get("status") != "approved" or r.get("over_cap") or r.get("date") != day:
            continue
        d = decs.get(str(r.get("id")))
        if not d or not d.get("approved"):
            continue
        try:
            created = datetime.strptime(str(r.get("created"))[:16], "%Y-%m-%d %H:%M")
            start_dt = datetime.strptime(f"{day} {r['start']}", "%Y-%m-%d %H:%M")
        except (ValueError, KeyError):
            continue
        if (start_dt - created).total_seconds() < MIN_LEAD_HOURS * 3600:
            continue   # 念のため（作成時にも弾いている）
        out.append({"title": f"{r.get('company', '')} {r.get('kind', '')}".strip(),
                    "start": policy.shift_clamped(day, r["start"], -MARGIN_MIN),
                    "end": policy.shift_clamped(day, r["end"], MARGIN_MIN),
                    "source": "claude", "id": r.get("id")})
    return out


class RequestBody(BaseModel):
    date: str          # "YYYY-MM-DD"
    start: str         # "HH:MM"
    end: str
    company: str       # 会社・団体名
    kind: str          # KINDS のどれか
    evidence: str      # 根拠（案内メールの件名・予約ページ・担当者など）


def create_request(db: Session, body: RequestBody, now: datetime | None = None) -> dict:
    now = now or datetime.now()
    try:
        d = datetime.strptime(body.date.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="日付は YYYY-MM-DD で入力してください")
    start, end = _norm_hm(body.start), _norm_hm(body.end)
    if start >= end:
        raise HTTPException(status_code=400, detail="終了時刻は開始時刻より後にしてください")
    sh, sm = [int(x) for x in start.split(":")]
    eh, em = [int(x) for x in end.split(":")]
    minutes = (eh * 60 + em) - (sh * 60 + sm)
    if minutes > MAX_MINUTES:
        raise HTTPException(status_code=400, detail=f"1件は {MAX_MINUTES} 分以内にしてください（前後{MARGIN_MIN}分は自動で付きます）")
    start_dt = datetime.combine(d, datetime.strptime(start, "%H:%M").time())
    if (start_dt - now).total_seconds() < MIN_LEAD_HOURS * 3600:
        raise HTTPException(status_code=400,
                            detail=f"特例の申請は開始の {MIN_LEAD_HOURS} 時間以上前に行ってください（当日の分は解除申請＝AI審査へ）")
    company = (body.company or "").strip()
    kind = (body.kind or "").strip()
    evidence = (body.evidence or "").strip()
    if len(company) < MIN_COMPANY:
        raise HTTPException(status_code=400, detail="会社・団体名を入力してください")
    if kind not in KINDS:
        raise HTTPException(status_code=400, detail="種類は " + "／".join(KINDS) + " から選んでください")
    if len(evidence) < MIN_EVIDENCE:
        raise HTTPException(status_code=400, detail="根拠（案内メールの件名・予約ページ・担当者名など）を書いてください")
    dup = db.execute(select(models.ExemptionRequest).where(
        models.ExemptionRequest.date == d.isoformat(), models.ExemptionRequest.start == start,
        models.ExemptionRequest.status.in_(("pending", "approved")))).scalars().first()
    if dup is not None:
        raise HTTPException(status_code=400, detail="同じ日時の申請がすでにあります")
    row = models.ExemptionRequest(id=uuid.uuid4().hex[:8], created=now.strftime("%Y-%m-%d %H:%M:%S"),
                                  date=d.isoformat(), start=start, end=end, minutes=minutes,
                                  company=company[:60], kind=kind, evidence=evidence[:300], status="pending")
    db.add(row)
    db.commit()
    write_requests_file([_to_dict(r) for r in _rows(db)])
    _log(f"requested: {row.date} {start}-{end} {company} {kind} id={row.id} / {evidence[:80]}")
    return _to_dict(row)


@router.get("/api/gate/exemptions")
def list_exemptions(db: Session = Depends(get_db)):
    """制限タブ用：申請一覧（新しい順）・今日の有効な特例・ルール"""
    reqs = merged_requests(db)
    today = date_cls.today().isoformat()
    return {"requests": sorted(reqs, key=lambda r: (r.get("date", ""), r.get("start", "")), reverse=True),
            "today": approved_windows(db, today),
            "rules": {"min_lead_hours": MIN_LEAD_HOURS, "max_minutes": MAX_MINUTES, "margin_min": MARGIN_MIN,
                      "week_cap": WEEK_CAP, "kinds": list(KINDS), "criteria": CRITERIA,
                      "decision_file": str(DEC_FILE), "request_file": str(REQ_FILE)}}


@router.post("/api/gate/exemption_request")
def post_request(body: RequestBody, db: Session = Depends(get_db)):
    return create_request(db, body)


@router.post("/api/gate/exemption_request/{req_id}/cancel")
def cancel_request(req_id: str, db: Session = Depends(get_db)):
    """申請の取り下げ（特例を使わない方向なのでいつでも可）"""
    hit = db.get(models.ExemptionRequest, req_id)
    if hit is None:
        raise HTTPException(status_code=404, detail="その申請が見つかりません")
    hit.status = "cancelled"
    db.commit()
    write_requests_file([_to_dict(r) for r in _rows(db)])
    _log(f"cancelled: id={req_id}")
    return {"ok": True}
