# -*- coding: utf-8 -*-
"""PCスクリーンタイム自動記録（常駐ワーカー）。

最前面ウィンドウの「アプリ名＋ウィンドウタイトル」を5秒ごとに監視し、
同じ画面を見続けた区間を1セッションとして本体API（POST /api/pc/sessions）へ送る。
データはローカルのSQLiteにのみ保存され、外部には送信しない。

- 5分以上無操作（アイドル）の間は記録しない（離席をPC使用に数えない）
- 10秒未満の切り替えはノイズとして捨てる
- 本体サーバーが落ちている間はメモリに溜め、復帰後にまとめて送る
- 起動: 通常は start_all.bat が自動で起動する（単独: venvのpythonで実行）
- 停止: Ctrl + C（またはウィンドウを閉じる）
"""
import ctypes
import json
import time
import urllib.request
from ctypes import wintypes

import psutil

API = "http://127.0.0.1:8000"
POLL_SEC = 5            # 監視間隔
IDLE_LIMIT_SEC = 300    # これ以上無操作なら「離席」とみなす
MIN_SESSION_SEC = 10    # これ未満のセッションは記録しない
FLUSH_EVERY_SEC = 30    # サーバーへ送る間隔
CHECKPOINT_SEC = 600    # 長いセッションはこの長さで区切って保存（強制終了対策）
MAX_BUFFER = 2000       # サーバー停止時に溜める上限

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def idle_seconds() -> float:
    """最後のキー/マウス操作からの経過秒"""
    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if user32.GetLastInputInfo(ctypes.byref(lii)):
        return (kernel32.GetTickCount() - lii.dwTime) / 1000.0
    return 0.0


def foreground():
    """最前面ウィンドウの (アプリ名, タイトル)。取得できなければ None"""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    try:
        app = psutil.Process(pid.value).name()
    except Exception:
        app = "unknown"
    return app, buf.value


buffer: list[dict] = []
current: dict | None = None  # {"app","title","start"}


def close_current(now: float) -> None:
    global current
    if current is not None and now - current["start"] >= MIN_SESSION_SEC:
        if len(buffer) < MAX_BUFFER:
            buffer.append({
                "start_ts": current["start"], "end_ts": now,
                "app": current["app"], "title": current["title"][:200],
            })
    current = None


def flush() -> None:
    global buffer
    if not buffer:
        return
    body = json.dumps({"sessions": buffer}).encode("utf-8")
    req = urllib.request.Request(
        API + "/api/pc/sessions", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5):
            buffer = []
    except Exception:
        pass  # サーバー停止中は保持して次回再送


def main():
    global current
    print("PCスクリーンタイム記録を開始しました。停止は Ctrl + C。")
    last_flush = time.time()
    while True:
        now = time.time()
        if idle_seconds() > IDLE_LIMIT_SEC:
            close_current(now - 0)  # 離席：現セッションを閉じる
        else:
            fg = foreground()
            if fg is None:
                close_current(now)
            else:
                app, title = fg
                if current is None:
                    current = {"app": app, "title": title, "start": now}
                elif current["app"] != app or current["title"] != title:
                    close_current(now)
                    current = {"app": app, "title": title, "start": now}
                elif now - current["start"] >= CHECKPOINT_SEC:
                    # 長時間同じ画面：一旦区切って保存し、続きを新セッションに
                    close_current(now)
                    current = {"app": app, "title": title, "start": now}
        if now - last_flush >= FLUSH_EVERY_SEC:
            flush()
            last_flush = now
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        close_current(time.time())
        flush()
        print("\nPCスクリーンタイム記録を停止しました。")
