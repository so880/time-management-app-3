"""利用通知メールの自動取り込み（リアルタイム家計簿の入口）。

- Gmail(IMAP)を数分おきにチェックし、カードの利用通知メール（三井住友カード・
  JCBデビット等）から 日付・金額・利用先 を読み取って「通常の支出」に自動登録する。
- 設定は settings テーブルの mail_* キーに保存する（アプリパスワードはこのPCのDBのみ）。
- 通常の自動チェックは、有効化した時点より後に届いたメール（INBOXのUID基準）だけが対象。
- 「過去メールの取り込み」（backfill)は、指定日以降の通知メールを全件さかのぼって取り込む
  （Gmailの「すべてのメール」を対象。バックグラウンドで実行し進行状況を mail_status に記録）。
- 登録時は 日付+金額+利用先 の重複ガード付き。CSV取り込み（答え合わせ）側では
  メール由来の記録と ±2日・同額 の明細が「メール登録済みの疑い」になる（csv.js）。
"""
import email
import email.utils
import imaplib
import re
import threading
import time
import unicodedata
from datetime import datetime
from email.header import decode_header

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import crud, models
from .database import SessionLocal, get_db
from .money_api import JudgeCache, _dup_key, all_entries, ensure_money_defaults

router = APIRouter()

IMAP_HOST = "imap.gmail.com"
POLL_SECONDS = 300  # 自動チェックの間隔（5分）

# 通知メールの差出人ドメイン（設定 mail_senders で上書き可能）
DEFAULT_SENDERS = ["vpass.ne.jp", "smbc-card.com", "jcb.co.jp", "qa.jcb.co.jp"]

# ---- 本文の読み取りパターン（表記揺れに幅を持たせている） ----
_AMOUNT_LABELS = r"(?:ご利用金額|利用金額|ご利用額|取引金額|決済金額|お支払金額|お支払い金額|ご請求金額|お引落金額|お引き落とし金額"
# 「◯◯金額 … 1,234円」（間に】や：・改行・空白などが入ってもよい）
AMOUNT_RE = re.compile(_AMOUNT_LABELS + r")[^0-9\-]{0,20}([0-9,，]+)\s*円")
# 「◯◯金額（円）：1234」のように 円 が後ろに付かない形式の保険
AMOUNT_RE2 = re.compile(_AMOUNT_LABELS + r")（?\(?円?\)?）?[ \t]*[:：][ \t]*([0-9,，]+)")
MERCHANT_RE = re.compile(
    r"(?:ご利用先|利用先|ご利用店舗名|ご利用店名|ご利用加盟店|加盟店名|加盟店|ご利用場所|利用店名)"
    r"[】\s]*[:：]?[ \t]*(.+)")
DATE_RE = re.compile(r"(?:ご利用日時|利用日時|ご利用日|利用日|取引日時|取引日)[^0-9]{0,12}(20\d{2})[/\-年.](\d{1,2})[/\-月.](\d{1,2})")
CANCEL_RE = re.compile(r"取消|取り消し|キャンセル|返品")

# IMAPの日付形式（ロケール非依存で自前変換する）
IMAP_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# 店名 → カテゴリの自動推定（frontend/src/money/csv.js の CAT_KEYWORDS と同じ内容）
CAT_KEYWORDS = [
    (re.compile(r"セブン|ｾﾌﾞﾝ|ファミリーマート|ファミマ|ﾌｧﾐﾘ|ローソン|ﾛｰｿﾝ|ミニストップ|デイリーヤマザキ|スーパー|イオン|マルエツ|ライフ|西友|イトーヨーカドー|業務スーパー|オーケー", re.I), "食費"),
    (re.compile(r"マクドナルド|ﾏｸﾄﾞ|モスバーガー|ケンタッキー|すき家|吉野家|松屋|サイゼリヤ|ガスト|バーミヤン|くら寿司|スシロー|スターバックス|ｽﾀｰﾊﾞ|ドトール|タリーズ|カフェ|ラーメン|食堂|レストラン|居酒屋|UBER\s*EATS|出前館", re.I), "外食"),
    (re.compile(r"JR|ジェイアール|メトロ|地下鉄|鉄道|電鉄|バス|タクシー|SUICA|ｽｲｶ|PASMO|モバイルスイカ|ETC|高速道路", re.I), "交通"),
    (re.compile(r"マツモトキヨシ|ﾏﾂﾓﾄｷﾖｼ|ウエルシア|スギ薬局|ツルハ|ココカラ|ドラッグ|ダイソー|セリア|キャンドゥ|ニトリ|無印良品|カインズ|ホームセンター", re.I), "日用品"),
    (re.compile(r"書店|ブックオフ|BOOK|紀伊國屋|ジュンク|有隣堂|UDEMY|スクール|講座", re.I), "勉強・自己投資"),
    (re.compile(r"NETFLIX|SPOTIFY|APPLE\s*COM\s*BILL|APPLE\.COM/BILL|GOOGLE|YOUTUBE|AMAZON\s*PRIME|PRIME\s*VIDEO|DAZN|HULU|U-NEXT|ニコニコ|携帯|ドコモ|DOCOMO|SOFTBANK|ソフトバンク|楽天モバイル|UQ|電気|ガス|水道|家賃|NHK", re.I), "固定費"),
    (re.compile(r"STEAM|NINTENDO|任天堂|PLAYSTATION|ゲーム|カラオケ|映画|TOHO|イオンシネマ|ライブ|チケット", re.I), "趣味・娯楽"),
    (re.compile(r"ユニクロ|UNIQLO|ジーユー|しまむら|ZOZO|ABCマート", re.I), "衣服"),
    (re.compile(r"病院|クリニック|歯科|調剤|内科|皮膚科|眼科|整骨", re.I), "健康・医療"),
]

