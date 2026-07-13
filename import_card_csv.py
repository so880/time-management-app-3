# -*- coding: utf-8 -*-
"""カード・デビット明細CSVの一括取り込みスクリプト（再利用可）。

対応形式（ファイル名で自動判別）:
  1. *_debitmeisai.csv  … デビット明細
       列: ご利用者, お振替日, ご利用先など, お振替金額, 摘要, 承認番号
  2. 6桁数字.csv (例 202608.csv) … 三井住友カード（Vpass）明細
       旧形式: 利用日, 店名, 利用金額(3列目), …
       新形式: 利用日, 店名, ご本人, 支払方法, , お支払月, お支払金額(7列目), …
       （行の3列目が「ご本人/家族」なら新形式と判定）

二重計上を防ぐ仕組み（フロントの csv.js と同じ考え方）:
  a) 登録済みと同じ 日付+金額+内容 はサーバー側 bulk API が件数つきでスキップ
  b) 途中まで手動取込した分（source=import）は 日付+金額 が一致すれば
     店名表記が違ってもスキップ（列の対応づけ違いの保険）
  c) メール通知から自動登録された分（source=mail）は ±2日以内・同額ならスキップ
     （デビットは摘要の「利用日」も見る）
  d) マイナス金額（返金）は、同じ店・同額の購入1件と相殺して両方とも取り込まない

Amazon系（＊アマゾン / ＡＭＡＺＯＮ．ＣＯ．ＪＰ など）は店名をそのまま内容に
残して「その他」で登録する。後日Amazon公式の注文履歴が届いたら、
マネータブの突き合わせ機能で商品名・カテゴリを更新できる。

使い方:  python import_card_csv.py [CSVフォルダ]
  フォルダ省略時は下の DEFAULT_DIR（今回アップロードされた場所）を読む。
"""
import csv
import glob
import io
import json
import os
import re
import sys
import unicodedata
import urllib.request
from collections import Counter
from datetime import date as _date

API = "http://127.0.0.1:8000"
DEFAULT_DIR = (r"C:\Users\PC_User\AppData\Roaming\Claude\local-agent-mode-sessions"
               r"\53ecccd2-8fcc-485c-b4f2-0994d220414e"
               r"\f136f436-6835-4d66-acbb-a39746427afc"
               r"\local_e02dd867-b6af-41fd-8cd1-ec7f4941eedd\uploads")

DATE_RE = re.compile(r"(20\d{2})[/\-.年](\d{1,2})[/\-.月](\d{1,2})")

# 店名 → カテゴリの自動推定（フロント csv.js の CAT_KEYWORDS と同じ内容）
CAT_KEYWORDS = [
    (re.compile(r"セブン|ｾﾌﾞﾝ|ファミリーマート|ファミマ|ﾌｧﾐﾘ|ローソン|ﾛｰｿﾝ|ミニストップ|デイリーヤマザキ|スーパー|イオン|マルエツ|ライフ|西友|イトーヨーカドー|業務スーパー|オーケー", re.I), "食費"),
    (re.compile(r"マクドナルド|ﾏｸﾄﾞ|モスバーガー|モスバ|ケンタッキー|すき家|吉野家|松屋|サイゼリヤ|ガスト|バーミヤン|くら寿司|スシロー|スターバックス|ｽﾀｰﾊﾞ|ドトール|タリーズ|カフェ|ラーメン|食堂|レストラン|居酒屋|UBER\s*EATS|出前館", re.I), "外食"),
    (re.compile(r"JR|ジェイアール|メトロ|地下鉄|鉄道|電鉄|バス|タクシー|SUICA|ｽｲｶ|PASMO|モバイルスイカ|ETC|高速道路|えきねっと", re.I), "交通"),
    (re.compile(r"マツモトキヨシ|ﾏﾂﾓﾄｷﾖｼ|ウエルシア|スギ薬局|ツルハ|ココカラ|ドラッグ|ダイソー|セリア|キャンドゥ|ニトリ|無印良品|カインズ|ホームセンター", re.I), "日用品"),
    (re.compile(r"書店|ブックオフ|BOOK|紀伊國屋|ジュンク|有隣堂|UDEMY|スクール|講座", re.I), "勉強・自己投資"),
    (re.compile(r"NETFLIX|SPOTIFY|APPLE\s*COM\s*BILL|APPLE\.COM/BILL|GOOGLE|YOUTUBE|AMAZON\s*PRIME|Amazonプライム|PRIME\s*VIDEO|DAZN|HULU|U-NEXT|ニコニコ|携帯|ドコモ|DOCOMO|SOFTBANK|ソフトバンク|楽天モバイル|UQ|電気|ガス|水道|家賃|NHK", re.I), "固定費"),
    (re.compile(r"STEAM|NINTENDO|任天堂|PLAYSTATION|ゲーム|カラオケ|映画|TOHO|イオンシネマ|ライブ|チケット", re.I), "趣味・娯楽"),
    (re.compile(r"ユニクロ|UNIQLO|ジーユー|しまむら|ZOZO|ABCマート", re.I), "衣服"),
    (re.compile(r"病院|クリニック|歯科|調剤|内科|皮膚科|眼科|整骨", re.I), "健康・医療"),
]


