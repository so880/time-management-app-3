// 📦 Amazon注文履歴の解析と、カード記録との突き合わせ
// 使い方：amazon.co.jp の「注文履歴」ページを Ctrl+A → Ctrl+C で丸ごと貼り付ける。
// - 金額は「合計」を含む行からだけ取る（商品単価やポイントを誤って拾わない）
// - カテゴリは商品名専用のキーワード辞書で推定（食品・日用品・本など）

const DATE_RE = /(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日/
// 「合計 ￥1,234」（同じ行）
const TOTAL_RE = /(?:合計|注文合計|ご?請求額)[^0-9¥￥]{0,10}[￥¥]?\s*([0-9][0-9,]*)/
// 「合計」だけの行（金額は次の行にあるレイアウト用）
const TOTAL_LABEL_RE = /^(?:合計|注文合計|ご?請求額)\s*[:：]?$/
const YEN_RE = /[￥¥]\s*([0-9][0-9,]*)/
// 商品名らしくない行（ボイラープレート）を除外する
const NOISE_RE = /注文|お届け|配達|配送|返品|交換|領収|合計|再度購入|購入手続|カートに|レビュー|受け取|発送|到着|数量|販売元|出荷元|ギフト|問題|請求|支払|カスタマー|プライム|ポイント|クーポン|表示|検索|アカウント|ヘルプ|サインイン|すべて|カテゴリー|設定|置き配|評価|お問い合わせ|サポート|[￥¥]/

/* 商品名 → カテゴリの推定（Amazonの商品タイトル向けキーワード辞書） */
const AMZ_KEYWORDS = [
  [/食品|フルグラ|グラノーラ|シリアル|白米|玄米|パックご飯|サトウのごはん|パスタ|そば|うどん|ラーメン|カップ麺|カレー|レトルト|味噌|醤油|だし|調味料|ふりかけ|缶詰|お茶|緑茶|麦茶|コーヒー|珈琲|紅茶|ココア|ミネラルウォーター|天然水|炭酸水|ジュース|コーラ|お菓子|チョコ|スナック|ポテトチップス|グミ|クッキー|ビスケット|せんべい|ナッツ|アーモンド|ドライフルーツ|はちみつ|ジャム|シリアルバー|ゼリー飲料/i, '食費'],
  [/プロテイン|サプリ|ビタミン|亜鉛|マグネシウム|クレアチン|BCAA|EAA|マスク|絆創膏|バンドエイド|湿布|目薬|胃腸薬|うがい薬|体温計|コンタクト/i, '健康・医療'],
  [/洗剤|柔軟剤|漂白|シャンプー|コンディショナー|トリートメント|ボディソープ|ハンドソープ|石鹸|歯磨|歯ブラシ|フロス|ティッシュ|トイレットペーパー|キッチンペーパー|ウェットシート|ゴミ袋|ラップ|アルミホイル|電池|乾電池|文房具|ノート|ボールペン|シャープペン|消しゴム|ファイル|収納|ハンガー|タオル|バスタオル|掃除|クリーナー|芳香剤|除湿|カミソリ|髭剃り|綿棒|爪切り/i, '日用品'],
  [/単行本|文庫|新書|参考書|問題集|テキスト|過去問|Kindle|書籍|第\d+巻|(\d+)巻|著\b|出版|技術書|入門|教科書|辞典|TOEIC|英単語/i, '勉強・自己投資'],
  [/Switch|Nintendo|任天堂|PlayStation|PS[45]|Xbox|Steam|ゲーム|コントローラ|Proコン|フィギュア|プラモ|ガンプラ|Blu-ray|ブルーレイ|DVD|サントラ|アルバム|イヤホン|ヘッドホン|ヘッドセット|スピーカ|マンガ|コミック|ライトノベル|ラノベ|トレカ|カードゲーム|ボードゲーム/i, '趣味・娯楽'],
  [/Tシャツ|シャツ|パーカー|スウェット|ジャケット|コート|パンツ|ジーンズ|スラックス|ショーツ|靴下|ソックス|インナー|肌着|スニーカー|シューズ|ブーツ|サンダル|ベルト|帽子|キャップ|ニット帽|手袋|マフラー|財布|リュック|バッグ/i, '衣服'],
  [/USB|Type-?C|Lightning|ケーブル|充電器|急速充電|モバイルバッテリー|マウス|キーボード|SSD|HDD|microSD|SDカード|HDMI|ディスプレイ|モニター|Webカメラ|マイク|ハブ|ドッキング|LANケーブル|ルーター|スタンド|保護フィルム|スマホケース/i, '日用品'],
]

export function suggestAmazonCategory(title, cats) {
  const t = String(title || '').normalize('NFKC')
  for (const [re, cat] of AMZ_KEYWORDS) {
    if (re.test(t) && cats.includes(cat)) return cat
  }
  return cats.includes('その他') ? 'その他' : cats[0]
}

const pad2 = (n) => (n < 10 ? '0' : '') + n

const BULLET_RE = /^[*\-・•]\s+/          // コピー時に行頭へ付く「* 」など
const MD_LINK_RE = /\[([^\]]+)\]\([^)]*\)/g  // [テキスト](URL)
// 商品ページへのリンク（URLに /dp/ か /gp/product/ を含む）＝確実な商品名
const DP_LINK_RE = /\[([^\]]{4,})\]\([^)]*\/(?:dp|gp\/product)\/[^)]*\)/

