"""🔒 制限のルール（定数と判定）を1か所にまとめたもの。

本体（gate_api / exemption_api / presence_api / logic）と、ワーカー（blocker.py / site_blocker.py /
stop_guard.py）の両方がここを読む。ワーカーは本体を import しない（FastAPI や DB の準備が要らないように、
このファイルは標準ライブラリだけで書く）。

依頼者の決定（docs/BACKLOG.md）：
- ゲームができる時間帯は 07:00〜21:00 に固定（設定では変えられない）
- 面接などの特例は前後60分、開始の24時間以上前に登録されたものだけ
- 制限を弱める変更（解除の抜け道・設定ロックの緩和）は行わない
"""
from datetime import datetime, timedelta

# ---- ゲームができる時間帯（起きている時間。21:00〜翌7:00 は不可）----
GAME_WINDOW = {"start": "07:00", "end": "21:00"}
# 在席の監視時間帯（ゲームの時間帯と同じ）
MONITOR_WINDOW = dict(GAME_WINDOW)

# ---- 面接などの特例（Google カレンダーの予定・Claude 審査の申請 共通）----
EXEMPT_KINDS = ("面接", "面談", "説明会", "選考", "座談会", "インターン", "テスト", "試験",
                "GD", "グループディスカッション")
EXEMPT_MARGIN_MIN = 60      # 前後の余白（準備・移動）。2026-11-03：15→60（依頼者の指示）
EXEMPT_MIN_LEAD_HOURS = 24  # 開始の24時間以上前に登録されたものだけ
EXEMPT_MAX_MINUTES = 180    # 1件の長さの上限（前後の余白は別）。Google カレンダーの予定・Claude 審査の申請 共通
EXEMPT_WEEK_CAP = 3         # Claude 審査の申請の承認は週3件まで（Google カレンダーの予定には付けない：依頼者の指示）
# Google カレンダーの予定による特例は、1日の合計（前後の余白を除く）をこの分数までにする（2026-11-06 依頼者の承認）
EXEMPT_CALENDAR_DAY_MAX_MINUTES = 240

# ---- 緊急解除（stop_all の AI 審査）の上限（2026-11-06 依頼者の承認）----
UNLOCK_DAILY_MAX = 2             # 1日に申請できる回数（承認・却下・審査できなかった分を含む）
UNLOCK_RETRY_WAIT_MIN = 30       # 却下されたあと、次の申請までに空ける分数
UNLOCK_MAX_MINUTES = 180         # 1回の解除の長さの上限（分）

# ---- 時計の確認（2026-11-06）----
# 判定はすべて PC の時計（日本時間）で行う。タイムゾーンを変えると時間帯の判定をずらせるため、
# 日本時間（UTC+9）でないときは「解放しない」（安全側）
EXPECTED_UTC_OFFSET_SEC = 9 * 3600


def clock_ok() -> bool:
    """PC のタイムゾーンが日本時間（UTC+9）か"""
    import time as _time
    return _time.localtime().tm_gmtoff == EXPECTED_UTC_OFFSET_SEC

# ---- 本体の判定（settings["gate_today"]）の鮮度 ----
# 本体は60秒ごとに gate_today を書き直す。これより古い判定は「本体が止まっている」とみなして使わない
# （解放されたまま本体が落ちると、その日はずっと解放のままになる抜け道を防ぐ。2026-11-06）
GATE_STALE_SEC = 180


def norm_hm(v) -> str | None:
    """"H:M" / "HH:MM" を "HH:MM" に。不正なら None"""
    try:
        h, m = [int(x) for x in str(v).strip().split(":")[:2]]
    except (ValueError, AttributeError):
        return None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return f"{h:02d}:{m:02d}"


def hm_minutes(hm: str) -> int:
    """"HH:MM" → 0時からの分"""
    h, m = [int(x) for x in hm.split(":")[:2]]
    return h * 60 + m


def in_window(hm: str, start: str, end: str) -> bool:
    """"HH:MM" が start〜end に入るか。end の時刻になったら外。start > end なら日またぎ。幅ゼロは常に外"""
    if start == end:
        return False
    if start < end:
        return start <= hm < end
    return hm >= start or hm < end


def shift_clamped(day: str, hm: str, minutes: int) -> str:
    """day の hm を minutes ずらす。その日の 00:00〜23:59 からはみ出したら端で止める
    （日をまたいで「夜通しの時間帯」と読まれないように）"""
    t = datetime.strptime(f"{day} {hm}", "%Y-%m-%d %H:%M") + timedelta(minutes=minutes)
    lo = datetime.strptime(f"{day} 00:00", "%Y-%m-%d %H:%M")
    hi = datetime.strptime(f"{day} 23:59", "%Y-%m-%d %H:%M")
    return min(max(t, lo), hi).strftime("%H:%M")


ALL_GATES = "game+site"   # 解除の対象の既定値（ゲームとサイトの両方）。gates はこの形の文字列で持つ


def unlock_window_active(eu: dict | None, gate: str, now: datetime | None = None) -> bool:
    """承認された解除（settings["emergency_unlock_day"]）が「今日・その時間帯・その対象」で有効か。
    gate は "game" か "site" """
    now = now or datetime.now()
    eu = eu or {}
    if eu.get("date") != now.date().isoformat():
        return False
    if gate not in (eu.get("gates") or ALL_GATES):
        return False
    return in_window(now.strftime("%H:%M"), eu.get("start") or "00:00", eu.get("end") or "23:59")


# ---- 制限のオン／オフ（2026-11-06 依頼者の承認：オフにしてもその日だけ。翌日は自動でオンに戻る）----
SWITCH_KEYS = {"game": "block_enabled", "site": "site_block_enabled"}
OFF_DATE_KEYS = {"game": "block_off_date", "site": "site_block_off_date"}   # オフにした日（本体だけが書く）


def block_active(settings: dict, gate: str, now: datetime | None = None) -> bool:
    """その制限が有効か。オフは「オフにした日」の間だけ（日付が変われば、本体が止まっていても有効に戻る）"""
    if settings.get(SWITCH_KEYS[gate], True) is not False:
        return True
    today = (now or datetime.now()).date().isoformat()
    return settings.get(OFF_DATE_KEYS[gate]) != today


def gate_fresh(gt: dict | None, now: datetime | None = None) -> bool:
    """本体の判定 gate_today が今日の分で、GATE_STALE_SEC 以内に書かれたものか"""
    now = now or datetime.now()
    gt = gt or {}
    if gt.get("date") != now.date().isoformat():
        return False
    try:
        updated = datetime.strptime(str(gt.get("updated"))[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return False
    age = (now - updated).total_seconds()
    return -60 <= age <= GATE_STALE_SEC   # 時計のずれ（少し未来）も許す


def worker_unlocked(settings: dict, gate: str, now: datetime | None = None) -> bool:
    """ワーカー（blocker / site_blocker / stop_guard）が使う解放判定。gate は "game" か "site"。
    - 承認された解除の時間帯なら解放（時間帯の境目をワーカー側で正確に守るため、ここでも見る）
    - それ以外は本体の判定 gate_today に従う。古い・無い・読めないときは制限する（安全側）
    - PC のタイムゾーンが日本時間でないときは制限する（clock_ok）"""
    if now is None:
        if not clock_ok():
            return False
        now = datetime.now()
    if unlock_window_active(settings.get("emergency_unlock_day"), gate, now):
        return True
    gt = settings.get("gate_today") or {}
    if not gate_fresh(gt, now):
        return False
    return bool(gt.get("game_unlocked" if gate == "game" else "site_unlocked"))
