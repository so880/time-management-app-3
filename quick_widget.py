# -*- coding: utf-8 -*-
"""クイックスタート小窓（React + FastAPI 版に接続・テーマ＆形 切替対応）。

デスクトップの小窓からボタン一つで勉強を開始・計測する（PySide6製・常に最前面）。
- 起動時の選択はデフォルトで「選択なし（あとで決める）」。
- 「選択なし」のまま終了した場合は、終了時にダイアログで選択または自由記入できる。
- 記録は POST /api/logs へ送られる（今日の勉強時間は本体が記録の合計から数える）。
- 🎨ボタン：テーマ切替（ダーク／丸っこい／コーヒー）
- 🔘ボタン：形の切替（⬜カード／⚪まる／☕カップ）
- 計測中は ➖ボタンで丸いミニ表示（経過時間＋実行中だけ）に小さくできる。
  ミニ表示をクリックすると元の大きさに戻る。テーマ・形の選択は本体の設定に保存。

起動: 通常は start_all.bat が自動で起動する（単独: python quick_widget.py）
※ 本体（start_backend.bat）が起動していないと記録できません。
"""
import json
import os
import re
import sys
import time
import urllib.request
import webbrowser
from string import Template

from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel,
    QPushButton, QVBoxLayout, QWidget,
)

import appctl  # noqa: E402  本体・画面の URL（番号は backend/data/runtime.json。8000 / 5173 を直接書かない）


def _api(path: str) -> str:
    return appctl.backend_url() + path


UNSELECTED = "── 選択なし（あとで決める）──"

# ===== 見た目（テーマ：色 ／ 形：ウィンドウの輪郭。どちらも設定に保存） =====
_QSS_TEMPLATE = Template("""
QFrame#card { background: transparent; border: none; }
QLabel { color: $text; background: transparent; }
QLabel#title { color: $sub; font-weight: bold; }
QLabel#timer {
    color: $timer;
    font-family: Consolas, 'Courier New', monospace;
    font-weight: 800;
}
QLabel#status { color: $sub; }
QLabel#minitag { color: $sub; font-weight: bold; }
QComboBox {
    background-color: $combo_bg;
    color: $text;
    border: 1px solid $card_border;
    border-radius: ${combo_radius}px;
    padding: 6px 10px;
}
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView {
    background-color: $list_bg;
    color: $text;
    border: 1px solid $card_border;
    selection-background-color: $select_bg;
}
QPushButton#start {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 $accent1, stop:1 $accent2);
    color: white;
    font-weight: 800;
    border: none;
    border-radius: ${btn_radius}px;
    padding: 10px;
}
QPushButton#start:hover { background-color: $accent_hover; }
QPushButton#start[running="true"] {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(255, 91, 91, 245), stop:1 rgba(211, 47, 47, 245));
}
QPushButton#close {
    background: transparent; color: $sub;
    border: none; border-radius: 12px; font-weight: bold;
}
QPushButton#close:hover { background: rgba(255, 255, 255, 30); color: #fff; }
QPushButton#titlebtn {
    background: transparent; color: $sub;
    border: none; font-weight: bold; text-align: left; padding: 0;
}
QPushButton#titlebtn:hover { color: $text; }
QPushButton.pill {
    background-color: $pill_bg;
    color: $pill_fg; font-weight: bold;
    border: none; border-radius: ${combo_radius}px; padding: 8px 14px;
}
QPushButton.pill:hover { background-color: $select_bg; }
QPushButton.ghost {
    background: transparent; color: $sub;
    border: 1px solid $card_border;
    border-radius: ${combo_radius}px; padding: 8px 14px;
}
QPushButton.ghost:hover { color: #fff; border-color: rgba(255, 255, 255, 90); }
QDialog { background-color: $dialog_bg; }
""")

# テーマ一覧（dark=いつもの / round=丸っこい / coffee=コーヒー）
THEMES = {
    "dark": {
        "label": "🌙 ダーク",
        "card_bg": "rgba(20, 24, 32, 235)", "card_border": "rgba(255, 255, 255, 40)",
        "radius": 18, "btn_radius": 16, "combo_radius": 10,
        "text": "#e8eaed", "sub": "#9aa0a8", "timer": "#4CAF50",
        "combo_bg": "rgba(118, 118, 128, 60)", "list_bg": "#1a1f29",
        "select_bg": "rgba(76, 175, 80, 120)",
        "accent1": "rgba(76, 175, 80, 245)", "accent2": "rgba(56, 142, 60, 245)",
        "accent_hover": "#5CBF60",
        "pill_bg": "rgba(76, 175, 80, 40)", "pill_fg": "#A5F0A9",
        "dialog_bg": "#14181f",
        "mug": "#2B5E3C", "mug_dark": "#1E4029", "outline": "#10151c",  # ☕カップ形のマグの色
    },
    "round": {
        "label": "🫧 丸っこい",
        "card_bg": "rgba(32, 34, 48, 242)", "card_border": "rgba(180, 196, 255, 60)",
        "radius": 28, "btn_radius": 24, "combo_radius": 18,
        "text": "#eef1ff", "sub": "#aab3d6", "timer": "#8AB4F8",
        "combo_bg": "rgba(138, 150, 200, 55)", "list_bg": "#232637",
        "select_bg": "rgba(138, 180, 248, 120)",
        "accent1": "rgba(122, 156, 248, 245)", "accent2": "rgba(94, 114, 228, 245)",
        "accent_hover": "#93B5FA",
        "pill_bg": "rgba(138, 180, 248, 45)", "pill_fg": "#C5D8FF",
        "dialog_bg": "#1b1e2c",
        "mug": "#46549E", "mug_dark": "#313B74", "outline": "#141727",
    },
    "coffee": {
        "label": "☕ コーヒー",
        "card_bg": "rgba(43, 32, 26, 246)", "card_border": "rgba(255, 226, 190, 55)",
        "radius": 20, "btn_radius": 18, "combo_radius": 12,
        "text": "#f3e9dc", "sub": "#c9b8a6", "timer": "#D7A86E",
        "combo_bg": "rgba(150, 120, 95, 70)", "list_bg": "#2a211b",
        "select_bg": "rgba(215, 168, 110, 120)",
        "accent1": "rgba(139, 94, 60, 250)", "accent2": "rgba(111, 68, 40, 250)",
        "accent_hover": "#A9744B",
        "pill_bg": "rgba(215, 168, 110, 45)", "pill_fg": "#F0D3B0",
        "dialog_bg": "#241b15",
        "mug": "#8C5A3C", "mug_dark": "#5F3D29", "outline": "#1c130d",
    },
}
THEME_ORDER = ["dark", "round", "coffee"]

