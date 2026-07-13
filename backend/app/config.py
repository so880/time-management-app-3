"""定数・初期設定・各種パス。

既存アプリ（Streamlit版）の config.py を移植したもの。
DEFAULT_SETTINGS の内容・キー名は既存の settings.json と完全互換。
"""
from pathlib import Path

# === パス：このファイルの場所（backend/app/）を基準にする ===
# どこから起動しても必ず backend/data/ を使う（既存 config.py と同じ考え方）
_BASE_DIR = Path(__file__).resolve().parent.parent  # .../backend
DATA_DIR = _BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_FILE = DATA_DIR / "focus_cafe.db"

# 既存データ（移行元）ファイルのパス（段階3で使用）
LEGACY_SETTINGS_FILE = DATA_DIR / "settings.json"
LEGACY_LOG_FILE = DATA_DIR / "activity_log.csv"
LEGACY_SESSION_FILE = DATA_DIR / "session_state.json"

# === 定数（既存 config.py より） ===
SHORT_TASK_THRESHOLD = 40  # これ以下(分)の勉強課題は「短い課題」
GOAL_CAP = 6               # 目標は最大6個まで
GAME_LIST = ["イナイレ", "スト６", "バウンティ", "ドラゴンボールスクアドラ"]
SOS_LIST = ["瞑想", "深呼吸", "腹筋30回", "昼寝", "読書", "Geminiと話す"]

# === ゲーム解放の時間帯（20:00〜翌2:59。ユーザー確認済みで2:59に統一） ===
GAME_UNLOCK_START_HOUR = 20  # この時刻以降（含む）
GAME_UNLOCK_END_HOUR = 3     # この時刻より前（3:00になったら未解放）

# === 初期設定（既存 config.py の DEFAULT_SETTINGS をそのまま移植） ===
DEFAULT_SETTINGS = {
    "toeic_date": "2026-05-24",
    "intern_date": "2026-06-01",
    "daily_hours_toeic": 3,
    "daily_hours_intern": 2,
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
    "daily_window": [      # 曜日別の「勉強に使える時間帯」(月=0 ... 日=6)
        {"start": "09:00", "end": "22:00"},
        {"start": "09:00", "end": "22:00"},
        {"start": "09:00", "end": "22:00"},
        {"start": "09:00", "end": "22:00"},
        {"start": "09:00", "end": "22:00"},
        {"start": "10:00", "end": "23:00"},
        {"start": "10:00", "end": "23:00"},
    ],
    "goals": [             # 目標（可変個）
        {"name": "TOEIC", "date": "2026-05-24", "hours": 3},
        {"name": "インターン", "date": "2026-06-01", "hours": 2},
    ],
    "study_list_disabled": [],   # 無効化した通常勉強項目
    "focus_study_list_disabled": [],
    "refresh_list_disabled": [],
    "mustdo_list_disabled": [],
    # --- ゲームブロック機能 ---
    "block_enabled": True,        # ブロック機能のON/OFF
    "block_process_list": [],     # ブロック対象のプロセス名
    # --- リキッドグラス風UI ---
    "liquid_glass_enabled": False,
    "toeic_name": "TOEIC",
    "intern_name": "インターン",
    "bg_url": "https://images.unsplash.com/photo-1497935586351-b67a49e012bf?q=80&w=2000&auto=format&fit=crop",
    "bg_mode": "カフェ画像",
    "bg_history": [],       # 過去にアップロードした画像ファイル名の履歴
    "bg_current_file": "",  # 現在選択中のアップロード画像ファイル名
    "snd_cafe_url": "e_04ZrNroTo",   # 環境音「カフェ」のYouTube URL/ID
    "snd_chat_url": "bZ2XhA_kXYQ",   # 環境音「雑踏」のYouTube URL/ID
    "snd_relax_url": "vPhg6sc1Mk4",  # 環境音「波と鯨」のYouTube URL/ID
    "mustdo_list": [],   # 今日絶対やる（あれば勉強の抽選はここからのみ）
    "study_list": [
        "Santa Part7長文の写経", "英語の記事の写経", "Gemini提案英文の写経",
        "プログラミング(paiza)", "洋楽の本気カラオケ(英語発音)",
        "Santa Part3・4のオーバーラッピング", "海外車レビュー記事の音読・写経",
        "Santa 単語", "Geminiと面接練習"
    ],
    "focus_study_list": ["大学の履修について考える"],
    "refresh_list": [
        "料理探し", "読書", "仮眠", "腕立て30回", "腹筋30回",
        "ダンベル30回", "洋楽カラオケ", "机の掃除", "床の片づけ",
        "掃除機掛け", "スト6 コンボ練習"
    ]
}
