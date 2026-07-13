# -*- coding: utf-8 -*-
"""Amazon公式の注文履歴エクスポート（Your Orders.zip）で
登録済みのAmazon系支出に商品名・カテゴリを付けるスクリプト。

読むもの（zipの中の2ファイル）:
  - Your Amazon Orders/Order History.csv          … 通常の注文（商品ごとに1行）
  - Your Amazon Orders/Digital Content Orders.csv … デジタル注文（Prime会費・Kindle等）

突き合わせのルール（マネータブの突き合わせ機能と同じ考え方）:
  - 対象は 内容に amazon/アマゾン/amzn/prime video を含む支出
    （すでに「Amazon: 」付きのもの、Amazon Pay提携サイト＝外部サイト決済は除く）
  - 「同額 かつ ±5日以内」だけを一致とみなす（1注文=1記録の1対1）
  - 注文全体の合計 → 発送グループごとの合計 → 注文内の商品の組み合わせ の順で照合
    （分割発送・出品者ごとの分割だとカードには分かれて請求されるため）
  - 一致した記録は 内容=「Amazon: 商品名」・カテゴリ=商品名から推定 に更新
    （間違っていた場合は POST /api/money/amazon/reset で一括で元に戻せる）

使い方:  python import_amazon_orders.py [Your Orders.zip のパス]
"""
import csv
import io
import json
import re
import sys
import unicodedata
import urllib.request
import zipfile
from collections import defaultdict
from itertools import combinations
from datetime import datetime, timedelta, date as _date

API = "http://127.0.0.1:8000"
DEFAULT_ZIP = (r"C:\Users\PC_User\AppData\Roaming\Claude\local-agent-mode-sessions"
               r"\53ecccd2-8fcc-485c-b4f2-0994d220414e"
               r"\f136f436-6835-4d66-acbb-a39746427afc"
               r"\local_e02dd867-b6af-41fd-8cd1-ec7f4941eedd\uploads\Your Orders.zip")
SINCE = "2025-03-01"   # マネーのデータは2025-04-01からなので、それより前の注文は見ない
MAX_DAYS = 5           # 注文日/発送日とカード利用日のずれの許容（±5日）

