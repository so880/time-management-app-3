// 週次レポート（L5）：日別のカテゴリ積み上げグラフ・勉強合計・課題の消化状況など
import { useEffect, useState } from 'react'
import * as api from '../api.js'
import { CATEGORY_COLORS } from '../lib/categories.js'
import { fmtMinJa as fmtMin, ymd as fmtDate } from '../lib/format.js'

const DAY_NAMES = ['月', '火', '水', '木', '金', '土', '日']

function WeekReport({ onBack }) {
  const [weekOffset, setWeekOffset] = useState(0) // 0=今週, -1=先週
  const [data, setData] = useState(null)
  const [prev, setPrev] = useState(null)
  const [avg, setAvg] = useState(null)   // 📊 平均勉強時間（曜日別・平日/休日・月別）
  const [cam, setCam] = useState(null)   // 📷 在席率（F22。オフまたは記録なしなら出さない）

  useEffect(() => {
    const d = new Date()
    d.setDate(d.getDate() + weekOffset * 7)
    const p = new Date(d)
    p.setDate(p.getDate() - 7)
    api.getLifeWeek(fmtDate(d)).then(setData).catch(() => {})
    api.getLifeWeek(fmtDate(p)).then(setPrev).catch(() => {})
    const e = new Date(d)
    e.setDate(e.getDate() + (6 - (e.getDay() + 6) % 7))  // その週の日曜まで
    api.getPresenceWeek(fmtDate(e)).then(setCam).catch(() => setCam(null))
  }, [weekOffset])
  useEffect(() => {
    api.getStudyAverages().then(setAvg).catch(() => {})
  }, [])

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
      <button type="button" className="ios-back" onClick={onBack}>‹ 今日</button>
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

      {/* 📊 平均勉強時間（直近90日：曜日別・平日/休日・月別の1日平均） */}
      {avg && (() => {
        const wdMax = Math.max(...avg.weekday.map((w) => w.avg), 1)
        return (
          <div className="ios-widget" style={{ marginTop: 12 }}>
            <div className="w-label">📊 1日あたりの平均勉強時間（直近{avg.days}日・勉強しなかった日も0分として計算）</div>
            {avg.weekday.map((w) => (
              <div className="hbar-row" key={w.weekday}>
                <span className="hbar-label">{w.label}曜</span>
                <div className="hbar-track">
                  <div className="hbar-fill"
                       style={{ width: `${Math.max(2, (w.avg / wdMax) * 100)}%`,
                                background: w.weekday >= 5 ? '#FF9F0A' : '#4CAF50' }} />
                </div>
                <span className="hbar-val">{fmtMin(w.avg)}</span>
              </div>
            ))}
            <div className="edit-row" style={{ marginTop: 8 }}>
              <span className="caption">🏢 平日平均：<strong style={{ color: '#fff' }}>{fmtMin(avg.workday_avg)}</strong></span>
              <span className="caption">🏖 休日平均（土日祝）：<strong style={{ color: '#fff' }}>{fmtMin(avg.holiday_avg)}</strong></span>
            </div>
            <div className="caption" style={{ marginTop: 10 }}>📅 月別の1日平均</div>
            {avg.months.map((m) => (
              <div className="hbar-row" key={m.ym}>
                <span className="hbar-label">{m.label}</span>
                <div className="hbar-track">
                  <div className="hbar-fill"
                       style={{ width: `${Math.max(2, (m.avg / Math.max(...avg.months.map((x) => x.avg), 1)) * 100)}%`,
                                background: '#5E5CE6' }} />
                </div>
                <span className="hbar-val">{fmtMin(m.avg)}<span className="caption">（計{fmtMin(m.total)}）</span></span>
              </div>
            ))}
          </div>
        )
      })()}

      {/* 📷 在席率（在席判定がオンで記録がある週だけ） */}
      {cam && cam.days.some((x) => x.rate != null) && (
        <div className="ios-widget" style={{ marginTop: 12 }}>
          <div className="w-label">📷 在席率（監視時間のうち顔が映っていた割合。基準 {cam.rate_min}%）</div>
          {cam.days.map((x) => (
            <div className="hbar-row" key={x.date}>
              <span className="hbar-label">{x.label}</span>
              <div className="hbar-track">
                <div className="hbar-fill" style={{ width: `${x.rate ?? 0}%`, background: x.rate == null ? 'transparent' : x.rate >= cam.rate_min ? '#4CAF50' : '#FF9F0A' }} />
              </div>
              <span className="hbar-val">{x.rate == null ? '—' : `${x.rate}%`}<span className="caption">（在席 {x.present_min}分／監視 {x.monitored_min}分）</span></span>
            </div>
          ))}
          <div className="caption">不在＝サボりとは限りません（画角外の作業・外出など）。</div>
        </div>
      )}
    </div>
  )
}

export default WeekReport