_backfill_running = threading.Event()


def ensure_mail_defaults(db: Session) -> None:
    """mail_* 設定キーの欠損補完"""
    settings = crud.get_all_settings(db)
    changed = False
    for key, default in (
        ("mail_import_enabled", False),
        ("mail_user", ""),
        ("mail_app_password", ""),
        ("mail_senders", DEFAULT_SENDERS),
        ("mail_last_uid", 0),
        ("mail_status", {}),
    ):
        if key not in settings:
            crud.set_setting(db, key, default)
            changed = True
    if changed:
        db.commit()


def suggest_category(desc: str, shopmap: dict, cats: list) -> str:
    """店名からカテゴリを推定（csv.js の suggestCategory と同じ考え方）"""
    d = str(desc or "").strip()
    if d and shopmap.get(d) in cats:
        return shopmap[d]
    d2 = unicodedata.normalize("NFKC", d)
    for regex, cat in CAT_KEYWORDS:
        if (regex.search(d2) or regex.search(d)) and cat in cats:
            return cat
    return "その他" if "その他" in cats else (cats[0] if cats else "その他")


# ---------- メールの解析 ----------
def _decode_mime(s) -> str:
    if s is None:
        return ""
    out = []
    for part, cs in decode_header(str(s)):
        if isinstance(part, bytes):
            try:
                out.append(part.decode(cs or "utf-8", "ignore"))
            except LookupError:
                out.append(part.decode("utf-8", "ignore"))
        else:
            out.append(part)
    return "".join(out)


def _decode_payload(p) -> str:
    raw = p.get_payload(decode=True)
    if raw is None:
        return ""
    cs = p.get_content_charset() or "utf-8"
    try:
        return raw.decode(cs, "ignore")
    except LookupError:
        return raw.decode("utf-8", "ignore")


def _body_text(msg) -> str:
    """text/plain を優先して本文を取り出す（無ければHTMLからタグを除去）"""
    plains, htmls = [], []
    parts = msg.walk() if msg.is_multipart() else [msg]
    for p in parts:
        ctype = p.get_content_type()
        if ctype == "text/plain":
            plains.append(_decode_payload(p))
        elif ctype == "text/html":
            htmls.append(_decode_payload(p))
    if plains:
        return "\n".join(plains)
    if htmls:
        text = re.sub(r"<(br|/p|/div|/tr)[^>]*>", "\n", "\n".join(htmls), flags=re.I)
        return re.sub(r"<[^>]+>", "", text)
    return ""


def parse_usage_mail(subject: str, body: str, fallback_date: str) -> dict | None:
    """通知メール1通 → {date, amount, merchant} または None（読み取り不可）"""
    text = unicodedata.normalize("NFKC", (subject or "") + "\n" + (body or ""))
    if CANCEL_RE.search(subject or ""):
        return {"cancel": True}
    m = AMOUNT_RE.search(text) or AMOUNT_RE2.search(text)
    if not m:
        return None
    amount = int(m.group(1).replace(",", "").replace("，", ""))
    if amount <= 0:
        return None
    dm = DATE_RE.search(text)
    if dm:
        date = f"{int(dm.group(1)):04d}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}"
    else:
        date = fallback_date
    mm = MERCHANT_RE.search(text)
    merchant = (mm.group(1).strip() if mm else "").strip()[:80] or "（利用先不明）"
    return {"date": date, "amount": amount, "merchant": merchant}


