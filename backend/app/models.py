"""テーブル定義（SQLAlchemy 2.0 の公式スタイル）。

- settings      : アプリ設定（既存 settings.json の1キー＝1行）
- activity_log  : 履歴（既存 activity_log.csv の1行＝1行）
- daily_state   : その日の状態（既存 session_state.json ＝ id=1 の1行）
"""
from typing import Optional

from sqlalchemy import Boolean, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class Setting(Base):
    """アプリ設定。既存 settings.json の1キー＝1行。

    可変長リストやネスト構造（daily_routine, goals 等）は
    JSON文字列として value に保存する（依頼仕様どおり）。
    """
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)  # JSON文字列


class ActivityLog(Base):
    """履歴。既存 activity_log.csv の列に1対1対応。

    進捗度合い・集中度・満足度は既存CSVで「空欄」「3.0」「2」など
    表記が揺れているため、忠実さを優先して文字列のまま保存する。
    """
    __tablename__ = "activity_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[str] = mapped_column(String(19))          # 日付 "YYYY-MM-DD HH:MM:SS"
    category: Mapped[str] = mapped_column(String(30))      # カテゴリ
    content: Mapped[str] = mapped_column(Text)             # 内容
    bgm: Mapped[str] = mapped_column(String(50), default="")        # BGM
    minutes: Mapped[int] = mapped_column(Integer, default=0)        # 経過時間(分)
    done_text: Mapped[str] = mapped_column(Text, default="")        # やったこと
    progress: Mapped[str] = mapped_column(String(10), default="")   # 進捗度合い
    focus: Mapped[str] = mapped_column(String(10), default="")      # 集中度
    satisfaction: Mapped[str] = mapped_column(String(10), default="")  # 満足度
    note: Mapped[str] = mapped_column(Text, default="")             # メモ


class ScheduleBlock(Base):
    """時間割（曜日ごとの繰り返し予定。大学の授業・バイトなど）"""
    __tablename__ = "schedule_blocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    weekday: Mapped[int] = mapped_column(Integer)           # 月=0 ... 日=6
    start: Mapped[str] = mapped_column(String(5))           # "HH:MM"
    end: Mapped[str] = mapped_column(String(5))
    title: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(30), default="大学")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    room: Mapped[str] = mapped_column(String(100), default="")  # 教室などのメモ（GCalにも反映）


class LifeEvent(Base):
    """単発予定（その日だけの予定）"""
    __tablename__ = "life_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[str] = mapped_column(String(10))           # "YYYY-MM-DD"
    start: Mapped[str] = mapped_column(String(5))
    end: Mapped[str] = mapped_column(String(5))
    title: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(30), default="予定")
    note: Mapped[str] = mapped_column(Text, default="")     # 場所などのメモ（GCalにも反映）


class LifeEntry(Base):
    """手入力の実績（その時間に実際何をしたか）"""
    __tablename__ = "life_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[str] = mapped_column(String(10))
    start: Mapped[str] = mapped_column(String(5))
    end: Mapped[str] = mapped_column(String(5))
    title: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(30), default="生活")
    note: Mapped[str] = mapped_column(Text, default="")


class DayOverride(Base):
    """日付単位の曜日振替・祝日扱い。

    mode="holiday" → その日は祝日・休業扱い（土曜の時間割＝生活リズムのみ）
    mode="weekday" → その日は weekday の曜日日程を適用（例：祝日の振替で月曜日程）
    """
    __tablename__ = "day_overrides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[str] = mapped_column(String(10), unique=True)  # "YYYY-MM-DD"
    mode: Mapped[str] = mapped_column(String(10))               # holiday / weekday
    weekday: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 月=0...日=6


class ScheduleCancellation(Base):
    """休講情報（特定の日付の時間割ブロックを休講にする）"""
    __tablename__ = "schedule_cancellations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[str] = mapped_column(String(10))           # "YYYY-MM-DD"
    block_id: Mapped[int] = mapped_column(Integer)          # schedule_blocks.id


class Assignment(Base):
    """課題（Notion風：期限・進捗・コメント付き）。

    期限が2日以内に迫った未完了の課題は、時間管理アプリの
    「今日絶対やる」リストへ自動で追加される（life_api.sync_assignments_to_mustdo）。
    recurring_id が入っている行は「毎週の課題」から自動生成された週ごとのインスタンス。
    """
    __tablename__ = "assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200))
    due_date: Mapped[str] = mapped_column(String(10))       # "YYYY-MM-DD"
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0〜100（100=完了）
    note: Mapped[str] = mapped_column(Text, default="")     # コメント（メモ）
    created: Mapped[str] = mapped_column(String(19), default="")
    recurring_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    category: Mapped[str] = mapped_column(String(20), default="大学")  # 大学/私生活/就活


