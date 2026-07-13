# -*- coding: utf-8 -*-
"""クイックスタート小窓（React + FastAPI 版に接続・テーマ＆形 切替対応）。

デスクトップの小窓からボタン一つで勉強を開始・計測する（PySide6製・常に最前面）。
- 起動時の選択はデフォルトで「選択なし（あとで決める）」。
- 「選択なし」のまま終了した場合は、終了時にダイアログで選択または自由記入できる。
- 記録は POST /api/logs（add_to_today=True）へ送られ、今日の勉強合計に加算される。
- 🎨ボタン：テーマ切替（ダーク／丸っこい／コーヒー）
- 🔘ボタン：形の切替（⬜カード／⚪まる／☕カップ）
- 計測中は ➖ボタンで丸いミニ表示（経過時間＋実行中だけ）に小さくできる。
  ミニ表示をクリックすると元の大きさに戻る。テーマ・形の選択は本体の設定に保存。

起動: 通常は start_all.bat が自動で起動する（単独: python quick_widget.py）
※ 本体（start_backend.bat）が起動していないと記録できません。
"""
import json
import re
import sys
import time
import urllib.request
import webbrowser
from string import Template

from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel,
    QPushButton, QVBoxLayout, QWidget,
)

API_BASE = "http://127.0.0.1:8000"
APP_URL = "http://localhost:5173"
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
        with urllib.request.urlopen(API_BASE + "/api/settings", timeout=3) as res:
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
        API_BASE + "/api/settings", data=body,
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
        self._warmth = 1.0    # 0=冷めきった 〜 1=淹れたて
        self._heating = False  # 記録中＝ヒーターON

    def set_look(self, shape, theme, mini):
        self._shape = shape
        self._theme = theme
        self._mini = mini
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

        # ミニ表示・まる：円
        if self._mini or self._shape == "circle":
            d = min(w, h) - 6
            rect = QRectF((w - d) / 2, (h - d) / 2, d, d)
            p.setPen(pen)
            p.setBrush(bg)
            p.drawEllipse(rect)
            if self._mini:  # 実行中の目印にアクセント色のリング
                ring = QPen(accent)
                ring.setWidthF(3.0)
                p.setPen(ring)
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(rect.adjusted(5, 5, -5, -5))
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
    """『🔴今日絶対やる』→『📘重点・通常勉強』の有効項目を返す。取得失敗なら ([], False)"""
    try:
        with urllib.request.urlopen(API_BASE + "/api/settings", timeout=3) as res:
            s = json.load(res)
    except Exception:
        return [], False
    mustdo, study = [], []
    disabled = set(s.get("mustdo_list_disabled", []) or [])
    for t in s.get("mustdo_list", []) or []:
        if t and t not in disabled:
            mustdo.append(t)
    for key in ("focus_study_list", "study_list"):
        dis = set(s.get(key + "_disabled", []) or [])
        for t in s.get(key, []) or []:
            if t and t not in dis and t not in study and t not in mustdo:
                study.append(t)
    return {"mustdo": mustdo, "study": study}, True


def record_study(task_name, minutes):
    body = json.dumps({
        "content": task_name, "category": "勉強", "minutes": int(minutes),
        "bgm": "設定BGM", "add_to_today": True,
    }).encode("utf-8")
    req = urllib.request.Request(
        API_BASE + "/api/logs", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5):
            return True
    except Exception as e:
        print("[quick_widget] 記録に失敗:", e)
        return False


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
            combo.addItem("🔴 ── 今日絶対やる ──")
            combo.model().item(combo.count() - 1).setEnabled(False)
            for t in tasks["mustdo"]:
                combo.addItem("　" + t, t)
        if tasks["study"]:
            combo.insertSeparator(combo.count())
            combo.addItem("📘 ── 勉強カテゴリ ──")
            combo.model().item(combo.count() - 1).setEnabled(False)
            for t in tasks["study"]:
                combo.addItem("　" + t, t)
    combo.setCurrentIndex(0)


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
MINI_SIZE = 118
WARM_SECONDS = 3 * 3600  # 湯気が完全に消える／完全に戻るまでの時間（3時間）


class QuickWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Focus Quick")
        # 枠なし・常に最前面（ドラッグで移動可能）
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self.theme = load_pref("quick_widget_theme", "dark", THEMES)
        self.shape = load_pref("quick_widget_shape", "card", SHAPES)
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
        self.mini_btn = self._tool_btn("➖", "小さくする（ミニ表示をクリックで戻る）", lambda: self.set_mini(True))
        self.mini_btn.hide()  # 計測中だけ表示
        self.close_btn = self._tool_btn("✕", "閉じる", self.close)
        top.addWidget(self.title, 1)
        top.addWidget(self.theme_btn, 0)
        top.addWidget(self.shape_btn, 0)
        top.addWidget(self.mini_btn, 0)
        top.addWidget(self.close_btn, 0)
        self.root.addLayout(top)

        # タスク選択（デフォルトは「選択なし」）
        self.combo = QComboBox()
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

        self.apply_look()

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
        save_pref("quick_widget_warmth", round(self.warmth, 4))
        save_pref("quick_widget_warmth_at", time.time())
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
        self.card.set_look(self.shape, THEMES.get(self.theme, THEMES["dark"]), self.mini)
        self.card.set_state(getattr(self, "warmth", 1.0), self._running)

        f = QFont()
        if self.mini:
            self.setFixedSize(MINI_SIZE, MINI_SIZE)
            self.root.setContentsMargins(10, 28, 10, 28)
            for w in (self.title, self.theme_btn, self.shape_btn, self.mini_btn,
                      self.close_btn, self.combo, self.status_label, self.start_btn):
                w.hide()
            f.setPointSize(15)
            f.setBold(True)
            self.time_label.setFont(f)
            self.mini_tag.show()
        else:
            geom = SHAPE_GEOM.get(self.shape, SHAPE_GEOM["card"])
            self.setFixedSize(*geom["size"])
            self.root.setContentsMargins(*geom["margins"])
            self.mini_tag.hide()
            for w in (self.title, self.theme_btn, self.shape_btn,
                      self.close_btn, self.combo, self.status_label, self.start_btn):
                w.show()
            if self._running:
                self.mini_btn.show()
            else:
                self.mini_btn.hide()
            f.setPointSize(30)
            f.setBold(True)
            self.time_label.setFont(f)
        self.update()

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

    # ---- アプリをブラウザで開く（タイトルをクリックしたときだけ） ----
    def open_app(self):
        try:
            webbrowser.open(APP_URL)
        except Exception as e:
            print("[quick_widget] ブラウザ起動に失敗:", e)

    # ---- ミニ表示（実行中に小さくする／クリックで戻す） ----
    def set_mini(self, on):
        self.mini = bool(on)
        self.apply_look()

    # ---- スタート / ストップ ----
    def toggle(self):
        if not self._running:
            self.start()
        else:
            self.stop()

    def start(self):
        self._running = True
        self._start_ts = time.monotonic()
        self.combo.setEnabled(False)
        self.start_btn.setText("■ ストップ")
        self.start_btn.setProperty("running", "true")
        self.start_btn.style().unpolish(self.start_btn)
        self.start_btn.style().polish(self.start_btn)
        task = selected_task(self.combo)
        self.status_label.setText(f"📚 {task}" if task else "🕐 あとで決める（終了時に選択）")
        self.time_label.setText("00:00")
        self.mini_btn.show()  # 計測中は「小さくする」を出す
        self.card.set_state(self.warmth, True)  # ヒーターON（すぐ描画に反映）
        self._timer.start()

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
            dlg = WhatDialog(self.tasks, minutes, self, qss=build_qss(self.theme))
            if dlg.exec() == QDialog.Accepted and dlg.result_task:
                task = dlg.result_task
            else:
                do_record = False  # 「記録しない」

        if do_record:
            ok = record_study(task, minutes)
            self.status_label.setText(
                f"✅ 「{task}」{minutes}分を記録しました" if ok
                else "⚠️ 記録失敗（本体を起動してください）")
            # ブラウザは自動では開かない（タブが増え続けるため）。
            # アプリを見たいときはタイトル「☕ Focus Quick」をクリック。
        else:
            self.status_label.setText("記録せずに終了しました")

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

    def _tick(self):
        if self._start_ts is not None:
            self.time_label.setText(_fmt_elapsed(time.monotonic() - self._start_ts))

    # ---- 枠なしウィンドウのドラッグ移動（ミニ表示はクリックで復帰） ----
    def mousePressEvent(self, e):
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
        self._drag_pos = None
        self._drag_moved = False


def main():
    app = QApplication(sys.argv)
    w = QuickWidget()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