# ---------- IMAP まわりの共通処理 ----------
def _login(user: str, pw: str, db: Session, now_str: str):
    try:
        box = imaplib.IMAP4_SSL(IMAP_HOST)
        box.login(user, pw)
        return box
    except imaplib.IMAP4.error as e:
        reason = str(e)
        # Gmailが返した本当の理由から、対処のヒントを組み立てる
        if "Too many simultaneous connections" in reason:
            hint = "同時接続が上限に達しています。10〜15分待ってから再試行してください（前回の中断で接続が残っている状態。自動で解消します）。"
        elif "Application-specific password required" in reason:
            hint = "通常のGoogleパスワードではログインできません。「アプリパスワード」（16文字）を使ってください。"
        elif "Invalid credentials" in reason or "AUTHENTICATIONFAILED" in reason.upper():
            hint = "アドレスまたはアプリパスワードが違います。myaccount.google.com/apppasswords で作り直して貼り直してください。"
        elif "Web login required" in reason or "accounts.google.com" in reason:
            hint = "Googleがセキュリティ確認を求めています。myaccount.google.com/notifications で「ブロックされたログイン」を確認・許可してください。"
        else:
            hint = "アドレスとアプリパスワードを確認してください。"
        msg = f"Gmailログインに失敗: {reason}｜{hint}"
        _set_status(db, last_check=now_str, error=msg)
        raise HTTPException(status_code=400, detail=msg)


def _all_mail_folder(box) -> str:
    """Gmailの「すべてのメール」フォルダ名を探す（見つからなければINBOX）"""
    try:
        _typ, data = box.list()
        for line in data or []:
            s = line.decode("utf-8", "ignore") if isinstance(line, bytes) else str(line)
            if "\\All" in s:
                m = re.search(r'"([^"]+)"\s*$', s)
                if m:
                    return m.group(1)
    except Exception:
        pass
    return "INBOX"


def _imap_date(ymd: str) -> str:
    """'2025-04-01' → '01-Apr-2025'（IMAP SEARCH用・ロケール非依存）"""
    y, m, d = ymd.split("-")
    return f"{int(d):02d}-{IMAP_MONTHS[int(m) - 1]}-{y}"


FETCH_CHUNK = 50  # 一括取得の通数（1通ずつだと往復時間で極端に遅くなる）


def _fetch_messages(box, uid_chunk: list) -> list:
    """複数UIDを1回のIMAP FETCHでまとめて取得する（高速化の要）。

    BODY.PEEK[] は本文全体を既読フラグを付けずに取る指定。
    応答はメッセージごとのタプルとして返るので、それだけ拾う。
    """
    _typ, mdata = box.uid("fetch", ",".join(str(u) for u in uid_chunk), "(BODY.PEEK[])")
    msgs = []
    for part in mdata or []:
        if isinstance(part, tuple) and part[1]:
            msgs.append(email.message_from_bytes(part[1]))
    return msgs


def _import_uids(box, db: Session, uids: list, senders: list,
                 cats: list, shopmap: dict, existing: set,
                 progress=None) -> tuple:
    """UIDのリストをまとめて取得・解析・登録する（通常チェックとbackfillの共通部）。

    高速化のポイント：
      1. IMAPからは FETCH_CHUNK 通ずつまとめて取得（往復回数を1/50に）
      2. 妥当性判定は JudgeCache（最初に1回だけ集計し、以後はメモリ計算）
    """
    checked = added = 0
    unparsed = []
    judge = JudgeCache(db)
    done = 0
    for ci in range(0, len(uids), FETCH_CHUNK):
        chunk = uids[ci:ci + FETCH_CHUNK]
        for msg in _fetch_messages(box, chunk):
            from_addr = email.utils.parseaddr(msg.get("From") or "")[1].lower()
            if not any(s in from_addr for s in senders):
                continue  # 通知メール以外は無視
            checked += 1
            subject = _decode_mime(msg.get("Subject"))
            try:
                mail_dt = email.utils.parsedate_to_datetime(msg.get("Date"))
                fallback_date = mail_dt.strftime("%Y-%m-%d")
            except (TypeError, ValueError):
                fallback_date = datetime.now().strftime("%Y-%m-%d")
            parsed = parse_usage_mail(subject, _body_text(msg), fallback_date)
            if parsed is None:
                unparsed.append(subject[:40] or "（件名なし）")
                continue
            if parsed.get("cancel"):
                continue  # 取消通知は自動登録しない（CSVの答え合わせで整合する）
            key = _dup_key(parsed["date"], parsed["amount"], parsed["merchant"])
            if key in existing:
                continue
            row = models.MoneyEntry(
                kind="spend", date=parsed["date"], amount=float(parsed["amount"]),
                category=suggest_category(parsed["merchant"], shopmap, cats),
                detail=parsed["merchant"],
                created_at=time.time() * 1000, source="mail",
            )
            judge.judge_and_add(row)
            db.add(row)
            existing.add(key)
            added += 1
        done += len(chunk)
        if progress:
            progress(done, len(uids), added)
    return checked, added, unparsed


