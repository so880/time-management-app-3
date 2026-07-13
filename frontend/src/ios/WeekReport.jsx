// 週次レポート（L5）：日別のカテゴリ積み上げグラフ・勉強合計・課題の消化状況など
import { useEffect, useState } from 'react'
import * as api from '../api.js'
import { CATEGORY_COLORS } from './LifeIos.jsx'

const DAY_NAMES = ['月', '火', '水', '木', '金', '土', '日']

function fmtMin(m) {
  const h = Math.floor(m / 60)
  return h > 0 ? `${h}時間${m % 60 > 0 ? `${m % 60}分` : ''}` : `${m}分`
}

function fmtDate(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function WeekReport({ onBack }) {
  const [weekOffset, setWeekOffset] = useState(0) // 0=今週, -1=先週
  const [data, setData] = useState(null)
  const [prev, setPrev] = useState(null)

  useEffect(() => {
    const d = new Date()
    d.setDate(d.getDate() + weekOffset * 7)
    const p = new Date(d)
    p.setDate(p.getDate() - 7)
    api.getLifeWeek(fmtDate(d)).then(setData).catch(() => {})
    api.getLifeWeek(fmtDate(p)).then(setPrev).catch(() => {})
  }, [weekOffset])

  if (!data) return <div className="caption">集計中…</div>

  // 積み上げグラフ（睡眠は除いて見やすく）
  const stacks = data.days.map((d) => {
    const segs = Object.entries(d.categories)
      .filter(([c]) => c !== '睡眠')
      .sort((a, b) => b[1] - a[1])
    return { total: segs.reduce((s, [, m]) => s + m, 0), segs }
  })
  const maxTotal = Math.max(...stacks.map((s) => s.total), 1)
  const diff = prev ? data.study_total - prev.study_total : 0

  // 凡例（登場したカテゴリ）
  const legend = [...new Set(stacks.flatMap((s) => s.segs.map(([c]) => c)))]

  return (
    <div className="page-anim">
      <button type="button" className="ios-back" onClick={onBack}>‹ ライフ</button>
      <h2 className="ios-section-title">
        <span className="r-icon" style={{ background: '#34C759' }}>📈</span>
        週次レポート
      </h2>

      <div className="life-datenav">
        <button className="small" onClick={() => setWeekOffset(weekOffset - 1)}>‹ 前週</button>
        <div className="life-date">
          {data.week_start.slice(5).replace('-', '/')} 〜 {data.week_end.slice(5).replace('-', '/')}
          {weekOffset === 0 ? '・今週' : ''}
        </div>
        <button className="small" onClick={() => setWeekOffset(weekOffset + 1)}
                disabled={weekOffset >= 0}>翌週 ›</button>
      </div>

      {/* 勉強合計と前週比 */}
      <div className="ios-widget" style={{ marginBottom: 12 }}>
        <div className="w-label">📚 今週の勉強合計</div>
        <div className="w-big">{fmtMin(data.study_total)}</div>
        {prev && (
          <div className="w-sub">
            前週 {fmtMin(prev.study_total)}（{diff >= 0 ? `+${fmtMin(diff)} 🔥` : `−${fmtMin(-diff)}`}）
          </div>
        )}
      </div>

      {/* 日別の積み上げグラフ */}
      <div className="ios-widget" style={{ marginBottom: 12 }}>
        <div className="w-label">📊 日別の過ごし方（睡眠を除く）</div>
        <div className="week-bars" style={{ height: 150 }}>
          {stacks.map((s, i) => (
            <div className="wb-col" key={i}>
              <div className="wb-val">{s.total > 0 ? Math.round(s.total / 60) + 'h' : ''}</div>
              <div className="wb-stack" style={{ height: `${Math.max(4, (s.total / maxTotal) * 110)}px` }}>
                {s.segs.map(([c, m]) => (
                  <div key={c} title={`${c} ${fmtMin(m)}`}
                       style={{ height: `${(m / Math.max(s.total, 1)) * 100}%`,
                                background: CATEGORY_COLORS[c] ?? '#8E8E93' }} />
                ))}
              </div>
              <div className="wb-day">{DAY_NAMES[i]}</div>
            </div>
          ))}
        </div>
        <div className="week-legend">
          {legend.map((c) => (
            <span key={c} className="legend-item">
              <span className="legend-dot" style={{ background: CATEGORY_COLORS[c] ?? '#8E8E93' }} />
              {c}
            </span>
          ))}
        </div>
      </div>

      {/* 今週の支出（マネー連動） */}
      <div className="ios-widget" style={{ marginBottom: 12 }}>
        <div className="w-label">💰 今週の支出</div>
        <div className="w-big">¥{Math.round(data.money_total ?? 0).toLocaleString()}</div>
        {prev && (
          <div className="w-sub">
            前週 ¥{Math.round(prev.money_total ?? 0).toLocaleString()}（
            {(data.money_total ?? 0) - (prev.money_total ?? 0) >= 0 ? '+' : '−'}
            ¥{Math.abs(Math.round((data.money_total ?? 0) - (prev.money_total ?? 0))).toLocaleString()}）
          </div>
        )}
        {(data.money_by_category ?? []).map((m) => (
          <div className="hbar-row" key={m.category}>
            <span className="hbar-label">{m.category}</span>
            <div className="hbar-track">
              <div className="hbar-fill"
                   style={{ width: `${(m.amount / (data.money_by_category[0]?.amount ?? 1)) * 100}%`,
                            background: '#FFD60A' }} />
            </div>
            <span className="hbar-val">¥{Math.round(m.amount).toLocaleString()}</span>
          </div>
        ))}
      </div>

      {/* 課題の消化状況 */}
      <div className="ios-widget" style={{ marginBottom: 12 }}>
        <div className="w-label">📚 今週期限の課題</div>
        <div className="w-big">
          {data.assignments.done}<span className="w-unit">/{data.assignments.total} 完了</span>
        </div>
        {data.assignments.overdue > 0 && (
          <div className="w-sub" style={{ color: '#FF6B62' }}>
            ⚠️ 期限切れが {data.assignments.overdue} 件あります
          </div>
        )}
      </div>

      {/* 週のPC使用上位 */}
      <div className="ios-widget">
        <div className="w-label">💻 今週よく使ったアプリ</div>
        {(data.pc_apps ?? []).length === 0 && <div className="caption">記録なし</div>}
        {(data.pc_apps ?? []).map((a) => (
          <div className="hbar-row" key={a.app}>
            <span className="hbar-label">{a.app}</span>
            <div className="hbar-track">
              <div className="hbar-fill"
                   style={{ width: `${(a.minutes / (data.pc_apps[0]?.minutes ?? 1)) * 100}%`,
                            background: '#64D2FF' }} />
            </div>
            <span className="hbar-val">{fmtMin(a.minutes)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default WeekReport
