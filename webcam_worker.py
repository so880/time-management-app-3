"""📷 Webカメラのワーカー（F22・2026-11-01 夜）。PC の中だけで動き、外部には何も送らない。

やること（どちらも設定でオフにできる。両方オフなら カメラは開かない）
  1. 在席判定（presence_enabled）
     約10秒ごとに1フレーム取り、OpenCV の顔検出（Haar cascade。opencv-python に同梱）で
     「顔が映っているか」だけを判定 → POST /api/presence/ping {present: true/false}。
     画像は保存しない。何をしているかは判定しない。
  2. 時刻入り静止画の記録（webcam_log_enabled。10/30 に受け取った webcam_log.py 相当）
     webcam_log_interval_sec（既定30秒）ごとに、左上に日時を描いた JPEG を
     logs/webcam/YYYY-MM-DD/HHMMSS.jpg に保存。古い日（webcam_log_keep_days より前）のフォルダは消す。
     1日分の一覧画像（make_summary.py 相当）は webcam_summary.py が作る（画面の「まとめ画像を作る」）。

監視する時間は本体が決める（GET /api/presence/config の camera_ok / monitor）：
  07:00〜21:00 のうち、授業（時間割＋Googleカレンダーの【大学】）と面接などの特例を除いた時間だけ。
  それ以外はカメラを閉じる（ランプも消える）。

起動：launcher.py / ensure_workers.py が venv の pythonw で起こす（blocker 等と同じ）。
必要なパッケージ：backend/venv に opencv-python の 4 系
（`backend\\venv\\Scripts\\python.exe -m pip install "opencv-python<5"`。5 系は顔検出 CascadeClassifier が無い）。
無ければ logs/webcam.log に1行書いて、10分ごとに再確認するだけ（カメラは開かない）。
"""
import json
import os
import sys
import time
import traceback
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
import appctl  # noqa: E402  本体の URL（番号は runtime.json から。8000 を直接書かない）
LOGS = ROOT / "logs"
WEBCAM_DIR = LOGS / "webcam"

CONFIG_EVERY = 20       # 設定・監視可否を聞く間隔（秒）
DETECT_EVERY = 10       # 顔検出の間隔（秒）
# カメラ番号：設定（その他 › 在席判定・カメラ の camera_index、既定 0）で選ぶ。
# 環境変数 FC_CAMERA_INDEX があればそちらを優先する（起動時の一時的な切り替え用）
ENV_CAMERA_INDEX = os.environ.get("FC_CAMERA_INDEX", "").strip()
SCAN_MAX_INDEX = 4      # 「カメラを確認」で index 0〜4 を試す
DETECT_WIDTH = 320      # 判定用に縮小する幅（軽くするため）