# ---------- チェック本体 ----------
def _set_status(db: Session, **kw) -> None:
    st = crud.get_all_settings(db).get("mail_status") or {}
    st.update(kw)
    crud.set_setting(db, "mail_status", st)
    db.commit()


def _clean_cred(s: str) -> str:
    """アドレス/アプリパスワードの空白を除去。
    Googleはアプリパスワードを「xxxx xxxx xxxx xxxx」と空白入りで表示するため、
    そのまま貼り付けてもログインできるようにする。"""
    return (s or "").replace(" ", "").replace("　", "").strip()


def check_once(db: Session) -> dict:
    """新着メールを1回チェックして登録する（手動・自動の両方から呼ばれる）"""
    ensure_money_defaults(db)
    ensure_mail_defaults(db)
    settings = crud.get_all_settings(db)
    user = _clean_cred(settings.get("mail_user"))
    pw = _clean_cred(settings.get("mail_app_password"))
    if not user or not pw:
        raise HTTPException(status_code=400, detail="Gmailアドレスとアプリパスワードを設定してください")
    senders = settings.get("mail_senders") or DEFAULT_SENDERS
    last_uid = int(settings.get("mail_last_uid") or 0)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    box = _login(user, pw, db, now_str)
    try:
        box.select("INBOX", readonly=True)

        if last_uid <= 0:
            # 初回：現時点までのメールは自動対象外にして、以後の新着だけ取り込む
            # （過去分は「過去メールの取り込み」で明示的にさかのぼれる）
            _typ, data = box.uid("search", None, "ALL")
            uids = data[0].split()
            new_last = int(uids[-1]) if uids else 0
            crud.set_setting(db, "mail_last_uid", new_last)
            db.commit()
            _set_status(db, last_check=now_str, checked=0, added=0, error=None,
                        note="初期化完了。これ以降に届く通知メールから取り込みます。")
            return {"ok": True, "checked": 0, "added": 0,
                    "note": "初期化しました。これ以降に届く通知メールから自動で取り込みます。"}

        _typ, data = box.uid("search", None, f"UID {last_uid + 1}:*")
        uids = sorted(int(u) for u in data[0].split() if int(u) > last_uid)

        existing = {_dup_key(e.date, e.amount, e.detail)
                    for e in all_entries(db) if e.kind == "spend"}
        cats = settings.get("money_categories") or ["その他"]
        shopmap = settings.get("money_shopmap") or {}

        checked, added, unparsed = _import_uids(
            box, db, uids, senders, cats, shopmap, existing)

        if uids:
            crud.set_setting(db, "mail_last_uid", uids[-1])
        db.commit()
        st_prev = crud.get_all_settings(db).get("mail_status") or {}
        total = int(st_prev.get("added_total") or 0) + added
        _set_status(db, last_check=now_str, checked=checked, added=added,
                    added_total=total, error=None, note=None,
                    unparsed=unparsed[-5:] if unparsed else [])
        return {"ok": True, "checked": checked, "added": added, "unparsed": len(unparsed)}
    finally:
        try:
            box.logout()
        except Exception:
            pass


