"""見守り：制限・記録のワーカーと、本体（アプリ）が止まっていたら起こす。

タスクスケジューラ「FocusCafe Guard」から1分ごとに pythonw.exe で実行される（窓を一切出さない）。
手で実行しても害はない。

- ワーカー（blocker / site_blocker / pc_tracker / webcam_worker）：止まっていれば起こす。重複は古い方を残す
- 本体：応答しなければ launcher.py auto で起こす（制限の判定は本体が60秒ごとに更新するため。
  本体が止まったままだとワーカーは安全側＝制限に倒れる）。ただし stop_all.bat all で本人が止めたときは起こさない
- logs/_request.txt に "restart" か "diag" とあれば実行して消す（AI が遠隔で再起動・診断するため）
- SYSTEM として動いているとき（harden_install.bat）は、ユーザーの画面が要るものは起こさない
"""
import os
import subprocess

import appctl

REQUEST_FILE = appctl.LOGS / "_request.txt"
LOGNAME = "guard.log"


def glog(msg: str) -> None:
    appctl.log(LOGNAME, msg)


def run_launcher(mode: str) -> None:
    appctl.spawn([str(appctl.VENV_PYW), str(appctl.ROOT / "launcher.py"), mode])


def handle_request(is_system: bool) -> None:
    """許可するのは "restart" と "diag" だけ。SYSTEM として動いているときは何もしない（権限の抜け道にしないため）"""
    if is_system or not REQUEST_FILE.exists():
        return
    try:
        req = REQUEST_FILE.read_text(encoding="utf-8").strip().lower()
        REQUEST_FILE.unlink()
    except OSError:
        return
    glog(f"request: {req!r}")
    try:
        if req == "restart":
            run_launcher("restart")
        elif req == "diag":
            appctl.spawn([str(appctl.VENV_PYW), str(appctl.ROOT / "diag.py")])
        glog(f"request started: {req!r}")
    except Exception as e:
        glog(f"request failed: {type(e).__name__}: {e}")


def main() -> None:
    if not appctl.VENV_PYW.exists():
        return
    # 二重実行の防止（前回の見守りが固まっていても、OS のロックはプロセスが終われば外れる）
    lock = appctl.acquire_lock("guard", wait_sec=0)
    if lock is None:
        glog("skip: another guard is running")
        return
    # launcher.py が起動・再起動の途中なら今回は何もしない（同じワーカーを両方が起こして二重になるのを防ぐ）
    launcher_lock = appctl.acquire_lock("launcher", wait_sec=0)
    if launcher_lock is None:
        glog("skip: launcher is running")
        return
    is_system = os.environ.get("USERNAME", "").upper() == "SYSTEM"
    handle_request(is_system)
    for s in appctl.WORKERS:
        appctl.dedupe(s, LOGNAME)
    if not appctl.running("blocker.py"):
        glog("start blocker.py")
        appctl.start_script("blocker.py")
    # site_blocker は最前面ウィンドウを見るので、ログオン中のユーザーの画面で動く必要がある
    if not appctl.running("site_blocker.py", user_session_only=True):
        glog("start site_blocker.py")
        if is_system:
            subprocess.run(["schtasks", "/Run", "/TN", "FocusCafe SiteBlocker"], check=False,
                           creationflags=appctl.NO_WINDOW)
        else:
            appctl.start_script("site_blocker.py")
    if not appctl.running("pc_tracker.py"):
        glog("start pc_tracker.py")
        appctl.start_script("pc_tracker.py")
    # カメラはログオン中のユーザーのセッションでしか見えない
    if not is_system and not appctl.running("webcam_worker.py", user_session_only=True):
        glog("start webcam_worker.py")
        appctl.start_script("webcam_worker.py")
    # 本体：止まっていたら起こす（本人が stop_all.bat all で止めたときと、起動中の launcher があるときは除く）
    if (not is_system and not appctl.read_runtime().get("stopped_by_user")
            and not appctl.backend_alive()):
        glog("本体が応答しないので launcher auto を起動")
        run_launcher("auto")


if __name__ == "__main__":
    # 固まったときに「どこで止まっているか」を logs/guard_hang.txt に残して終了する（50秒で打ち切り）
    try:
        import faulthandler
        appctl.LOGS.mkdir(parents=True, exist_ok=True)
        _hf = open(appctl.LOGS / "guard_hang.txt", "a", encoding="utf-8")
        faulthandler.dump_traceback_later(50, exit=True, file=_hf)
    except Exception:
        pass
    try:
        main()
    except Exception as e:
        glog(f"guard error: {type(e).__name__}: {e}")