SHAPES = ["card", "circle", "cup"]
SHAPE_LABEL = {"card": "⬜ カード", "circle": "⚪ まる", "cup": "☕ カップ"}


def build_qss(theme_name):
    t = THEMES.get(theme_name) or THEMES["dark"]
    return _QSS_TEMPLATE.substitute(t)


def _rgba(s):
    """'rgba(20, 24, 32, 235)' や '#4CAF50' → QColor"""
    s = str(s).strip()
    if s.startswith("#"):
        return QColor(s)
    nums = re.findall(r"[\d.]+", s)
    if len(nums) >= 3:
        a = int(float(nums[3])) if len(nums) >= 4 else 255
        return QColor(int(float(nums[0])), int(float(nums[1])), int(float(nums[2])), a)
    return QColor(30, 30, 30, 235)


# ---- 設定の読み書き（本体のDBに保存 → 次回起動時も同じ見た目） ----
def load_pref(key, default, allowed=None):
    try:
        with urllib.request.urlopen(_api("/api/settings"), timeout=3) as res:
            s = json.load(res)
        v = s.get(key)
        if allowed is not None and v not in allowed:
            return default
        return v if v is not None else default
    except Exception:
        return default


def save_pref(key, value):
    body = json.dumps({key: value}).encode("utf-8")
    req = urllib.request.Request(
        _api("/api/settings"), data=body,
        headers={"Content-Type": "application/json"}, method="PUT")
    try:
        with urllib.request.urlopen(req, timeout=3):
            pass
    except Exception as e:
        print("[quick_widget] 設定の保存に失敗:", e)