# 商品名 → カテゴリ（フロント amazon.js の AMZ_KEYWORDS と同じ内容）
AMZ_KEYWORDS = [
    (re.compile(r"食品|フルグラ|グラノーラ|シリアル|白米|玄米|パックご飯|サトウのごはん|パスタ|そば|うどん|ラーメン|カップ麺|カレー|レトルト|味噌|醤油|だし|調味料|ふりかけ|缶詰|お茶|緑茶|麦茶|コーヒー|珈琲|紅茶|ココア|ミネラルウォーター|天然水|炭酸水|ジュース|コーラ|お菓子|チョコ|スナック|ポテトチップス|グミ|クッキー|ビスケット|せんべい|ナッツ|アーモンド|ドライフルーツ|はちみつ|ジャム|シリアルバー|ゼリー飲料|ゼリー", re.I), "食費"),
    (re.compile(r"プロテイン|サプリ|ビタミン|亜鉛|マグネシウム|クレアチン|BCAA|EAA|マスク|絆創膏|バンドエイド|湿布|目薬|胃腸薬|うがい薬|体温計|コンタクト|医薬部外品|デオドラント|制汗|あせワキ", re.I), "健康・医療"),
    (re.compile(r"洗剤|柔軟剤|漂白|シャンプー|コンディショナー|トリートメント|ボディソープ|ボディーソープ|ハンドソープ|石鹸|歯磨|歯ブラシ|フロス|うがいコップ|ティッシュ|トイレットペーパー|キッチンペーパー|ウェットシート|ウェットティッシュ|ゴミ袋|ラップ|アルミホイル|ジップロック|保存容器|電池|乾電池|文房具|ノート|ボールペン|シャープペン|シャープ芯|消しゴム|ファイル|収納|ハンガー|タオル|バスタオル|掃除|クリーナー|芳香剤|除湿|カミソリ|髭剃り|綿棒|爪切り|スリッパ|インソール|中敷き", re.I), "日用品"),
    (re.compile(r"単行本|文庫|新書|参考書|問題集|テキスト|過去問|Kindle|書籍|第\d+巻|\d+巻|出版|技術書|入門|教科書|辞典|TOEIC|英単語|Office|オフィス", re.I), "勉強・自己投資"),
    (re.compile(r"Switch|Nintendo|任天堂|PlayStation|PS[45]|Xbox|Steam|ゲーム|コントローラ|Proコン|フィギュア|プラモ|ガンプラ|Blu-ray|ブルーレイ|DVD|サントラ|アルバム|イヤホン|ヘッドホン|ヘッドセット|スピーカ|マンガ|コミック|ライトノベル|ラノベ|トレカ|カードゲーム|ボードゲーム|卓球|ラケット|ラバー", re.I), "趣味・娯楽"),
    (re.compile(r"Tシャツ|シャツ|パーカー|スウェット|ジャケット|コート|パンツ|ジーンズ|スラックス|ショーツ|靴下|ソックス|インナー|肌着|スニーカー|シューズ|ブーツ|サンダル|ベルト|帽子|キャップ|ニット帽|手袋|マフラー|財布|リュック|バッグ", re.I), "衣服"),
    (re.compile(r"USB|Type-?C|Lightning|ケーブル|充電器|急速充電|モバイルバッテリー|マウス|キーボード|SSD|HDD|microSD|SDカード|HDMI|ディスプレイ|モニター|Webカメラ|マイク|ハブ|ドッキング|LANケーブル|ルーター|スタンド|保護フィルム|スマホケース|スイッチボット|SwitchBot", re.I), "日用品"),
]
# デジタルのサブスク名 → 固定費（毎月の定額）
DIGITAL_SUBS = re.compile(r"^(Prime|Kindle Unlimited|Amazon Music Unlimited|アニメタイムズ)$", re.I)


def req(path, method="GET", body=None, timeout=120):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(API + path, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=timeout) as res:
        return json.load(res)


def jst_date(s):
    """'2025-11-29T08:35:06Z' などのUTC時刻 → 日本時間の日付 'YYYY-MM-DD'"""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})", str(s or ""))
    if not m:
        return None
    dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                  int(m.group(4)), int(m.group(5))) + timedelta(hours=9)
    return dt.date().isoformat()


def amount_of(s):
    t = str(s or "").replace(",", "").strip()
    try:
        v = float(t)
        return v if v == v else None
    except ValueError:
        return None


def day_diff(a, b):
    return abs((_date.fromisoformat(a) - _date.fromisoformat(b)).days)


def suggest_category(title, cats, digital=False):
    t = unicodedata.normalize("NFKC", str(title or ""))
    if digital and DIGITAL_SUBS.match(t.strip()) and "固定費" in cats:
        return "固定費"
    for pat, c in AMZ_KEYWORDS:
        if pat.search(t) and c in cats:
            return c
    if digital and "趣味・娯楽" in cats:   # 映画・コミック等のデジタル購入
        return "趣味・娯楽"
    return "その他" if "その他" in cats else (cats[0] if cats else "その他")


def join_titles(titles, limit=90):
    ts = [t for t in titles if t]
    if not ts:
        return "（商品名不明）"
    s = "／".join(ts[:2])
    if len(ts) > 2:
        s += f" 他{len(ts) - 2}点"
    return ("Amazon: " + s)[:limit]


