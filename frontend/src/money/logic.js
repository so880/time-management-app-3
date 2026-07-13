// 金銭管理の集計ロジック（旧 ikaseru/js/logic.js の移植・純粋関数版）
// entries（APIから取得した全記録）と settings を引数に取る。

export const VALIDITY_LABEL = { high: '高', fair: '適正', low: '安', unrated: '未判定' }
export const REC_LABEL = { buy: '買ってよい', consider: '要検討', hold: '今は見送り' }
export const USAGE_LABEL = { daily: 'ほぼ毎日', weekly: '週に数回', monthly: '月に数回', rare: 'ほとんど使っていない' }
export const NEED_LABEL = { high: '高い・必要', mid: 'ふつう', low: '低い・欲しいだけ' }

export function yen(n) {
  if (n == null || Number.isNaN(n)) return '—'
  return '¥' + Math.round(n).toLocaleString('ja-JP')
}

export function yenShort(n) {
  n = Math.round(n)
  if (n >= 10000) return (Math.round(n / 1000) / 10) + '万'
  return n.toLocaleString('ja-JP')
}

const pad2 = (n) => (n < 10 ? '0' : '') + n
export function todayStr() {
  const d = new Date()
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`
}
export const thisYM = () => todayStr().slice(0, 7)
export const ymOf = (dateStr) => (dateStr || '').slice(0, 7)
export function prevYM() {
  const d = new Date()
  d.setDate(1)
  d.setMonth(d.getMonth() - 1)
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}`
}

export const spends = (entries) => entries.filter((e) => e.kind === 'spend')
export const subs = (entries) => entries.filter((e) => e.kind === 'sub')
export const wishes = (entries) => entries.filter((e) => e.kind === 'wish')

export function monthlyOf(e) {
  if (e.kind === 'sub' && e.planMonths > 0) return e.amount / e.planMonths
  return e.amount
}

/* 今月の通常支出（合計・件数・「高め」件数） */
export function statsThisMonth(entries) {
  const ym = thisYM()
  const list = spends(entries).filter((e) => ymOf(e.date) === ym)
  return {
    total: list.reduce((a, b) => a + b.amount, 0),
    count: list.length,
    high: list.filter((e) => e.validity === 'high').length,
  }
}

/* サブスクの月あたり合計・件数・年額換算 */
export function subStats(entries) {
  const list = subs(entries)
  const monthly = list.reduce((a, b) => a + monthlyOf(b), 0)
  return { monthly, count: list.length, yearly: monthly * 12 }
}

export function prevMonthSpendTotal(entries) {
  const p = prevYM()
  return spends(entries).filter((e) => ymOf(e.date) === p)
    .reduce((a, b) => a + b.amount, 0)
}

/* 期間で通常支出を絞る（month / year / all） */
export function periodFilter(entries, period) {
  const ym = thisYM()
  const y = String(new Date().getFullYear())
  return spends(entries).filter((e) => {
    if (period === 'month') return ymOf(e.date) === ym
    if (period === 'year') return (e.date || '').slice(0, 4) === y
    return true
  })
}

export function periodTotal(entries, period) {
  return periodFilter(entries, period).reduce((a, b) => a + b.amount, 0)
}

/* 折れ線グラフ用の系列（旧 seriesForPeriod） */
export function seriesForPeriod(entries, period) {
  const now = new Date()
  if (period === 'month') {
    const ym = thisYM()
    const days = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate()
    const vals = Array(days).fill(0)
    const labels = Array.from({ length: days }, (_, i) => String(i + 1))
    spends(entries).forEach((e) => {
      if (ymOf(e.date) === ym) {
        const d = parseInt(e.date.slice(8, 10), 10)
        if (d >= 1 && d <= days) vals[d - 1] += e.amount
      }
    })
    return { labels, values: vals }
  }
  let startY, startM
  if (period === 'year') {
    startY = now.getFullYear(); startM = 1
  } else {
    const ds = spends(entries).map((e) => e.date).filter(Boolean).sort()
    if (ds.length) {
      startY = parseInt(ds[0].slice(0, 4), 10)
      startM = parseInt(ds[0].slice(5, 7), 10)
    } else {
      startY = now.getFullYear(); startM = now.getMonth() + 1
    }
  }
  const endY = now.getFullYear(); const endM = now.getMonth() + 1
  const keys = []; const labels = []
  let y = startY; let m = startM; let guard = 0
  while ((y < endY || (y === endY && m <= endM)) && guard++ < 600) {
    keys.push(`${y}-${pad2(m)}`)
    labels.push(period === 'year' ? `${m}月` : `${y}/${m}`)
    m++
    if (m > 12) { m = 1; y++ }
  }
  const idx = {}
  keys.forEach((k, i) => { idx[k] = i })
  const vals = keys.map(() => 0)
  spends(entries).forEach((e) => {
    const i = idx[ymOf(e.date)]
    if (i != null) vals[i] += e.amount
  })
  return { labels, values: vals }
}