# =========================================================
# 形つきカード（カード／まる／カップ をQPainterで描く）
# カップは「温度」を持つ：湯気の本数・長さ・濃さが warmth(0〜1) で変わり、
# 記録中は下に電子ヒーターが現れて赤く光る。
# =========================================================
class ShapedCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self._shape = "card"
        self._theme = THEMES["dark"]
        self._mini = False
        self._mini_style = "circle"
        self._warmth = 1.0    # 0=冷めきった 〜 1=淹れたて
        self._heating = False  # 記録中＝ヒーターON

    def set_look(self, shape, theme, mini, mini_style="circle"):
        self._shape = shape
        self._theme = theme
        self._mini = mini
        self._mini_style = mini_style
        self.update()

    def set_state(self, warmth, heating):
        self._warmth = max(0.0, min(1.0, float(warmth)))
        self._heating = bool(heating)
        if self._shape == "cup" and not self._mini:
            self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = self._theme
        bg = _rgba(t["card_bg"])
        border = _rgba(t["card_border"])
        accent = _rgba(t["accent1"])
        w, h = float(self.width()), float(self.height())
        pen = QPen(border)
        pen.setWidthF(1.5)

        # ミニ表示：丸 or 横バー（どちらも実行中の目印にアクセント色のリング）
        if self._mini:
            if self._mini_style == "circle":
                d = min(w, h) - 6
                rect = QRectF((w - d) / 2, (h - d) / 2, d, d)
                p.setPen(pen)
                p.setBrush(bg)
                p.drawEllipse(rect)
                ring = QPen(accent)
                ring.setWidthF(3.0)
                p.setPen(ring)
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(rect.adjusted(5, 5, -5, -5))
            else:  # bar / quiet：細長いピル
                rect = QRectF(1.5, 1.5, w - 3, h - 3)
                r = rect.height() / 2
                p.setPen(pen)
                p.setBrush(bg)
                p.drawRoundedRect(rect, r, r)
                ring = QPen(accent)
                ring.setWidthF(2.5)
                p.setPen(ring)
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(rect.adjusted(3, 3, -3, -3), r - 3, r - 3)
            return

        # まる（通常サイズ）
        if self._shape == "circle":
            d = min(w, h) - 6
            rect = QRectF((w - d) / 2, (h - d) / 2, d, d)
            p.setPen(pen)
            p.setBrush(bg)
            p.drawEllipse(rect)
            return

        if self._shape == "cup":
            self._paint_cup(p, t, bg, border, w, h)
            return

        # 通常のカード（角丸）
        p.setPen(pen)
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), t["radius"], t["radius"])

    # ---- コーヒーカップの描画（ねこラテ：茶色マグ＋ねこ型フォーム＋シナモン） ----
    def _paint_cup(self, p, t, bg, border, w, h):
        from PySide6.QtGui import QLinearGradient
        steam_top = 6.0
        # 参考イラスト準拠の固定パレット（テーマに関わらず、かわいい茶色マグ）
        body = QRectF(12, 118, w - 84, h - 196)
        mug = QColor("#7B5139")        # マグ本体（あたたかい茶色）
        mug_dark = QColor("#5E3C2A")   # 影
        rim_in = QColor("#CFC3BA")     # マグの内側（明るいベージュ）
        coffee = QColor("#5C3A2E")     # コーヒー
        cream = QColor("#FDF6F1")      # ねこフォーム
        cream_sh = QColor(214, 190, 178, 120)  # フォームの影
        face = QColor("#8A5147")       # 目・口・耳の内側
        stick = QColor("#8A5A40")      # シナモンスティック
        stick_dk = QColor("#6F4530")

        # 電子ヒーター（記録中だけ現れて赤く光り、カップを温める）
        if self._heating:
            hx = body.left() + body.width() * 0.10
            hw = body.width() * 0.80
            hy = body.bottom() + 14
            # ふんわりした赤い光
            glow = QColor(255, 110, 40, 55)
            p.setPen(Qt.NoPen)
            p.setBrush(glow)
            p.drawEllipse(QRectF(hx - 14, hy - 10, hw + 28, 34))
            # ヒーター本体（黒いベース）
            base = QColor(30, 30, 34, 235)
            p.setBrush(base)
            p.drawRoundedRect(QRectF(hx, hy, hw, 16), 8, 8)
            # 電熱線（オレンジのコイル2本）
            coil = QPen(QColor(255, 120, 45, 230))
            coil.setWidthF(2.6)
            coil.setCapStyle(Qt.RoundCap)
            p.setPen(coil)
            p.setBrush(Qt.NoBrush)
            for cy in (hy + 5.0, hy + 11.0):
                path = QPainterPath()
                path.moveTo(hx + 8, cy)
                x = hx + 8
                up = True
                while x < hx + hw - 8:
                    nx = min(x + 12, hx + hw - 8)
                    path.quadTo((x + nx) / 2, cy + (-3.5 if up else 3.5), nx, cy)
                    x = nx
                    up = not up
                p.drawPath(path)

        # 取っ手（右側の太いリング。下側にやわらかい影）
        handle_rect = QRectF(body.right() - 8, body.top() + body.height() * 0.22,
                             62, body.height() * 0.5)
        pen_h = QPen(mug)
        pen_h.setWidthF(15.0)
        pen_h.setCapStyle(Qt.RoundCap)
        p.setPen(pen_h)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(handle_rect)
        pen_hs = QPen(mug_dark)
        pen_hs.setWidthF(15.0)
        pen_hs.setCapStyle(Qt.RoundCap)
        p.setPen(pen_hs)
        p.drawArc(handle_rect, -85 * 16, 110 * 16)  # 下側の影

        # マグ本体（ずんぐり・輪郭なしのやわらかい塗り。下にいくほど濃い）
        taper = body.width() * 0.05
        r = 34.0
        path = QPainterPath()
        path.moveTo(body.left(), body.top())
        path.lineTo(body.right(), body.top())
        path.lineTo(body.right() - taper, body.bottom() - r)
        path.quadTo(body.right() - taper, body.bottom(),
                    body.right() - taper - r, body.bottom())
        path.lineTo(body.left() + taper + r, body.bottom())
        path.quadTo(body.left() + taper, body.bottom(),
                    body.left() + taper, body.bottom() - r)
        path.closeSubpath()
        grad = QLinearGradient(body.left(), body.top(), body.left(), body.bottom())
        grad.setColorAt(0.0, mug)
        grad.setColorAt(0.85, mug_dark)
        grad.setColorAt(1.0, mug_dark)
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        p.drawPath(path)

        # マグの口（上から覗いた楕円）：外側マグ色 → 内側ベージュ → コーヒーの水面
        rim_rect = QRectF(body.left() - 2, body.top() - 20, body.width() + 4, 40)
        p.setBrush(mug)
        p.drawEllipse(rim_rect)
        inner = rim_rect.adjusted(8, 7, -8, -7)
        p.setBrush(rim_in)
        p.drawEllipse(inner)
        coffee_rect = inner.adjusted(5, 6, -5, -2)
        p.setBrush(coffee)
        p.drawEllipse(coffee_rect)

        # シナモンスティック2本（ねこの右うしろから斜めに）
        for ang, off in ((13, 0), (25, 18)):
            p.save()
            p.translate(rim_rect.center().x() + 58 + off, rim_rect.center().y() + 2)
            p.rotate(ang)
            p.setPen(Qt.NoPen)
            p.setBrush(stick)
            p.drawRoundedRect(QRectF(-5, -76, 10, 80), 5, 5)
            p.setBrush(stick_dk)
            p.drawRoundedRect(QRectF(-5, -76, 10, 9), 4, 4)  # 先端
            p.restore()

        # ねこ型フォーム（コーヒーに浮かぶ白いねこ）
        cxh = body.center().x() - 6
        head = QRectF(cxh - 62, rim_rect.top() - 60, 124, 88)
        p.setPen(Qt.NoPen)
        # 水面に広がるフォームのすそ
        p.setBrush(cream)
        p.drawEllipse(QRectF(head.left() - 16, inner.top() + 8, head.width() + 32, 26))
        # 耳（左右の三角）＋内耳
        for sx, mirror in ((head.left() + 12, 1), (head.right() - 12, -1)):
            ear = QPainterPath()
            ear.moveTo(sx, head.top() + 26)
            ear.lineTo(sx + mirror * 8, head.top() - 12)
            ear.lineTo(sx + mirror * 40, head.top() + 12)
            ear.closeSubpath()
            p.setBrush(cream)
            p.drawPath(ear)
            ear_in = QPainterPath()
            ear_in.moveTo(sx + mirror * 8, head.top() + 18)
            ear_in.lineTo(sx + mirror * 11, head.top() - 2)
            ear_in.lineTo(sx + mirror * 28, head.top() + 10)
            ear_in.closeSubpath()
            p.setBrush(face)
            p.drawPath(ear_in)
        # 頭（丸いブロブ）＋ 下側のうっすら影
        p.setBrush(cream)
        p.drawRoundedRect(head, 46, 46)
        p.setBrush(cream_sh)
        p.drawRoundedRect(QRectF(head.left() + 10, head.bottom() - 22,
                                 head.width() - 20, 20), 10, 10)
        # 顔（目・ω口・ひげ）
        p.setBrush(face)
        ey = head.top() + 46
        p.drawEllipse(QRectF(head.left() + 32, ey, 7, 7))
        p.drawEllipse(QRectF(head.right() - 39, ey, 7, 7))
        pen_f = QPen(face)
        pen_f.setWidthF(2.2)
        pen_f.setCapStyle(Qt.RoundCap)
        p.setPen(pen_f)
        p.setBrush(Qt.NoBrush)
        mx = head.center().x()
        p.drawLine(mx, ey + 6, mx, ey + 11)
        p.drawArc(QRectF(mx - 9, ey + 7, 9, 8), 180 * 16, 180 * 16)
        p.drawArc(QRectF(mx, ey + 7, 9, 8), 180 * 16, 180 * 16)
        pen_w = QPen(QColor(185, 146, 135, 220))
        pen_w.setWidthF(1.6)
        pen_w.setCapStyle(Qt.RoundCap)
        p.setPen(pen_w)
        for i in range(3):
            yw = ey + 2 + i * 6
            p.drawLine(head.left() - 4, yw + 2, head.left() + 16, yw)
            p.drawLine(head.right() + 4, yw + 2, head.right() - 16, yw)

        # 湯気（温度で本数・長さ・濃さが変わる：1/3ごとに1本ずつ減る）
        #   真ん中の1本が最後まで残る → 冷めるほど短く・薄くなる
        cxs = (body.left() + body.width() * 0.14,   # ねこの左（最後まで残る）
               body.left() + body.width() * 0.88,   # シナモンの右
               body.left() + body.width() * 0.26)
        for i, cx in enumerate(cxs):
            s = max(0.0, min(1.0, (self._warmth - i / 3.0) * 3.0))
            if s <= 0.03:
                continue
            steam = QColor(255, 255, 255)  # 湯気は白（マンガ風）
            steam.setAlpha(int(45 + 120 * s))
            pen_st = QPen(steam)
            pen_st.setWidthF(2.4 + 1.4 * s)
            pen_st.setCapStyle(Qt.RoundCap)
            p.setPen(pen_st)
            p.setBrush(Qt.NoBrush)
            top_y = body.top() - 26
            length = (14 + 22 * s)
            sway = 5 + 3 * s
            path = QPainterPath()
            path.moveTo(cx, top_y)
            path.cubicTo(cx - sway, top_y - length * 0.33,
                         cx + sway, top_y - length * 0.66,
                         cx, top_y - length)
            end_y = max(steam_top, top_y - length)
            path.cubicTo(cx - sway * 0.7, end_y - 4,
                         cx + sway * 0.4, end_y - 8,
                         cx - 1, max(steam_top, end_y - 12))
            p.drawPath(path)


