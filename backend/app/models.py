"""テーブル定義（SQLAlchemy 2.0 の公式スタイル）。

- settings      : アプリ設定（1キー＝1行。値は JSON）
- activity_log  : 履歴（勉強・気分転換などの記録。今日の勉強時間はここの合計＝唯一の元データ）
- daily_state   : その日の状態（id=1 の1行）
- 外部キー（ForeignKey）は database.py で SQLite の foreign_keys を有効にしている（2026-11-06）
- 既存 DB の構造の変更は migrate.upgrade（PRAGMA user_version で1回だけ）
"""
from typing import Optional

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from . import policy
from .config import DEFAULT_STUDY_TARGET_MIN
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
    __table_args__ = (Index("ix_activity_log_date", "date"),)

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
    done: Mapped[bool] = mapped_column(Boolean, default=False)  # 完了したか


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
    block_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("schedule_blocks.id", ondelete="CASCADE"))   # 時間割を消すと休講も消える


class Assignment(Base):
    """🎲 ルーレット項目（2026-09 に「課題」と「通常勉強／重点」を統合）。

    勉強の抽選はここから行う（progress<100 かつ enabled の項目）。
    - category … タグ（就活／大学／私用／その他）
    - due_date … 期限（任意。"" なら期限なし）。期限があればカレンダー・今日やることに出る
    - focus    … 重点（抽選で3倍出やすい）
    - recurring_id が入っている行は「毎週の項目」から自動生成された週ごとのインスタンス
    テーブル名は互換のため assignments のまま。
    """
    __tablename__ = "assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200))
    due_date: Mapped[str] = mapped_column(String(10), default="")  # "YYYY-MM-DD" / ""=期限なし
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0〜100（100=完了）
    note: Mapped[str] = mapped_column(Text, default="")     # コメント（メモ）
    created: Mapped[str] = mapped_column(String(19), default="")
    recurring_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("recurring_assignments.id", ondelete="SET NULL"), nullable=True)
    category: Mapped[str] = mapped_column(String(20), default="その他")  # 就活/大学/私用/その他
    focus: Mapped[bool] = mapped_column(Boolean, default=False)    # 重点（抽選3倍）
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)   # 抽選に出す


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
    application_id=NULL は「会社に紐づかない就活予定」（合同説明会など。API では 0 として受け渡す）。
    choice=0 は確定した日程、1以上は「第N希望」の候補日
    （同じ会社の候補日同士は日程被りとして扱わない）。
    日程同士が重なった場合は、応募先の priority を使って優先順位を表示する。
    """
    __tablename__ = "job_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("job_applications.id", ondelete="CASCADE"), nullable=True)   # NULL=紐づけなし
    label: Mapped[str] = mapped_column(String(100), default="")   # 例: 一次面接
    date: Mapped[str] = mapped_column(String(10))                 # 開始日 "YYYY-MM-DD"
    end_date: Mapped[str] = mapped_column(String(10), default="") # 期間の最終日（空=1日）
    start: Mapped[str] = mapped_column(String(5), default="")     # "HH:MM"（空=終日）
    end: Mapped[str] = mapped_column(String(5), default="")
    choice: Mapped[int] = mapped_column(Integer, default=0)       # 0=確定 / 1〜=第N希望


class JobDoc(Base):
    """就活の応募先ごとの自由メモ（ES・面接メモなど、タイトルは自分で決める）"""
    __tablename__ = "job_docs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("job_applications.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(100))        # 例: ES / 一次面接メモ
    body: Mapped[str] = mapped_column(Text, default="")


# （旧 habit_checks テーブルは 2026-09 の統合で todo_completions に置き換え、migrate で削除済み）


# やること（todo_items.kind）の種類。文字列は DB に保存されている値なので変えないこと
KIND_MUST = "must"          # 今日の必須
KIND_HABIT = "habit"        # 習慣
KIND_PERIODIC = "periodic"  # 週単位・不定期


class TodoItem(Base):
    """「やること」の統合テーブル（2026-09 決定事項）。

    kind:
      must     … 今日の必須（date を持つ。その日限り。翌日に繰り越さない）
      habit    … 毎日の習慣（weekdays="0,1,..." と時刻。解放判定に含む）
      periodic … 週単位・不定期（every_days。記録のみ、解放判定に含めない）
    """
    __tablename__ = "todo_items"
    __table_args__ = (Index("ix_todo_items_kind_date", "kind", "date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(10))
    title: Mapped[str] = mapped_column(String(200))
    date: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)      # must のみ "YYYY-MM-DD"
    weekdays: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # habit: "0,1,2,3,4,5,6"
    every_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)   # periodic: 0=不定期
    start: Mapped[str] = mapped_column(String(5), default="")   # habit の時刻（表示・通知用）
    end: Mapped[str] = mapped_column(String(5), default="")
    min_action: Mapped[str] = mapped_column(Text, default="")   # habit の「5分だけ着手」の最小単位
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created: Mapped[str] = mapped_column(String(19), default="")
    sort: Mapped[int] = mapped_column(Integer, default=0)
    # 2026-09-22 追加（起動時の「今日の必須」画面用。must のみ使う）
    tag: Mapped[str] = mapped_column(String(30), default="")            # 就活/大学/私用/その他/自由記入
    due_date: Mapped[str] = mapped_column(String(10), default="")       # 締切 "YYYY-MM-DD"（空=なし）
    asg_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("assignments.id", ondelete="SET NULL"), nullable=True)  # 格上げ元のルーレット項目


class TodoCompletion(Base):
    """やることの完了記録（todo_items.id に紐づく。タイトル文字列では判定しない）"""
    __tablename__ = "todo_completions"
    __table_args__ = (UniqueConstraint("item_id", "date", name="uq_todo_completion"),
                      Index("ix_todo_completions_date", "date"))

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(Integer, ForeignKey("todo_items.id", ondelete="CASCADE"))
    date: Mapped[str] = mapped_column(String(10))
    at: Mapped[str] = mapped_column(String(5), default="")        # 完了時刻 "HH:MM"
    level: Mapped[str] = mapped_column(String(10), default="full")  # full / min


class PcSession(Base):
    """PC使用の自動記録（最前面ウィンドウのセッション）。pc_tracker.py が書き込む"""
    __tablename__ = "pc_sessions"
    __table_args__ = (Index("ix_pc_sessions_start_ts", "start_ts"),)

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
    target_value: Mapped[int] = mapped_column(Integer, default=DEFAULT_STUDY_TARGET_MIN)
    target_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    last_was_refresh: Mapped[bool] = mapped_column(Boolean, default=False)
    force_study_only: Mapped[bool] = mapped_column(Boolean, default=False)
    mock_exam_done: Mapped[bool] = mapped_column(Boolean, default=False)
    pending_review: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sos_task: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rolled_options: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class UnlockRequest(Base):
    """解除申請（AI 審査）の記録。旧 settings["emergency_unlocks"]（2026-11-06 に表へ移行）。
    承認されたときに有効になる時間帯は settings["emergency_unlock_day"]（ワーカーが読む）"""
    __tablename__ = "unlock_requests"
    __table_args__ = (Index("ix_unlock_requests_ts", "ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[str] = mapped_column(String(19))                 # 申請日時 "YYYY-MM-DD HH:MM:SS"
    reason: Mapped[str] = mapped_column(Text, default="")
    gates: Mapped[str] = mapped_column(String(20), default=policy.ALL_GATES)
    start: Mapped[str] = mapped_column(String(5), default="")
    end: Mapped[str] = mapped_column(String(5), default="")
    approved: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)   # 古い記録は不明（NULL）
    judge: Mapped[str] = mapped_column(Text, default="")        # 審査の理由


class ExemptionRequest(Base):
    """面接などの特例の申請（Claude 審査）。旧 settings["exemption_requests"]（2026-11-06 に表へ移行）。
    有効かどうかは Claude の決定ファイル（logs/claude_exemptions.json）で決める（exemption_api）"""
    __tablename__ = "exemption_requests"
    __table_args__ = (Index("ix_exemption_requests_date", "date"),)

    id: Mapped[str] = mapped_column(String(16), primary_key=True)   # 申請ID（8桁の16進）
    created: Mapped[str] = mapped_column(String(19))
    date: Mapped[str] = mapped_column(String(10))
    start: Mapped[str] = mapped_column(String(5))
    end: Mapped[str] = mapped_column(String(5))
    minutes: Mapped[int] = mapped_column(Integer, default=0)
    company: Mapped[str] = mapped_column(String(60), default="")
    kind: Mapped[str] = mapped_column(String(30), default="")
    evidence: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending/approved/rejected/cancelled
    decision_reason: Mapped[str] = mapped_column(Text, default="")
    decision_at: Mapped[str] = mapped_column(String(20), default="")
    decision_by: Mapped[str] = mapped_column(String(20), default="")
    over_cap: Mapped[bool] = mapped_column(Boolean, default=False)    # 週の上限を超えた承認（無効）


class GoogleEvent(Base):
    """Google メインカレンダーから読み取った予定（表示・面接などの特例の判定用）。
    旧 settings["gcal_google_events"]（2026-11-06 に表へ移行）。読み取りのたびに全件入れ替える"""
    __tablename__ = "google_events"
    __table_args__ = (Index("ix_google_events_dates", "date", "end_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(200), default="")   # Google 側の ID
    title: Mapped[str] = mapped_column(String(300), default="")
    allday: Mapped[bool] = mapped_column(Boolean, default=False)
    date: Mapped[str] = mapped_column(String(10))
    end_date: Mapped[str] = mapped_column(String(10))
    start: Mapped[str] = mapped_column(String(5), default="")
    end: Mapped[str] = mapped_column(String(5), default="")
    location: Mapped[str] = mapped_column(Text, default="")
    created: Mapped[str] = mapped_column(String(19), default="")     # 作成日時（特例の「24時間前」の判定）
    # 面接などの特例の判定用（2026-11-07 依頼者の承認）。Apps Script が古い・列の追加前のデータは None＝特例にしない
    recurring: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)    # 繰り返しの予定か
    owned_by_me: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)  # 自分が作った予定か（招待でないか）
