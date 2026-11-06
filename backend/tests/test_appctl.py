r"""起動・停止の共通部品（C:\Life_app\appctl.py）のテスト：ポートの選び方・runtime.json・プロセスの見分け方"""
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import appctl  # noqa: E402


def _listen(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", port))
    s.listen(1)
    return s


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_choose_port_skips_used_one():
    base = _free_port()
    rng = range(base, base + 5)
    held = _listen(base)          # 他のアプリが base を使っている
    try:
        assert appctl.choose_port(rng, preferred=base) != base
        assert appctl.choose_port(rng, preferred=base) in rng
    finally:
        held.close()
    assert appctl.choose_port(rng, preferred=base) == base   # 空いたら先頭を使う


def test_runtime_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(appctl, "RUNTIME_FILE", tmp_path / "runtime.json")
    monkeypatch.setattr(appctl, "DATA_DIR", tmp_path)
    assert appctl.backend_url() == "http://127.0.0.1:8000"          # 未記録なら既定
    appctl.write_runtime(backend_port=8003, frontend_port=5175)
    assert appctl.backend_url() == "http://127.0.0.1:8003"
    assert appctl.frontend_url() == "http://localhost:5175"
    appctl.write_runtime(backend_port=1)                              # 範囲外の値は使わない
    assert appctl.backend_port() == 8000


def test_backend_alive_rejects_other_app():
    held = _listen(_free_port())   # 何も返さない別のプログラム
    try:
        assert appctl.backend_alive(held.getsockname()[1], timeout=0.5) is False
    finally:
        held.close()


def test_script_matching_is_exact():
    root = str(appctl.ROOT).lower()
    cl = rf"c:\venv\pythonw.exe {root}\site_blocker.py"
    assert appctl._is_script(cl, "", "site_blocker.py") is True
    assert appctl._is_script(cl, "", "blocker.py") is False          # site_blocker を blocker と取り違えない
    other = r"c:\other_app\blocker.py"
    assert appctl._is_script(other, r"c:\other_app", "blocker.py") is False


def test_backend_and_frontend_matching_only_ours():
    be = str(appctl.BACKEND_DIR).lower()
    fe = str(appctl.FRONTEND_DIR).lower()
    assert appctl._is_backend("python.exe -m fastapi run app/main.py", be) is True
    assert appctl._is_backend("python.exe -m pytest", be) is False   # テストの実行は止めない
    assert appctl._is_backend("python.exe -m fastapi run app/main.py", r"c:\financeapp\backend") is False
    assert appctl._is_frontend("node vite.js --port 5173", fe) is True
    assert appctl._is_frontend(r"node c:\financeapp\frontend\node_modules\vite\bin\vite.js",
                               r"c:\financeapp\frontend") is False  # 他のアプリの Vite は止めない