# =========================================================
# API連携
# =========================================================
def load_study_tasks():
    """『🔴今日絶対やる』→『📘重点・通常勉強』→『🔁今日の習慣』の有効項目を返す。取得失敗なら ([], False)"""
    try:
        with urllib.request.urlopen(_api("/api/health"), timeout=3):
            pass   # 本体が応答するかの確認
    except Exception:
        return [], False
    mustdo, study, habits = [], [], []
    # 🔴 今日の必須（未完了）・🔁 今日の習慣・📅 週単位 は統合API（/api/todo/today）から
    #    （取得に失敗しても勉強カテゴリは表示する）
    try:
        with urllib.request.urlopen(_api("/api/todo/today"), timeout=3) as res:
            td = json.load(res)
        for m in td.get("must") or []:
            if not m.get("checked") and m.get("title") and m["title"] not in mustdo:
                mustdo.append(m["title"])
        for h in (td.get("habits") or []) + (td.get("periodic") or []):
            t = h.get("title")
            if t and t not in habits and t not in mustdo:
                habits.append(t)
    except Exception:
        pass
    # 📘 ルーレット項目（旧・通常勉強／重点／課題。未完了・有効のみ。重点を先に）
    try:
        with urllib.request.urlopen(_api("/api/assignments"), timeout=3) as res:
            rows = [a for a in json.load(res) if not a.get("done") and a.get("enabled", True)]
        for a in sorted(rows, key=lambda x: (not x.get("focus"), x.get("id", 0))):
            t = a.get("title")
            if t and t not in study and t not in mustdo:
                study.append(t)
    except Exception:
        pass
    return {"mustdo": mustdo, "study": study, "habits": habits}, True


def record_study(task_name, minutes, end_at=None):
    """勉強の記録を本体へ送る。end_at は計測を終えた時刻（UNIX 秒）。
    送り直し（pending）のときに渡すと、本体は「送った時刻」ではなく「終えた時刻」の日付で記録する"""
    payload = {"content": task_name, "category": "勉強", "minutes": int(minutes), "bgm": "設定BGM"}
    if end_at:
        payload["end_at"] = float(end_at)
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        _api("/api/logs"), data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        # 本体が保存したあとで返事が遅れると「失敗」とみなして二重に送ってしまうので、待ち時間は長めにする
        with urllib.request.urlopen(req, timeout=15):
            return True
    except Exception as e:
        print("[quick_widget] 記録に失敗:", e)
        return False


# ===== 計測中の状態をファイルに残す（2026-11-06） =====
# restart_all / stop_all all / 異常終了では小窓が強制終了され closeEvent が走らないため、計測分が消えていた。
# 計測中は「何を・何秒計測したか」を10秒ごとに保存し、次に起動したときに引き継ぐ。
# 送れなかった記録（本体が止まっていた等）も pending に残し、本体が応答したら送り直す。
SESSION_FILE = appctl.DATA_DIR / "quick_widget_session.json"
RESUME_LIMIT_SEC = 10 * 60  # 最後の保存からこれ以内に起動した＝再起動とみなして計測を続ける。超えたら止まった時点までを記録


def _load_session_file():
    try:
        with open(SESSION_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {"session": data.get("session"), "pending": list(data.get("pending") or [])}
    except FileNotFoundError:
        pass
    except Exception as e:
        print("[quick_widget] 計測状態ファイルを読めません:", e)
    return {"session": None, "pending": []}


def _write_session_file(data):
    try:
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = SESSION_FILE.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, SESSION_FILE)  # 書き込み途中で落ちても壊れたファイルを残さない
    except Exception as e:
        print("[quick_widget] 計測状態ファイルを書けません:", e)


def _fmt_elapsed(secs):
    secs = int(secs)
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"


def fill_combo(combo, tasks):
    """コンボボックスに『選択なし』＋区切り付きの選択肢を入れる"""
    combo.clear()
    combo.addItem(UNSELECTED)
    if tasks:
        if tasks["mustdo"]:
            combo.insertSeparator(combo.count())
            combo.addItem("🔴 ── 今日の必須（未完了） ──")
            combo.model().item(combo.count() - 1).setEnabled(False)
            for t in tasks["mustdo"]:
                combo.addItem("　" + t, t)
        if tasks["study"]:
            combo.insertSeparator(combo.count())
            combo.addItem("📘 ── ルーレット項目 ──")
            combo.model().item(combo.count() - 1).setEnabled(False)
            for t in tasks["study"]:
                combo.addItem("　" + t, t)
        if tasks.get("habits"):
            combo.insertSeparator(combo.count())
            combo.addItem("🔁 ── 今日の習慣・週単位 ──")
            combo.model().item(combo.count() - 1).setEnabled(False)
            for t in tasks["habits"]:
                combo.addItem("　" + t, t)
    combo.setCurrentIndex(0)


class RefreshCombo(QComboBox):
    """開くたびに最新のタスク一覧をAPIから取り直すコンボボックス。

    起動時にバックエンドがまだ立ち上がっていなかった場合や、
    アプリ側でタスク・習慣を変更した場合も、開き直すだけで反映される。
    """

    def showPopup(self):
        try:
            tasks, ok = load_study_tasks()
            if ok:
                keep = self.currentData()  # いまの選択を維持したまま入れ替える
                fill_combo(self, tasks)
                if keep:
                    i = self.findData(keep)
                    if i >= 0:
                        self.setCurrentIndex(i)
        except Exception:
            pass  # 取得失敗時は今のリストのまま開く
        super().showPopup()


def selected_task(combo):
    """選択中のタスク名（『選択なし』や見出し行なら None）"""
    if combo.currentIndex() <= 0:
        return None
    data = combo.currentData()
    return data if data else None


