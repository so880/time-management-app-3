"""起動・停止・ポート・プロセスの共通部品（launcher / ensure_workers / stop_guard / diag / 小窓 / ワーカーが使う）。

ここに集めたもの（以前は各ファイルが別々の書き方で持っていて、判定がずれていた）:
- 場所（ROOT・venv・logs・DB）とワーカーの一覧
- ポート：本体（既定 8000）と画面（Vite。既定 5173）。使われていれば空いている番号を自分で選び、
  選んだ番号を backend/data/runtime.json に書く。他のプログラムはここを読んで接続先を知る
- プロセス：「Life_app のどのプロセスか」の判定と停止（他のアプリは決して止めない）
- 子プロセスの起動（窓を出さない）
- ワーカー用の DB 読み取り（読み取り専用）

標準ライブラリ＋psutil だけで書く（venv の python と、小窓を動かす python のどちらからも import できるように）。
"""
import json
import os
import socket
import sqlite3
import subprocess
import time
import urllib.request
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parent
BACKEND_DIR = ROOT / "backend"
FRONTEND_DIR = ROOT / "frontend"
VENV_PY = BACKEND_DIR / "venv" / "Scripts" / "python.exe"
VENV_PYW = BACKEND_DIR / "venv" / "Scripts" / "pythonw.exe"
LOGS = ROOT / "logs"
DATA_DIR = BACKEND_DIR / "data"
DB_FILE = DATA_DIR / "focus_cafe.db"
RUNTIME_FILE = DATA_DIR / "runtime.json"

APP_ID = "focus-cafe"                 # /api/health が返す名前（他のアプリの :8000 と区別する）
BACKEND_PORTS = range(8000, 8100)     # 8000 が使われていたら 8001… の空きを使う
FRONTEND_PORTS = range(5173, 5200)    # 5173 が使われていたら 5174… の空きを使う