# ---------- 過去メールの一括取り込み（backfill） ----------
def _backfill_worker(since: str) -> None:
    _backfill_running.set()
    try:
        with SessionLocal() as db:
            settings = crud.get_all_settings(db)
            user = _clean_cred(settings.get("mail_user"))
            pw = _clean_cred(settings.get("mail_app_password"))
            senders = settings.get("mail_senders") or DEFAULT_SENDERS
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
            box = _login(user, pw, db, now_str)
            try:
                folder = _all_mail_folder(box)
                box.select(f'"{folder}"', readonly=True)
                # 差出人ごとに SINCE 検索して対象を絞る（全メール走査を避ける）
                uid_set = set()
                for s in senders:
                    _typ, data = box.uid(
                        "search", None, f'(SINCE {_imap_date(since)} FROM "{s}")')
                    for u in (data[0].split() if data and data[0] else []):
                        uid_set.add(int(u))
                uids = sorted(uid_set)
                _set_status(db, note=f"過去メール取り込み中… 対象{len(uids)}件（{since}以降）")

                existing = {_dup_key(e.date, e.amount, e.detail)
                            for e in all_entries(db) if e.kind == "spend"}
                cats = settings.get("money_categories") or ["その他"]
                shopmap = settings.get("money_shopmap") or {}

                def progress(done, total_n, added_n):
                    _set_status(db, note=f"過去メール取り込み中… {done}/{total_n}件（登録{added_n}件）")

                checked, added, unparsed = _import_uids(
                    box, db, uids, senders, cats, shopmap, existing, progress=progress)
                db.commit()
                st_prev = crud.get_all_settings(db).get("mail_status") or {}
                total = int(st_prev.get("added_total") or 0) + added
                _set_status(db, last_check=now_str, added_total=total, error=None,
                            note=f"過去メールの取り込みが完了：{since}以降の通知{checked}件から{added}件を登録"
                                 + (f"（読み取れず{len(unparsed)}件）" if unparsed else ""),
                            unparsed=unparsed[-5:] if unparsed else [])
            finally:
                try:
                    box.logout()
                except Exception:
                    pass
    except HTTPException:
        pass  # ログイン失敗などは mail_status に記録済み
    except Exception as e:
        try:
            with SessionLocal() as db:
                _set_status(db, error=f"過去メール取り込みに失敗: {e}")
        except Exception:
            pass
    finally:
        _backfill_running.clear()


class BackfillBody(BaseModel):
    since: str  # 'YYYY-MM-DD'：この日以降の通知メールを全件取り込む


@router.post("/api/money/mail/backfill")
def mail_backfill(body: BackfillBody, db: Session = Depends(get_db)):
    """過去メールの一括取り込みを開始する（バックグラウンド実行）"""
    ensure_mail_defaults(db)
    settings = crud.get_all_settings(db)
    if not (settings.get("mail_user") or "").strip() or not (settings.get("mail_app_password") or "").strip():
        raise HTTPException(status_code=400, detail="先にGmailアドレスとアプリパスワードを設定・保存してください")
    try:
        datetime.strptime(body.since, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="日付は YYYY-MM-DD 形式で指定してください")
    if _backfill_running.is_set():
        raise HTTPException(status_code=400, detail="過去メールの取り込みは実行中です。完了までお待ちください。")
    threading.Thread(target=_backfill_worker, args=(body.since,), daemon=True).start()
    return {"ok": True,
            "note": "過去メールの取り込みを開始しました。件数によっては数分かかります。「🔄 状態を更新」で進行状況を確認できます。"}


# ---------- 自動チェック（バックグラウンド） ----------
def poll_loop() -> None:
    """main.py の起動時にデーモンスレッドとして開始される"""
    time.sleep(20)  # 起動直後は待つ
    while True:
        try:
            if not _backfill_running.is_set():  # backfill中は自動チェックを休む
                with SessionLocal() as db:
                    settings = crud.get_all_settings(db)
                    if (settings.get("mail_import_enabled")
                            and settings.get("mail_user")
                            and settings.get("mail_app_password")):
                        check_once(db)
        except HTTPException:
            pass  # 設定不備・ログイン失敗は mail_status に記録済み
        except Exception as e:
            try:
                with SessionLocal() as db:
                    _set_status(db, error=f"自動チェックに失敗: {e}")
            except Exception:
                pass
        time.sleep(POLL_SECONDS)


# ---------- API ----------
@router.post("/api/money/mail/check")
def mail_check(db: Session = Depends(get_db)):
    """今すぐチェック（設定画面のボタンから）"""
    return check_once(db)


@router.get("/api/money/mail/status")
def mail_status(db: Session = Depends(get_db)):
    ensure_mail_defaults(db)
    settings = crud.get_all_settings(db)
    return {
        "enabled": bool(settings.get("mail_import_enabled")),
        "user": settings.get("mail_user") or "",
        "has_password": bool((settings.get("mail_app_password") or "").strip()),
        "initialized": int(settings.get("mail_last_uid") or 0) > 0,  # 初期化（今すぐチェック1回目）済みか
        "backfill_running": _backfill_running.is_set(),
        "status": settings.get("mail_status") or {},
    }
