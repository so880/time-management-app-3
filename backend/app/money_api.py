"""金銭管理（旧 ikaseru）のAPI。

- 記録（支出/サブスク/欲しい物）のCRUD・一括登録（CSV取り込み用）
- 簡易判定・欲しい物評価（旧 logic.js の judgeSimple / judgeWish を移植）
- AI判定（旧 ai.js を移植。キーはSQLiteに保存し、バックエンドがAnthropicを呼ぶ）
- ikaseru互換バックアップJSONの取り込み・書き出し（旧データの引き継ぎ）
設定は settings テーブルの money_* キーに保存する。
"""
import json
import time
import urllib.request
from datetime import date as date_cls

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import crud, models
from .database import get_db

router = APIRouter()

DEFAULT_CATS = ["食費", "外食", "日用品", "交通", "勉強・自己投資", "趣味・娯楽",
                "衣服", "健康・医療", "交際費", "固定費", "その他"]
VALIDITY_LABEL = {"high": "高", "fair": "適正", "low": "安", "unrated": "未判定"}
REC_LABEL = {"buy": "買ってよい", "consider": "要検討", "hold": "今は見送り"}
USAGE_LABEL = {"daily": "ほぼ毎日", "weekly": "週に数回", "monthly": "月に数回", "rare": "ほとんど使っていない"}
NEED_LABEL = {"high": "高い・必要", "mid": "ふつう", "low": "低い・欲しいだけ"}

AI_SYSTEM = ("あなたは個人の家計を支援するアドバイザーです。説教や罪悪感をあおる言い方はせず、"
             "本人の満足度や理由を尊重し、前向きで具体的な助言をします。指定された形式だけで答えてください。")


def yen(n) -> str:
    if n is None:
        return "—"
    return "¥" + f"{round(n):,}"


def ensure_money_defaults(db: Session) -> None:
    """money_* 設定キーの欠損補完（初回起動時）"""
    settings = crud.get_all_settings(db)
    changed = False
    for key, default in (
        ("money_categories", DEFAULT_CATS),
        ("money_allowance", None),
        ("money_api_key", ""),
        ("money_ai_model", "claude-haiku-4-5-20251001"),
        ("money_ai_enabled", False),
        ("money_shopmap", {}),
    ):
        if key not in settings:
            crud.set_setting(db, key, default)
            changed = True
    if changed:
        db.commit()


# ---------- 変換 ----------
def entry_dict(r: models.MoneyEntry) -> dict:
    """旧 entries と同じキー名（camelCase）で返す（フロント移植を容易に）"""
    return {
        "id": r.id, "kind": r.kind, "date": r.date, "amount": r.amount,
        "category": r.category, "detail": r.detail,
        "satisfaction": r.satisfaction, "validity": r.validity,
        "advice": r.advice, "method": r.method,
        "createdAt": r.created_at, "source": r.source,
        "planMonths": r.plan_months, "usage": r.usage, "reason": r.reason,
        "satLog": json.loads(r.sat_log) if r.sat_log else {},
        "need": r.need, "wantLevel": r.want_level,
        "ownedSimilar": r.owned_similar, "betterPoint": r.better_point,
        "recommendation": r.recommendation,
        "recLabel": REC_LABEL.get(r.recommendation or "", None),
    }


def all_entries(db: Session) -> list[models.MoneyEntry]:
    return db.execute(select(models.MoneyEntry)).scalars().all()


def monthly_of(r: models.MoneyEntry) -> float:
    """サブスクは月あたり額に換算（旧 monthlyOf）"""
    if r.kind == "sub" and (r.plan_months or 0) > 0:
        return r.amount / r.plan_months
    return r.amount