/* カテゴリ別内訳（金額の多い順・％付き） */
export function breakdown(entries, period) {
  const list = periodFilter(entries, period)
  const map = {}
  let total = 0
  list.forEach((e) => {
    map[e.category] = (map[e.category] || 0) + e.amount
    total += e.amount
  })
  return Object.keys(map)
    .map((k) => ({ category: k, amount: map[k], pct: total > 0 ? (map[k] / total) * 100 : 0 }))
    .sort((a, b) => b.amount - a.amount)
}

/* 見直しポイント（旧 buildInsights） */
export function buildInsights(entries, allowance) {
  const out = []
  const st = statsThisMonth(entries)
  const ss = subStats(entries)
  const ym = thisYM()

  if (allowance != null && allowance !== '') {
    const bal = Number(allowance) - (st.total + ss.monthly)
    if (bal < 0) {
      out.push({ type: 'warn', text: `今月は仕送りより ${yen(-bal)} 多く使っています。下の内訳で金額の大きいカテゴリから見直すのが近道です。` })
    }
  }
  const prev = prevMonthSpendTotal(entries)
  if (prev > 0 && st.total > prev * 1.2) {
    out.push({ type: 'warn', text: `今月の通常支出は先月（${yen(prev)}）より約${Math.round((st.total / prev - 1) * 100)}%増えています。何にいくら増えたか、内訳で確認してみましょう。` })
  }
  const bd = breakdown(entries, 'month')
  if (bd.length && st.total > 0 && bd[0].pct >= 40) {
    out.push({ type: 'info', text: `今月は「${bd[0].category}」が支出の約${Math.round(bd[0].pct)}%を占めています。ここを1割減らすだけで約 ${yen(bd[0].amount * 0.1)} 浮きます。` })
  }
  const lowSat = spends(entries).filter((e) =>
    ymOf(e.date) === ym && e.validity === 'high' && e.satisfaction != null && e.satisfaction <= 2)
  if (lowSat.length) {
    out.push({ type: 'warn', text: `金額が高めなのに満足感が低い支出が${lowSat.length}件あります（例：「${lowSat[0].detail || lowSat[0].category}」）。次は同じ目的を小さい金額で満たせないか考えてみましょう。` })
  }
  const badSubs = subs(entries).filter((e) => {
    const s = e.satLog ? (e.satLog[ym] != null ? e.satLog[ym] : e.satLog[prevYM()]) : null
    return e.usage === 'rare' || (s != null && s <= 2)
  })
  if (badSubs.length) {
    const m = badSubs.reduce((a, b) => a + monthlyOf(b), 0)
    const names = badSubs.map((e) => e.detail || e.category).join('、')
    out.push({ type: 'warn', text: `使用頻度や満足度が低いサブスクが${badSubs.length}件（月あたり計 ${yen(m)}）：${names}。解約や安いプランへの変更を検討する価値があります。` })
  }
  const lowCnt = spends(entries).filter((e) => ymOf(e.date) === ym && e.validity === 'low').length
  if (lowCnt) {
    out.push({ type: 'good', text: `今月は「安く抑えられた」支出が${lowCnt}件ありました。良い選び方が増えています。` })
  }
  if (!out.length) {
    out.push({ type: 'good', text: '今のところ大きな見直しポイントはありません。記録を続けると、より具体的なアドバイスが出せるようになります。' })
  }
  return out
}

/* 月ごとの使用率（旧 monthlyUsageSeries） */
export function monthlyUsageSeries(entries, allowanceRaw) {
  const now = new Date()
  const ds = entries.map((e) => e.date).filter(Boolean).sort()
  let startY, startM
  if (ds.length) {
    startY = parseInt(ds[0].slice(0, 4), 10)
    startM = parseInt(ds[0].slice(5, 7), 10)
  } else {
    startY = now.getFullYear(); startM = now.getMonth() + 1
  }
  const endY = now.getFullYear(); const endM = now.getMonth() + 1
  const months = []
  let y = startY; let m = startM; let guard = 0
  while ((y < endY || (y === endY && m <= endM)) && guard++ < 600) {
    months.push({ ym: `${y}-${pad2(m)}`, label: `${y}年${m}月`, spend: 0, sub: 0 })
    m++
    if (m > 12) { m = 1; y++ }
  }
  const idx = {}
  months.forEach((o, i) => { idx[o.ym] = i })
  spends(entries).forEach((e) => {
    const i = idx[ymOf(e.date)]
    if (i != null) months[i].spend += e.amount
  })
  subs(entries).forEach((e) => {
    const start = ymOf(e.date)
    if (!start) return
    const sy = parseInt(start.slice(0, 4), 10)
    const sm = parseInt(start.slice(5, 7), 10)
    const n = e.planMonths || 1
    const per = e.amount / n
    for (let k = 0; k < n; k++) {
      const yy = sy + Math.floor((sm - 1 + k) / 12)
      const mm = ((sm - 1 + k) % 12) + 1
      const j = idx[`${yy}-${pad2(mm)}`]
      if (j != null) months[j].sub += per
    }
  })
  const allowance = (allowanceRaw != null && allowanceRaw !== '') ? Number(allowanceRaw) : null
  months.forEach((o) => {
    o.total = o.spend + o.sub
    o.pct = allowance && allowance > 0 ? (o.total / allowance) * 100 : null
  })
  return { months, allowance }
}