# 制限・記録のワーカー（見守りタスクが1分ごとに起こし直す）
WORKERS = ("blocker.py", "site_blocker.py", "pc_tracker.py", "webcam_worker.py")
LOCK_WORKERS = ("blocker.py", "site_blocker.py")
WIDGET = "quick_widget.py"

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ======================= ログ =======================
def log(name: str, msg: str) -> None:
    """logs/<name> に1行追記する（失敗しても止まらない）"""
    try:
        LOGS.mkdir(parents=True, exist_ok=True)
        with open(LOGS / name, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except OSError:
        pass


# ======================= runtime.json（いま使っているポート） =======================
def read_runtime() -> dict:
    try:
        with open(RUNTIME_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_runtime(**changes) -> dict:
    """runtime.json を部分更新する（途中で落ちても壊れたファイルを残さない）"""
    data = read_runtime()
    data.update(changes)
    data["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = RUNTIME_FILE.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, RUNTIME_FILE)
    except OSError as e:
        log("launcher.log", f"runtime.json を書けません: {e}")
    return data


def backend_port() -> int:
    p = read_runtime().get("backend_port")
    return int(p) if isinstance(p, int) and p in BACKEND_PORTS else BACKEND_PORTS[0]


def frontend_port() -> int:
    p = read_runtime().get("frontend_port")
    return int(p) if isinstance(p, int) and p in FRONTEND_PORTS else FRONTEND_PORTS[0]


def backend_url() -> str:
    """本体の URL（小窓・ワーカー・ツールはここを使う。8000 を直接書かない）"""
    return f"http://127.0.0.1:{backend_port()}"


def frontend_url() -> str:
    """画面の URL（ブラウザで開く先）"""
    return f"http://localhost:{frontend_port()}"


# ======================= 本体の生存確認 =======================
def backend_alive(port: int | None = None, timeout: float = 2) -> bool:
    """その番号で「この Life_app の本体」が応答しているか（他のアプリの :8000 は False）"""
    port = port or backend_port()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=timeout) as r:
            return json.load(r).get("app") == APP_ID
    except Exception:
        return False


# ======================= ポート =======================
def listening_pids(port: int) -> set[int]:
    """その番号で待ち受けているプロセス（IPv4/IPv6 どちらも）"""
    out = set()
    try:
        for c in psutil.net_connections(kind="tcp"):
            if c.status == psutil.CONN_LISTEN and c.laddr and c.laddr.port == port:
                out.add(c.pid or 0)
    except Exception:
        pass
    return out


def port_free(port: int) -> bool:
    """だれも待ち受けておらず、実際に確保できる番号か"""
    if listening_pids(port):
        return False
    for family, addr in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as s:
                s.bind((addr, port))
        except OSError as e:
            if family == socket.AF_INET6 and getattr(e, "errno", None) in (10047, 10049, 97, 99):
                continue   # IPv6 が無い環境
            return False
    return True


def choose_port(ports: range, preferred: int | None = None) -> int:
    """preferred（前回の番号）→ 範囲の先頭から順に、空いている番号を返す"""
    cand = ([preferred] if preferred in ports else []) + [p for p in ports if p != preferred]
    for p in cand:
        if port_free(p):
            return p
    raise RuntimeError(f"空いているポートがありません（{ports.start}〜{ports.stop - 1}）")


# ======================= プロセスの判定 =======================
def _info(p):
    """(cmdline 小文字・区切りは \\, cwd 小文字)。読めなければ None"""
    try:
        cl = " ".join(p.cmdline()).lower().replace("/", "\\")
        try:
            cwd = (p.cwd() or "").lower().rstrip("\\")
        except (psutil.AccessDenied, OSError):
            cwd = ""
        return cl, cwd
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        return None


def _is_script(cl: str, cwd: str, script: str) -> bool:
    """コマンドラインが ROOT のその .py を動かしているか（"blocker.py" を site_blocker.py と取り違えない）"""
    full = str(ROOT / script).lower()
    if full in cl:
        return True
    # 相対パスで起動された古いもの（作業フォルダが ROOT）
    return cwd == str(ROOT).lower() and (f" {script.lower()}" in cl or f"\\{script.lower()}" in cl)


def _is_backend(cl: str, cwd: str) -> bool:
    """本体（fastapi / uvicorn と、その子プロセス）。作業フォルダが backend のものだけ"""
    return cwd == str(BACKEND_DIR).lower() and any(k in cl for k in ("fastapi", "uvicorn", "spawn_main"))


def _is_frontend(cl: str, cwd: str) -> bool:
    """画面（Vite：node と、それを起こした cmd / npm）。frontend フォルダのものだけ"""
    fe = str(FRONTEND_DIR).lower()
    return (cwd == fe or fe in cl) and any(k in cl for k in ("vite", "npm"))


def find(kind: str, name: str | None = None) -> list:
    """kind = "script"（name に .py）／"backend"／"frontend"。見つかったプロセスの一覧。
    自分自身と自分の親（venv の起動役）は含めない"""
    mine = _self_and_parents()
    out = []
    for p in psutil.process_iter():
        if p.pid in mine:
            continue
        inf = _info(p)
        if inf is None:
            continue
        cl, cwd = inf
        if kind == "script" and _is_script(cl, cwd, name):
            out.append(p)
        elif kind == "backend" and _is_backend(cl, cwd):
            out.append(p)
        elif kind == "frontend" and _is_frontend(cl, cwd):
            out.append(p)
    return out


def _self_and_parents() -> set[int]:
    out = {os.getpid()}
    try:
        for par in psutil.Process().parents():
            out.add(par.pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return out


def roots(procs: list) -> list:
    """venv の python.exe / pythonw.exe は「起動役」が同じコマンドラインの子を1つ作るので、
    親子で同じものは親だけを数える。古い順に並べる"""
    by_pid = {p.pid: p for p in procs}
    out = []
    for p in procs:
        try:
            par = by_pid.get(p.ppid())
            if par is not None and par.cmdline() == p.cmdline():
                continue
            out.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return sorted(out, key=lambda x: _ctime(x))


def _ctime(p) -> float:
    try:
        return p.create_time()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return 0.0


def running(script: str, user_session_only: bool = False) -> bool:
    """その .py が動いているか。user_session_only=True ならセッション0（SYSTEM 側）は数えない"""
    for p in roots(find("script", script)):
        if user_session_only and _session_id(p.pid) == 0:
            continue
        return True
    return False


def _session_id(pid: int) -> int | None:
    try:
        import ctypes
        sid = ctypes.c_ulong()
        if ctypes.windll.kernel32.ProcessIdToSessionId(pid, ctypes.byref(sid)):
            return sid.value
    except Exception:
        pass
    return None


def frontend_listening_port() -> int | None:
    """Life_app の Vite が実際に待ち受けている番号（無ければ None）"""
    pids = {p.pid for p in find("frontend")}
    if not pids:
        return None
    try:
        ports = {c.laddr.port for c in psutil.net_connections(kind="tcp")
                 if c.status == psutil.CONN_LISTEN and c.laddr and c.pid in pids}
    except Exception:
        return None
    return min(ports) if ports else None


# ======================= 停止 =======================
def terminate(procs: list, logname: str = "launcher.log", label: str = "") -> int:
    """子プロセスごと止め、消えるまで待つ（最大5秒。残れば強制終了）。止めた数を返す。
    管理者で起動されたものなど、止められないものはログに残す"""
    victims = {}
    for p in procs:
        try:
            for ch in p.children(recursive=True):
                victims[ch.pid] = ch
            victims[p.pid] = p
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            victims.setdefault(p.pid, p)
    victims.pop(os.getpid(), None)
    alive = []
    for p in victims.values():
        try:
            p.terminate()
            alive.append(p)
        except psutil.NoSuchProcess:
            pass
        except psutil.AccessDenied:
            log(logname, f"止められません（権限不足）: pid={p.pid} {label}")
    try:
        _gone, still = psutil.wait_procs(alive, timeout=5)
    except Exception:
        still = []
    for p in still:
        try:
            p.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            log(logname, f"止められません: pid={p.pid} {type(e).__name__} {label}")
    if alive:
        log(logname, f"停止 {label}: {len(alive)} プロセス")
    return len(alive)


def stop_scripts(scripts, logname: str = "launcher.log") -> None:
    procs = []
    for s in scripts:
        procs.extend(find("script", s))
    terminate(procs, logname, ",".join(scripts))


def stop_backend(logname: str = "launcher.log") -> None:
    terminate(find("backend"), logname, "本体")


def stop_frontend(logname: str = "launcher.log") -> None:
    terminate(find("frontend"), logname, "画面")


def dedupe(script: str, logname: str = "guard.log") -> None:
    """同じワーカーが2つ以上動いていたら、いちばん古いものだけ残す"""
    extra = roots(find("script", script))[1:]
    if extra:
        terminate(extra, logname, f"重複 {script}")


# ======================= 起動 =======================
def spawn(args, cwd=None, logfile: str | None = None, env: dict | None = None) -> subprocess.Popen:
    """窓を出さずに起こす。logfile があれば出力をそこへ（logs/ の下）。
    CREATE_NO_WINDOW だけを使う（DETACHED_PROCESS を付けると出力が残らず、uvicorn・Vite の
    Ctrl+C による停止も届かなくなる。2026-11-06 に確認）。起こした側が終わっても子は動き続ける"""
    out = None
    if logfile:
        LOGS.mkdir(parents=True, exist_ok=True)
        out = open(LOGS / logfile, "a", encoding="utf-8", errors="replace")
    e = dict(os.environ)
    e.setdefault("PYTHONUTF8", "1")         # 子の Python の出力を UTF-8 に（cp932 で絵文字が書けず落ちるのを防ぐ）
    e.setdefault("PYTHONIOENCODING", "utf-8")
    if env:
        e.update(env)
    try:
        return subprocess.Popen(args, cwd=str(cwd or ROOT), creationflags=NO_WINDOW, close_fds=True, env=e,
                                stdin=subprocess.DEVNULL, stdout=out,
                                stderr=subprocess.STDOUT if out else None)
    finally:
        if out is not None:
            out.close()   # 子が自分の複製を持っているので、こちらの分は閉じてよい


def start_script(script: str, logfile: str = "workers.log") -> None:
    """ROOT の .py を venv の pythonw で起こす（落ちたときの traceback は logfile に残る）"""
    spawn([str(VENV_PYW), str(ROOT / script)], logfile=logfile)


def widget_python() -> str:
    """小窓を動かす pythonw。venv に PySide6 があれば venv、無ければ PATH の pythonw"""
    if (BACKEND_DIR / "venv" / "Lib" / "site-packages" / "PySide6").is_dir():
        return str(VENV_PYW)
    return "pythonw"


# ======================= 二重起動の防止 =======================
def acquire_lock(name: str, wait_sec: float = 120):
    """logs/<name>.lock を OS のロック（msvcrt.locking）で押さえる。押さえられたらファイルを返す
    （プロセスが終われば OS が自動で外す）。wait_sec 待っても取れなければ None"""
    import msvcrt
    LOGS.mkdir(parents=True, exist_ok=True)
    f = open(LOGS / f"{name}.lock", "a+")
    deadline = time.time() + wait_sec
    while True:
        try:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            return f
        except OSError:
            if time.time() >= deadline:
                f.close()
                return None
            time.sleep(1)


# ======================= ワーカー用：DB の読み取り =======================
def read_settings(keys, timeout: float = 5) -> dict | None:
    """settings テーブルから keys の値を読む（読み取り専用）。読めなければ None。
    ワーカーは None のとき「前回読めた値」を使い、一度も読めていなければ制限する（安全側）"""
    try:
        con = sqlite3.connect(f"file:{DB_FILE.as_posix()}?mode=ro", uri=True, timeout=timeout)
        try:
            marks = ",".join("?" for _ in keys)
            rows = con.execute(f"SELECT key, value FROM settings WHERE key IN ({marks})", list(keys)).fetchall()
        finally:
            con.close()
        out = {}
        for k, v in rows:
            try:
                out[k] = json.loads(v)
            except (TypeError, ValueError):
                out[k] = None
        return out
    except Exception:
        return None
