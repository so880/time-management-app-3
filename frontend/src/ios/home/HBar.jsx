// ホーム（HomeIos.jsx）の部品：消化率の横棒。HomeIos.jsx から分けた（中身は同じ）

function HBar({ label, done, total, pct }) {
  const p = pct ?? (total > 0 ? Math.round((done / total) * 100) : null)
  return (
    <div className="habit-rate">
      <span className="habit-rate-label">{label}</span>
      <div className="habit-rate-track">
        <div className="habit-rate-fill"
             style={{ width: `${p ?? 0}%`,
                      background: (p ?? 0) >= 70 ? '#4CAF50' : (p ?? 0) >= 40 ? '#FF9F0A' : '#FF6B62' }} />
      </div>
      <span className="habit-rate-val">{p == null ? '—' : total != null ? `${done}/${total}` : `${p}%`}</span>
    </div>
  )
}

export default HBar
