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


class WidgetPing(BaseModel):
    """小窓（quick_widget.py）からの生存通知。小窓は {"alive": true, "running": ...} を送り、
    計測中だけ task / elapsed_sec を付ける（alive など知らない項目は無視する）"""
    running: bool = False
    task: str = ""
    elapsed_sec: int = 0        # 小窓の計測開始からの経過秒（本体で 0〜MAX_LOG_MINUTES 分に収める）


class WidgetStart(BaseModel):
    """アプリから小窓のタイマーを開始させる。
    task が空のときは本体が 400「task を指定してください」を返す（以前の返事のまま保つため既定値は空）"""
    task: str = ""


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
    # 計測を終えた時刻（UNIX 秒・任意）。小窓が送れなかった記録を後で送り直すときに付ける。
    # 無ければ受け取った時刻を終わりとみなす
    end_at: float | None = None