def load_orders(zip_path):
    """zip → (physical, digital)
    physical: {order_id: {date, ship_dates, items:[{title, amount, ship}]}}
    digital:  [{date, amount, title}]
    """
    zf = zipfile.ZipFile(zip_path)
    names = {n.split("/")[-1]: n for n in zf.namelist()}

    with zf.open(names["Order History.csv"]) as f:
        rows = list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")))
    physical = {}
    for r in rows:
        if r.get("Order Status") == "Cancelled":
            continue
        d = jst_date(r.get("Order Date"))
        a = amount_of(r.get("Total Amount"))
        if not d or d < SINCE or not a or a <= 0:
            continue
        ship = jst_date(r.get("Ship Date")) or d
        o = physical.setdefault(r["Order ID"], {"date": d, "items": []})
        o["items"].append({"title": str(r.get("Product Name") or "").strip(),
                           "amount": a, "ship": ship})

    with zf.open(names["Digital Content Orders.csv"]) as f:
        rows = list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")))
    dig = {}
    for r in rows:
        d = jst_date(r.get("Order Date"))
        if not d or d < SINCE:
            continue
        a = amount_of(r.get("Transaction Amount"))
        o = dig.setdefault((r["Order ID"]), {"date": d, "amount": 0.0,
                                             "title": str(r.get("Product Name") or "").strip()})
        if a and a > 0:
            o["amount"] += a
    digital = [o for o in dig.values() if o["amount"] > 0]
    return physical, digital


