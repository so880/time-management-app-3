"""小窓の ping / start の受け口（schemas.WidgetPing / WidgetStart）が、小窓・画面が送る形のまま受け付けるか。
計測中（running=True）は DB に記録するので、ここでは DB に触れない「計測していない」場合だけ確かめる。
start はタスクが空の場合だけ（タスクがあると小窓を起動してしまうため）"""
import pytest
from fastapi.testclient import TestClient

from app import main


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(main, "_WIDGET_STATE",
                        {"last_ping": 0.0, "running": False, "task": "", "elapsed_sec": 0})
    monkeypatch.setattr(main, "_WIDGET_COMMAND", {"start": "", "stop": False, "at": 0.0})
    # lifespan（起動時の処理）は動かさない：with を使わずに作る
    return TestClient(main.app, base_url="http://localhost")


def test_ping_without_body(client):
    r = client.post("/api/widget/ping")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert main._WIDGET_STATE["running"] is False
    assert main._WIDGET_STATE["last_ping"] > 0


def test_ping_widget_payload_ignores_unknown_keys(client):
    # quick_widget.py の _ping が計測していないときに送る形
    r = client.post("/api/widget/ping", json={"alive": True, "running": False})
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_ping_clamps_elapsed(client):
    client.post("/api/widget/ping", json={"running": False, "task": "x", "elapsed_sec": -5})
    assert main._WIDGET_STATE["elapsed_sec"] == 0
    client.post("/api/widget/ping", json={"running": False, "elapsed_sec": 10 ** 9})
    assert main._WIDGET_STATE["elapsed_sec"] == main.MAX_LOG_MINUTES * 60


def test_ping_returns_start_command(client):
    main._WIDGET_COMMAND.update({"start": "SPI", "at": main.time.time()})
    r = client.post("/api/widget/ping", json={"alive": True, "running": False})
    assert r.json() == {"ok": True, "start": "SPI"}
    assert main._WIDGET_COMMAND["start"] == ""


@pytest.mark.parametrize("kwargs", [{}, {"json": {}}, {"json": {"task": "  "}}])
def test_start_requires_task(client, kwargs):
    r = client.post("/api/widget/start", **kwargs)
    assert r.status_code == 400
    assert r.json()["detail"] == "task を指定してください"
