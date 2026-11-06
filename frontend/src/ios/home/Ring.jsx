// ホーム（HomeIos.jsx）の部品：今日の進捗のリング。HomeIos.jsx から分けた（中身は同じ）

// Apple Watch のアクティビティリング風
function Ring({ pct, size = 108, stroke = 11 }) {
  const r = (size - stroke) / 2
  const c = 2 * Math.PI * r
  return (
    <svg width={size} height={size} role="img" aria-label={`進捗 ${Math.round(pct * 100)}%`}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(255,255,255,0.12)" strokeWidth={stroke} />
      <circle cx={size / 2} cy={size / 2} r={r} fill="none"
              stroke="#4CAF50" strokeWidth={stroke} strokeLinecap="round"
              strokeDasharray={c} strokeDashoffset={c * (1 - pct)}
              transform={`rotate(-90 ${size / 2} ${size / 2})`}
              style={{ transition: 'stroke-dashoffset 0.8s cubic-bezier(0.32,0.72,0.28,1)' }} />
      <text x="50%" y="50%" textAnchor="middle" dominantBaseline="central"
            fill="#4CAF50" fontSize="1.4rem" fontWeight="800">{Math.round(pct * 100)}%</text>
    </svg>
  )
}

export default Ring
