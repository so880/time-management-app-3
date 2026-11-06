"""ゲームブロッカー（React + FastAPI 版に接続した独立ワーカー）。

「ゲーム解放条件」を満たしていない間、設定に登録されたプロセス
（ゲームの .exe）を検知して終了させ続ける。条件を満たすと自動で解除。

SQLite（backend/data/focus_cafe.db）を読み取り専用で2秒ごとに読み直すので、
設定変更はワーカー再起動なしで反映される。解放の判定は backend/app/policy.py（本体と共通）。
DB が読めないときは前回読めた内容で続け、一度も読めていなければ止める側（安全側）に倒す。

- 起動: python blocker.py（通常は start_all.bat が自動で起動する）
- 停止: Ctrl + C（またはウィンドウを閉じる）
"""
import sys
import time
from pathlib import Path

import psutil

import appctl

sys.path.insert(0, str(appctl.BACKEND_DIR))
from app import policy  # noqa: E402  本体と同じ解放判定（標準ライブラリだけのモジュール）

DB_FILE = appctl.DB_FILE
SETTING_KEYS = ("block_enabled", "block_off_date", "block_process_list", "emergency_unlock_day", "gate_today")
CHECK_INTERVAL_SEC = 2  # 監視間隔

# ---- 自動検知（設定に書かなくても止める） ----
# 1) ゲームのランチャー・ストア本体（これが動いているとゲームも起動できる）
BUILTIN_BLOCK = {
    "steam.exe", "steamwebhelper.exe", "steamservice.exe",
    "epicgameslauncher.exe", "epicwebhelper.exe",
    "battle.net.exe", "battle.net launcher.exe",
    "riotclientservices.exe", "riotclientux.exe", "leagueclient.exe", "valorant.exe", "valorant-win64-shipping.exe",
    "origin.exe", "eadesktop.exe", "ealauncher.exe", "upc.exe", "ubisoftconnect.exe", "ubisoftgamelauncher.exe",
    "galaxyclient.exe", "goggalaxy.exe", "rockstarlauncher.exe",
    "genshinimpact.exe", "starrail.exe", "zenlesszonezero.exe", "hoyoplay.exe",
    "shadowversewb.exe", "shadowverse.exe",
}
# 2) 実行ファイルの場所でゲームと判定する（Steam でインストールしたものは全部ここに入る）
GAME_PATH_PARTS = ("\\steamapps\\common\\", "\\epic games\\", "\\riot games\\",
                   "\\battle.net\\", "\\ubisoft game launcher\\games\\", "\\gog galaxy\\games\\",
                   "\\hoyoplay\\", "\\genshin impact\\", "\\cygames\\")
# 3) 実行ファイルと同じフォルダに Steam / Unity / Unreal の部品があればゲーム
GAME_SIBLING_FILES = ("steam_api.dll", "steam_api64.dll", "steamclient.dll", "steamclient64.dll",
                      "unityplayer.dll", "gameassembly.dll")
GAME_SUFFIX_HINTS = ("-win64-shipping.exe", "-win32-shipping.exe", "-wingdk-shipping.exe")  # Unreal Engine 製
# 4) 作業に必要なので絶対に止めない
NEVER_BLOCK = {"discord.exe", "code.exe", "chrome.exe", "msedge.exe", "firefox.exe", "explorer.exe",
               "python.exe", "pythonw.exe", "node.exe", "cmd.exe", "powershell.exe", "windowsterminal.exe",
               "slack.exe", "zoom.exe", "teams.exe", "ms-teams.exe", "obs64.exe", "spotify.exe"}


def looks_like_game(name_lower: str, exe_path: str) -> bool:
    """設定に無くてもゲームと判定する（ランチャー名／インストール場所／同じフォルダの部品）"""
    if name_lower in BUILTIN_BLOCK:
        return True
    if name_lower.endswith(GAME_SUFFIX_HINTS):
        return True
    return game_by_location(exe_path)


def game_by_location(exe_path: str) -> bool:
    """実行ファイルの場所・同じフォルダの部品だけでゲームと判定する（名前は見ない）。
    名前を変えても場所は変わらないので、NEVER_BLOCK より優先する"""
    p = (exe_path or "").lower()
    if not p:
        return False
    if any(part in p for part in GAME_PATH_PARTS):
        return True
    try:
        folder = Path(exe_path).parent
        for f in GAME_SIBLING_FILES:
            if (folder / f).exists():
                return True
    except (OSError, ValueError):
        pass
    return False




LOG_FILE = Path(__file__).resolve().parent / "logs" / "blocked.log"


def log_kill(name, path):
    """ブロックで終了させた記録（制限タブで見られる）"""
    from datetime import datetime
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] game {name} {path}\n")
    except OSError:
        pass


def kill_blocked(blocked_names_lower):
    """ブロック対象プロセスを終了させる。設定の一覧＋自動検知。名前は大文字小文字を無視。"""
    for proc in psutil.process_iter(["pid", "name", "exe"]):
        try:
            name = proc.info.get("name")
            if not name:
                continue
            nl = name.lower()
            exe = proc.info.get("exe") or ""
            # NEVER_BLOCK は名前だけの判定なので、ゲームの場所にある exe には効かせない
            # （ゲームの exe を code.exe などに改名して検知を逃れる抜け道を防ぐ。2026-11-06）
            if nl in NEVER_BLOCK and not game_by_location(exe):
                continue
            if nl in blocked_names_lower or looks_like_game(nl, exe):
                log_kill(name, exe)
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except psutil.TimeoutExpired:
                    proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        except Exception:
            # 想定外でもループは絶対に落とさない
            continue


def main():
    print("ゲームブロッカーを起動しました。停止は Ctrl + C。")
    print(f"監視対象DB: {DB_FILE}")
    settings = {}   # 前回読めた設定（DB が一時的に読めないときに使う。最初は空＝制限する）
    while True:
        fresh = appctl.read_settings(SETTING_KEYS)
        if fresh is not None:
            settings = fresh
        try:
            if policy.block_active(settings, "game") and not policy.worker_unlocked(settings, "game"):
                names = settings.get("block_process_list") or []
                if not isinstance(names, list):
                    names = []   # 設定が壊れていても自動検知分は止め続ける
                blocked = {str(n).strip().lower() for n in names if str(n).strip()}
                kill_blocked(blocked)  # 一覧が空でも自動検知分は止める
        except Exception:
            # 想定外の設定値などでワーカーごと落ちると、見守りタスクが起こすまで制限が外れるため、ループは止めない
            kill_blocked(set())
        time.sleep(CHECK_INTERVAL_SEC)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nゲームブロッカーを停止しました。")
