// 日付・時刻・分数の書式（各画面で同じものを別々に書いていたのをまとめた。2026-11-06）
// 日付はすべて「端末の現地時刻」で扱う（toISOString は UTC なので、日本では朝9時前に前日になる）

export const pad2 = (n) => String(n).padStart(2, '0')

// Date → "YYYY-MM-DD"（現地時刻）
export function ymd(d = new Date()) {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`
}

// Date → "YYYY-MM"（現地時刻）
export const ym = (d = new Date()) => ymd(d).slice(0, 7)

// "HH:MM" → 0時からの分。不正な値は fallback
export function hmToMin(hm, fallback = 0) {
  const [h, m] = String(hm ?? '').split(':').map(Number)
  return Number.isFinite(h) ? h * 60 + (Number.isFinite(m) ? m : 0) : fallback
}

// 分 → "HH:MM"
export const fmtHM = (min) => `${pad2(Math.floor(min / 60))}:${pad2(Math.round(min % 60))}`

// 分 → 「1時間30分」「45分」
export function fmtMinJa(m) {
  const h = Math.floor(m / 60)
  return h > 0 ? `${h}時間${m % 60 > 0 ? `${m % 60}分` : ''}` : `${m}分`
}