# ---------- 簡易判定（旧 judgeSimple の移植） ----------
def _judgement_text(category: str, is_sub: bool, value: float,
                    count: int, avg: float) -> tuple[str, str]:
    """判定の本体（過去 count 件・平均 avg と比較）。judge_simple と JudgeCache が共用"""
    if count == 0:
        return ("unrated",
                f"「{category}」の{'固定費' if is_sub else '支出'}はこれが最初の記録です。"
                "まだ比べる基準がないので判定はお休み。記録が増えるほど、自分にとっての適正額が見えてきます。")
    ratio = value / avg if avg > 0 else 1
    base = f"（同カテゴリ{count}件・平均{yen(avg)}{'/月' if is_sub else ''}との比較）"
    if ratio >= 1.2:
        return ("high",
                f"いつもの「{category}」より高めです{base}。内容が価値に見合っているなら問題ありません。"
                "もし「なんとなく」の出費だったなら、次は小さめの金額で同じ満足が得られないか試してみましょう。")
    if ratio <= 0.8:
        return ("low",
                f"いつもより安く抑えられています{base}。良い選び方です。"
                "無理な我慢でなければ、次も同じ選び方を再現してみましょう。")
    return ("fair",
            f"いつもの範囲内の金額です{base}。無理のないペースです。"
            "続けて記録すると、自分の適正額がさらにはっきりします。")


def judge_simple(db: Session, entry: models.MoneyEntry) -> tuple[str, str]:
    is_sub = entry.kind == "sub"
    value = entry.amount / (entry.plan_months or 1) if is_sub else entry.amount
    past = [e for e in all_entries(db)
            if e.kind == entry.kind and e.category == entry.category and e.id != entry.id]
    vals = [e.amount / (e.plan_months or 1) if e.kind == "sub" else e.amount for e in past]
    avg = (sum(vals) / len(vals)) if vals else 0.0
    return _judgement_text(entry.category, is_sub, value, len(past), avg)


class JudgeCache:
    """一括登録用の高速判定。

    judge_simple は1件ごとに全記録をDBから読むため、大量登録では二乗で遅くなる。
    最初に1回だけ集計（カテゴリ別の件数・平均）を作り、以後はメモリ上で
    同じ基準の判定を行う（メール取り込み・CSV一括登録で使用）。
    """

    def __init__(self, db: Session):
        self.stats: dict[tuple, list] = {}  # (kind, category) -> [count, total]
        for e in all_entries(db):
            v = e.amount / (e.plan_months or 1) if e.kind == "sub" else e.amount
            s = self.stats.setdefault((e.kind, e.category), [0, 0.0])
            s[0] += 1
            s[1] += v

    def judge_and_add(self, row: models.MoneyEntry) -> None:
        """row に判定を書き込み、集計にも加える（DBアクセスなし）"""
        is_sub = row.kind == "sub"
        value = row.amount / (row.plan_months or 1) if is_sub else row.amount
        s = self.stats.setdefault((row.kind, row.category), [0, 0.0])
        count, total = s[0], s[1]
        avg = (total / count) if count else 0.0
        row.validity, row.advice = _judgement_text(row.category, is_sub, value, count, avg)
        row.method = "simple"
        s[0] += 1
        s[1] += value


# ---------- 欲しい物の簡易評価（旧 judgeWish の移植） ----------
def judge_wish(db: Session, entry: models.MoneyEntry) -> tuple[str, str]:
    past = [e for e in all_entries(db) if e.kind == "spend" and e.category == entry.category]
    note = ""
    if past:
        avg = sum(e.amount for e in past) / len(past)
        if avg > 0 and entry.amount >= avg * 3:
            note = f"ふだんの「{entry.category}」（平均{yen(avg)}）と比べて大きめの買い物です。"
    if entry.need == "high":
        return ("buy", f"必要度が高いので、無理のない範囲で買ってOKです。{note}"
                       "買い時の目安：予算に余裕のあるタイミングで、近いうちに。")
    if entry.need == "mid":
        return ("consider", f"必要度は「ふつう」。{note}"
                            "買い時の目安：2週間ほど置いて、それでもまだ欲しければ買い時です。")
    return ("hold", f"今は「欲しいだけ」の段階です。{note}"
                    "買い時の目安：1ヶ月後にもう一度このリストを見て、それでも欲しければ検討しましょう。")


def apply_judgement(db: Session, row: models.MoneyEntry) -> None:
    """種類に応じて簡易判定を書き込む"""
    if row.kind == "wish":
        rec, advice = judge_wish(db, row)
        row.recommendation = rec
        row.advice = advice
    else:
        validity, advice = judge_simple(db, row)
        row.validity = validity
        row.advice = advice
    row.method = "simple"


