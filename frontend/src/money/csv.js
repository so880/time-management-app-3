// 利用明細CSVの取り込みロジック（旧 ikaseru/js/import.js の移植・純粋関数版）
// Shift-JIS/UTF-8自動判別・列自動判定・店名→カテゴリ推定・重複検知

const pad2 = (n) => (n < 10 ? '0' : '') + n

/* 文字コードの自動判別：UTF-8として厳密に読めなければShift-JIS */
export function decodeCSVBuffer(buf) {
  try {
    return new TextDecoder('utf-8', { fatal: true }).decode(buf)
  } catch {
    return new TextDecoder('shift_jis').decode(buf)
  }
}

/* CSVの解析（"" 引用・改行・カンマ対応） */
export function parseCSV(text) {
  const rows = []
  let row = []
  let cur = ''
  let inQ = false
  for (let i = 0; i < text.length; i++) {
    const c = text[i]
    if (inQ) {
      if (c === '"') {
        if (text[i + 1] === '"') { cur += '"'; i++ } else inQ = false
      } else cur += c
    } else {
      if (c === '"') inQ = true
      else if (c === ',') { row.push(cur); cur = '' }
      else if (c === '\n') { row.push(cur); rows.push(row); row = []; cur = '' }
      else if (c === '\r') { /* CRは無視 */ }
      else cur += c
    }
  }
  if (cur !== '' || row.length) { row.push(cur); rows.push(row) }
  return rows.filter((r) => r.some((cell) => String(cell).trim() !== ''))
}

/* 日付の正規化（"2026/6/5"・"2026-06-05"・"2026年6月5日"・時刻付き に対応） */
export function normalizeDate(s) {
  if (s == null) return null
  const m = String(s).trim().match(/(20\d{2})[/\-.年](\d{1,2})[/\-.月](\d{1,2})/)
  if (!m) return null
  const y = parseInt(m[1], 10); const mo = parseInt(m[2], 10); const d = parseInt(m[3], 10)
  if (mo < 1 || mo > 12 || d < 1 || d > 31) return null
  return `${y}-${pad2(mo)}-${pad2(d)}`
}