def main():
    zip_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ZIP
    physical, digital = load_orders(zip_path)
    n_items = sum(len(o["items"]) for o in physical.values())
    print(f"◆ 注文データ読み込み（{SINCE} 以降）")
    print(f"  通常の注文: {len(physical)}件（商品 {n_items}点） / デジタル注文: {len(digital)}件")

    # 対象の記録（Amazon系の支出で、まだ商品名が付いていないもの）
    entries = req("/api/money/entries")
    backup = req("/api/money/backup/export")
    cats = backup.get("cats") or ["その他"]
    def _nfkc(s):
        return unicodedata.normalize("NFKC", str(s or ""))

    targets = []
    n_pay = 0
    for e in entries:
        if e["kind"] != "spend":
            continue
        d = _nfkc(e.get("detail"))
        if str(e.get("detail") or "").startswith("Amazon: "):
            continue
        if re.search(r"amazon\s*pay|アマゾンペイ", d, re.I):
            n_pay += 1   # Amazon Pay＝外部サイトの決済。注文履歴には載らないので対象外
            continue
        if re.search(r"amazon|アマゾン|amzn|prime\s*video", d, re.I):
            targets.append(dict(e, used=False))
    print(f"  突き合わせ対象の記録: {len(targets)}件"
          f"（Amazon Pay提携サイトの決済 {n_pay}件は対象外）")

    def find_entry(amount, dates):
        """同額 かつ どれかの日付と±MAX_DAYS日以内の未使用記録（最も近い日を優先）"""
        best, bestd = None, None
        for e in targets:
            if e["used"] or round(float(e["amount"])) != round(amount):
                continue
            d = min(day_diff(e["date"], dd) for dd in dates)
            if d <= MAX_DAYS and (bestd is None or d < bestd):
                best, bestd = e, d
        return best

    updates = []   # (entry, new_detail, new_category, memo)

    # パス1: 注文全体の合計で照合
    unmatched_orders = []
    for oid, o in physical.items():
        total = sum(it["amount"] for it in o["items"])
        dates = [o["date"]] + [it["ship"] for it in o["items"]]
        e = find_entry(total, dates)
        if e:
            e["used"] = True
            titles = [it["title"] for it in o["items"]]
            cat = next((suggest_category(t, cats) for t in titles
                        if suggest_category(t, cats) != "その他"), suggest_category(titles[0], cats))
            updates.append((e, join_titles(titles), cat, f"注文合計 {total:,.0f}円"))
        else:
            unmatched_orders.append((oid, o))

    # パス2: 発送グループごとの合計で照合（分割発送＝分割請求に対応）
    still = []
    for oid, o in unmatched_orders:
        groups = defaultdict(list)
        for it in o["items"]:
            groups[it["ship"]].append(it)
        hit_any = False
        if len(groups) > 1:
            for ship, its in groups.items():
                sub = sum(it["amount"] for it in its)
                e = find_entry(sub, [ship, o["date"]])
                if e:
                    e["used"] = True
                    hit_any = True
                    titles = [it["title"] for it in its]
                    cat = next((suggest_category(t, cats) for t in titles
                                if suggest_category(t, cats) != "その他"), suggest_category(titles[0], cats))
                    updates.append((e, join_titles(titles), cat, f"発送分 {sub:,.0f}円"))
        if not hit_any:
            still.append((oid, o))

    # パス3: 注文内の商品の組み合わせで照合（出品者ごとの分割請求・単品に対応）
    #   大きい組み合わせから試し、一致したら残りの商品でさらに照合を続ける
    leftover_orders = []
    for oid, o in still:
        items = list(o["items"])
        hit_any = False
        if len(items) <= 14:   # 組み合わせ爆発の保険（通常は数点まで）
            progress = True
            while progress and items:
                progress = False
                for k in range(len(items), 0, -1):
                    if k == len(items) and hit_any is False and k > 1:
                        pass  # 全部の合計はパス1で照合済みだが、日付条件が同じなので再試行しても結果は同じ
                    found = None
                    for combo in combinations(items, k):
                        sub = sum(it["amount"] for it in combo)
                        e = find_entry(sub, [o["date"]] + [it["ship"] for it in combo])
                        if e:
                            found = (e, combo, sub)
                            break
                    if found:
                        e, combo, sub = found
                        e["used"] = True
                        hit_any = True
                        titles = [it["title"] for it in combo]
                        cat = next((suggest_category(t, cats) for t in titles
                                    if suggest_category(t, cats) != "その他"),
                                   suggest_category(titles[0], cats))
                        updates.append((e, join_titles(titles), cat,
                                        f"組み合わせ{k}点 {sub:,.0f}円"))
                        for it in combo:
                            items.remove(it)
                        progress = True
                        break
        else:
            for it in items:
                e = find_entry(it["amount"], [it["ship"], o["date"]])
                if e:
                    e["used"] = True
                    hit_any = True
                    updates.append((e, join_titles([it["title"]]),
                                    suggest_category(it["title"], cats),
                                    f"単品 {it['amount']:,.0f}円"))
        if not hit_any:
            leftover_orders.append((oid, o))

    # デジタル注文の照合
    leftover_digital = []
    for o in digital:
        e = find_entry(o["amount"], [o["date"]])
        if e:
            e["used"] = True
            updates.append((e, join_titles([o["title"]]),
                            suggest_category(o["title"], cats, digital=True),
                            f"デジタル {o['amount']:,.0f}円"))
        else:
            leftover_digital.append(o)

    # 更新を適用
    print(f"\n◆ 一致: {len(updates)}件 → 商品名・カテゴリを更新します")
    done = 0
    for e, detail, cat, memo in updates:
        req(f"/api/money/entries/{e['id']}", "PATCH",
            {"detail": detail, "category": cat})
        done += 1
        print(f"  {e['date']} {float(e['amount']):>9,.0f}円 [{cat}] {detail[:60]}（{memo}）")
    print(f"  更新完了: {done}件")

    # 残り物レポート
    rest = [e for e in targets if not e["used"]]
    print(f"\n◆ 商品名が付かなかったAmazon系の記録: {len(rest)}件")
    for e in sorted(rest, key=lambda x: x["date"])[:30]:
        print(f"  {e['date']} {float(e['amount']):>9,.0f}円 {e.get('detail')}")
    if len(rest) > 30:
        print(f"  …ほか{len(rest) - 30}件")
    print(f"\n◆ カード記録が見つからなかった注文: 通常{len(leftover_orders)}件 / デジタル{len(leftover_digital)}件")
    for oid, o in leftover_orders[:15]:
        total = sum(it["amount"] for it in o["items"])
        print(f"  {o['date']} {total:>9,.0f}円 {o['items'][0]['title'][:40]}"
              + (f" 他{len(o['items'])-1}点" if len(o['items']) > 1 else ""))
    for o in leftover_digital[:15]:
        print(f"  {o['date']} {o['amount']:>9,.0f}円 {o['title'][:40]}")
    print("\n間違いがあれば、マネータブの「↩ 突き合わせを全部取り消す」でいつでも元に戻せます。")
    input("\nPress Enter to close...")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("エラー:", e)
        input("Press Enter to close...")