# ---------- 入力の型 ----------
class EntryBody(BaseModel):
    kind: str                       # spend / sub / wish
    date: str
    amount: float
    category: str
    detail: str = ""
    satisfaction: int | None = None
    planMonths: int | None = None
    usage: str | None = None
    reason: str = ""
    need: str | None = None
    wantLevel: int | None = None
    ownedSimilar: str = ""
    betterPoint: str = ""


class PatchBody(BaseModel):
    satisfaction: int | None = None
    sat_month: str | None = None    # サブスクの月次満足度: 対象の月 "YYYY-MM"
    sat_value: int | None = None    # 0なら解除
    detail: str | None = None
    amount: float | None = None
    category: str | None = None


class BulkItem(BaseModel):
    date: str
    amount: float
    category: str
    detail: str = ""


class BulkBody(BaseModel):
    items: list[BulkItem]


class RenameBody(BaseModel):
    old: str
    new: str


# ---------- 記録のCRUD ----------
@router.get("/api/money/entries")
def list_entries(db: Session = Depends(get_db)):
    ensure_money_defaults(db)
    return [entry_dict(r) for r in all_entries(db)]


@router.post("/api/money/entries")
def create_entry(body: EntryBody, db: Session = Depends(get_db)):
    if body.amount is None or body.amount <= 0:
        raise HTTPException(status_code=400, detail="金額を入力してください")
    if body.kind == "sub" and (body.planMonths is None or body.planMonths < 1):
        raise HTTPException(status_code=400, detail="契約プラン（月数）を入力してください")
    if body.kind == "wish" and not body.detail.strip():
        raise HTTPException(status_code=400, detail="欲しいものの名前を入力してください")
    row = models.MoneyEntry(
        kind=body.kind, date=body.date or date_cls.today().isoformat(),
        amount=body.amount, category=body.category, detail=body.detail.strip(),
        satisfaction=body.satisfaction if body.kind == "spend" else None,
        plan_months=body.planMonths if body.kind == "sub" else None,
        usage=body.usage if body.kind == "sub" else None,
        reason=body.reason if body.kind in ("sub", "wish") else "",
        sat_log="{}" if body.kind == "sub" else None,
        need=body.need if body.kind == "wish" else None,
        want_level=body.wantLevel if body.kind == "wish" else None,
        owned_similar=body.ownedSimilar if body.kind == "wish" else "",
        better_point=body.betterPoint if body.kind == "wish" else "",
        created_at=time.time() * 1000,
    )
    db.add(row)
    db.flush()
    apply_judgement(db, row)
    db.commit()
    return entry_dict(row)


@router.patch("/api/money/entries/{entry_id}")
def patch_entry(entry_id: int, body: PatchBody, db: Session = Depends(get_db)):
    row = db.get(models.MoneyEntry, entry_id)
    if row is None:
        raise HTTPException(status_code=404, detail="記録が見つかりません")
    if body.satisfaction is not None:
        # 同じ★をもう一度 → 解除（旧仕様）。0 は解除として扱う
        row.satisfaction = None if body.satisfaction == 0 else body.satisfaction
    if body.sat_month is not None:
        log = json.loads(row.sat_log) if row.sat_log else {}
        if body.sat_value in (None, 0) or log.get(body.sat_month) == body.sat_value:
            log.pop(body.sat_month, None)
        else:
            log[body.sat_month] = body.sat_value
        row.sat_log = json.dumps(log, ensure_ascii=False)
    if body.category is not None and body.category != row.category:
        # 店名→カテゴリを学習（自動取り込みの精度が上がる）。
        # Amazonは商品ごとに中身が違うため学習しない。
        import re as _re
        old_detail = (row.detail or "").strip()
        row.category = body.category
        if old_detail and not _re.search(r"amazon|アマゾン|amzn", old_detail, _re.I):
            settings = crud.get_all_settings(db)
            shopmap = settings.get("money_shopmap") or {}
            shopmap[old_detail] = body.category
            crud.set_setting(db, "money_shopmap", shopmap)
    if body.detail is not None:
        row.detail = body.detail
    if body.amount is not None and body.amount > 0:
        row.amount = body.amount
    db.commit()
    return entry_dict(row)