def req(path, method="GET", body=None, timeout=120):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(API + path, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=timeout) as res:
        return json.load(res)


def norm_date(s):
    if s is None:
        return None
    m = DATE_RE.search(unicodedata.normalize("NFKC", str(s)))
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return None
    return f"{y}-{mo:02d}-{d:02d}"


def parse_amount(s):
    if s is None:
        return None
    t = unicodedata.normalize("NFKC", str(s))
    t = re.sub(r"[¥￥,，円\s\"']", "", t)
    if t == "" or not re.fullmatch(r"-?\d+(\.\d+)?", t):
        return None
    return float(t)


def norm_desc(s):
    d = unicodedata.normalize("NFKC", str(s or "")).strip().lower()
    return " ".join(d.split())


def day_diff(a, b):
    return abs((_date.fromisoformat(a) - _date.fromisoformat(b)).days)


def read_csv_rows(path):
    with open(path, "rb") as f:
        raw = f.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp932")
    return [r for r in csv.reader(io.StringIO(text))
            if any(str(c).strip() for c in r)]


def parse_file(path):
    """1ファイル → [{date, amount, desc, usedate}] （日付が読めない行は自動で除外）"""
    fn = os.path.basename(path)
    rows = read_csv_rows(path)
    out = []
    if fn.endswith("_debitmeisai.csv"):
        for r in rows:
            if len(r) < 4:
                continue
            d = norm_date(r[1])
            a = parse_amount(r[3])
            if not d or a is None:
                continue
            note = unicodedata.normalize("NFKC", str(r[4]).strip()) if len(r) > 4 else ""
            m = re.search(r"利用日[）)]?\s*[：:]\s*(20\d{2}年\d{1,2}月\d{1,2}日)", note)
            out.append({"date": d, "amount": a, "desc": str(r[2]).strip(),
                        "usedate": norm_date(m.group(1)) if m else None})
    else:  # Vpassカード明細（旧/新形式を行の3列目で判別）
        for r in rows:
            if len(r) < 3:
                continue
            d = norm_date(r[0])
            if not d:
                continue  # ヘッダー行・合計行
            new_style = len(r) >= 7 and str(r[2]).strip() in ("ご本人", "家族")
            a = parse_amount(r[6]) if new_style else parse_amount(r[2])
            if a is None:
                continue
            out.append({"date": d, "amount": a, "desc": str(r[1]).strip(),
                        "usedate": None})
    return out