def log(msg: str) -> None:
    try:
        LOGS.mkdir(parents=True, exist_ok=True)
        with open(LOGS / "webcam.log", "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except OSError:
        pass


def api_get(path: str, timeout: float = 3.0):
    with urllib.request.urlopen(appctl.backend_url() + path, timeout=timeout) as r:
        return json.load(r)


def api_post(path: str, body: dict, timeout: float = 3.0):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(appctl.backend_url() + path, data=data, headers={"Content-Type": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


PIP_HINT = 'backend\\venv\\Scripts\\python.exe -m pip install "opencv-python<5"'


def _import_cv2():
    try:
        import cv2  # noqa: F401
    except Exception as e:  # ImportError など
        log(f"opencv-python が見つかりません（{PIP_HINT}）: {e}")
        return None
    if not hasattr(cv2, "CascadeClassifier") or not hasattr(cv2, "data"):
        # opencv-python 5 系は顔検出（Haar cascade）が本体から外れている → 4 系を入れ直す
        log(f"この opencv-python（{getattr(cv2, '__version__', '?')}）には顔検出 CascadeClassifier がありません。"
            f"4 系を入れてください（{PIP_HINT}）")
        return None
    return cv2


class Camera:
    """カメラを必要なときだけ開く（閉じている間はランプも消える）"""

    def __init__(self, cv2, index: int = 0):
        self.cv2 = cv2
        self.cap = None
        self.index = index
        cascade = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
        self.face = cv2.CascadeClassifier(str(cascade))
        if self.face.empty():
            raise RuntimeError(f"顔検出モデルが読めません: {cascade}")

    def open(self) -> bool:
        if self.cap is not None and self.cap.isOpened():
            return True
        cv2 = self.cv2
        # Windows では CAP_DSHOW の方が起動が速く、固まりにくい
        backend = getattr(cv2, "CAP_DSHOW", 0) if os.name == "nt" else 0
        self.cap = cv2.VideoCapture(self.index, backend) if backend else cv2.VideoCapture(self.index)
        if not self.cap.isOpened():
            self.cap.release()
            self.cap = None
            return False
        try:
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)   # 古いフレームをためない
        except Exception:
            pass
        # 開いた直後は自動露出が効く前の暗いフレームが来るので、1.5秒ぶん読み捨てる
        t = time.time()
        while time.time() - t < 1.5:
            self.cap.grab()
        return True

    @staticmethod
    def brightness(frame) -> float:
        """フレームの平均輝度（0〜255）。真っ暗（カバー・仮想カメラ）の検知用"""
        try:
            return float(frame.mean())
        except Exception:
            return -1.0

    def info(self) -> dict:
        if self.cap is None:
            return {}
        cv2 = self.cv2
        try:
            return {"width": int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                    "height": int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                    "backend": str(self.cap.getBackendName())}
        except Exception:
            return {}

    def set_index(self, index: int) -> None:
        """カメラ番号が変わったら閉じて、次の grab で開き直す"""
        index = int(index)
        if index != self.index:
            self.close()
            self.index = index
            log(f"カメラ番号を {index} にしました")

    def scan(self, max_index: int = SCAN_MAX_INDEX) -> list[dict]:
        """index 0〜max_index のうち開けたカメラの一覧（番号・解像度・バックエンド）。
        いま使っているカメラは一度閉じる（Windows は同じカメラを2つ開けないため）"""
        cv2 = self.cv2
        self.close()
        backend = getattr(cv2, "CAP_DSHOW", 0) if os.name == "nt" else 0
        found = []
        for i in range(0, max_index + 1):
            cap = None
            try:
                cap = cv2.VideoCapture(i, backend) if backend else cv2.VideoCapture(i)
                if cap.isOpened():
                    ok, _ = cap.read()
                    if ok:
                        found.append({"index": i,
                                      "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                                      "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                                      "backend": str(cap.getBackendName())})
            except Exception as e:
                log(f"カメラ index={i} の確認でエラー: {type(e).__name__}: {e}")
            finally:
                try:
                    if cap is not None:
                        cap.release()
                except Exception:
                    pass
        return found

    def close(self) -> None:
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None

    def grab(self):
        """最新の1フレームを読む（取れなければ None）。たまっていた古いフレームを捨ててから読む"""
        if not self.open():
            return None
        for _ in range(2):
            self.cap.grab()
        ok, frame = self.cap.read()
        if not ok or frame is None:
            self.close()
            return None
        return frame

    def count_faces(self, frame) -> int:
        cv2 = self.cv2
        h, w = frame.shape[:2]
        scale = DETECT_WIDTH / float(w) if w > DETECT_WIDTH else 1.0
        small = cv2.resize(frame, (int(w * scale), int(h * scale))) if scale != 1.0 else frame
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)
        faces = self.face.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
        return 0 if faces is None else len(faces)

    def save_still(self, frame, now: datetime) -> Path | None:
        cv2 = self.cv2
        day_dir = WEBCAM_DIR / now.strftime("%Y-%m-%d")
        try:
            day_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return None
        img = frame.copy()
        stamp = now.strftime("%Y-%m-%d %H:%M:%S")
        # 読みやすいように黒い縁取り＋白文字
        cv2.putText(img, stamp, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(img, stamp, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
        out = day_dir / (now.strftime("%H%M%S") + ".jpg")
        cv2.imwrite(str(out), img, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        return out


def cleanup_old(keep_days: int) -> None:
    """keep_days より古い日の静止画フォルダとまとめ画像を消す（自分で作ったものだけ）"""
    if not WEBCAM_DIR.exists():
        return
    limit = (datetime.now() - timedelta(days=keep_days)).strftime("%Y-%m-%d")
    for p in WEBCAM_DIR.iterdir():
        try:
            if p.is_dir() and len(p.name) == 10 and p.name < limit:
                for f in p.glob("*.jpg"):
                    f.unlink()
                p.rmdir()
                log(f"古い静止画を削除: {p.name}")
            elif p.is_file() and p.name.startswith("summary_") and p.name[8:18] < limit:
                p.unlink()
        except OSError:
            pass


def main() -> None:
    log(f"webcam_worker 開始: {sys.executable}")
    cv2 = _import_cv2()
    if cv2 is None:
        # 入っていないときは10分ごとに再確認（ensure_workers が起こし直しても静かに待つ）
        while cv2 is None:
            time.sleep(600)
            cv2 = _import_cv2()
    cam = Camera(cv2, int(ENV_CAMERA_INDEX) if ENV_CAMERA_INDEX.isdigit() else 0)
    if ENV_CAMERA_INDEX:
        log(f"環境変数 FC_CAMERA_INDEX={ENV_CAMERA_INDEX} を優先します（設定の camera_index は無視）")
    cfg = None
    last_cfg = 0.0
    last_detect = 0.0
    last_still = 0.0
    last_cleanup = 0.0
    cam_fail_logged = False
    while True:
        now_ts = time.time()
        if now_ts - last_cfg >= CONFIG_EVERY or cfg is None:
            try:
                cfg = api_get("/api/presence/config")
            except Exception:
                cfg = None  # 本体未起動：カメラを閉じて待つ
            last_cfg = now_ts
        if not cfg:
            cam.close()
            time.sleep(5)
            continue
        if not ENV_CAMERA_INDEX:
            try:
                cam.set_index(int(cfg.get("camera_index") or 0))
            except (TypeError, ValueError):
                pass
        want_presence = bool(cfg.get("monitor"))
        wl = cfg.get("webcam_log") or {}
        want_still = bool(wl.get("enabled")) and bool(cfg.get("camera_ok"))
        # 画面の「カメラを確認」：1回だけ撮って明るさ・顔の数・解像度を報告する（監視時間外でも動く）
        if (cfg.get("camera") or {}).get("test_pending"):
            cfg["camera"]["test_pending"] = False
            result = {"ok": False, "error": "", "faces": 0, "brightness": None,
                      "index": cam.index, "found": []}
            try:
                result["found"] = cam.scan()
                frame = cam.grab()
                if frame is None:
                    result["error"] = f"カメラを開けません（index={cam.index}）"
                else:
                    result.update({"ok": True, "faces": int(cam.count_faces(frame)),
                                   "brightness": round(cam.brightness(frame), 1), **cam.info()})
            except Exception as e:
                result["error"] = f"{type(e).__name__}: {e}"
            try:
                api_post("/api/presence/camera_result", result)
            except Exception as e:
                log(f"カメラ確認の報告に失敗: {type(e).__name__}: {e}")
            log(f"カメラ確認: {result}")
            if not (want_presence or want_still):
                cam.close()
        if not (want_presence or want_still):
            cam.close()
            time.sleep(2)
            continue
        now = datetime.now()
        need_detect = want_presence and (now_ts - last_detect >= DETECT_EVERY)
        interval = max(10, int(wl.get("interval_sec") or 30))
        need_still = want_still and (now_ts - last_still >= interval)
        if not (need_detect or need_still):
            time.sleep(1)
            continue
        frame = cam.grab()
        if frame is None:
            if not cam_fail_logged:
                log(f"カメラを開けません（index={cam.index}。他のアプリが使用中か、接続を確認）")
                cam_fail_logged = True
            time.sleep(15)
            continue
        cam_fail_logged = False
        if need_detect:
            last_detect = now_ts
            try:
                n = cam.count_faces(frame)
                api_post("/api/presence/ping", {"present": n > 0, "faces": int(n),
                                                "brightness": round(cam.brightness(frame), 1)})
            except Exception as e:
                log(f"判定/送信に失敗: {type(e).__name__}: {e}")
        if need_still:
            last_still = now_ts
            try:
                cam.save_still(frame, now)
            except Exception as e:
                log(f"静止画の保存に失敗: {type(e).__name__}: {e}")
            if now_ts - last_cleanup > 3600:
                last_cleanup = now_ts
                cleanup_old(max(1, int(wl.get("keep_days") or 14)))
        time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("webcam_worker エラー:\n" + traceback.format_exc())
        raise