@router.post("/api/money/entries/{entry_id}/buy")
def buy_wish(entry_id: int, db: Session = Depends(get_db)):
    """欲しい物 → 今日買った通常支出へ変換（旧 buyWish）"""
    row = db.get(models.MoneyEntry, entry_id)
    if row is None or row.kind != "wish":
        raise HTTPException(status_code=404, detail="欲しい物が見つかりません")
    row.kind = "spend"
    row.date = date_cls.today().isoformat()
    row.satisfaction = None
    row.plan_months = None
    row.recommendation = None
    row.created_at = time.time() * 1000
    apply_judgement(db, row)
    db.commit()
    return entry_dict(row)


@router.delete("/api/money/entries/{entry_id}")
def delete_entry(entry_id: int, db: Session = Depends(get_db)):
    row = db.get(models.MoneyEntry, entry_id)
    if row is not None:
        db.delete(row)
        db.commit()
    return {"ok": True}


def _dup_key(date: str, amount, detail) -> str:
    """重複判定用のキー（フロント csv.js の normKey と同じ考え方）。
    内容は全半角・空白・大文字小文字の揺れを吸収して比較する。"""
    import unicodedata
    d = unicodedata.normalize("NFKC", str(detail or "")).strip().lower()
    d = " ".join(d.split())
    return f"{date}|{float(amount)}|{d}"


@router.post("/api/money/entries/bulk")
def bulk_create(body: BulkBody, db: Session = Depends(get_db)):
    """CSV取り込みの一括登録。店名→カテゴリの学習（shopMap）も更新する。

    登録済みと同じ 日付+金額+内容 の明細はサーバー側でも自動でスキップする
    （期間の重なるCSVをいつ何度取り込んでも二重計上されない保険）。
    件数つきで数えるので、同じ日に同額同店で複数回買った記録は正しく残る。
    """
    from collections import Counter
    settings = crud.get_all_settings(db)
    shopmap = settings.get("money_shopmap") or {}
    existing = Counter(_dup_key(e.date, e.amount, e.detail)
                       for e in all_entries(db) if e.kind == "spend")
    judge = JudgeCache(db)  # 判定は集計キャッシュで高速に（1件ごとの全件読み直しをしない）
    added = 0
    skipped = 0
    for it in body.items:
        if it.amount is None or it.amount <= 0:
            continue
        key = _dup_key(it.date, it.amount, it.detail)
        if existing[key] > 0:
            existing[key] -= 1
            skipped += 1
            continue
        row = models.MoneyEntry(
            kind="spend", date=it.date, amount=it.amount,
            category=it.category, detail=it.detail,
            created_at=time.time() * 1000, source="import",
        )
        judge.judge_and_add(row)
        db.add(row)
        if it.detail:
            shopmap[it.detail] = it.category
        added += 1
    crud.set_setting(db, "money_shopmap", shopmap)
    db.commit()
    return {"ok": True, "added": added, "skipped": skipped}


@router.post("/api/money/amazon/reset")
def reset_amazon_enrichment(db: Session = Depends(get_db)):
    """📦突き合わせで付けた商品名・カテゴリを一括で取り消す。

    金額・日付・記録そのものは残し、内容を「AMAZON.CO.JP」・カテゴリを
    「その他」に戻す（正確なデータが揃ってからやり直すための機能）。
    """
    n = 0
    for r in all_entries(db):
        if r.kind == "spend" and (r.detail or "").startswith("Amazon: "):
            r.detail = "AMAZON.CO.JP"
            r.category = "その他"
            n += 1
    db.commit()
    return {"ok": True, "reset": n}


# ---------- カテゴリの改名（過去の記録・店名学習もそろえる） ----------
@router.post("/api/money/categories/rename")
def rename_category(body: RenameBody, db: Session = Depends(get_db)):
    settings = crud.get_all_settings(db)
    cats = settings.get("money_categories") or DEFAULT_CATS
    if body.new in cats:
        raise HTTPException(status_code=400, detail="同じ名前のカテゴリがすでにあります")
    if body.old not in cats:
        raise HTTPException(status_code=404, detail="カテゴリが見つかりません")
    cats[cats.index(body.old)] = body.new
    crud.set_setting(db, "money_categories", cats)
    for r in all_entries(db):
        if r.category == body.old:
            r.category = body.new
    shopmap = settings.get("money_shopmap") or {}
    for k in list(shopmap.keys()):
        if shopmap[k] == body.old:
            shopmap[k] = body.new
    crud.set_setting(db, "money_shopmap", shopmap)
    db.commit()
    return {"ok": True, "categories": cats}


