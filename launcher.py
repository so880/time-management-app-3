"""窓を出さない起動役（start_all.bat / restart_all.bat / 見守りタスクから呼ばれる）。

使い方:
  pythonw launcher.py          … 全部起動し、準備ができたらブラウザを開く（start_all.bat）
  pythonw launcher.py auto     … 全部起動するがブラウザは開かない（見守りタスク・ログオン時用）
  pythonw launcher.py widget   … 小窓だけ起こす
  pythonw launcher.py backend  … 本体だけ起動し直す（本体の .py を変えたあと。画面・小窓・ワーカーはそのまま）
  pythonw launcher.py restart  … 全部止めて最新のコードで起動し直す（restart_all.bat。ブラウザは開かない）

起動するもの（すべてウィンドウなし。出力は logs/ に書く）:
  - 制限・記録ワーカー blocker.py / site_blocker.py / pc_tracker.py / webcam_worker.py（venv の pythonw）
  - 小窓 quick_widget.py（計測中の状態はファイルに残るので、restart で止めても続きから再開する）
  - 本体   python -m fastapi run（自動再読み込みなし・127.0.0.1 のみ） → logs/backend.log
  - 画面   npm run dev（Vite。本体へは Vite の proxy で中継）            → logs/frontend.log
  - 見守りタスク「FocusCafe Guard」が無ければ登録

ポート：本体は 8000、画面は 5173 を使う。他のアプリが使っていれば空いている番号を自分で選び、
backend/data/runtime.json に書く（小窓・ワーカー・ブラウザはそこから接続先を知る。appctl.py）。

本体を `fastapi dev`（自動再読み込み）で動かさない理由（2026-11-06）：Windows では再読み込みのとき
古いプロセスに Ctrl+C を送って止めるが、窓のない起動では届かず、古いコードのまま居座っていた。
本体のコードを変えたら `launcher.py backend`（または restart_all.bat）で起動し直す。
"""
import subprocess
import sys
import time
import traceback

import appctl

LOGNAME = "launcher.log"


def log(msg: str) -> None:
    appctl.log(LOGNAME, msg)


# ======================= 各部品 =======================
def ensure_workers(restart: bool = False) -> None:
    """ワーカーを起こす。restart=True なら止めてから最新のコードで起こし直す"""
    if restart:
        appctl.stop_scripts(appctl.WORKERS, LOGNAME)
    for s in appctl.WORKERS:
        appctl.dedupe(s, LOGNAME)
        if not appctl.running(s):
            appctl.start_script(s)


def ensure_widget(restart: bool = False) -> None:
    if restart:
        appctl.stop_scripts((appctl.WIDGET,), LOGNAME)   # 計測中でも状態ファイルから続きを再開する
    if not appctl.running(appctl.WIDGET):
        appctl.spawn([appctl.widget_python(), str(appctl.ROOT / appctl.WIDGET)], logfile="widget.log")
        log("小窓を起動しました")


def wait_until(check, seconds: int) -> bool:
    for _ in range(seconds):
        if check():
            return True
        time.sleep(1)
    return check()


def ensure_backend(force_restart: bool = False) -> int:
    """本体が動いていなければ起動する。使っている番号を返す"""
    port = appctl.backend_port()
    if not force_restart and appctl.backend_alive(port):
        return port
    appctl.stop_backend(LOGNAME)   # 応答しない古い本体（固まった・古いコードのまま）を片づける
    port = appctl.choose_port(appctl.BACKEND_PORTS, preferred=appctl.BACKEND_PORTS[0])
    if port != appctl.BACKEND_PORTS[0]:
        log(f"本体：{appctl.BACKEND_PORTS[0]} 番は他のアプリが使用中なので {port} 番を使います")
    appctl.write_runtime(backend_port=port)
    appctl.spawn([str(appctl.VENV_PY), "-m", "fastapi", "run", "app/main.py",
                  "--host", "127.0.0.1", "--port", str(port)],
                 cwd=appctl.BACKEND_DIR, logfile="backend.log")
    if wait_until(lambda: appctl.backend_alive(port), 60):
        log(f"本体を起動しました（{port} 番）")
    else:
        log(f"⚠ 本体が60秒以内に応答しません（{port} 番）。logs/backend.log を確認してください")
    return port


