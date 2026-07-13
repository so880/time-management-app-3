// 1日のタイムライン（横型：時間が左→右に流れる）
// 3レーン：予定（時間割＋単発）／実績（手入力＋勉強アプリ）／PC（自動記録）
// - 横スクロール（今日は現在時刻付近まで自動スクロール）
// - 小さいブロックはカーソルを合わせるとツールチップで内容を表示
// - 日をまたぐ予定（睡眠等）は分割して表示
import { useEffect, useRef, useState } from 'react'
import { useNow } from '../components/useNow.js'
import { CATEGORY_COLORS } from './LifeIos.jsx'

const HOUR_W = 56               // 1時間の幅(px)
const DAY_W = 24 * HOUR_W

function toMin(hhmm) {
  const [h, m] = String(hhmm ?? '0:0').split(':').map(Number)
  return (h * 60 + m) || 0
}

// 開始/終了(分)を、日またぎなら2つに分割して返す
function segments(startMin, endMin) {
  if (endMin > startMin) return [[startMin, endMin]]
  if (endMin === startMin) return []
  return [[startMin, 1440], [0, endMin]]  // 例: 睡眠 23:00〜06:30
}

// PCセッションを見やすくまとめる（同じアプリが60秒以内に続いたら結合）
function mergePc(sessions) {
  const out = []
  for (const s of sessions ?? []) {
    const last = out[out.length - 1]
    if (last && last.app === s.app && s.start_ts - last.end_ts < 60) {
      last.end_ts = s.end_ts
    } else {
      out.push({ ...s })
    }
  }
  return out
}

const fmtMin = (m) =>
  `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(Math.round(m % 60)).padStart(2, '0')}`

function TimelineDay({ day, date, isToday }) {
  const now = useNow(30000)
  const scrollRef = useRef(null)
  const [tip, setTip] = useState(null) // {x, y, title, sub}

  const dayStartMs = new Date(date + 'T00:00:00').getTime()
  const nowMin = (now - dayStartMs) / 60000
  const toPx = (min) => (min / 60) * HOUR_W

  // 今日は現在時刻の少し手前まで自動スクロール（初回のみ）
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollLeft = isToday
        ? Math.max(0, toPx(nowMin) - 260)
        : toPx(7 * 60) // 過去日は朝7時から
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [date])

  // レーン1：予定（時間割＋単発予定）
  const plans = []
  for (const b of day?.schedule ?? []) {
    for (const [s, e] of segments(toMin(b.start), toMin(b.end))) {
      plans.push({ s, e, title: b.title, cat: b.category, cancelled: b.cancelled })
    }
  }
  for (const ev of day?.events ?? []) {
    for (const [s, e] of segments(toMin(ev.start), toMin(ev.end))) {
      plans.push({ s, e, title: ev.title, cat: ev.category })
    }
  }
  // レーン2：実績（手入力＋勉強アプリの記録）
  const acts = []
  for (const en of day?.entries ?? []) {
    for (const [s, e] of segments(toMin(en.start), toMin(en.end))) {
      acts.push({ s, e, title: en.title, cat: en.category })
    }
  }
  for (const st of day?.study ?? []) {
    for (const [s, e] of segments(toMin(st.start), toMin(st.end))) {
      acts.push({ s, e, title: st.title, cat: st.category })
    }
  }
  // レーン3：PC（自動記録）
  const pcs = mergePc(day?.pc).map((p) => {
    const s = Math.max(0, (p.start_ts * 1000 - dayStartMs) / 60000)
    const e = Math.min(1440, (p.end_ts * 1000 - dayStartMs) / 60000)
    return { s, e, title: p.app.replace(/\.exe$/i, ''), cat: null, sub: p.title }
  }).filter((p) => p.e > p.s)

  const show = (ev, b) => {
    setTip({
      x: ev.clientX, y: ev.clientY,
      title: b.title + (b.cancelled ? '（休講）' : ''),
      sub: `${fmtMin(b.s)}〜${fmtMin(b.e)}（${Math.round(b.e - b.s)}分）` + (b.sub ? `\n${b.sub}` : ''),
    })
  }
  const hide = () => setTip(null)

  const Lane = ({ label, items, color }) => (
    <div className="tlh-lane">
      <span className="tlh-lane-label">{label}</span>
      {items.map((b, i) => (
        <div key={i}
             className={'tlh-block' + (b.cancelled ? ' cancelled' : '')}
             style={{
               left: `${toPx(b.s)}px`,
               width: `${Math.max(toPx(b.e - b.s), 6)}px`,
               background: (color ?? CATEGORY_COLORS[b.cat] ?? '#8E8E93') + '3A',
               borderLeftColor: color ?? CATEGORY_COLORS[b.cat] ?? '#8E8E93',
             }}
             onMouseEnter={(ev) => show(ev, b)}
             onMouseMove={(ev) => show(ev, b)}
             onMouseLeave={hide}>
          <span className="tlh-title">{b.title}</span>
        </div>
      ))}
    </div>
  )

  return (
    <div className="tlh-outer">
      <div className="tlh-scroll" ref={scrollRef}>
        <div className="tlh-inner" style={{ width: `${DAY_W}px` }}>
          {/* 時刻の目盛り（上辺） */}
          <div className="tlh-hours">
            {Array.from({ length: 24 }, (_, h) => (
              <span key={h} className="tlh-hlabel" style={{ left: `${toPx(h * 60)}px` }}>
                {h}:00
              </span>
            ))}
          </div>
          <div className="tlh-lanes">
            <Lane label="📋 予定" items={plans} />
            <Lane label="✅ 実績" items={acts} />
            <Lane label="💻 PC" items={pcs} color="#64D2FF" />
            {/* 現在時刻の赤線（今日のみ） */}
            {isToday && nowMin >= 0 && nowMin <= 1440 && (
              <div className="tlh-nowline" style={{ left: `${toPx(nowMin)}px` }}>
                <span />
              </div>
            )}
          </div>
        </div>
      </div>
      <div className="caption" style={{ margin: '6px 4px' }}>
        ← 横にスクロールできます。ブロックにカーソルを合わせると詳細が出ます。
      </div>

      {/* カーソル追従ツールチップ */}
      {tip && (
        <div className="tl-tip"
             style={{
               left: Math.min(tip.x + 14, window.innerWidth - 280),
               top: tip.y + 16,
             }}>
          <div className="tl-tip-title">{tip.title}</div>
          <div className="tl-tip-sub">{tip.sub}</div>
        </div>
      )}
    </div>
  )
}

export default TimelineDay