# ---------- バックアップ（ikaseru互換JSON） ----------
@router.post("/api/money/backup/import")
def import_backup(obj: dict, db: Session = Depends(get_db)):
    """旧アプリの「バックアップを書き出す」で作ったJSONを取り込む（全置き換え）"""
    if obj.get("app") != "ikaseru" or not isinstance(obj.get("entries"), list):
        raise HTTPException(status_code=400, detail="このファイルは ikaseru のバックアップではありません")
    for r in all_entries(db):
        db.delete(r)
    count = 0
    for e in obj["entries"]:
        if not isinstance(e, dict):
            continue
        db.add(models.MoneyEntry(
            kind=str(e.get("kind") or "spend"),
            date=str(e.get("date") or date_cls.today().isoformat()),
            amount=float(e.get("amount") or 0),
            category=str(e.get("category") or "その他"),
            detail=str(e.get("detail") or ""),
            satisfaction=e.get("satisfaction"),
            validity=e.get("validity"),
            advice=str(e.get("advice") or ""),
            method=str(e.get("method") or "simple"),
            created_at=float(e.get("createdAt") or 0),
            source=str(e.get("source") or ""),
            plan_months=e.get("planMonths"),
            usage=e.get("usage"),
            reason=str(e.get("reason") or ""),
            sat_log=json.dumps(e.get("satLog"), ensure_ascii=False) if e.get("satLog") else None,
            need=e.get("need"),
            want_level=e.get("wantLevel"),
            owned_similar=str(e.get("ownedSimilar") or ""),
            better_point=str(e.get("betterPoint") or ""),
            recommendation=e.get("recommendation"),
        ))
        count += 1
    if isinstance(obj.get("cats"), list) and obj["cats"]:
        crud.set_setting(db, "money_categories", obj["cats"])
    s = obj.get("settings") or {}
    if s.get("allowance") is not None:
        crud.set_setting(db, "money_allowance", s["allowance"])
    if s.get("apiKey"):
        crud.set_setting(db, "money_api_key", s["apiKey"])
    if s.get("aiModel"):
        crud.set_setting(db, "money_ai_model", s["aiModel"])
    crud.set_setting(db, "money_ai_enabled", bool(s.get("aiEnabled")))
    if isinstance(obj.get("shopMap"), dict):
        crud.set_setting(db, "money_shopmap", obj["shopMap"])
    db.commit()
    return {"ok": True, "imported": count}


@router.get("/api/money/backup/export")
def export_backup(db: Session = Depends(get_db)):
    """ikaseru互換のバックアップJSONを返す（旧アプリでも読める）"""
    from datetime import datetime
    settings = crud.get_all_settings(db)
    return {
        "app": "ikaseru",
        "version": 2,
        "exportedAt": datetime.now().isoformat(),
        "entries": [entry_dict(r) for r in all_entries(db)],
        "cats": settings.get("money_categories") or DEFAULT_CATS,
        "settings": {
            "allowance": settings.get("money_allowance"),
            "apiKey": settings.get("money_api_key") or "",
            "aiModel": settings.get("money_ai_model") or "claude-haiku-4-5-20251001",
            "aiEnabled": bool(settings.get("money_ai_enabled")),
        },
        "shopMap": settings.get("money_shopmap") or {},
    }