def ensure_frontend(api_port: int, force_restart: bool = False) -> int:
    """画面（Vite）が動いていて、今の本体へ中継していればそのまま。違えば起動し直す。使っている番号を返す"""
    rt = appctl.read_runtime()
    cur = appctl.frontend_listening_port()
    if (not force_restart and cur is not None and cur == rt.get("frontend_port")
            and rt.get("frontend_api_port") == api_port):
        return cur
    appctl.stop_frontend(LOGNAME)
    port = appctl.choose_port(appctl.FRONTEND_PORTS, preferred=appctl.FRONTEND_PORTS[0])
    if port != appctl.FRONTEND_PORTS[0]:
        log(f"画面：{appctl.FRONTEND_PORTS[0]} 番は他のアプリが使用中なので {port} 番を使います")
    appctl.write_runtime(frontend_port=port, frontend_api_port=api_port)
    # --strictPort：指定した番号が使えなければ別の番号に逃げずに失敗する（番号がずれて接続先が分からなくなるのを防ぐ）
    appctl.spawn(["cmd", "/c", "npm", "run", "dev", "--", "--port", str(port), "--strictPort"],
                 cwd=appctl.FRONTEND_DIR, logfile="frontend.log",
                 env={"LIFEAPP_API_PORT": str(api_port)})
    if wait_until(lambda: appctl.frontend_listening_port() == port, 60):
        log(f"画面を起動しました（{port} 番 → 本体 {api_port} 番へ中継）")
    else:
        log(f"⚠ 画面が60秒以内に起動しません（{port} 番）。logs/frontend.log を確認してください")
    return port


def ensure_guard_task() -> None:
    """見守りタスク（1分ごとに ensure_workers.py）が無い・古い形式なら登録し直す"""
    try:
        q = subprocess.run(["schtasks", "/Query", "/TN", "FocusCafe Guard", "/V", "/FO", "LIST"],
                           capture_output=True, text=True, errors="replace", stdin=subprocess.DEVNULL,
                           creationflags=appctl.NO_WINDOW)
        if q.returncode == 0 and "ensure_workers.bat" not in (q.stdout or ""):
            return
        tr = f'"{appctl.VENV_PYW}" "{appctl.ROOT / "ensure_workers.py"}"'
        # ONLOGON のタスクは管理者権限が要るので harden_install.bat に任せる（1分ごとのタスクで十分）
        subprocess.run(["schtasks", "/Delete", "/TN", "FocusCafe Guard", "/F"],
                       capture_output=True, stdin=subprocess.DEVNULL, creationflags=appctl.NO_WINDOW)
        subprocess.run(["schtasks", "/Create", "/TN", "FocusCafe Guard", "/SC", "MINUTE", "/MO", "1",
                        "/TR", tr, "/F"], capture_output=True, stdin=subprocess.DEVNULL,
                       creationflags=appctl.NO_WINDOW)
        log("見守りタスクを登録しました")
    except Exception as e:
        log(f"見守りタスクの確認・登録に失敗: {type(e).__name__}: {e}")


def open_browser() -> None:
    import webbrowser
    webbrowser.open(appctl.frontend_url())


# ======================= 入口 =======================
def main() -> None:
    mode = (sys.argv[1] if len(sys.argv) > 1 else "").lower()
    if not appctl.VENV_PY.exists():
        log("venv が見つかりません（scripts\\setup_env.bat を先に実行）")
        return
    # 二重起動の防止（見守りタスクの auto と start_all が重なった等）：先に動いている方が終わるまで待つ
    lock = appctl.acquire_lock("launcher", wait_sec=150)
    if lock is None:
        log("別の launcher が終わらないので中止します")
        return
    if mode == "widget":
        ensure_widget()
        return
    if mode == "backend":
        api = ensure_backend(force_restart=True)
        ensure_frontend(api)   # 本体の番号が変わったときだけ画面も起動し直す
        return

    restart = mode == "restart"
    appctl.write_runtime(stopped_by_user=False)   # stop_all.bat all の「本人が止めた」を解除
    ensure_guard_task()
    ensure_workers(restart=restart)
    api = ensure_backend(force_restart=restart)
    ensure_frontend(api, force_restart=restart)
    ensure_widget(restart=restart)
    log(f"起動完了：本体 {api} 番・画面 {appctl.frontend_port()} 番")
    # ブラウザを開くのは引数なし（start_all.bat）のときだけ。restart はすでに開いているタブが
    # 画面の再起動後に自動で再接続するので新しいタブを開かない（takeover で古いタブが閉じる案内になるため）
    if mode == "":
        open_browser()


if __name__ == "__main__":
    log(f"launcher 開始: {sys.executable} {sys.argv[1:]}")
    try:
        main()
    except Exception:
        log("launcher エラー:\n" + traceback.format_exc())
