// ホーム（HomeIos.jsx）の部品：最近14日の折れ線。HomeIos.jsx から分けた（中身は同じ）

// 📈 折れ線（勉強分＝緑・習慣達成率＝青）＋ ノルマ達成✓／stop_all🛑
function TrendChart({ data }) {
  const W = 340, H = 120, PADL = 8, PADR = 8, TOP = 10, BOT = 22
  const n = data.length
  if (n === 0) return null
  const xs = (i) => PADL + (n === 1 ? (W - PADL - PADR) / 2 : (i * (W - PADL - PADR)) / (n - 1))
  const maxStudy = Math.max(60, ...data.map((d) => d.study_min))
  const yStudy = (v) => TOP + (H - TOP - BOT) * (1 - v / maxStudy)
  const yRate = (v) => TOP + (H - TOP - BOT) * (1 - v / 100)
  const studyPts = data.map((d, i) => `${xs(i)},${yStudy(d.study_min)}`).join(' ')
  const ratePts = data.filter((d) => d.habit_rate != null)
    .map((d) => `${xs(data.indexOf(d))},${yRate(d.habit_rate)}`).join(' ')
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="trend-svg" role="img">
      {[0, 50, 100].map((p) => (
        <line key={p} x1={PADL} x2={W - PADR} y1={yRate(p)} y2={yRate(p)} stroke="rgba(255,255,255,0.12)" strokeDasharray="3 3" />
      ))}
      {ratePts && <polyline points={ratePts} fill="none" stroke="#64B5F6" strokeWidth="2" />}
      <polyline points={studyPts} fill="none" stroke="#4CAF50" strokeWidth="2.5" />
      {data.map((d, i) => (
        <g key={d.date}>
          <circle cx={xs(i)} cy={yStudy(d.study_min)} r="3" fill="#4CAF50" />
          {d.habit_rate != null && <circle cx={xs(i)} cy={yRate(d.habit_rate)} r="2.5" fill="#64B5F6" />}
          <text x={xs(i)} y={H - 6} textAnchor="middle" fontSize="11"
                fill={d.stopped ? '#FF6B62' : d.gate_done ? '#4CAF50' : 'rgba(255,255,255,0.35)'}>
            {d.stopped ? '🛑' : d.gate_done === true ? '✓' : d.gate_done === false ? '○' : ''}
          </text>
        </g>
      ))}
      <text x={PADL} y={H - 6} fontSize="9" fill="#9aa0a8" textAnchor="start" dy="-12">{data[0].label}</text>
      <text x={W - PADR} y={H - 6} fontSize="9" fill="#9aa0a8" textAnchor="end" dy="-12">{data[n - 1].label}</text>
    </svg>
  )
}

export default TrendChart