/* 金額の正規化（¥・カンマ・全角数字・円 に対応） */
export function parseAmountCell(s) {
  if (s == null) return null
  const t = String(s)
    .replace(/[０-９]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0xFEE0))
    .replace(/[¥￥,，円\s"']/g, '')
  if (t === '' || !/^-?\d+(\.\d+)?$/.test(t)) return null
  const n = Number(t)
  return Number.isFinite(n) ? n : null
}

/* 列の自動判定 */
export function autoDetectColumns(rows) {
  let maxCols = 0
  rows.forEach((r) => { if (r.length > maxCols) maxCols = r.length })
  const n = Math.min(rows.length, 80)
  const dateHits = Array(maxCols).fill(0)
  const amtHits = Array(maxCols).fill(0)
  const txtLen = Array(maxCols).fill(0)
  for (let i = 0; i < n; i++) {
    const r = rows[i]
    for (let c = 0; c < maxCols; c++) {
      const v = r[c]
      if (v == null || String(v).trim() === '') continue
      if (normalizeDate(v)) dateHits[c]++
      else if (parseAmountCell(v) != null) amtHits[c]++
      else txtLen[c] += String(v).trim().length
    }
  }
  const argmax = (arr, exclude) => {
    let bi = -1; let bv = 0
    for (let k = 0; k < arr.length; k++) {
      if (exclude.includes(k)) continue
      if (arr[k] > bv) { bv = arr[k]; bi = k }
    }
    return bi
  }
  const dc = argmax(dateHits, [])
  const ac = argmax(amtHits, [dc])
  const tc = argmax(txtLen, [dc, ac])
  return { date: dc, amount: ac, desc: tc, cols: maxCols }
}

/* 店名 → カテゴリの自動推定（旧 CAT_KEYWORDS） */
const CAT_KEYWORDS = [
  [/セブン|ｾﾌﾞﾝ|ファミリーマート|ファミマ|ﾌｧﾐﾘ|ローソン|ﾛｰｿﾝ|ミニストップ|デイリーヤマザキ|スーパー|イオン|マルエツ|ライフ|西友|イトーヨーカドー|業務スーパー|オーケー/i, '食費'],
  [/マクドナルド|ﾏｸﾄﾞ|モスバーガー|ケンタッキー|すき家|吉野家|松屋|サイゼリヤ|ガスト|バーミヤン|くら寿司|スシロー|スターバックス|ｽﾀｰﾊﾞ|ドトール|タリーズ|カフェ|ラーメン|食堂|レストラン|居酒屋|UBER\s*EATS|出前館/i, '外食'],
  [/JR|ジェイアール|メトロ|地下鉄|鉄道|電鉄|バス|タクシー|SUICA|ｽｲｶ|PASMO|モバイルスイカ|ETC|高速道路/i, '交通'],
  [/マツモトキヨシ|ﾏﾂﾓﾄｷﾖｼ|ウエルシア|スギ薬局|ツルハ|ココカラ|ドラッグ|ダイソー|セリア|キャンドゥ|ニトリ|無印良品|カインズ|ホームセンター/i, '日用品'],
  [/書店|ブックオフ|BOOK|紀伊國屋|ジュンク|有隣堂|UDEMY|スクール|講座/i, '勉強・自己投資'],
  [/NETFLIX|SPOTIFY|APPLE\s*COM\s*BILL|APPLE\.COM\/BILL|GOOGLE|YOUTUBE|AMAZON\s*PRIME|PRIME\s*VIDEO|DAZN|HULU|U-NEXT|ニコニコ|携帯|ドコモ|DOCOMO|SOFTBANK|ソフトバンク|楽天モバイル|UQ|電気|ガス|水道|家賃|NHK/i, '固定費'],
  [/STEAM|NINTENDO|任天堂|PLAYSTATION|ゲーム|カラオケ|映画|TOHO|イオンシネマ|ライブ|チケット/i, '趣味・娯楽'],
  [/ユニクロ|UNIQLO|ジーユー|しまむら|ZOZO|ABCマート/i, '衣服'],
  [/病院|クリニック|歯科|調剤|内科|皮膚科|眼科|整骨/i, '健康・医療'],
]

export function suggestCategory(desc, shopMap, cats) {
  const d = String(desc || '').trim()
  if (d && shopMap[d] && cats.includes(shopMap[d])) return shopMap[d]
  const d2 = d.normalize ? d.normalize('NFKC') : d
  for (const [re, c] of CAT_KEYWORDS) {
    if ((re.test(d2) || re.test(d)) && cats.includes(c)) return c
  }
  return cats.includes('その他') ? 'その他' : cats[0]
}

/* 重複判定用のキー：日付+金額+内容（内容は全半角・空白・大文字小文字の揺れを吸収） */
export function normKey(date, amount, desc) {
  const d = String(desc ?? '').normalize('NFKC').trim().replace(/\s+/g, ' ').toLowerCase()
  return `${date}|${Number(amount)}|${d}`
}

/* 登録済みと同じ 日付+金額+内容 は「重複の疑い」 */
export function isDuplicate(entries, date, amount, desc) {
  const k = normKey(date, amount, desc)
  return entries.some((e) => e.kind === 'spend' && normKey(e.date, e.amount, e.detail) === k)
}

/* 日付文字列 'YYYY-MM-DD' 同士の差（日数・絶対値） */
function dayDiff(a, b) {
  return Math.abs(new Date(a + 'T00:00:00') - new Date(b + 'T00:00:00')) / 86400000
}

/* テキスト → 取り込み候補（旧 prepareImportFromText + rebuildImportItems）
   1) 登録済み明細（日付+金額+内容の完全一致）は件数つきで数え、その件数まで重複と見なす
      （同じ日に同じ店で同額を2回買った場合、2件目まで正しく取り込める）。
   2) メール通知から自動登録された記録（source==='mail'）は、明細と店名表記が違っても
      「±2日以内かつ同額」なら重複の疑いにする（月1のCSV答え合わせで二重計上しない）。
   これにより、期間が重なるCSVをいつ何度取り込んでも二重計上されない。 */
export function buildImportItems(rows, mapping, entries, shopMap, cats) {
  const counts = new Map()
  const mailEntries = []
  for (const e of entries) {
    if (e.kind !== 'spend') continue
    const k = normKey(e.date, e.amount, e.detail)
    counts.set(k, (counts.get(k) ?? 0) + 1)
    if (e.source === 'mail') mailEntries.push({ date: e.date, amount: e.amount, used: false })
  }
  const items = []
  rows.forEach((r) => {
    const date = normalizeDate(r[mapping.date])
    const amount = parseAmountCell(r[mapping.amount])
    if (!date || amount == null) return // ヘッダー行や合計行は自動的に外れる
    const desc = String(r[mapping.desc] == null ? '' : r[mapping.desc]).trim()
    const k = normKey(date, amount, desc)
    const left = counts.get(k) ?? 0
    let dup = left > 0
    let dupMail = false
    if (dup) {
      counts.set(k, left - 1)
    } else {
      // メール由来の登録と ±2日・同額 なら重複の疑い（1件のメール記録は1行までに対応）
      const m = mailEntries.find((me) => !me.used && me.amount === amount && dayDiff(me.date, date) <= 2)
      if (m) { m.used = true; dup = true; dupMail = true }
    }
    items.push({
      date, amount, desc,
      category: suggestCategory(desc, shopMap, cats),
      dup, dupMail,
      include: !dup && amount > 0, // 重複の疑い・マイナス（返金等）は初期チェックを外す
    })
  })
  return items
}