def suggest_category(desc, shopmap, cats):
    d = str(desc or "").strip()
    if d and shopmap.get(d) in cats:
        return shopmap[d]
    d2 = unicodedata.normalize("NFKC", d)
    for pat, c in CAT_KEYWORDS:
        if (pat.search(d2) or pat.search(d)) and c in cats:
            return c
    return "その他" if "その他" in cats else (cats[0] if cats else "その他")


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DIR
    files = sorted(glob.glob(os.path.join(folder, "*_debitmeisai.csv")))
    files += sorted(p for p in glob.glob(os.path.join(folder, "*.csv"))
                    if re.fullmatch(r"\d{6}\.csv", os.path.basename(p)))
    if not files:
        print("CSVが見つかりません:", folder)
        input("Press Enter to close...")
        return

    # 1. CSVを読む
    all_rows = []
    print("◆ 読み込み")
    for p in files:
        rs = parse_file(p)
        for r in rs:
            r["file"] = os.path.basename(p)
        all_rows += rs
        print(f"  {os.path.basename(p)}: {len(rs)}件")
    print(f"  合計 {len(all_rows)}件")

    # 2. 返金（マイナス）を同じ店・同額の購入と相殺
    print("\n◆ 返金の相殺")
    negatives = [r for r in all_rows if r["amount"] <= 0]
    cancelled = set()
    for neg in negatives:
        key = (norm_desc(neg["desc"]), abs(neg["amount"]))
        target_day = neg.get("usedate") or neg["date"]
        cands = [r for r in all_rows
                 if id(r) not in cancelled and r["amount"] > 0
                 and (norm_desc(r["desc"]), r["amount"]) == key]
        if cands:
            best = min(cands, key=lambda r: day_diff(r["date"], target_day))
            cancelled.add(id(best))
            cancelled.add(id(neg))
            print(f"  相殺: {best['date']} {best['desc']} +{best['amount']:,.0f}円"
                  f" ↔ {neg['date']} 返金 {neg['amount']:,.0f}円 → 両方とも登録しない")
        else:
            cancelled.add(id(neg))
            print(f"  注意: {neg['date']} {neg['desc']} {neg['amount']:,.0f}円 の返金に"
                  f" 対応する購入がCSV内に見つからず → 返金行だけ除外。"
                  f" もし購入が登録済みなら手動で削除してください")
    if not negatives:
        print("  なし")
    rows = [r for r in all_rows if id(r) not in cancelled]

    # 3. 既存データを取得して重複チェックの準備
    entries = req("/api/money/entries")
    backup = req("/api/money/backup/export")
    cats = backup.get("cats") or ["その他"]
    shopmap = backup.get("shopMap") or {}
    imported = Counter((e["date"], float(e["amount"])) for e in entries
                       if e["kind"] == "spend" and e.get("source") == "import")
    mails = [{"date": e["date"], "amount": float(e["amount"]), "used": False}
             for e in entries if e["kind"] == "spend" and e.get("source") == "mail"]

    # 4. 重複を除外して登録候補を作る
    items = []
    skip_import = 0
    skip_mail = 0
    for r in rows:
        k = (r["date"], r["amount"])
        if imported[k] > 0:                       # 途中まで取込済みの分
            imported[k] -= 1
            skip_import += 1
            continue
        hit = None                                 # メール通知と ±2日・同額
        for m in mails:
            if m["used"] or m["amount"] != r["amount"]:
                continue
            if day_diff(m["date"], r["date"]) <= 2 or \
               (r.get("usedate") and day_diff(m["date"], r["usedate"]) <= 2):
                hit = m
                break
        if hit:
            hit["used"] = True
            skip_mail += 1
            continue
        items.append({"date": r["date"], "amount": r["amount"],
                      "category": suggest_category(r["desc"], shopmap, cats),
                      "detail": r["desc"]})

    print("\n◆ 重複チェック")
    print(f"  取込済み(source=import)と一致 → スキップ: {skip_import}件")
    print(f"  メール自動登録と±2日・同額 → スキップ: {skip_mail}件")
    print(f"  登録候補: {len(items)}件")

    # 5. 一括登録（サーバー側でも 日付+金額+内容 の完全一致は自動スキップされる）
    if items:
        res = req("/api/money/entries/bulk", "POST", {"items": items})
        print("\n◆ 登録結果")
        print(f"  追加: {res.get('added')}件 / サーバー側で重複スキップ: {res.get('skipped')}件")
    else:
        print("\n◆ 登録結果\n  追加するものがありません")

    amz = sum(1 for it in items
              if re.search(r"amazon|アマゾン|amzn",
                           unicodedata.normalize("NFKC", it["detail"]), re.I))
    print(f"\nAmazon系はそのままの店名で {amz}件 登録（カテゴリはその他中心）。")
    print("公式の注文履歴が届いたら、マネータブの突き合わせで商品名・カテゴリを更新できます。")
    input("\nPress Enter to close...")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("エラー:", e)
        input("Press Enter to close...")
