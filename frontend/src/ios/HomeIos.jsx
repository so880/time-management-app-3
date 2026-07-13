// iOS風ホーム画面（リキッドグラスON時のみ使用）
// iPhoneのホーム画面のように「ウィジェット＋1つの大きなアクション」で構成する。
// ウィジェットは並べ替え可能（iPhoneの編集モードと同じく、ぷるぷる揺れてドラッグで入替）。
// 並び順は設定 home_widget_order としてSQLiteに保存される。
import { useEffect, useRef, useState } from 'react'
import * as api from '../api.js'
import { ensureNotifyPermission } from '../components/notify.js'
import { useNow } from '../components/useNow.js'
import { todayIntervalsMs } from '../views/Dashboard.jsx'

// ローカル日付を 'YYYY-MM-DD' にする（ログの日付列と同じ形式）
function fmtDate(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

// Apple Watch のアクティビティリング風の進捗表示
function Ring({ pct, size = 116, stroke = 11 }) {
  const r = (size - stroke) / 2
  const c = 2 * Math.PI * r
  return (
    <svg width={size} height={size}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none"
              stroke="rgba(255,255,255,0.12)" strokeWidth={stroke} />
      <circle cx={size / 2} cy={size / 2} r={r} fill="none"
              stroke="#4CAF50" strokeWidth={stroke} strokeLinecap="round"
              strokeDasharray={c} strokeDashoffset={c * (1 - pct)}
              transform={`rotate(-90 ${size / 2} ${size / 2})`}
              style={{ transition: 'stroke-dashoffset 0.8s cubic-bezier(0.32,0.72,0.28,1)' }} />
      <text x="50%" y="50%" textAnchor="middle" dominantBaseline="central"
            fill="#4CAF50" fontSize="1.6rem" fontWeight="800">
        {Math.round(pct * 100)}%
      </text>
    </svg>
  )
}

// iOS風の −／＋ ステッパー
function Stepper({ label, value, onChange, min, max, step }) {
  const set = (v) => onChange(Math.max(min, Math.min(max, v)))
  return (
    <div className="ios-stepper">
      <span className="s-label">{label}</span>
      <button type="button" onClick={() => set(value - step)}>−</button>
      <span className="s-value">{value}</span>
      <button type="button" onClick={() => set(value + step)}>＋</button>
    </div>
  )
}

function HomeIos({ settings, state, logs, onStateChange, onSettingsChange, resetTick }) {
  const now = useNow(1000)
  const [game, setGame] = useState(null)
  const [busy, setBusy] = useState(false)
  const [selected, setSelected] = useState(null)
  const [arrange, setArrange] = useState(false) // ウィジェット並べ替えモード
  const [brief, setBrief] = useState(null)      // ☀️ 今日のブリーフィング
  const dragIdRef = useRef(null)
  const [h, setH] = useState(Math.min(Math.floor(state.target_value / 60), 16))
  const [m, setM] = useState(Math.min(Math.round((state.target_value % 60) / 15) * 15, 45))

  // ブリーフィングは 起動時＋ホームタブを押すたび＋10分おき に更新
  useEffect(() => {
    let alive = true
    const load = () => api.getBriefing().then((b) => { if (alive) setBrief(b) }).catch(() => {})
    load()
    const id = setInterval(load, 600000)
    return () => { alive = false; clearInterval(id) }
  }, [resetTick, state.study_time_total])

  useEffect(() => {
    let alive = true
    const load = () => api.getGameStatus().then((g) => { if (alive) setGame(g) }).catch(() => {})
    load()
    const id = setInterval(load, 60000)
    return () => { alive = false; clearInterval(id) }
  }, [state.study_time_total, state.target_value])

  // 今日まだ勉強できる時間（1秒カウントダウン）
  const ivs = todayIntervalsMs(settings)
  let totalMs = 0
  for (const [s, e] of ivs) if (now < e) totalMs += e - Math.max(now, s)
  const r = Math.floor(totalMs / 1000)
  const rh = Math.floor(r / 3600)
  const rm = Math.floor((r % 3600) / 60)
  const rs = r % 60

  const target = state.target_locked ? state.target_value : Math.max(30, h * 60 + m)
  const pct = target > 0 ? Math.min(state.study_time_total / target, 1) : 1

  const lockTarget = async () => {
    const st = await api.patchState({ target_value: Math.max(30, h * 60 + m), target_locked: true })
    onStateChange(st)
  }

  const roll = async () => {
    if (busy) return
    setBusy(true)
    try {
      await api.rollRoulette()
      const st = await api.getState()
      setSelected(st.rolled_options ? `【勉強】 ${st.rolled_options['勉強']}` : null)
      onStateChange(st)
    } finally {
      setBusy(false)
    }
  }

  const start = async () => {
    if (!selected || busy) return
    ensureNotifyPermission() // 終了通知のための許可をユーザー操作のタイミングで求める
    setBusy(true)
    try {
      const cat = selected.includes('【勉強】') ? '勉強' : '気分転換'
      const task = selected.replace(`【${cat}】 `, '')
      onStateChange(await api.chooseTask(cat, task))
    } finally {
      setBusy(false)
    }
  }

  // ===== 統計（履歴＋今日の状態から計算。今日ぶんは state が正） =====
  const studyPerDay = {}
  for (const log of logs ?? []) {
    const ds = String(log['日付'] ?? '').slice(0, 10)
    if (!ds || !String(log['カテゴリ'] ?? '').includes('勉強')) continue
    studyPerDay[ds] = (studyPerDay[ds] ?? 0) + (parseInt(log['経過時間(分)'], 10) || 0)
  }
  const todayKey = fmtDate(new Date())
  const minutesOf = (key) => (key === todayKey ? state.study_time_total : (studyPerDay[key] ?? 0))
  const weekDays = []
  for (let i = 6; i >= 0; i--) {
    const d = new Date()
    d.setDate(d.getDate() - i)
    const key = fmtDate(d)
    weekDays.push({
      key,
      label: '月火水木金土日'[(d.getDay() + 6) % 7],
      min: minutesOf(key),
      isToday: i === 0,
    })
  }
  const weekMax = Math.max(...weekDays.map((d) => d.min), 1)
  const weekTotal = weekDays.reduce((a, d) => a + d.min, 0)
  // 連続勉強日数（今日まだ0分なら昨日から数える）
  let streak = 0
  {
    const d = new Date()
    if (minutesOf(fmtDate(d)) <= 0) d.setDate(d.getDate() - 1)
    while (minutesOf(fmtDate(d)) > 0) {
      streak++
      d.setDate(d.getDate() - 1)
    }
  }

  // ===== ウィジェットの並び（設定 home_widget_order に保存） =====
  const goals = settings.goals ?? []
  const goalIds = goals.map((_, i) => `goal-${i}`)
  const allIds = ['progress', 'target', 'remain', 'game', 'week', 'streak', ...goalIds]
  const saved = Array.isArray(settings.home_widget_order) ? settings.home_widget_order : []
  const order = [
    ...saved.filter((id) => allIds.includes(id)),
    ...allIds.filter((id) => !saved.includes(id)),
  ]

  const saveOrder = async (newOrder) => {
    onSettingsChange(await api.updateSettings({ home_widget_order: newOrder }))
  }

  // ホームの見た目（ウィジェット/フォーカス）。設定として保存され次回も維持される
  const layout = settings.home_layout ?? 'widgets'
  const saveLayout = async (v) => {
    setArrange(false)
    onSettingsChange(await api.updateSettings({ home_layout: v }))
  }
  const dropSwap = (targetId) => {
    const src = dragIdRef.current
    dragIdRef.current = null
    if (!src || src === targetId) return
    const no = [...order]
    const a = no.indexOf(src)
    const b = no.indexOf(targetId)
    no[a] = targetId
    no[b] = src
    saveOrder(no)
  }

  const midnight = new Date(); midnight.setHours(0, 0, 0, 0)

  // ウィジェットの中身（idごと）。null を返すと非表示。
  const renderWidget = (id) => {
    if (id === 'progress') {
      return (
        <>
          <div className="w-label">📊 今日の進捗</div>
          <div className="w-ring-row">
            <Ring pct={pct} />
            <div>
              <div className="w-big">{state.study_time_total}<span className="w-unit">分</span></div>
              <div className="w-sub">目標 {target}分{state.target_locked ? '' : '（仮）'}</div>
              <div className="w-sub">☕ 気分転換 {state.refresh_time_total}分</div>
            </div>
          </div>
        </>
      )
    }
    if (id === 'target') {
      if (state.target_locked) return null // 確定後は消える（迷いを減らす）
      return (
        <>
          <div className="w-label">🎯 今日の目標を決める</div>
          <Stepper label="時間" value={h} onChange={setH} min={0} max={16} step={1} />
          <Stepper label="分" value={m} onChange={setM} min={0} max={45} step={15} />
          <button className="w-action" onClick={lockTarget}>
            ✅ {h}時間{m}分 で確定する
          </button>
          <div className="w-sub" style={{ marginTop: 6 }}>確定すると今日は変更できません</div>
        </>
      )
    }
    if (id === 'remain') {
      return (
        <>
          <div className="w-label">🕐 今日まだ勉強できる時間</div>
          {r <= 0 ? (
            <div className="w-big" style={{ color: '#ff5252' }}>本日は終了</div>
          ) : (
            <div className="w-big">
              {rh > 0 ? `${rh}:` : ''}{String(rm).padStart(2, '0')}:{String(rs).padStart(2, '0')}
            </div>
          )}
          <div className="w-sub">勉強できる時間帯のみで計算</div>
        </>
      )
    }
    if (id === 'game') {
      return (
        <>
          <div className="w-label">🎮 ゲーム解放</div>
          {game?.unlocked ? (
            <>
              <div className="w-big" style={{ fontSize: '1.6rem' }}>🔓 解放中！</div>
              <div className="w-sub">気分転換にゲームが追加されています</div>
            </>
          ) : (
            <>
              <div className="w-big" style={{ fontSize: '1.6rem' }}>🔒 ロック中</div>
              <div className="w-sub">
                勉強 {game?.study_time_total ?? state.study_time_total}/{game?.target_value ?? target}分
                ＋ 20時以降で解放
              </div>
            </>
          )}
        </>
      )
    }
    if (id === 'week') {
      return (
        <>
          <div className="w-label">📈 今週の勉強時間</div>
          <div className="week-bars">
            {weekDays.map((d) => (
              <div className="wb-col" key={d.key}>
                <div className="wb-val">{d.min > 0 ? d.min : ''}</div>
                <div className="wb-bar"
                     style={{
                       height: `${Math.max(6, (d.min / weekMax) * 64)}px`,
                       background: d.isToday ? '#4CAF50' : 'rgba(255,255,255,0.28)',
                     }} />
                <div className="wb-day" style={d.isToday ? { color: '#4CAF50', fontWeight: 700 } : undefined}>
                  {d.label}
                </div>
              </div>
            ))}
          </div>
          <div className="w-sub">合計 {weekTotal}分（過去7日）</div>
        </>
      )
    }
    if (id === 'streak') {
      return (
        <>
          <div className="w-label">🔥 連続勉強日数</div>
          <div className="w-big">{streak}<span className="w-unit">日</span></div>
          <div className="w-sub">
            {state.study_time_total > 0 ? '今日もクリア！🔥' : '今日はこれから！'}
          </div>
        </>
      )
    }
    if (id.startsWith('goal-')) {
      const g = goals[parseInt(id.slice(5), 10)]
      if (!g) return null
      const d = new Date(g.date + 'T00:00:00')
      const days = Number.isNaN(d.getTime()) ? 0 : Math.max(Math.round((d - midnight) / 86400000), 0)
      const hours = parseInt(g.hours ?? 2, 10)
      return (
        <>
          <div className="w-label">🏁 {g.name}</div>
          <div className="w-big">あと {days}<span className="w-unit">日</span></div>
          <div className="w-sub">{g.date} ／ 残り作業可能 {days * hours} 時間</div>
        </>
      )
    }
    return null
  }

  const ro = state.rolled_options
  const studyOnly = state.last_was_refresh || state.force_study_only
  const choices = ro
    ? [`【勉強】 ${ro['勉強']}`, ...(!studyOnly ? [`【気分転換】 ${ro['気分転換']}`] : [])]
    : []

  const dateStr = new Date().toLocaleDateString('ja-JP', { month: 'long', day: 'numeric', weekday: 'long' })

  return (
    <div>
      <div className="ios-date">{dateStr}</div>
      <div className="ios-title-row">
        <h1 className="ios-large-title">☕ Focus &amp; Cafe</h1>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {/* ホームの見た目切替（設定として保存・両方いつでも選べる） */}
          <div className="seg home-seg">
            {[['widgets', '🧩 ウィジェット'], ['focus', '🎯 フォーカス']].map(([v, l]) => (
              <button key={v} type="button" className={'seg-btn' + (layout === v ? ' on' : '')}
                      onClick={() => saveLayout(v)}>{l}</button>
            ))}
          </div>
          {layout === 'widgets' && (
            <button type="button" className="small" onClick={() => setArrange((a) => !a)}>
              {arrange ? '✅ 完了' : '⇄ 並べ替え'}
            </button>
          )}
        </div>
      </div>
      {arrange && layout === 'widgets' && (
        <div className="info-box" style={{ marginBottom: 10 }}>
          ウィジェットをドラッグして、置きたい場所のウィジェットに重ねると入れ替わります。
        </div>
      )}

      {/* ☀️ 今日の一枚（ブリーフィング）：全タブの「今日大事なこと」を1枚に */}
      {brief && (() => {
        // いまの時間帯の予定（時間割＋単発予定）。無い時間帯は何も表示しない
        const hm = new Date(now).toTimeString().slice(0, 5)
        const inRange = (b) => (b.start <= b.end)
          ? (hm >= b.start && hm < b.end)
          : (hm >= b.start || hm < b.end)  // 23:00〜06:30 のような日またぎに対応
        const nowItems = [...(brief.timetable ?? []), ...(brief.events ?? [])]
          .filter((b) => b.start && b.end && inRange(b))
        return (
        <div className="ios-widget brief-card">
          {nowItems.length > 0 && (
            <div className="brief-now">
              ▶ いまの予定：{nowItems.map((b) =>
                `${b.start}〜${b.end} ${b.title}${b.room ? `（${b.room}）` : ''}`
              ).join('　/　')}
            </div>
          )}
          <div className="w-label">
            ☀️ 今日の一枚
            {brief.holiday_name && <span className="brief-chip red">🎌 {brief.holiday_name}</span>}
            {brief.overridden && <span className="brief-chip orange">🔀 振替日程</span>}
            {brief.job_conflicts > 0 && <span className="brief-chip orange">⚠️ 就活日程の被り {brief.job_conflicts}件</span>}
          </div>
          <div className="brief-rows">
            <div className="brief-row">
              <span className="brief-k">🎓 授業</span>
              <span>{brief.classes.length === 0 ? 'なし'
                : brief.classes.map((c) => `${c.start} ${c.title}`).join('　/　')}</span>
            </div>
            {brief.events.length > 0 && (
              <div className="brief-row">
                <span className="brief-k">📌 予定</span>
                <span>{brief.events.map((e) => `${e.start} ${e.title}`).join('　/　')}</span>
              </div>
            )}
            {brief.assignments.length > 0 && (
              <div className="brief-row">
                <span className="brief-k">📚 課題</span>
                <span>{brief.assignments.map((a) =>
                  `${a.title}（${a.daysLeft <= 0 ? '今日締切！' : `あと${a.daysLeft}日`}・${a.progress}%）`
                ).join('　/　')}</span>
              </div>
            )}
            {brief.jobs.length > 0 && (
              <div className="brief-row">
                <span className="brief-k">💼 就活</span>
                <span>{brief.jobs.map((j) =>
                  `${j.date.slice(5).replace('-', '/')} ${j.company ?? ''} ${j.label}`.trim()
                ).join('　/　')}</span>
              </div>
            )}
            <div className="brief-row">
              <span className="brief-k">⏱ 勉強</span>
              <span>
                今日 {brief.study.today_min}分 / 目標 {brief.study.target_min}分
                <span className="brief-sub">　昨日 {brief.study.yesterday_min}分</span>
              </span>
            </div>
            {brief.money.allowance != null && (
              <div className="brief-row">
                <span className="brief-k">💰 お金</span>
                <span style={{ color: brief.money.remaining >= 0 ? undefined : '#FF6B62' }}>
                  今月あと {brief.money.remaining?.toLocaleString()}円
                  <span className="brief-sub">
                    　今日の支出 {brief.money.today_spent.toLocaleString()}円
                    ・固定費 {brief.money.subs_monthly?.toLocaleString()}円/月 込み
                  </span>
                </span>
              </div>
            )}
          </div>
        </div>
        )
      })()}

      {/* メインアクション：タイトル直下（スクロールせず押せる位置） */}
      <button className="big ios-roll" style={{ marginTop: 4, marginBottom: 16 }}
              onClick={roll} disabled={busy || !!ro || arrange}>
        <span className="roll-emoji" aria-hidden="true">{busy ? '☕' : '🎲'}</span>
        <span className="roll-text">
          <span className="roll-main">{busy ? '抽選中…' : 'ルーレットを回す'}</span>
          <span className="roll-sub">☕ 今日の一杯はおまかせで — 勉強メニューを抽選</span>
        </span>
      </button>

      {layout === 'widgets' && (
        <div className={'ios-widget-grid' + (arrange ? ' arrange' : '')}>
          {order.map((id) => {
            const content = renderWidget(id)
            if (content === null) return null
            return (
              <div key={id}
                   className="ios-widget"
                   draggable={arrange}
                   onDragStart={() => { dragIdRef.current = id }}
                   onDragOver={(e) => { if (arrange) e.preventDefault() }}
                   onDrop={(e) => { e.preventDefault(); dropSwap(id) }}>
                {content}
              </div>
            )
          })}
        </div>
      )}

      {layout === 'focus' && (
        /* 🎯 フォーカス表示：Apple Watchの文字盤風に「今いちばん大事な数字」だけ */
        <div className="focus-home" key="focus">
          <div className="focus-ring-wrap"><Ring pct={pct} size={210} stroke={16} /></div>
          <div className="focus-nums">
            今日の勉強 <strong>{state.study_time_total}分</strong> ／ 目標 {target}分
            {state.target_locked ? '' : '（仮）'}
          </div>
          <div className="focus-remain">
            {r <= 0 ? '本日終了' : `${rh > 0 ? rh + ':' : ''}${String(rm).padStart(2, '0')}:${String(rs).padStart(2, '0')}`}
          </div>
          <div className="caption">今日まだ勉強できる時間</div>
          <div className="focus-pills">
            <span className="focus-pill">{game?.unlocked ? '🔓 ゲーム解放中' : '🔒 ゲームロック中'}</span>
            <span className="focus-pill">🔥 連続 {streak}日</span>
            <span className="focus-pill">☕ 気分転換 {state.refresh_time_total}分</span>
          </div>
          {!state.target_locked && (
            <div className="ios-widget" style={{ maxWidth: 360, margin: '10px auto', textAlign: 'left' }}>
              <div className="w-label">🎯 今日の目標を決める</div>
              <Stepper label="時間" value={h} onChange={setH} min={0} max={16} step={1} />
              <Stepper label="分" value={m} onChange={setM} min={0} max={45} step={15} />
              <button className="w-action" onClick={lockTarget}>✅ {h}時間{m}分 で確定する</button>
            </div>
          )}
        </div>
      )}

      {/* 抽選結果：下からスライドするシート（iOSのアクションシート風） */}
      {ro && (
        <>
          <div className="ios-sheet-backdrop" />
          <div className="ios-sheet">
            <div className="ios-grabber" />
            <h3 style={{ textAlign: 'center', margin: '4px 0 14px' }}>🎲 今回のお題</h3>
            {state.force_study_only && !state.last_was_refresh && (
              <div className="info-box">📚 今回は『勉強』のみの抽選です</div>
            )}
            {choices.map((c) => (
              <label key={c}
                     className={'option-label' + (selected === c ? ' selected' : '')}>
                <input type="radio" name="ios_task" checked={selected === c}
                       onChange={() => setSelected(c)} />
                {c}
              </label>
            ))}
            <button className="big" onClick={start} disabled={!selected || busy}>
              集中モードへ！
            </button>
          </div>
        </>
      )}
    </div>
  )
}

export default HomeIos
