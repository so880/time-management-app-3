"""定数・初期設定・各種パス。

DEFAULT_SETTINGS は新しい DB（settings が空）に入れる初期設定。
値の多くは旧版（Streamlit 版）の config.py から引き継いだもの。
"""
from pathlib import Path

# === パス：このファイルの場所（backend/app/）を基準にする ===
# どこから起動しても必ず backend/data/ を使う
_BASE_DIR = Path(__file__).resolve().parent.parent  # .../backend
DATA_DIR = _BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_FILE = DATA_DIR / "focus_cafe.db"

# === 定数 ===
SHORT_TASK_THRESHOLD = 40  # これ以下(分)の勉強課題は「短い課題」
GOAL_CAP = 6               # 目標は最大6個まで
DEFAULT_STUDY_TARGET_MIN = 180   # 今日の勉強目標（分）の既定値。日付が変わったときもこの値に戻す
GAME_LIST = ["イナイレ", "スト６", "バウンティ", "ドラゴンボールスクアドラ"]
SOS_LIST = ["瞑想", "深呼吸", "腹筋30回", "昼寝", "読書", "Geminiと話す"]

# ゲームができる時間帯は backend/app/policy.py（GAME_WINDOW）に集約

# === 初期設定（新しい DB のときだけ使う） ===
DEFAULT_SETTINGS = {
    "study_dur_min": 30,   # 勉強タスクのランダム所要時間（最短・分）※30分固定
    "study_dur_max": 60,   # 勉強タスクのランダム所要時間（最長・分）
    "daily_routine": [     # 曜日別の「勉強できる時間帯」(複数OK・月=0 ... 日=6)
        [{"start": "09:00", "end": "22:00"}],
        [{"start": "09:00", "end": "22:00"}],
        [{"start": "09:00", "end": "22:00"}],
        [{"start": "09:00", "end": "22:00"}],
        [{"start": "09:00", "end": "22:00"}],
        [{"start": "10:00", "end": "23:00"}],
        [{"start": "10:00", "end": "23:00"}],
    ],
    "goals": [             # 目標（可変個）
        {"name": "TOEIC", "date": "2026-05-24", "hours": 3},
        {"name": "インターン", "date": "2026-06-01", "hours": 2},
    ],
    "refresh_list_disabled": [],
    # --- ゲームブロック機能 ---
    "block_enabled": True,        # ブロック機能のON/OFF
    "block_process_list": [],     # ブロック対象のプロセス名
    "bg_url": "https://images.unsplash.com/photo-1497935586351-b67a49e012bf?q=80&w=2000&auto=format&fit=crop",
    "bg_mode": "カフェ画像",
    "bg_history": [],       # 過去にアップロードした画像ファイル名の履歴
    "bg_current_file": "",  # 現在選択中のアップロード画像ファイル名
    "snd_cafe_url": "e_04ZrNroTo",   # 環境音「カフェ」のYouTube URL/ID
    "snd_chat_url": "bZ2XhA_kXYQ",   # 環境音「雑踏」のYouTube URL/ID
    "snd_relax_url": "vPhg6sc1Mk4",  # 環境音「波と鯨」のYouTube URL/ID
    # 勉強の抽選項目（旧 study_list / focus_study_list）は assignments テーブル（ルーレット項目）へ移行済み
    "refresh_list": [
        "料理探し", "読書", "仮眠", "腕立て30回", "腹筋30回",
        "ダンベル30回", "洋楽カラオケ", "机の掃除", "床の片づけ",
        "掃除機掛け", "スト6 コンボ練習"
    ]
}