/* 貼り付けテキスト → 注文リスト [{date, amount, title}]
   - 行頭の「* 」やMarkdownリンク形式（[商品名](URL)）に対応
   - 商品名は「商品ページ（/dp/）へのリンク」を最優先で採用（誤爆しない）
   - 金額は「合計」ラベルに紐づくものだけ（同じ行 or 直後1〜2行の￥金額）
   - 合計が読めなかった注文は除外（別注文の金額を誤って割り当てないため） */
export function parseAmazonOrders(text) {
  const rawLines = String(text || '').normalize('NFKC')
    .split(/\r?\n/).map((s) => s.trim().replace(BULLET_RE, '')).filter(Boolean)
  // Markdownリンクをテキストに落とした版（日付・合計・ノイズ判定用）
  const plain = rawLines.map((s) => s.replace(MD_LINK_RE, '$1'))

  const orders = []
  const push = (o) => {
    if (o && o.amount != null && o.amount > 0) orders.push(o)
  }
  let cur = null
  for (let i = 0; i < rawLines.length; i++) {
    const raw = rawLines[i]
    const line = plain[i]
    const dm = line.match(DATE_RE)
    // 注文の区切り：「注文日」ラベルと同じ行 or 直前の行がラベルの日付
    const isOrderStart = dm && (/注文日/.test(line) || /注文日/.test(plain[i - 1] ?? ''))
    if (isOrderStart) {
      push(cur)
      cur = {
        date: `${dm[1]}-${pad2(+dm[2])}-${pad2(+dm[3])}`,
        amount: null,
        dpTitles: [],   // 商品リンク由来（最優先）
        heurTitles: [], // 見た目からの推測（リンクが無いコピー形式用の保険）
      }
      continue
    }
    if (!cur) continue

    // 金額：「合計」に紐づくものだけを信じる
    if (cur.amount == null) {
      const tm = line.match(TOTAL_RE)
      if (tm) {
        cur.amount = parseInt(tm[1].replace(/,/g, ''), 10)
        continue
      }
      if (TOTAL_LABEL_RE.test(line)) {
        for (let j = i + 1; j <= i + 2 && j < plain.length; j++) {
          const ym = plain[j].match(YEN_RE)
          if (ym) {
            cur.amount = parseInt(ym[1].replace(/,/g, ''), 10)
            i = j
            break
          }
        }
        continue
      }
    }

    // 商品名①：商品ページ（/dp/）へのリンク＝確実
    const dp = raw.match(DP_LINK_RE)
    if (dp) {
      const t = dp[1].replace(/\s+/g, ' ').trim()
      if (t && !cur.dpTitles.includes(t)) cur.dpTitles.push(t)
      continue
    }
    // 商品名②：保険の推測（リンク形式でないコピー用）
    if (line.length >= 8 && line.length <= 120
        && !DATE_RE.test(line) && !NOISE_RE.test(line)) {
      if (cur.heurTitles.length < 3 && !cur.heurTitles.includes(line)) cur.heurTitles.push(line)
    }
  }
  push(cur)

  return orders.map((o) => {
    const ts = o.dpTitles.length ? o.dpTitles : o.heurTitles
    let title = '（商品名を読み取れず）'
    if (ts.length) {
      title = ts.slice(0, 2).join('／')
      if (ts.length > 2) title += ` 他${ts.length - 2}点`
      title = title.slice(0, 90)
    }
    return { date: o.date, amount: o.amount, title, items: o.dpTitles.length || o.heurTitles.length }
  })
}

const dayDiff = (a, b) =>
  Math.abs(new Date(a + 'T00:00:00') - new Date(b + 'T00:00:00')) / 86400000

/* 注文リスト × 既存記録 → マッチ一覧
   対象記録：内容に amazon/アマゾン を含む支出（同額・±5日・1対1）
   同額の候補が複数あるときは日付が最も近いものを選ぶ */
export function matchAmazonOrders(orders, entries) {
  const cands = entries
    .filter((e) => e.kind === 'spend'
      && /amazon|アマゾン|amzn/i.test(String(e.detail || '').normalize('NFKC')))
    .map((e) => ({ ...e, used: false }))
  const matches = []
  const unmatched = []
  for (const o of orders) {
    const hits = cands
      .filter((c) => !c.used
        && Math.round(c.amount) === Math.round(o.amount)
        && dayDiff(c.date, o.date) <= 5)
      .sort((a, b) => dayDiff(a.date, o.date) - dayDiff(b.date, o.date))
    if (hits.length) {
      hits[0].used = true
      matches.push({ order: o, entry: hits[0] })
    } else {
      unmatched.push(o)
    }
  }
  return { matches, unmatched, candidates: cands.length }
}
