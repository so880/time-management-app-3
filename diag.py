"""診断：Life_app のプロセス・ポート・本体の応答・見守りタスク・各ログの末尾を logs/diag_out.txt に書く。
pythonw で動かしても窓は出ない。diag.bat はこれを呼ぶだけ。判定は appctl.py（launcher と共通）。"""
import subprocess
import sys
import time
import traceback

import appctl

appctl.LOGS.mkdir(parents=True, exist_ok=True)
OUT = open(appctl.LOGS / "diag_out.txt", "w", encoding="utf-8")


def emit(line: str) -> None:
    """1行ずつ書いて flush（途中で止まっても、どこまで進んだか分かるように）"""
    OUT.write(line + "\n")
    OUT.flush()


def run(args) -> str:
    try:
        r = subprocess.run(args, capture_output=True, stdin=subprocess.DEVNULL,
                           creationflags=appctl.NO_WINDOW, timeout=30)
        out = r.stdout or b""
        for enc in ("utf-8", "cp932"):
            try:
                return out.decode(enc)
            except UnicodeDecodeError:
                continue
        return out.decode("utf-8", "replace")
    except Exception as e:
        return f"(failed: {type(e).__name__}: {e})"


def tail(name: str, n: int = 20) -> str:
    p = appctl.LOGS / name
    if not p.exists():
        return "(none)"
    try:
        return "\n".join(p.read_text(encoding="utf-8", errors="replace").splitlines()[-n:])
    except OSError as e:
        return f"(failed: {e})"


def describe(p) -> str:
    try:
        return (f"{p.pid:<7} {p.name():<14} {time.strftime('%H:%M:%S', time.localtime(p.create_time()))} "
                f"| {' '.join(p.cmdline())[:160]}")
    except Exception as e:
        return f"{p.pid} ({type(e).__name__})"


def main() -> None:
    emit(f"===== {time.strftime('%Y-%m-%d %H:%M:%S')} ===== python={sys.executable}")
    emit("--- runtime.json ---")
    emit(str(appctl.read_runtime()))
    emit("--- processes ---")
    for s in appctl.WORKERS + (appctl.WIDGET, "launcher.py", "ensure_workers.py"):
        procs = appctl.find("script", s)
        emit(f"[{s}] {len(appctl.roots(procs))} 個")
        for p in procs:
            emit("  " + describe(p))
    for kind in ("backend", "frontend"):
        procs = appctl.find(kind)
        emit(f"[{kind}] {len(procs)} プロセス")
        for p in procs:
            emit("  " + describe(p))
    emit("--- ports ---")
    for port in (appctl.backend_port(), appctl.frontend_port()):
        pids = appctl.listening_pids(port)
        emit(f"port {port}: {sorted(pids) or '待ち受けなし'}")
    for rng in (appctl.BACKEND_PORTS, appctl.FRONTEND_PORTS):
        used = [p for p in rng if appctl.listening_pids(p)]
        emit(f"{rng.start}〜{rng.stop - 1} で使用中: {used}")
    emit("--- backend ---")
    emit(f"{appctl.backend_url()} 応答: {appctl.backend_alive()}")
    emit(f"画面: {appctl.frontend_url()}（Vite の実際の番号: {appctl.frontend_listening_port()}）")
    emit("--- tasks ---")
    for name in ("FocusCafe Guard", "FocusCafe Guard Logon", "FocusCafe SiteBlocker"):
        t = run(["schtasks", "/Query", "/TN", name, "/V", "/FO", "LIST"])
        keep = [ln for ln in t.splitlines() if any(k in ln for k in
                ("タスク名", "TaskName", "実行するタスク", "Task To Run", "前回の実行時刻", "Last Run Time",
                 "前回の結果", "Last Result", "状態", "Status", "ユーザーとして実行", "Run As User", "ERROR", "エラー"))]
        emit(f"[{name}]\n" + ("\n".join(keep) if keep else t.strip()[:200]))
    for name in ("launcher.log", "workers.log", "widget.log", "backend.log", "frontend.log", "guard.log"):
        emit(f"--- {name} tail ---")
        emit(tail(name))
    emit("===== done =====")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        emit("diag failed:\n" + traceback.format_exc())
    finally:
        OUT.close()
