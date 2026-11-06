"""💼 面接などの特例（Claude 審査版）のテスト。決定ファイルは一時フォルダ。実データに触れない"""
import json
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import crud, exemption_api, gate_api, models


@pytest.fixture()
def db(tmp_path, monkeypatch):
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    crud.set_setting(s, "todo_v1_migrated", True)
    s.commit()
    monkeypatch.setattr(exemption_api, "LOGS", tmp_path)
    monkeypatch.setattr(exemption_api, "REQ_FILE", tmp_path / "exemption_requests.json")
    monkeypatch.setattr(exemption_api, "DEC_FILE", tmp_path / "claude_exemptions.json")
    monkeypatch.setattr(exemption_api, "UNLOCK_LOG", tmp_path / "emergency_unlock.log")
    yield s
    s.close()


def _body(**kw):
    base = {"date": "2026-11-10", "start": "14:00", "end": "15:00", "company": "テスト株式会社",
            "kind": "面接", "evidence": "案内メール『二次面接のご案内』11/5 受信"}
    base.update(kw)
    return exemption_api.RequestBody(**base)


NOW = datetime(2026, 11, 5, 10, 0)


def _decide(tmp_path, *items):
    (tmp_path / "claude_exemptions.json").write_text(json.dumps({"decisions": list(items)}, ensure_ascii=False),
                                                    encoding="utf-8")


def test_request_validation(db):
    with pytest.raises(HTTPException) as e:
        exemption_api.create_request(db, _body(date="2026-11-05", start="20:00", end="21:00"), NOW)
    assert "24 時間" in e.value.detail
    with pytest.raises(HTTPException):
        exemption_api.create_request(db, _body(end="18:00"), NOW)        # 240分 > 180分
    with pytest.raises(HTTPException):
        exemption_api.create_request(db, _body(company="A"), NOW)        # 会社名が短い
    with pytest.raises(HTTPException):
        exemption_api.create_request(db, _body(kind="遊び"), NOW)
    with pytest.raises(HTTPException):
        exemption_api.create_request(db, _body(evidence="なし"), NOW)
    r = exemption_api.create_request(db, _body(), NOW)
    assert r["status"] == "pending" and len(r["id"]) == 8
    with pytest.raises(HTTPException):
        exemption_api.create_request(db, _body(), NOW)                   # 同じ日時は二重に出せない
    # Claude が読むファイルができている
    data = json.loads(exemption_api.REQ_FILE.read_text(encoding="utf-8"))
    assert data["pending"][0]["id"] == r["id"] and "how_to_decide" in data


def test_pending_is_not_exempt_and_claude_approval_opens_window(db, tmp_path):
    r = exemption_api.create_request(db, _body(), NOW)
    assert exemption_api.approved_windows(db, "2026-11-10") == []
    assert gate_api.exemption_windows(db, "2026-11-10") == [] or all(w.get("source") != "claude" for w in gate_api.exemption_windows(db, "2026-11-10"))
    # 画面からは承認できない（settings を直接 approved にしても決定ファイルが無ければ…）：決定はファイルが正
    _decide(tmp_path, {"request_id": r["id"], "approved": True, "reason": "案内メールあり・実在企業", "at": "2026-11-05 21:00", "by": "claude"})
    wins = exemption_api.approved_windows(db, "2026-11-10")
    assert wins and wins[0]["start"] == "13:00" and wins[0]["end"] == "16:00"   # 前後60分
    assert any(w["start"] == "13:00" and w["end"] == "16:00" for w in gate_api.exemption_windows(db, "2026-11-10"))
    assert gate_api.current_exemption(db, datetime(2026, 11, 10, 13, 30)) is not None
    assert gate_api.current_exemption(db, datetime(2026, 11, 10, 16, 30)) is None
    # 記録に残る
    assert "approved" in exemption_api.UNLOCK_LOG.read_text(encoding="utf-8")
    # 却下に変わればすぐ無効
    _decide(tmp_path, {"request_id": r["id"], "approved": False, "reason": "根拠が不十分", "at": "2026-11-05 22:00"})
    assert exemption_api.approved_windows(db, "2026-11-10") == []
    st = [x for x in exemption_api.merged_requests(db) if x["id"] == r["id"]][0]
    assert st["status"] == "rejected" and st["decision"]["reason"] == "根拠が不十分"


def test_week_cap_and_broken_decision_file(db, tmp_path):
    ids = []
    for i, d in enumerate(["2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12"]):
        r = exemption_api.create_request(db, _body(date=d, company=f"会社{i}"), NOW + timedelta(minutes=i))
        ids.append(r["id"])
    _decide(tmp_path, *[{"request_id": i, "approved": True, "reason": "ok", "at": "2026-11-05 21:00"} for i in ids])
    # 同じ週の4件目は無効
    assert exemption_api.approved_windows(db, "2026-11-11") != []
    assert exemption_api.approved_windows(db, "2026-11-12") == []
    # 決定ファイルが壊れていれば承認なし（制限は外れない方向）
    (tmp_path / "claude_exemptions.json").write_text("{broken", encoding="utf-8")
    assert exemption_api.load_decisions() == {}
    assert exemption_api.approved_windows(db, "2026-11-11") == []
    assert gate_api.exemption_windows(db, "2026-11-11") == []


def test_cancel(db, tmp_path):
    r = exemption_api.create_request(db, _body(), NOW)
    _decide(tmp_path, {"request_id": r["id"], "approved": True, "reason": "ok", "at": "x"})
    assert exemption_api.approved_windows(db, "2026-11-10")
    exemption_api.cancel_request(r["id"], db)
    assert exemption_api.approved_windows(db, "2026-11-10") == []


def test_table_status_alone_does_not_approve(db):
    # 表の status を approved に書き換えても、Claude の決定ファイルに無ければ特例にならない
    r = exemption_api.create_request(db, _body(), NOW)
    row = db.get(models.ExemptionRequest, r["id"])
    row.status = "approved"
    db.commit()
    assert exemption_api.approved_windows(db, "2026-11-10") == []