# ---------- AI判定（バックエンドがAnthropicを呼ぶ・旧 ai.js の移植） ----------
def call_claude(db: Session, system_text: str, user_text: str, max_tokens: int = 500) -> str:
    settings = crud.get_all_settings(db)
    api_key = settings.get("money_api_key") or ""
    if not api_key:
        raise HTTPException(status_code=400, detail="APIキーが未設定です")
    body = json.dumps({
        "model": settings.get("money_ai_model") or "claude-haiku-4-5-20251001",
        "max_tokens": max_tokens,
        "system": system_text,
        "messages": [{"role": "user", "content": user_text}],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body,
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            data = json.load(res)
    except urllib.error.HTTPError as e:
        raise HTTPException(status_code=502,
                            detail=f"APIエラー({e.code}) {e.read()[:200].decode('utf-8', 'ignore')}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"接続に失敗しました: {e}")
    try:
        return data["content"][0]["text"]
    except (KeyError, IndexError):
        return ""


def extract_json(text: str):
    import re
    m = re.search(r"\{[\s\S]*\}", text or "")
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


@router.post("/api/money/ai/test")
def ai_test(db: Session = Depends(get_db)):
    text = call_claude(db, "テストです。", "接続テストです。「OK」とだけ返してください。", 20)
    return {"ok": True, "text": text}


@router.post("/api/money/ai/judge/{entry_id}")
def ai_judge(entry_id: int, db: Session = Depends(get_db)):
    """記録1件のAI判定（失敗時はHTTPエラー。フロントは簡易判定のまま続行する）"""
    row = db.get(models.MoneyEntry, entry_id)
    if row is None:
        raise HTTPException(status_code=404, detail="記録が見つかりません")

    lines = []
    if row.kind == "wish":
        lines.append("欲しい物の評価をお願いします:")
        lines.append(f"- 名前: {row.detail or '（名前なし）'}")
        lines.append(f"- 値段: {yen(row.amount)}")
        lines.append(f"- カテゴリ: {row.category}")
        lines.append(f"- 必要度: {NEED_LABEL.get(row.need or '', row.need)}")
        if row.want_level:
            lines.append(f"- どれくらい欲しいか: {row.want_level}/5")
        if row.reason:
            lines.append(f"- 欲しい理由: {row.reason}")
        if row.owned_similar:
            lines.append(f"- 似ていて既に持っている物: {row.owned_similar}")
        if row.better_point:
            lines.append(f"- 欲しい物のどこが良いか: {row.better_point}")
        past = [e for e in all_entries(db) if e.kind == "spend" and e.category == row.category]
        if past:
            avg = sum(e.amount for e in past) / len(past)
            lines.append(f"- 参考: 同カテゴリの通常支出の平均は {yen(avg)}（{len(past)}件）")
        lines.append("")
        lines.append("buy（買ってよい）/ consider（要検討）/ hold（今は見送り）のどれかで結論を出し、"
                     "理由と「いつ買うべきかの目安」を含む前向きなアドバイスを書いてください。")
        lines.append('出力は次のJSONのみ: {"recommendation":"buy または consider または hold","advice":"140字以内の日本語"}')
        j = extract_json(call_claude(db, AI_SYSTEM, "\n".join(lines), 400))
        if j and j.get("recommendation") in REC_LABEL and j.get("advice"):
            row.recommendation = j["recommendation"]
            row.advice = str(j["advice"])
            row.method = "ai"
            db.commit()
        return entry_dict(row)

    is_sub = row.kind == "sub"
    lines.append("判定対象の記録:")
    lines.append("- 種類: " + ("固定費・サブスク" if is_sub else "通常の支出"))
    if is_sub:
        lines.append(f"- 支払額: {yen(row.amount)}（{row.plan_months}ヶ月プラン → 月あたり {yen(row.amount / (row.plan_months or 1))}）")
        if row.reason:
            lines.append(f"- 契約理由: {row.reason}")
        if row.usage:
            lines.append(f"- 使用頻度: {USAGE_LABEL.get(row.usage, row.usage)}")
        log = json.loads(row.sat_log) if row.sat_log else {}
        if log:
            lines.append("- 月次満足度: " + ", ".join(f"{k}={log[k]}" for k in sorted(log)))
    else:
        lines.append(f"- 金額: {yen(row.amount)}")
        if row.satisfaction is not None:
            lines.append(f"- 満足感: {row.satisfaction}/5")
    lines.append(f"- カテゴリ: {row.category}")
    if row.detail:
        lines.append(f"- 詳細: {row.detail}")
    past = [e for e in all_entries(db)
            if e.kind == row.kind and e.category == row.category and e.id != row.id][-15:]
    if past:
        lines.append(f"同じカテゴリの過去の記録（最新{len(past)}件）:")
        for e in past:
            v = f"{yen(e.amount / (e.plan_months or 1))}/月" if e.kind == "sub" else yen(e.amount)
            sat = f"（満足感{e.satisfaction}）" if e.satisfaction is not None else ""
            lines.append(f"- {e.date} {v} {e.detail or ''}{sat}")
    else:
        lines.append("同じカテゴリの過去の記録: なし")
    lines.append("")
    lines.append(f"この{'固定費' if is_sub else '支出'}の妥当性を high（高め）/ fair（適正）/ low（安く抑えた）のどれかで判定し、"
                 "なぜその判定か＋次にどう生かすかを前向きな日本語で書いてください。")
    lines.append('出力は次のJSONのみ: {"validity":"high または fair または low","advice":"140字以内の日本語"}')
    j = extract_json(call_claude(db, AI_SYSTEM, "\n".join(lines), 400))
    if j and j.get("validity") in ("high", "fair", "low") and j.get("advice"):
        row.validity = j["validity"]
        row.advice = str(j["advice"])
        row.method = "ai"
        db.commit()
    return entry_dict(row)


@router.post("/api/money/ai/review")
def ai_review(db: Session = Depends(get_db)):
    """月次レビュー（旧 aiMonthlyReview の移植）"""
    from datetime import datetime
    entries = all_entries(db)
    settings = crud.get_all_settings(db)
    ym = datetime.now().strftime("%Y-%m")
    prev_d = datetime.now().replace(day=1)
    prev_ym = (prev_d.replace(year=prev_d.year - 1, month=12)
               if prev_d.month == 1 else prev_d.replace(month=prev_d.month - 1)).strftime("%Y-%m")

    sp = [e for e in entries if e.kind == "spend" and e.date[:7] == ym]
    sp_total = sum(e.amount for e in sp)
    prev_total = sum(e.amount for e in entries if e.kind == "spend" and e.date[:7] == prev_ym)
    sub_list = [e for e in entries if e.kind == "sub"]
    sub_monthly = sum(monthly_of(e) for e in sub_list)
    allowance = settings.get("money_allowance")

    lines = [f"今月（{ym}）の家計データ:"]
    if allowance is not None:
        lines.append(f"- 毎月の仕送り（収入）: {yen(allowance)}")
        lines.append(f"- 収支: {yen(float(allowance) - sp_total - sub_monthly)}")
    lines.append(f"- 通常支出の合計: {yen(sp_total)}（{len(sp)}件）")
    lines.append(f"- 先月の通常支出: {yen(prev_total)}")
    lines.append(f"- サブスク月額合計: {yen(sub_monthly)}（{len(sub_list)}件・年額換算 {yen(sub_monthly * 12)}）")

    bd: dict[str, float] = {}
    for e in sp:
        bd[e.category] = bd.get(e.category, 0) + e.amount
    if bd:
        lines.append("カテゴリ別内訳:")
        for c, a in sorted(bd.items(), key=lambda x: -x[1])[:6]:
            pct = round(a / sp_total * 100) if sp_total else 0
            lines.append(f"- {c}: {yen(a)}（{pct}%）")
    if sub_list:
        lines.append("サブスク一覧:")
        for e in sub_list:
            log = json.loads(e.sat_log) if e.sat_log else {}
            s = f"・今月の満足度{log[ym]}" if ym in log else ""
            lines.append(f"- {e.detail or e.category} {yen(monthly_of(e))}/月・{USAGE_LABEL.get(e.usage or '', '')}{s}")
    big = sorted(sp, key=lambda e: -e.amount)[:8]
    if big:
        lines.append("今月の大きい支出:")
        for e in big:
            sat = f"（満足感{e.satisfaction}）" if e.satisfaction is not None else ""
            lines.append(f"- {e.date} {yen(e.amount)} {e.category} {e.detail or ''}{sat}")
    lines.append("")
    lines.append("このデータをもとに、金の使い方のどこを直すべきかを明確にする「今月のレビュー」を日本語で書いてください。"
                 "良かった点1〜2個と、具体的な見直し提案2〜4個（金額の目安つき）を、短い箇条書きで。前向きなトーンで。")
    return {"text": call_claude(db, AI_SYSTEM, "\n".join(lines), 800)}
