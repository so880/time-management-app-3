// ホーム（HomeIos.jsx）の部品：今日の時間軸の帯。HomeIos.jsx から分けた（中身は同じ）

// 📅 今日の時間軸の帯（05:00〜23:00）。上段＝時間帯のある習慣、下段＝授業・予定・Google。赤い線＝いま
function DayStrip({ items, now }) {
  const H0 = 5, H1 = 23
  const pos = (t) => { const [h, m] = t.split(':').map(Number); return Math.max(0, Math.min(100, ((h + m / 60) - H0) / (H1 - H0) * 100)) }
  const hours = []
  for (let h = H0; h <= H1; h += 1) hours.push(h)
  return (
    <div className="day-strip" aria-label="今日の時間軸">
      {hours.map((h) => <span key={h} className="ds-h" style={{ left: `${pos(`${h}:00`)}%` }}>{h}</span>)}
      {items.map((b, i) => (
        <span key={i} className={'ds-blk ' + b.kind + (b.done ? ' done' : '')} title={`${b.start}〜${b.end} ${b.title}`}
              style={{ left: `${pos(b.start)}%`, width: `${Math.max(1.2, pos(b.end) - pos(b.start))}%` }}>{b.title}</span>
      ))}
      <span className="ds-now" style={{ left: `${pos(now)}%` }} />
    </div>
  )
}

export default DayStrip
