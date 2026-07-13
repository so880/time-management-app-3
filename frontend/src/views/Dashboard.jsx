// ダッシュボード（views/dashboard.py の使用モード部分の移植）
// 左：ルーレット＆残り作業可能時間 ／ 右：今日の進捗
import { useEffect, useRef, useState } from 'react'
import * as api from '../api.js'
import { ensureNotifyPermission } from '../components/notify.js'
import { useNow } from '../components/useNow.js'

// ---- 左カラム：ゲーム解放表示＋ルーレット＋目標カード ----
function RouletteAndGoals({ settings, state, game, onStateChange, showToast }) {
  const [selected, setSelected] = useState(null)
  const resultRef = useRef(null)
  const ro = state.rolled_options

  // 抽選結果が出たら結果へスクロール（既存のscrollIntoViewと同じ）
  useEffect(() => {
    if (ro && resultRef.current) {
      resultRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  }, [ro])

  const studyOnly = state.last_was_refresh || state.force_study_only

  const roll = async () => {
    await api.rollRoulette()
    const st = await api.getState()
    setSelected(`【勉強】 ${st.rolled_options?.['勉強'] ?? ''}`)
    onStateChange(st)
  }

  const start = async () => {
    if (!selected) return
    ensureNotifyPermission() // 終了通知のための許可をユーザー操作のタイミングで求める
    const cat = selected.includes('【勉強】') ? '勉強' : '気分転換'
    const task = selected.replace(`【${cat}】 `, '')
    const st = await api.chooseTask(cat, task)
    onStateChange(st)
  }

  const choices = ro
    ? [
        `【勉強】 ${ro['勉強']}`,
        ...(!studyOnly ? [`【気分転換】 ${ro['気分転換']}`] : []),
      ]
    : []

  return (
    <div>
      <h3>🎲 ルーレット ＆ 残り作業可能時間</h3>

      {game.unlocked ? (
        <div className="success-box">🎉 ゲーム解放条件クリア！</div>
      ) : (
        <div className="info-box">
          🔒 ゲーム解放まで: 勉強 {game.study_time_total}/{game.target_value}分 &amp; 20時以降
        </div>
      )}

      {!ro && (
        <button className="big" onClick={roll}>
          🎲 カフェルーレットを回す！
        </button>
      )}

      {ro && (
        <div ref={resultRef}>
          {state.force_study_only && !state.last_was_refresh && (
            <div className="info-box">
              📚 今回は『勉強』のみの抽選です（短い課題の早期修了後・SOS明けなど）。
            </div>
          )}
          {choices.map((c) => (
            <label
              key={c}
              className={'option-label' + (selected === c ? ' selected' : '')}
            >
              <input
                type="radio"
                name="exec_task"
                checked={selected === c}
                onChange={() => setSelected(c)}
                style={{ marginRight: 10 }}
              />
              {c}
            </label>
          ))}
          <button className="big" onClick={start} disabled={!selected}>
            集中モードへ！
          </button>
        </div>
      )}

      <div className="hr" />
      <h4>🏁 残り作業可能時間（目標まで）</h4>
      <GoalCards goals={settings.goals ?? []} />
    </div>
  )
}

function GoalCards({ goals }) {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const rows = []
  for (let i = 0; i < goals.length; i += 2) rows.push(goals.slice(i, i + 2))
  return (
    <>
      {rows.map((row, ri) => (
        <div className="milestone-row" key={ri}>
          {row.map((g) => {
            let days = 0
            const d = new Date(g.date + 'T00:00:00')
            if (!Number.isNaN(d.getTime())) {
              days = Math.max(Math.round((d - today) / 86400000), 0)
            }
            const hours = parseInt(g.hours ?? 2, 10)
            return (
              <div className="milestone-card" key={g.name}>
                <div className="milestone-title">
                  {g.name}（{g.date}）まであと {days} 日
                </div>
                <div style={{ color: '#ccc', marginTop: 2 }}>🔥 残り作業可能</div>
                <div className="glowing-hours">
                  {days * hours} <span className="unit">時間</span>
                </div>
              </div>
            )
          })}
        </div>
      ))}
    </>
  )
}

// ---- 右カラム：今日の進捗 ----
// 今日の「勉強できる時間帯」を [開始ms, 終了ms] のリストにする（既存 today_intervals_ms と同じ）
// ※ iOS版ホーム（ios/HomeIos.jsx）からも使うため export する
export function todayIntervalsMs(settings) {
  const routine = settings.daily_routine ?? []
  const jsDay = new Date().getDay() // 日=0 ... 土=6
  const wd = (jsDay + 6) % 7        // 月=0 ... 日=6（既存Pythonの weekday() に合わせる）
  const blocks = routine[wd] ?? []
  const out = []
  for (const b of blocks) {
    try {
      const [sh, sm] = String(b.start ?? '09:00').split(':').map(Number)
      const [eh, em] = String(b.end ?? '22:00').split(':').map(Number)
      const s = new Date(); s.setHours(sh, sm, 0, 0)
      const e = new Date(); e.setHours(eh, em, 0, 0)
      if (e > s) out.push([s.getTime(), e.getTime()])
    } catch { /* 形式が壊れた行は無視 */ }
  }
  return out
}

function Progress({ settings, state, onStateChange }) {
  const now = useNow(1000)
  const [h, setH] = useState(Math.min(Math.floor(state.target_value / 60), 16))
  const [m, setM] = useState(Math.min(Math.round((state.target_value % 60) / 15) * 15, 45))

  // 残り時間（1秒カウントダウン）
  const ivs = todayIntervalsMs(settings)
  let totalMs = 0
  for (const [s, e] of ivs) if (now < e) totalMs += e - Math.max(now, s)
  const r = Math.floor(totalMs / 1000)
  const rh = Math.floor(r / 3600)
  const rm = Math.floor((r % 3600) / 60)
  const rs = r % 60

  const lockTarget = async () => {
    const total = Math.max(30, h * 60 + m)
    const st = await api.patchState({ target_value: total, target_locked: true })
    onStateChange(st)
  }

  const target = state.target_locked ? state.target_value : Math.max(30, h * 60 + m)
  const percent = target > 0 ? Math.min(state.study_time_total / target, 1) : 1
  const deg = Math.round(percent * 360)
  const remaining = Math.max(0, target - state.study_time_total)

  return (
    <div>
      <h3>📊 今日の進捗</h3>

      <div className="remain-card">
        <div className="remain-label">🕐 今日まだ勉強できる時間</div>
        {r <= 0 ? (
          <div className="remain-value over">本日は終了です</div>
        ) : (
          <div className="remain-value">
            {rh > 0 ? `${rh}時間 ` : ''}{rm}分 {rs}秒
          </div>
        )}
        <div className="caption">勉強できる時間帯のみで計算（大学・食事などは除外）</div>
      </div>

      {!state.target_locked ? (
        <div style={{ marginTop: 12 }}>
          <strong>今日の目標勉強時間</strong>
          <div style={{ display: 'flex', gap: 10, marginTop: 6 }}>
            <label>
              時間{' '}
              <input type="number" min="0" max="16" step="1" value={h}
                     style={{ width: 80 }}
                     onChange={(e) => setH(Math.max(0, Math.min(16, parseInt(e.target.value || 0, 10))))} />
            </label>
            <label>
              分（15刻み）{' '}
              <input type="number" min="0" max="45" step="15" value={m}
                     style={{ width: 80 }}
                     onChange={(e) => setM(Math.max(0, Math.min(45, parseInt(e.target.value || 0, 10))))} />
            </label>
          </div>
          <div className="caption" style={{ margin: '6px 0' }}>
            → 合計 {h * 60 + m} 分（{h}時間{m}分）。最低30分。⚠️ 一度確定すると今日はもう変更できません。
          </div>
          <button onClick={lockTarget}>✅ この目標で今日を確定する</button>
        </div>
      ) : (
        <div style={{ marginTop: 12 }}>
          <div className="goal-time-card">
            <div className="goal-time-label">本日の目標（確定済み・変更不可）</div>
            <div className="goal-time-value">
              {Math.floor(state.target_value / 60)}時間 {state.target_value % 60}分 0秒
            </div>
            <div className="goal-time-label">（合計 {state.target_value}分）</div>
          </div>
          <div className="caption">🔒 本日は確定済みです（日付が変わるとリセット）。</div>
        </div>
      )}

      <div className="progress-cols" style={{ marginTop: 10 }}>
        <div className="donut-wrap">
          <div
            className="donut"
            style={{ background: `conic-gradient(#4CAF50 ${deg}deg, rgba(255,255,255,0.1) ${deg}deg)` }}
          >
            <div className="donut-inner"><span>{Math.round(percent * 100)}%</span></div>
          </div>
        </div>
        <div>
          <div className="metric">
            <div className="label">今日の勉強時間</div>
            <div className="value">{state.study_time_total} 分</div>
          </div>
          <div className="caption">目標まであと: {remaining} 分</div>
        </div>
        <div>
          <div className="metric">
            <div className="label">今日の気分転換</div>
            <div className="value">{state.refresh_time_total} 分</div>
          </div>
        </div>
      </div>
    </div>
  )
}

function Dashboard({ settings, state, onStateChange, showToast }) {
  const [game, setGame] = useState({ unlocked: false, study_time_total: 0, target_value: 180 })

  // ゲーム解放状態はサーバー判定を使う（1分ごと＋状態変化時に更新）
  useEffect(() => {
    let alive = true
    const load = () => api.getGameStatus().then((g) => { if (alive) setGame(g) }).catch(() => {})
    load()
    const id = setInterval(load, 60000)
    return () => { alive = false; clearInterval(id) }
  }, [state.study_time_total, state.target_value])

  return (
    <div>
      <h1>☕ Focus &amp; Cafe Roulette</h1>
      <div className="dash-grid">
        <RouletteAndGoals
          settings={settings} state={state} game={game}
          onStateChange={onStateChange} showToast={showToast}
        />
        <Progress settings={settings} state={state} onStateChange={onStateChange} />
      </div>
    </div>
  )
}

export default Dashboard