# =========================================================
# 終了時の「何をやった？」ダイアログ（選択なしで開始した場合）
# =========================================================
class WhatDialog(QDialog):
    def __init__(self, tasks, minutes, parent=None, qss=None):
        super().__init__(parent)
        self.setWindowTitle("何をやった？")
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.setStyleSheet(qss if qss else build_qss("dark"))
        self.result_task = None

        root = QVBoxLayout(self)
        head = QLabel(f"⏱ {minutes}分 おつかれさま！\n何をやったか選ぶか、入力してください。")
        head.setAlignment(Qt.AlignCenter)
        root.addWidget(head)

        self.combo = QComboBox()
        self.combo.setEditable(True)  # 自由記入もできる
        fill_combo(self.combo, tasks)
        self.combo.lineEdit().setPlaceholderText("例：レポートの下書き")
        self.combo.setCurrentText("")
        root.addWidget(self.combo)

        btns = QHBoxLayout()
        ok = QPushButton("💾 記録する")
        ok.setProperty("class", "pill")
        ok.setObjectName("start")
        ok.clicked.connect(self._ok)
        skip = QPushButton("記録しない")
        skip.setProperty("class", "ghost")
        skip.clicked.connect(self.reject)
        btns.addWidget(ok, 2)
        btns.addWidget(skip, 1)
        root.addLayout(btns)

    def _ok(self):
        data = self.combo.currentData()
        text = (data if data else self.combo.currentText()).strip()
        # 見出し行や区切りを選んだ/空欄なら「勉強」として記録
        if not text or text == UNSELECTED or text.startswith(("🔴", "📘")):
            text = "勉強"
        self.result_task = text
        self.accept()


# =========================================================
# 小窓（GUI）
# =========================================================
# 形ごとのウィンドウサイズと余白（left, top, right, bottom）
SHAPE_GEOM = {
    "card":   {"size": (320, 214), "margins": (16, 12, 16, 14)},
    "circle": {"size": (306, 306), "margins": (42, 44, 42, 46)},
    "cup":    {"size": (380, 400), "margins": (40, 146, 106, 80)},
}
COMPACT_SCALE = 0.78   # コンパクト表示の縮小率（🔍ボタンで切替）
MINI_SIZE = 118

# ミニ表示のスタイル（ミニ表示中に右クリックで切替）
DOCKS = ["tr", "tl", "bc"]   # 置き場所：右上／左上／下中央
DOCK_MARGIN = 12

MINI_STYLES = ["circle", "bar", "quiet"]
MINI_STYLE_LABEL = {"circle": "⚪ 丸（時間あり）",
                    "bar": "▬ バー（時間あり）",
                    "quiet": "▪ バー（実行中だけ）"}
MINI_GEOM = {"circle": (118, 118), "bar": (222, 46), "quiet": (142, 46)}
WARM_SECONDS = 3 * 3600  # 湯気が完全に消える／完全に戻るまでの時間（3時間）


class QuickWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Focus Quick")
        # 枠なし・常に最前面（ドラッグで移動可能）
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        # 2026-11-04：表示・再起動のときにフォーカスを奪わない（入力中の文字が別のアプリから外れていた）。
        # クリックすれば普通にフォーカスは来る（コンボの自由記入はそのまま使える）
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        # 置き場所：右上 tr／左上 tl／下中央 bc の3か所。掴んで離すと一番近い場所に吸い付く
        self.dock = load_pref("quick_widget_dock", "tr", DOCKS)

        self.theme = load_pref("quick_widget_theme", "dark", THEMES)
        self.shape = load_pref("quick_widget_shape", "card", SHAPES)
        self.compact = bool(load_pref("quick_widget_compact", False))  # 🔍小さめ表示
        self.mini_style = load_pref("quick_widget_mini_style", "circle", MINI_STYLES)
        self.mini = False

        self._running = False
        self._start_ts = None
        self._drag_pos = None
        self._drag_moved = False
        self.tasks, api_ok = load_study_tasks()

        # ---- カップの温度（湯気）：前回の温度から、起動していなかった時間ぶん冷ます ----
        try:
            saved_w = float(load_pref("quick_widget_warmth", 1.0))
            saved_at = float(load_pref("quick_widget_warmth_at", 0) or 0)
        except (TypeError, ValueError):
            saved_w, saved_at = 1.0, 0.0
        cooled = (time.time() - saved_at) / WARM_SECONDS if saved_at > 0 else 0.0
        self.warmth = max(0.0, min(1.0, saved_w - max(0.0, cooled)))
        self._warm_mono = time.monotonic()
        self._warm_ticks = 0

        self.card = ShapedCard(self)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.card)
        self.root = QVBoxLayout(self.card)
        self.root.setSpacing(8)

        # ヘッダー（タイトル＝クリックでアプリを開く＋テーマ／形／縮小／閉じる）
        top = QHBoxLayout()
        self.title = QPushButton("☕ Focus Quick")
        self.title.setObjectName("titlebtn")
        self.title.setToolTip("クリックでアプリ（ブラウザ）を開く")
        self.title.setCursor(Qt.PointingHandCursor)
        self.title.clicked.connect(self.open_app)
        self.theme_btn = self._tool_btn("🎨", "テーマを切り替える（ダーク → 丸っこい → コーヒー）", self.next_theme)
        self.shape_btn = self._tool_btn("🔘", "形を切り替える（カード → まる → カップ）", self.next_shape)
        self.size_btn = self._tool_btn("🔍", "大きさを切り替える（標準 ⇄ コンパクト）", self.toggle_compact)
        self.mini_btn = self._tool_btn(
            "➖", "小さくする（ミニ表示：左クリックで戻る／右クリックで 丸→バー→実行中だけ を切替）",
            lambda: self.set_mini(True))
        self.mini_btn.hide()  # 計測中だけ表示
        self.close_btn = self._tool_btn("✕", "閉じる", self.close)
        top.addWidget(self.title, 1)
        top.addWidget(self.theme_btn, 0)
        top.addWidget(self.shape_btn, 0)
        top.addWidget(self.size_btn, 0)
        top.addWidget(self.mini_btn, 0)
        top.addWidget(self.close_btn, 0)
        self.root.addLayout(top)

        # タスク選択（デフォルトは「選択なし」。開くたびに最新一覧を取り直す）
        self.combo = RefreshCombo()
        fill_combo(self.combo, self.tasks)
        self.root.addWidget(self.combo)

        # タイマー表示
        self.time_label = QLabel("00:00")
        self.time_label.setObjectName("timer")
        self.time_label.setAlignment(Qt.AlignCenter)
        self.root.addWidget(self.time_label)

        # ミニ表示用の「実行中」タグ（普段は隠す）
        self.mini_tag = QLabel("実行中")
        self.mini_tag.setObjectName("minitag")
        self.mini_tag.setAlignment(Qt.AlignCenter)
        self.mini_tag.hide()
        self.root.addWidget(self.mini_tag)

        # ステータス
        self.status_label = QLabel("" if api_ok else "⚠️ 本体が未起動です（start_all.bat）")
        self.status_label.setObjectName("status")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.root.addWidget(self.status_label)

        # スタート/ストップ
        self.start_btn = QPushButton("▶ スタート")
        self.start_btn.setObjectName("start")
        self.start_btn.setMinimumHeight(40)
        self.start_btn.clicked.connect(self.toggle)
        self.root.addWidget(self.start_btn)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

        # 温度の更新は常時（記録していない間は冷め、記録中はヒーターで温まる）
        self._warm_timer = QTimer(self)
        self._warm_timer.setInterval(1000)
        self._warm_timer.timeout.connect(self._warm_tick)
        self._warm_timer.start()

        # 生存通知（本体の「小窓を表示」ボタンが出す/出さないの判定に使う）
        self._ping_timer = QTimer(self)
        self._ping_timer.setInterval(20000)
        self._ping_timer.timeout.connect(self._ping)
        self._ping_timer.start()
        self._ping()

        self.apply_look()
        # 前回の計測（再起動で強制終了された等）を引き継ぐ／送れなかった記録を送り直す
        self._restore_session()

    # ---- 計測状態の保存と引き継ぎ（restart_all 等で強制終了されても計測分を失わない） ----
    def _save_session(self):
        if not self._running or self._start_ts is None:
            return
        data = _load_session_file()
        data["session"] = {
            "task": selected_task(self.combo),
            "elapsed_sec": int(time.monotonic() - self._start_ts),
            "last_seen": time.time(),
        }
        _write_session_file(data)

    def _clear_session(self):
        data = _load_session_file()
        data["session"] = None
        _write_session_file(data)

    def _add_pending(self, task, minutes):
        data = _load_session_file()
        data["pending"].append({"task": task, "minutes": int(minutes), "at": time.time()})
        _write_session_file(data)

    def _flush_pending(self):
        """送れなかった記録を送り直す。送れたものだけ消す"""
        data = _load_session_file()
        if not data["pending"]:
            return
        left, sent = [], []
        for item in data["pending"]:
            if record_study(item.get("task") or "勉強", item.get("minutes") or 1, item.get("at")):
                sent.append(item)
            else:
                left.append(item)
        if sent:
            # 送っている間に別の記録が足されていても消さないよう、読み直してから送れた分だけ外す
            data = _load_session_file()
            data["pending"] = [x for x in data["pending"] if x not in sent]
            _write_session_file(data)
            total = sum(int(x.get("minutes") or 0) for x in sent)
            if not self._running:
                self.status_label.setText(f"✅ 前回の計測 {total}分を記録しました")

    def _restore_session(self):
        data = _load_session_file()
        sess = data.get("session")
        if isinstance(sess, dict):
            elapsed = max(0, int(sess.get("elapsed_sec") or 0))
            task = sess.get("task")
            age = time.time() - float(sess.get("last_seen") or 0)
            if 0 <= age <= RESUME_LIMIT_SEC:
                # 再起動とみなして続きから（止まっていた数秒〜数分は数えない）
                if task:
                    self.select_task(task)
                self.start(resume_sec=elapsed)
                self.status_label.setText(f"⏯ 再起動前の計測（{_fmt_elapsed(elapsed)}）を引き継ぎました")
                return
            # 長く止まっていた（PC の電源断など）：止まった時点までを記録して終える
            data["session"] = None
            if elapsed > 0:
                # at は「止まった時刻」（最後に保存した時刻）。送った日ではなく、やった日の記録にするため
                stopped_at = float(sess.get("last_seen") or 0) or time.time()
                data["pending"].append({"task": task or "勉強", "minutes": max(1, elapsed // 60), "at": stopped_at})
            _write_session_file(data)
        if data["pending"]:
            # 本体は小窓より後に起動することがあるので少し待ってから送る（失敗しても ping のたびに送り直す）
            QTimer.singleShot(8000, self._flush_pending)

    def _ping(self):
        """生存通知。計測中なら「何を・何秒」も送り、アプリ側にリアルタイム表示させる"""
        running = bool(getattr(self, "_running", False)) and getattr(self, "_start_ts", None) is not None
        payload = {"alive": True, "running": running}
        if running:
            payload["task"] = selected_task(self.combo) or ""
            payload["elapsed_sec"] = int(time.monotonic() - self._start_ts)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(_api("/api/widget/ping"), data=body,
                                     headers={"Content-Type": "application/json"},
                                     method="POST")
        try:
            with urllib.request.urlopen(req, timeout=2) as res:
                reply = json.load(res)
        except Exception:
            return  # 本体未起動時は無視
        self._flush_pending()  # 本体が応答した：送れなかった記録があれば送る
        # アプリからの「この習慣でタイマー開始」指示（習慣の全画面ロック → 小窓で開始）
        # スマホからの「止めて記録」（PC のタイマーをスマホ側から終了）
        if isinstance(reply, dict) and reply.get("stop") and self._running:
            self.stop()
            return
        start_task = reply.get("start") if isinstance(reply, dict) else None
        if start_task and not self._running:
            self.select_task(start_task)
            self.showNormal()
            self.raise_()   # 前に出すだけ。activateWindow() はしない（入力中のアプリからフォーカスを奪わないため）
            self.start()

    def select_task(self, name):
        """コンボから同名の選択肢を選ぶ（無ければ自由記入として入れる）"""
        for i in range(self.combo.count()):
            if self.combo.itemData(i) == name:
                self.combo.setCurrentIndex(i)
                return
        self.combo.addItem("　" + name, name)
        self.combo.setCurrentIndex(self.combo.count() - 1)

    # ---- カップの温度（湯気の量）の更新 ----
    def _warm_tick(self):
        now = time.monotonic()
        dt = now - self._warm_mono
        self._warm_mono = now
        if dt <= 0:
            return
        # 記録中：3時間で完全復活 ／ 記録なし：3時間で湯気ゼロ（どちらも滑らかに）
        delta = dt / WARM_SECONDS if self._running else -dt / WARM_SECONDS
        self.warmth = max(0.0, min(1.0, self.warmth + delta))
        self.card.set_state(self.warmth, self._running)
        self._warm_ticks += 1
        if self._warm_ticks % 300 == 0:  # 5分おきに保存（再起動しても温度を引き継ぐ）
            save_pref("quick_widget_warmth", round(self.warmth, 4))
            save_pref("quick_widget_warmth_at", time.time())

    def closeEvent(self, e):
        # 計測中に✕で閉じた場合：その時点までの時間を自動で記録してから終了
        # （記録が消えて悔しい思いをしないための保険）
        if self._running and self._start_ts is not None:
            elapsed = time.monotonic() - self._start_ts
            minutes = max(1, int(elapsed // 60)) if elapsed > 0 else 0
            if minutes > 0:
                task = selected_task(self.combo) or "勉強"
                if not record_study(task, minutes):
                    self._add_pending(task, minutes)  # 本体が止まっていたら次回の起動時に送る
        self._running = False
        self._clear_session()
        save_pref("quick_widget_warmth", round(self.warmth, 4))
        save_pref("quick_widget_warmth_at", time.time())
        # 閉じたことを本体へ通知（「小窓を表示」ボタンをすぐ出せるように）
        try:
            req = urllib.request.Request(_api("/api/widget/bye"),
                                         data=b"{}",
                                         headers={"Content-Type": "application/json"},
                                         method="POST")
            with urllib.request.urlopen(req, timeout=2):
                pass
        except Exception:
            pass
        super().closeEvent(e)

    def _tool_btn(self, text, tip, slot):
        b = QPushButton(text)
        b.setObjectName("close")  # 控えめなアイコン風スタイルを共用
        b.setFixedSize(26, 26)
        b.setToolTip(tip)
        b.clicked.connect(slot)
        return b

    # ---- 見た目の適用（テーマ×形×ミニ状態） ----
    def apply_look(self):
        self.setStyleSheet(build_qss(self.theme))
        self.card.set_look(self.shape, THEMES.get(self.theme, THEMES["dark"]),
                           self.mini, self.mini_style)
        self.card.set_state(getattr(self, "warmth", 1.0), self._running)

        f = QFont()
        if self.mini:
            mw, mh = MINI_GEOM.get(self.mini_style, MINI_GEOM["circle"])
            self.setFixedSize(mw, mh)
            for w in (self.title, self.theme_btn, self.shape_btn, self.size_btn,
                      self.mini_btn, self.close_btn, self.combo,
                      self.status_label, self.start_btn):
                w.hide()
            if self.mini_style == "circle":
                # 丸：時間（大きめ）＋「実行中」
                self.root.setContentsMargins(10, 28, 10, 28)
                f.setPointSize(15)
                f.setBold(True)
                self.time_label.setFont(f)
                self.time_label.show()
                self.mini_tag.setText("実行中")
            else:
                # バー：1行にまとめる（bar=時間つき / quiet=実行中だけ）
                self.root.setContentsMargins(16, 4, 16, 4)
                self.time_label.hide()
                self._update_mini_tag()
            self.mini_tag.show()
        else:
            geom = SHAPE_GEOM.get(self.shape, SHAPE_GEOM["card"])
            k = COMPACT_SCALE if self.compact else 1.0
            w0, h0 = geom["size"]
            self.setFixedSize(int(w0 * k), int(h0 * k))
            self.root.setContentsMargins(*(int(m * k) for m in geom["margins"]))
            self.mini_tag.hide()
            for w in (self.title, self.theme_btn, self.shape_btn, self.size_btn,
                      self.close_btn, self.combo, self.status_label, self.start_btn):
                w.show()
            if self._running:
                self.mini_btn.show()
            else:
                self.mini_btn.hide()
            f.setPointSize(22 if self.compact else 30)
            f.setBold(True)
            self.time_label.setFont(f)
            self.start_btn.setMinimumHeight(30 if self.compact else 40)
        self.update()
        if self.isVisible():
            self._ensure_on_screen()  # サイズ変更で画面外にはみ出したら押し戻す

    def next_theme(self):
        i = THEME_ORDER.index(self.theme) if self.theme in THEME_ORDER else 0
        self.theme = THEME_ORDER[(i + 1) % len(THEME_ORDER)]
        self.apply_look()
        self.status_label.setText(f"テーマ：{THEMES[self.theme]['label']}")
        save_pref("quick_widget_theme", self.theme)

    def next_shape(self):
        i = SHAPES.index(self.shape) if self.shape in SHAPES else 0
        self.shape = SHAPES[(i + 1) % len(SHAPES)]
        self.apply_look()
        self.status_label.setText(f"形：{SHAPE_LABEL[self.shape]}")
        save_pref("quick_widget_shape", self.shape)

    def toggle_compact(self):
        self.compact = not self.compact
        self.apply_look()
        QTimer.singleShot(0, self._apply_dock)
        self.status_label.setText("大きさ：コンパクト" if self.compact else "大きさ：標準")
        save_pref("quick_widget_compact", self.compact)

    # ---- アプリをブラウザで開く（タイトルをクリックしたときだけ） ----
    def open_app(self):
        try:
            webbrowser.open(appctl.frontend_url())
        except Exception as e:
            print("[quick_widget] ブラウザ起動に失敗:", e)

    # ---- ミニ表示（実行中に小さくする／クリックで戻す） ----
    def set_mini(self, on):
        self.mini = bool(on)
        self.apply_look()
        QTimer.singleShot(0, self._apply_dock)

    # ---- スタート / ストップ ----
    def toggle(self):
        if not self._running:
            self.start()
        else:
            self.stop()

    def start(self, resume_sec=0):
        self._running = True
        self._start_ts = time.monotonic() - max(0, resume_sec)
        self.combo.setEnabled(False)
        self.start_btn.setText("■ ストップ")
        self.start_btn.setProperty("running", "true")
        self.start_btn.style().unpolish(self.start_btn)
        self.start_btn.style().polish(self.start_btn)
        task = selected_task(self.combo)
        self.status_label.setText(f"📚 {task}" if task else "🕐 あとで決める（終了時に選択）")
        self.time_label.setText(_fmt_elapsed(resume_sec))
        self.mini_btn.show()  # 計測中は「小さくする」を出す
        self.card.set_state(self.warmth, True)  # ヒーターON（すぐ描画に反映）
        self._timer.start()
        self._save_session()
        self._ping()  # 開始を即座にアプリへ知らせる

    def stop(self):
        self._timer.stop()
        self._running = False
        if self.mini:
            self.set_mini(False)  # 記録ダイアログが見えるように元の大きさへ
        self.mini_btn.hide()
        self.card.set_state(self.warmth, False)  # ヒーターOFF
        elapsed = time.monotonic() - self._start_ts if self._start_ts is not None else 0.0
        minutes = int(elapsed // 60)
        if elapsed > 0 and minutes < 1:
            minutes = 1  # 計測したなら最低1分として記録

        task = selected_task(self.combo)
        do_record = True
        if task is None:
            # 選択なしで開始 → 終了時に選択 or 自由記入
            # ダイアログを開く直前に最新のタスク一覧を取り直す
            fresh, ok = load_study_tasks()
            if ok:
                self.tasks = fresh
            dlg = WhatDialog(self.tasks, minutes, self, qss=build_qss(self.theme))
            if dlg.exec() == QDialog.Accepted and dlg.result_task:
                task = dlg.result_task
            else:
                do_record = False  # 「記録しない」

        if do_record:
            ok = record_study(task, minutes)
            if not ok:
                self._add_pending(task, minutes)  # 本体が応答したら自動で送り直す
            self.status_label.setText(
                f"✅ 「{task}」{minutes}分を記録しました" if ok
                else "⚠️ 本体が応答しません。記録は保存し、本体の起動後に自動で送ります")
            # ブラウザは自動では開かない（タブが増え続けるため）。
            # アプリを見たいときはタイトル「☕ Focus Quick」をクリック。
        else:
            self.status_label.setText("記録せずに終了しました")
        self._clear_session()
        self._ping()  # 終了（記録済み）を即座にアプリへ知らせる

        # 表示リセット＋選択肢を最新化
        self.tasks, _ = load_study_tasks()
        fill_combo(self.combo, self.tasks)
        self.combo.setEnabled(True)
        self.start_btn.setText("▶ スタート")
        self.start_btn.setProperty("running", "false")
        self.start_btn.style().unpolish(self.start_btn)
        self.start_btn.style().polish(self.start_btn)
        self.time_label.setText("00:00")
        self._start_ts = None

    def _update_mini_tag(self):
        """ミニ（バー）表示の1行テキストを更新する"""
        if self.mini_style == "quiet":
            self.mini_tag.setText("🔴 実行中")
        else:  # bar
            elapsed = time.monotonic() - self._start_ts if self._start_ts else 0
            self.mini_tag.setText(f"⏱ {_fmt_elapsed(elapsed)}　実行中")

    def _tick(self):
        if self._start_ts is not None:
            elapsed = time.monotonic() - self._start_ts
            self.time_label.setText(_fmt_elapsed(elapsed))
            self._save_ticks = getattr(self, "_save_ticks", 0) + 1
            if self._save_ticks % 10 == 0:  # 10秒ごとに計測状態を保存（強制終了されても引き継げるように）
                self._save_session()
            if self.mini and self.mini_style == "bar":
                self._update_mini_tag()

    # ---- 枠なしウィンドウのドラッグ移動（ミニ表示はクリックで復帰） ----
    def mousePressEvent(self, e):
        # ミニ表示中の右クリック：スタイル切替（丸→バー→実行中だけ→…）
        if e.button() == Qt.RightButton and self.mini:
            i = MINI_STYLES.index(self.mini_style) if self.mini_style in MINI_STYLES else 0
            self.mini_style = MINI_STYLES[(i + 1) % len(MINI_STYLES)]
            save_pref("quick_widget_mini_style", self.mini_style)
            self.apply_look()
            e.accept()
            return
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._drag_moved = False
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag_pos is not None and (e.buttons() & Qt.LeftButton):
            pos = e.globalPosition().toPoint()
            if (pos - self._drag_pos - self.frameGeometry().topLeft()).manhattanLength() > 4:
                self._drag_moved = True
            self.move(pos - self._drag_pos)
            e.accept()

    def mouseReleaseEvent(self, e):
        if self.mini and not self._drag_moved:
            self.set_mini(False)  # ミニ表示をクリック → 元の大きさに戻す
        elif self._drag_moved:
            self._snap_dock()  # 一番近い置き場所（右上／左上／下中央）に吸い付く
        self._drag_pos = None
        self._drag_moved = False

    # ---- 置き場所（2026-11-04 依頼者の指示：右上・左上・下中央の3か所に使い分け） ----
    def _dock_targets(self, screen=None):
        """3か所の左上座標 {dock: (x, y)}。作業領域（タスクバーを除く）の内側、余白 DOCK_MARGIN"""
        win = self.frameGeometry()
        screen = screen or QGuiApplication.screenAt(win.center()) or QGuiApplication.primaryScreen()
        a = screen.availableGeometry()
        m = DOCK_MARGIN
        return {
            "tr": (a.right() - win.width() - m + 1, a.top() + m),
            "tl": (a.left() + m, a.top() + m),
            "bc": (a.left() + (a.width() - win.width()) // 2, a.bottom() - win.height() - m + 1),
        }

    def _apply_dock(self):
        t = self._dock_targets().get(self.dock)
        if t:
            self.move(*t)

    def _snap_dock(self):
        win = self.frameGeometry()
        targets = self._dock_targets()
        best, best_d = self.dock, None
        for k, (x, y) in targets.items():
            d = (x - win.x()) ** 2 + (y - win.y()) ** 2
            if best_d is None or d < best_d:
                best, best_d = k, d
        if best != self.dock:
            self.dock = best
            save_pref("quick_widget_dock", best)
        self._apply_dock()

    def _ensure_on_screen(self):
        """ウィンドウが1つのモニターに完全に収まるように位置を補正する。

        デュアルモニターの「間」に落ちたり、2画面をまたいで置かれたりすると
        表示が壊れる・見えなくなるため、離した瞬間に一番近いモニターへスナップする。
        """
        win = self.frameGeometry()
        screen = QGuiApplication.screenAt(win.center())
        if screen is None:
            # 中心がどのモニターにも無い（隙間に落ちた）→ 一番近いモニターを探す
            best = None
            best_d = None
            for s in QGuiApplication.screens():
                c = s.availableGeometry().center()
                d = (c.x() - win.center().x()) ** 2 + (c.y() - win.center().y()) ** 2
                if best_d is None or d < best_d:
                    best, best_d = s, d
            screen = best
        if screen is None:
            return
        avail = screen.availableGeometry()
        if avail.contains(win):
            return  # 1画面に完全に収まっている → そのまま
        x = min(max(win.x(), avail.left()), avail.right() - win.width() + 1)
        y = min(max(win.y(), avail.top()), avail.bottom() - win.height() + 1)
        self.move(x, y)


def main():
    app = QApplication(sys.argv)
    w = QuickWidget()
    w.show()
    # 表示直後（大きさが決まってから）に保存してある置き場所へ。大きさを変えたときも同じ場所に留まる
    QTimer.singleShot(0, w._apply_dock)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