class RecurringAssignment(Base):
    """毎週の課題（テンプレート）。

    週ごとに Assignment のインスタンスが自動生成される。
    今週分を完了して mustdo から消しても、翌週の期限日が近づくと
    新しいインスタンスが作られて再び反映される。
    """
    __tablename__ = "recurring_assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200))
    weekday: Mapped[int] = mapped_column(Integer)           # 期限の曜日（月=0 ... 日=6）
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class MoneyEntry(Base):
    """金銭管理の記録（旧 ikaseru の entries と1対1対応）。

    kind: "spend"（通常支出）/ "sub"（固定費・サブスク）/ "wish"（欲しい物）
    """
    __tablename__ = "money_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(10))
    date: Mapped[str] = mapped_column(String(10))            # "YYYY-MM-DD"
    amount: Mapped[float] = mapped_column(Float)
    category: Mapped[str] = mapped_column(String(50))
    detail: Mapped[str] = mapped_column(Text, default="")
    satisfaction: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # ★1〜5
    validity: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)   # high/fair/low/unrated
    advice: Mapped[str] = mapped_column(Text, default="")
    method: Mapped[str] = mapped_column(String(10), default="simple")            # simple/ai
    created_at: Mapped[float] = mapped_column(Float, default=0)                  # Unixミリ秒（旧仕様）
    source: Mapped[str] = mapped_column(String(20), default="")                  # ""/import
    # --- sub 用 ---
    plan_months: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    usage: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)      # daily/weekly/monthly/rare
    reason: Mapped[str] = mapped_column(Text, default="")
    sat_log: Mapped[Optional[str]] = mapped_column(Text, nullable=True)          # JSON {"2026-07":4}
    # --- wish 用 ---
    need: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)       # high/mid/low
    want_level: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)    # ★1〜5
    owned_similar: Mapped[str] = mapped_column(Text, default="")
    better_point: Mapped[str] = mapped_column(Text, default="")
    recommendation: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # buy/consider/hold


class JobApplication(Base):
    """就活の応募先（夏インターン・本選考）。

    status  : 固定の段階（気になる/ES提出/Webテスト/面接/内定/お見送り）
    priority: 日程が被ったときの優先順位（1=高 / 2=中 / 3=低）
    submitted: 提出した内容（ESの本文・ポートフォリオなどのメモ）
    """
    __tablename__ = "job_applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(200), default="")   # 職種・コース名
    kind: Mapped[str] = mapped_column(String(10), default="intern")  # intern / fulltime
    status: Mapped[str] = mapped_column(String(20), default="気になる")
    priority: Mapped[int] = mapped_column(Integer, default=2)     # 1=高 2=中 3=低
    submitted: Mapped[str] = mapped_column(Text, default="")      # 提出した内容
    note: Mapped[str] = mapped_column(Text, default="")
    created: Mapped[str] = mapped_column(String(19), default="")


class JobEvent(Base):
    """就活の日程（説明会・面接・インターン本番など）。

    end_date を入れると期間（例：5日間のインターン）になる。
    application_id=0 は「会社に紐づかない就活予定」（合同説明会など）。
    choice=0 は確定した日程、1以上は「第N希望」の候補日
    （同じ会社の候補日同士は日程被りとして扱わない）。
    日程同士が重なった場合は、応募先の priority を使って優先順位を表示する。
    """
    __tablename__ = "job_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[int] = mapped_column(Integer)          # job_applications.id（0=紐づけなし）
    label: Mapped[str] = mapped_column(String(100), default="")   # 例: 一次面接
    date: Mapped[str] = mapped_column(String(10))                 # 開始日 "YYYY-MM-DD"
    end_date: Mapped[str] = mapped_column(String(10), default="") # 期間の最終日（空=1日）
    start: Mapped[str] = mapped_column(String(5), default="")     # "HH:MM"（空=終日）
    end: Mapped[str] = mapped_column(String(5), default="")
    choice: Mapped[int] = mapped_column(Integer, default=0)       # 0=確定 / 1〜=第N希望


class PcSession(Base):
    """PC使用の自動記録（最前面ウィンドウのセッション）。pc_tracker.py が書き込む"""
    __tablename__ = "pc_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    start_ts: Mapped[float] = mapped_column(Float)          # Unix秒
    end_ts: Mapped[float] = mapped_column(Float)
    app: Mapped[str] = mapped_column(String(100))           # 例: chrome.exe
    title: Mapped[str] = mapped_column(Text, default="")    # ウィンドウタイトル


class DailyState(Base):
    """その日の状態。既存 session_state.json のキーに1対1対応（常に id=1 の1行）。

    current_task / pending_review / rolled_options / sos_task は
    JSON文字列として保存する（null もあり得るため nullable）。
    """
    __tablename__ = "daily_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # 常に 1
    target_date: Mapped[str] = mapped_column(String(10))        # "YYYY-MM-DD"
    page: Mapped[str] = mapped_column(String(20), default="dashboard")
    current_task: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    start_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # Unix秒
    study_time_total: Mapped[int] = mapped_column(Integer, default=0)
    refresh_time_total: Mapped[int] = mapped_column(Integer, default=0)
    target_value: Mapped[int] = mapped_column(Integer, default=180)
    target_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    last_was_refresh: Mapped[bool] = mapped_column(Boolean, default=False)
    force_study_only: Mapped[bool] = mapped_column(Boolean, default=False)
    mock_exam_done: Mapped[bool] = mapped_column(Boolean, default=False)
    pending_review: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sos_task: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rolled_options: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
