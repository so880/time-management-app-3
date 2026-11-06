"""📷 1日分の静止画（logs/webcam/YYYY-MM-DD/HHMMSS.jpg）を1枚の一覧画像にまとめる
（10/30 に受け取った make_summary.py 相当。F22）。

使い方（本体の画面「まとめ画像を作る」が venv の python で実行する。手でも動かせる）:
  backend\\venv\\Scripts\\python.exe webcam_summary.py --date 2026-11-02
  backend\\venv\\Scripts\\python.exe webcam_summary.py            … 今日
出力: logs/webcam/summary_YYYY-MM-DD.jpg（横12枚＝30秒間隔なら1行6分。各コマの下に時刻）
必要なパッケージ: opencv-python（backend/venv）。外部には何も送らない。
"""
import argparse
import sys
from datetime import date as date_cls
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WEBCAM_DIR = ROOT / "logs" / "webcam"

COLS = 12
THUMB_W, THUMB_H = 160, 120
LABEL_H = 18
MAX_FRAMES = 2000  # 30秒間隔×14時間=1680。それより多ければ間引く


def build(day: str) -> Path:
    try:
        import cv2
        import numpy as np
    except Exception as e:
        raise SystemExit(f"opencv-python が必要です（backend\\venv\\Scripts\\pip install opencv-python）: {e}")
    src = WEBCAM_DIR / day
    files = sorted(src.glob("*.jpg"))
    if not files:
        raise SystemExit(f"{day} の静止画がありません: {src}")
    if len(files) > MAX_FRAMES:
        step = -(-len(files) // MAX_FRAMES)
        files = files[::step]
    rows = -(-len(files) // COLS)
    cell_h = THUMB_H + LABEL_H
    canvas = np.zeros((rows * cell_h + 30, COLS * THUMB_W, 3), dtype=np.uint8)
    canvas[:] = (24, 24, 24)
    cv2.putText(canvas, f"{day}  {len(files)} frames", (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                (255, 255, 255), 2, cv2.LINE_AA)
    for i, f in enumerate(files):
        img = cv2.imread(str(f))
        if img is None:
            continue
        thumb = cv2.resize(img, (THUMB_W, THUMB_H), interpolation=cv2.INTER_AREA)
        r, c = divmod(i, COLS)
        y = 30 + r * cell_h
        x = c * THUMB_W
        canvas[y:y + THUMB_H, x:x + THUMB_W] = thumb
        hhmmss = f.stem
        label = f"{hhmmss[0:2]}:{hhmmss[2:4]}:{hhmmss[4:6]}" if len(hhmmss) >= 6 else hhmmss
        cv2.putText(canvas, label, (x + 4, y + THUMB_H + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                    (220, 220, 220), 1, cv2.LINE_AA)
    out = WEBCAM_DIR / f"summary_{day}.jpg"
    cv2.imwrite(str(out), canvas, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="1日分の静止画の一覧画像を作る")
    ap.add_argument("--date", default=date_cls.today().isoformat(), help="YYYY-MM-DD（既定：今日）")
    args = ap.parse_args()
    out = build(args.date)
    print(str(out))


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        if e.code not in (0, None):
            print(e, file=sys.stderr)
        raise
