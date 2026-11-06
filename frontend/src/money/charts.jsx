// 💰 マネータブのグラフ（折れ線・月別使用率のドーナツ）。MoneyIos.jsx から分けた（中身は同じ）
import { yen, yenShort } from './logic.js'

/* ---------- 折れ線グラフ（旧 chartSVG） ---------- */
export function LineChart({ series }) {
  const { values: vals, labels } = series
  const w = 640; const h = 210; const pl = 56; const pr = 14; const pt = 16; const pb = 30
  const iw = w - pl - pr; const ih = h - pt - pb
  let max = 1
  vals.forEach((v) => { if (v > max) max = v })
  const x = (i) => (vals.length <= 1 ? pl + iw / 2 : pl + (iw * i) / (vals.length - 1))
  const y = (v) => pt + ih - (v / max) * ih
  const pts = vals.map((v, i) => `${x(i)},${y(v)}`).join(' ')
  const idxs = vals.length > 2 ? [0, Math.floor((vals.length - 1) / 2), vals.length - 1]
    : vals.map((_, i) => i)
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="m-chart" role="img">
      {[0, 0.5, 1].map((f) => {
        const gy = pt + ih - f * ih
        return (
          <g key={f}>
            <line x1={pl} y1={gy} x2={w - pr} y2={gy} stroke="rgba(255,255,255,0.12)" />
            <text x={pl - 6} y={gy + 4} textAnchor="end" fontSize="11" fill="#8a8f98">
              {yenShort(max * f)}
            </text>
          </g>
        )
      })}
      <polyline points={pts} fill="none" stroke="#4CAF50" strokeWidth="2" />
      {vals.map((v, i) => (v > 0
        ? <circle key={i} cx={x(i)} cy={y(v)} r="3" fill="#4CAF50"><title>{labels[i]} {yen(v)}</title></circle>
        : null))}
      {[...new Set(idxs)].map((i) => (
        <text key={i} x={x(i)} y={h - 8} textAnchor="middle" fontSize="11" fill="#8a8f98">
          {labels[i]}
        </text>
      ))}
    </svg>
  )
}

/* ---------- 月別使用率のドーナツ（旧 usageDonutSVG） ---------- */
export function UsageDonut({ pct }) {
  const r = 30; const c = 38; const sw = 10
  const C = 2 * Math.PI * r
  const p = Math.max(0, Math.min(pct, 100))
  const color = pct > 100 ? '#FF3B30' : pct >= 80 ? '#FF9F0A' : '#4CAF50'
  return (
    <svg viewBox="0 0 76 76" width="76" height="76">
      <circle cx={c} cy={c} r={r} fill="none" stroke="rgba(255,255,255,0.15)" strokeWidth={sw} />
      {p > 0 && (
        <circle cx={c} cy={c} r={r} fill="none" stroke={color} strokeWidth={sw}
                strokeLinecap="round" strokeDasharray={`${(p / 100) * C} ${C}`}
                transform={`rotate(-90 ${c} ${c})`} />
      )}
      <text x={c} y={c + 5} textAnchor="middle" fontSize="16" fontWeight="800" fill="#fff">
        {Math.round(pct)}%
      </text>
    </svg>
  )
}
