"""APIの入出力の型（Pydantic。FastAPI公式の使い方に準拠）"""
from pydantic import BaseModel


class ChooseBody(BaseModel):
    """ルーレット結果から実行タスクを選んで集中モードを開始する"""
    category: str   # "勉強" or "気分転換"
    task: str


class ReviewBody(BaseModel):
    """ふりかえりの保存（すべて任意）"""
    save_details: bool = True   # False=スキップ（記録のみ）
    done_text: str = ""
    progress: str = ""          # "1"〜"5" または ""（未記入）
    focus: str = ""
    satisfaction: str = ""
    remove_mustdo: bool = False  # 「終わったのでリストから消す」


class LogBody(BaseModel):
    """履歴の追加（クイックスタート小窓などの外部連携用の入り口）"""
    content: str
    category: str = "勉強"
    minutes: int = 0
    bgm: str = "設定BGM"
    done_text: str = ""
    progress: str = ""
    focus: str = ""
    satisfaction: str = ""
    note: str = ""
    add_to_today: bool = True   # True なら今日の合計にも加算する
