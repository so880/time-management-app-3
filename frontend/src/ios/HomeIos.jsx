// ホーム（2026-11-01 夜に作り直し）
// 画面に置くものを「上から順に読めば今日が分かる」5 つに絞った：
//   1. いまの状態（制限・今日の勉強・在席）… 押すとその画面へ
//   2. 次にやること（🎲 ルーレット／⏱ 自分で選ぶ）… この画面でいちばん大きいボタン
//   3. 今日やること（必須・習慣。完了は折りたたみ）
//   4. 今日の進捗（リング・残り時間・連続日数・今週）
//   5. 今日のまとめ（授業・就活・お金・AIプラン）、目標までの日数
// 横幅が広いときは 1〜3 を左、4〜5 を右の 2 列に並べる（index.css .home-grid）。
// 旧ホームにあった ウィジェットの並べ替え／非表示／⚙／表示切替（ウィジェット・フォーカス）は、
// 初めて使う人には「何が起きるか分からない操作」なので外した（設定値は残るが使わない）。
import { useEffect, useState } from 'react'
import * as api from '../api.js'
import HomeAgendaView from './HomeAgenda.jsx'
import { ensureNotifyPermission } from '../components/notify.js'
import { useNow } from '../components/useNow.js'
import { usePolling } from '../lib/usePolling.js'
import { todayIntervalsMs } from '../lib/schedule.js'
import { ymd } from '../lib/format.js'
import { tagIcon } from '../lib/categories.js'
import Ring from './home/Ring.jsx'
import Stepper from './home/Stepper.jsx'
import HBar from './home/HBar.jsx'
import TrendChart from './home/TrendChart.jsx'
import StatusChip from './home/StatusChip.jsx'
import DayStrip from './home/DayStrip.jsx'
import { dayComment } from './home/dayComment.js'

// 📐 F23：ホームの並び。two=横幅が広い横画面（やること｜進捗・まとめ の2列）、stacked=縦に長い画面（上下に積む）、
// single=それ以外（スマホ縦・低い画面。セグメントで切り替え）。ページ全体はスクロールしない（index.css .fit-page）
const MQ_TWO = '(min-width: 1000px) and (orientation: landscape)'
const MQ_TALL = '(min-height: 1300px)'
function homeLayout() {
  if (typeof window === 'undefined' || !window.matchMedia) return 'single'
  if (window.matchMedia(MQ_TWO).matches) return 'two'
  if (window.matchMedia(MQ_TALL).matches) return 'stacked'
  return 'single'
}

const LEAVE_MS = 450  // 完了にした行が光って縮むまでの時間（index.css の todoLeave と合わせる）

function HomeIos({ settings, state, logs, onStateChange, resetTick, onOpenPage,
                   showToast = (m) => window.alert(m) }) {
  const now = useNow(1000)
  const [busy, setBusy] = useState(false)
  const [selected, setSelected] = useState(null)
  const [brief, setBrief] = useState(null)
  const [planBusy, setPlanBusy] = useState(false)
  const [widgetAlive, setWidgetAlive] = useState(true)
  const [gate, setGate] = useState(null)
  const [dayRates, setDayRates] = useState([])
  const [evForm, setEvForm] = useState({ title: '', start: '18:00', end: '19:00' })
  const [recent, setRecent] = useState([])
  const [trendOpen, setTrendOpen] = useState(false)
  // 📐 F23：画面比率に合わせた並びと、狭い画面での表示切替（やること／進捗・まとめ）
  const [layout, setLayout] = useState(homeLayout)
  const [pane, setPane] = useState('todo')
  useEffect(() => {
    if (!window.matchMedia) return undefined
    const mqs = [window.matchMedia(MQ_TWO), window.matchMedia(MQ_TALL)]
    const h = () => setLayout(homeLayout())
    mqs.forEach((m) => m.addEventListener('change', h))
    return () => mqs.forEach((m) => m.removeEventListener('change', h))
  }, [])
  const single = layout === 'single'
  // 案C（横画面）はウルトラワイドの横幅を使う：本文の最大幅 1180px → 1640px。縦置き・スマホは元のまま
  useEffect(() => {
    const root = document.documentElement
    if (layout === 'two') root.style.setProperty('--fc-max', '1640px')
    else root.style.removeProperty('--fc-max')
    return () => root.style.removeProperty('--fc-max')
  }, [layout])
  const [leaving, setLeaving] = useState([])
  const [cam, setCam] = useState(null)            // 📷 在席判定の状態（オンのときだけチップを出す）
  const [presence, setPresence] = useState(null)  // 今日の在席まとめ

  // 最近14日の推移（5分ごと。勉強時間が増えたら読み直す）
  usePolling((isAlive) => {
    api.getRecentStats(14).then((r) => { if (isAlive()) setRecent(r) }).catch(() => {})
  }, 300000, [resetTick, state.study_time_total])

  useEffect(() => {
    let alive = true
    const load = () => {
      api.getGateStatus().then((g) => { if (alive) setGate(g) }).catch(() => {})
      api.getHabitDailyRates(7).then((r) => { if (alive) setDayRates(r) }).catch(() => {})
      api.getPresenceConfig().then((c) => { if (alive) setCam(c) }).catch(() => {})
      api.getPresenceDay().then((p) => { if (alive) setPresence(p) }).catch(() => {})
    }
    load()
    const id = setInterval(load, 120000)
    const onChanged = () => load()
    window.addEventListener('fc-todo-changed', onChanged)
    return () => { alive = false; clearInterval(id); window.removeEventListener('fc-todo-changed', onChanged) }
  }, [resetTick])

  // 小窓の生存確認＋計測中のリアルタイム表示（計測中 5 秒／待機中 30 秒）
  const [widgetLive, setWidgetLive] = useState(null)
  useEffect(() => {
    let alive = true
    let id = null
    const check = () => api.getWidgetStatus()
      .then((r) => {
        if (!alive) return
        setWidgetAlive(r.alive)
        setWidgetLive(r.running ? { task: r.task, elapsed_sec: r.elapsed_sec, at: Date.now() } : null)
        clearInterval(id)
        id = setInterval(check, r.running ? 5000 : 30000)
      })
      .catch(() => {})
    check()
    return () => { alive = false; clearInterval(id) }
  }, [resetTick])
  const liveSec = widgetLive ? widgetLive.elapsed_sec + Math.floor((now - widgetLive.at) / 1000) : 0
  const liveMin = Math.floor(liveSec / 60)

  const [h, setH] = useState(Math.min(Math.floor(state.target_value / 60), 16))
  const [m, setM] = useState(Math.min(Math.round((state.target_value % 60) / 15) * 15, 45))

  // 今日のまとめ（10分ごと。勉強時間が増えたら読み直す）
  usePolling((isAlive) => {
    api.getBriefing().then((b) => { if (isAlive()) setBrief(b) }).catch(() => {})
  }, 600000, [resetTick, state.study_time_total])

  // 今日まだ勉強できる時間
  const ivs = todayIntervalsMs(settings)
  let totalMs = 0
  for (const [s, e] of ivs) if (now < e) totalMs += e - Math.max(now, s)
  const r = Math.floor(totalMs / 1000)
  const rh = Math.floor(r / 3600)
  const rm = Math.floor((r % 3600) / 60)
  const rs = r % 60
  const remainText = r <= 0 ? '本日は終了' : `${rh > 0 ? rh + ':' : ''}${String(rm).padStart(2, '0')}:${String(rs).padStart(2, '0')}`

  const target = state.target_locked ? state.target_value : Math.max(30, h * 60 + m)
  const todayMin = state.study_time_total + liveMin
  const pct = target > 0 ? Math.min(todayMin / target, 1) : 1

  const lockTarget = async () => {
    try {
      const st = await api.patchState({ target_value: Math.max(30, h * 60 + m), target_locked: true })
      onStateChange(st)
    } catch (e) { showToast('⚠️ ' + e.message) }
  }

  // ⏱ 自分で選んで始める（下から出るシート）
  const [pickOpen, setPickOpen] = useState(false)
  const [pickLists, setPickLists] = useState(null)
  const [pickFree, setPickFree] = useState('')
  // Esc でシートを閉じる（iPhone の「下にスワイプで閉じる」に相当。背景タップでも閉じる）
  useEffect(() => {
    if (!pickOpen) return undefined
    const onKey = (e) => { if (e.key === 'Escape') { e.stopPropagation(); setPickOpen(false) } }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [pickOpen])
  const openPick = async () => {
    setPickOpen(true)
    setPickLists(null)
    try {
      const [td, asg] = await Promise.all([api.getTodoToday(), api.getAssignments()])
      setPickLists({
        must: td.must.filter((x) => !x.checked).map((x) => x.title),
        habits: td.habits.filter((x) => !x.done).map((x) => x.title),
        roulette: asg.filter((a) => !a.done && a.enabled !== false)
          .sort((a, b) => (b.focus ? 1 : 0) - (a.focus ? 1 : 0)).map((a) => a.title),
      })
    } catch { setPickLists({ must: [], habits: [], roulette: [] }) }
  }
  const startPicked = async (title) => {
    const t = (title || '').trim()
    if (!t || busy) return
    setBusy(true)
    try {
      ensureNotifyPermission()
      const st = await api.chooseTask('勉強', t)
      setPickOpen(false)
      onStateChange(st)
    } catch (e) {
      showToast('⚠️ ' + (e?.message ?? ''))
    } finally { setBusy(false) }
  }

  const roll = async () => {
    if (busy) return
    setBusy(true)
    try {
      await api.rollRoulette()
      const st = await api.getState()
      setSelected(st.rolled_options ? `【勉強】 ${st.rolled_options['勉強']}` : null)
      onStateChange(st)
    } catch (e) {
      showToast('⚠️ ' + (e?.message ?? ''))
    } finally { setBusy(false) }
  }
  const start = async () => {
    if (!selected || busy) return
    ensureNotifyPermission()
    setBusy(true)
    try {
      const cat = selected.includes('【勉強】') ? '勉強' : '気分転換'
      const task = selected.replace(`【${cat}】 `, '')
      onStateChange(await api.chooseTask(cat, task))
    } catch (e) {
      showToast('⚠️ ' + (e?.message ?? ''))
    } finally { setBusy(false) }
  }

  // ===== 統計 =====
  const studyPerDay = {}
  for (const log of logs ?? []) {
    const ds = String(log['日付'] ?? '').slice(0, 10)
    if (!ds || !String(log['カテゴリ'] ?? '').includes('勉強')) continue
    studyPerDay[ds] = (studyPerDay[ds] ?? 0) + (parseInt(log['経過時間(分)'], 10) || 0)
  }
  const todayKey = ymd(new Date())
  const minutesOf = (key) => (key === todayKey ? state.study_time_total : (studyPerDay[key] ?? 0))
  const weekDays = []
  for (let i = 6; i >= 0; i--) {
    const d = new Date()
    d.setDate(d.getDate() - i)
    const key = ymd(d)
    weekDays.push({ key, label: '月火水木金土日'[(d.getDay() + 6) % 7], min: minutesOf(key), isToday: i === 0 })
  }
  const weekMax = Math.max(...weekDays.map((d) => d.min), 1)
  const weekTotal = weekDays.reduce((a, d) => a + d.min, 0)
  let streak = 0
  {
    const d = new Date()
    if (minutesOf(ymd(d)) <= 0) d.setDate(d.getDate() - 1)
    while (minutesOf(ymd(d)) > 0) { streak++; d.setDate(d.getDate() - 1) }
  }

  // 消化率（一言コメント用）
  const bars = []
  if (gate && gate.required.length > 0) bars.push({ label: '🔴必須', done: gate.required.filter((t) => t.checked).length, total: gate.required.length })
  const gateHabitsAll = (gate?.habits ?? []).filter((x) => !x.record_only)   // 「記録のみ」は解放条件に入らないので進捗に数えない
  if (gateHabitsAll.length > 0) bars.push({ label: '🔁習慣', done: gateHabitsAll.filter((x) => x.done).length, total: gateHabitsAll.length })
  if (brief && brief.events.length > 0) bars.push({ label: '📌予定', done: brief.events.filter((e) => e.done).length, total: brief.events.length })
  if (brief && brief.study.target_min > 0) bars.push({ label: '⏱勉強', pct: Math.min(100, Math.round(brief.study.today_min / brief.study.target_min * 100)) })
  const barPcts = bars.map((b) => b.pct ?? (b.total > 0 ? (b.done / b.total) * 100 : 0))
  const overallRate = barPcts.length > 0 ? Math.round(barPcts.reduce((a, x) => a + x, 0) / barPcts.length) : 0
  const comment = dayComment(new Date(now).getHours(), overallRate)

  const goals = settings.goals ?? []
  const midnight = new Date(); midnight.setHours(0, 0, 0, 0)

  // ===== 今日やること =====
  const refreshTodo = async () => {
    setGate(await api.getGateStatus())
    api.getBriefing().then(setBrief).catch(() => {})
  }
  const check = async (itemId, done, level = 'full') => {
    if (done) setLeaving((l) => (l.includes(itemId) ? l : [...l, itemId]))
    try {
      await Promise.all([api.checkTodo(itemId, done, level),
                         done ? new Promise((res) => setTimeout(res, LEAVE_MS)) : Promise.resolve()])
    } catch (e) { showToast('⚠️ ' + e.message) }
    await refreshTodo().catch(() => {})
    setLeaving((l) => l.filter((x) => x !== itemId))
  }
  const rowClass = (itemId) => 'habit-check-row todo-row' + (leaving.includes(itemId) ? ' todo-leaving' : '')
  const mustRow = (x) => (
    <label key={x.id} className={rowClass(x.id)}>
      <input type="checkbox" checked={x.checked || leaving.includes(x.id)} onChange={(e) => check(x.id, e.target.checked)} />
      <span className={x.checked ? 'habit-done' : ''}>
        {x.tag ? `${tagIcon(x.tag)} ` : ''}{x.title}
        {x.due && <span className="caption">　📅 {x.due.slice(5).replace('-', '/')}締切</span>}
      </span>
    </label>
  )
  // 「記録のみ」の習慣（筋トレ等）：解放条件に入らないので、必須と同じくチェックで記録できる
  const recordOnlyRow = (x) => (
    <label key={x.id} className={rowClass(x.id)}>
      <input type="checkbox" checked={x.checked || leaving.includes(x.id)} onChange={(e) => check(x.id, e.target.checked)} />
      <span className={x.checked ? 'habit-done' : ''}>
        {x.title}<span className="caption">　{x.start && x.end ? `${x.start}〜${x.end}` : '自由枠'}</span>
        <span className="brief-chip">記録のみ</span>
      </span>
    </label>
  )
  const habitRow = (x) => x.record_only ? recordOnlyRow(x) : (
    <div key={x.id} className={rowClass(x.id)} style={{ cursor: 'default' }}>
      <span style={{ width: 24, textAlign: 'center', flexShrink: 0 }}>{x.done ? '✅' : '⏱'}</span>
      <span className={x.done ? 'habit-done' : ''} style={{ flex: 1 }}>
        {x.title}<span className="caption">　{x.start && x.end ? `${x.start}〜${x.end}` : '自由枠（25分）'}</span>
        {x.forced && <span className="brief-chip red">必須扱い（2日連続未完了）</span>}
      </span>
      {!x.done && (
        <button type="button" className="small" title="デスクトップのタイマー（小窓）で開始。規定時間で自動完了"
                onClick={async () => {
                  try { await api.widgetStart(x.title); showToast('タイマー（小窓）で開始しました ⏱ 規定時間で自動完了になります') }
                  catch (e) { showToast('⚠️ ' + (e?.message ?? '')) }
                }}>⏱ タイマー開始</button>
      )}
    </div>
  )
  const addEv = async () => {
    if (!evForm.title.trim()) return
    try {
      await api.addLifeEvent({ date: ymd(new Date()), start: evForm.start, end: evForm.end,
                               title: evForm.title.trim(), category: '予定', note: '' })
      setEvForm({ ...evForm, title: '' })
      setBrief(await api.getBriefing())
    } catch (e) { showToast('⚠️ ' + e.message) }
  }

  const ro = state.rolled_options
  const studyOnly = state.last_was_refresh || state.force_study_only
  const choices = ro ? [`【勉強】 ${ro['勉強']}`, ...(!studyOnly ? [`【気分転換】 ${ro['気分転換']}`] : [])] : []
  const dateStr = new Date().toLocaleDateString('ja-JP', { month: 'long', day: 'numeric', weekday: 'short' })

  // いまの予定
  const hm = new Date(now).toTimeString().slice(0, 5)
  const inRange = (b) => (b.start <= b.end) ? (hm >= b.start && hm < b.end) : (hm >= b.start || hm < b.end)
  const nowItems = brief ? [
    ...(brief.timetable ?? []), ...(brief.events ?? []),
    ...(brief.google ?? []).filter((g) => !g.allday).map((g) => ({ ...g, title: 'G ' + g.title })),
  ].filter((b) => b.start && b.end && inRange(b)) : []

  const gHabits = gate?.habits ?? []
  const periodic = gate?.periodic ?? []
  const mustOpen = gate ? gate.required.filter((x) => !x.checked || leaving.includes(x.id)) : []
  const mustDone = gate ? gate.required.filter((x) => x.checked && !leaving.includes(x.id)) : []
  // 📝 記録だけの習慣（筋トレ等）は一覧の先頭の「記録」欄に出す（解放条件には入らない）
  const recordHabits = gHabits.filter((x) => x.record_only)
  const gateHabits = gHabits.filter((x) => !x.record_only)
  const habitOpen = gateHabits.filter((x) => !x.done || leaving.includes(x.id))
  const habitDone = gateHabits.filter((x) => x.done && !leaving.includes(x.id))
  const events = brief?.events ?? []
  const google = brief?.google ?? []
  const dueSoon = brief?.assignments ?? []
  const periodicDue = periodic.filter((p) => p.due && !p.checkedToday).length

  const lockLabel = !gate ? '…'
    : gate.site_unlocked && gate.game_unlocked ? 'ゲーム・サイト 制限なし'
    : gate.site_unlocked ? 'サイトは解除・ゲームは条件待ち'
    : `ゲーム・サイト 制限中（あと${gate.remaining.length}件）`
  const lockTone = !gate ? '' : (gate.site_unlocked && gate.game_unlocked) ? 'ok' : gate.site_unlocked ? 'warn' : 'bad'

  // ===== 部品（配置 C／P2／スマホ で使い回す。2026-11-03 依頼者が選んだ配置：横画面=案C、縦置き=P2） =====
  const timedOpen = habitOpen.filter((x) => x.start && x.end)
  const freeOpen = habitOpen.filter((x) => !x.start || !x.end)
  const freeDone = habitDone.filter((x) => !x.start || !x.end)
  const timedDone = habitDone.filter((x) => x.start && x.end)
  const startHabit = async (x) => {
    try { await api.widgetStart(x.title); showToast('タイマー（小窓）で開始しました ⏱ 25分で自動完了になります') }
    catch (e) { showToast('⚠️ ' + (e?.message ?? '')) }
  }
  // 自由枠の習慣：チップ（押すとタイマー開始）。完了は薄く後ろへ
  const habitChips = (
    <div className="habit-chips">
      {freeOpen.map((x) => (
        <button key={x.id} type="button" className="habit-chip" title="押すとタイマー（小窓）で開始。25分で自動完了"
                onClick={() => startHabit(x)}>
          ⏱ {x.title}{x.forced && <span className="brief-chip red" style={{ marginLeft: 6 }}>必須扱い</span>}
        </button>
      ))}
      {freeDone.map((x) => <span key={x.id} className="habit-chip done">✅ {x.title}</span>)}
      {freeOpen.length + freeDone.length === 0 && <span className="w-sub">自由枠の習慣はありません</span>}
    </div>
  )
  const recordBox = (
    <>
      {recordHabits.length > 0 && (
        <div className="record-box" aria-label="記録">
          <div className="caption">📝 記録（やったら押す。解放条件には入りません）</div>
          <div className="record-row-list">
            {recordHabits.map((x) => (
              <div key={x.id} className="record-row">
                <span className="record-name">{x.title}<span className="caption">　{x.start && x.end ? `${x.start}〜${x.end}` : ''}</span></span>
                <div className="seg record-seg" role="group" aria-label={`${x.title} の記録`}>
                  <button type="button" className={'seg-btn' + (!x.checked ? ' on' : '')}
                          onClick={() => x.checked && api.checkTodo(x.id, false).then(refreshTodo).catch((e) => showToast('⚠️ ' + e.message))}>まだ</button>
                  <button type="button" className={'seg-btn' + (x.checked ? ' on ok' : '')}
                          onClick={() => !x.checked && api.checkTodo(x.id, true).then(refreshTodo).catch((e) => showToast('⚠️ ' + e.message))}>✅ やった</button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  )
  const mustBlock = (
    <>
      <div className="caption">🔴 必須</div>
      {gate && gate.required.length === 0 && <div className="w-sub">今日の必須はありません</div>}
      {gate && gate.required.length > 0 && mustOpen.length === 0 && <div className="w-sub">🎉 必須はすべて完了</div>}
      {mustOpen.map(mustRow)}
      {mustDone.length > 0 && (
        <details className="todo-fold"><summary>✓ 完了 {mustDone.length}件</summary>{mustDone.map(mustRow)}</details>
      )}
    </>
  )
  const habitsRows = (
    <>
      <div className="caption" style={{ marginTop: 6 }}>🔁 習慣
        <span className="caption hint">　タイマーか在席率で自動完了（チェックでは完了になりません）</span>
      </div>
      {gate && gateHabits.length === 0 && <div className="w-sub">今日は該当する習慣がありません</div>}
      {gateHabits.length > 0 && habitOpen.length === 0 && <div className="w-sub">🎉 習慣はすべて完了</div>}
      {habitOpen.map(habitRow)}
      {habitDone.length > 0 && (
        <details className="todo-fold"><summary>✓ 完了 {habitDone.length}件</summary>{habitDone.map(habitRow)}</details>
      )}
    </>
  )
  const eventsFold = (
    <details className="todo-fold section">
      <summary>📅 今日の予定 {events.length + google.length}件　＋ 追加</summary>
      {events.map((e) => (
        <label key={e.id ?? `${e.start}${e.title}`} className="habit-check-row" style={{ padding: '5px 10px' }}>
          <input type="checkbox" checked={!!e.done}
                 onChange={async (ev) => {
                   try { await api.toggleLifeEventDone(e.id, ev.target.checked); setBrief(await api.getBriefing()) }
                   catch (err) { showToast('⚠️ ' + err.message) }
                 }} />
          <span className={e.done ? 'habit-done' : ''}>{e.start}〜{e.end} {e.title}</span>
        </label>
      ))}
      {google.map((g, i) => (
        <div key={'g' + (g.id || i)} className="habit-check-row" style={{ padding: '5px 10px' }}>
          <span className="cal-google" style={{ fontSize: '0.72rem' }}>G</span>
          <span>{g.allday ? '終日' : `${g.start}〜${g.end}`} {g.title}{g.location && <span className="caption">　📍 {g.location}</span>}</span>
        </div>
      ))}
      {events.length + google.length === 0 && <div className="w-sub">今日の予定はありません</div>}
      <div className="edit-row" style={{ marginTop: 4 }}>
        <input type="time" value={evForm.start} aria-label="開始" onChange={(e) => setEvForm({ ...evForm, start: e.target.value })} />
        〜
        <input type="time" value={evForm.end} aria-label="終了" onChange={(e) => setEvForm({ ...evForm, end: e.target.value })} />
        <input type="text" value={evForm.title} placeholder="予定を追加（例：美容院）" style={{ flex: 1, minWidth: 120 }}
               onKeyDown={(e) => { if (e.key === 'Enter') addEv() }}
               onChange={(e) => setEvForm({ ...evForm, title: e.target.value })} />
        <button type="button" className="small" onClick={addEv}>＋</button>
      </div>
      <div className="caption">別の日の予定はカレンダータブで日付を押して追加できます</div>
    </details>
  )
  const dueFold = (
    <>
      {dueSoon.length > 0 && (
        <details className="todo-fold section">
          <summary>📌 期限が近い項目 {dueSoon.length}件{dueSoon.some((a) => a.daysLeft <= 0) && <span className="brief-due urgent">今日締切あり</span>}</summary>
          {dueSoon.map((a) => (
            <div key={a.id} className="habit-check-row" style={{ padding: '5px 10px' }}>
              <span style={{ flex: 1 }}>{a.title}
                <span className={a.daysLeft <= 0 ? 'brief-due urgent' : 'brief-due'}>{a.daysLeft <= 0 ? '今日締切！' : `あと${a.daysLeft}日`}</span>
              </span>
              <select value={String(a.progress)} aria-label="進捗"
                      onChange={async (e) => {
                        try {
                          await api.updateAssignment(a.id, { title: a.title, due_date: a.due, progress: parseInt(e.target.value, 10), note: a.note, category: a.category })
                          setBrief(await api.getBriefing())
                        } catch (err) { showToast('⚠️ ' + err.message) }
                      }}>
                {[0, 25, 50, 75, 100].map((p) => <option key={p} value={p}>{p === 100 ? '✅ 完了' : `${p}%`}</option>)}
              </select>
            </div>
          ))}
        </details>
      )}
    </>
  )
  const periodicFold = (
    <>
      {periodic.length > 0 && (
        <details className="todo-fold section">
          <summary>🔄 週単位・不定期 {periodic.length}件{periodicDue > 0 && <span className="brief-chip orange">そろそろ {periodicDue}</span>}</summary>
          {periodic.map((p) => (
            <div key={p.id} className="habit-check-row" style={{ padding: '5px 10px' }}>
              <input type="checkbox" checked={p.checkedToday} onChange={(e) => check(p.id, e.target.checked)} />
              <span style={{ flex: 1 }}>{p.title}
                <span className="caption">　{p.everyDays > 0 ? `${p.everyDays}日ごと` : '不定期'}{p.lastDone ? `・前回 ${p.daysSince}日前` : '・未実施'}</span>
                {p.due && !p.checkedToday && <span className="brief-chip orange">そろそろ</span>}
              </span>
            </div>
          ))}
        </details>
      )}
    </>
  )
  const kbLine = (
    <>
      {gate?.keyboardWeekly && <div className="w-sub" style={{ marginTop: 6 }}>⌨️ 今週の3つ：{gate.keyboardWeekly}</div>}
    </>
  )
  const unlockedNote = (
    <>
      {gate?.unlocked && (
        <div className="w-sub" style={{ marginBottom: 6 }}>
          {gate.unlockedBy === 'emergency' ? '🛑 承認された解除の時間帯です'
            : gate.unlockedBy === 'exempt' ? '💼 面接などの特例で制限を外しています'
            : gate.game_unlocked ? 'サイト制限・ゲーム制限とも解除されています。おつかれさま ☕'
            : 'サイト制限は解除。ゲームは勉強目標と 07:00〜21:00 の条件で解除されます'}
        </div>
      )}
    </>
  )
  const actionCard = (
    <section className="ios-widget home-action" aria-label="次にやること">
      <button className="big ios-roll" onClick={roll} disabled={busy || !!ro}>
        <span className="roll-emoji" aria-hidden="true">{busy ? '☕' : '🎲'}</span>
        <span className="roll-text">
          <span className="roll-main">{busy ? '抽選中…' : 'ルーレットを回す'}</span>
          <span className="roll-sub">勉強メニューを抽選して、そのまま集中モードへ</span>
        </span>
      </button>
      <button type="button" className="home-pick" onClick={openPick} disabled={busy}>
        ⏱ 自分で選んで始める
      </button>
    </section>
  )
  const progressCard = (
    <section className="ios-widget" id="home-progress" aria-label="今日の進捗">
      <div className="w-label">📊 今日の進捗</div>
      <div className="w-ring-row">
        <Ring pct={pct} size={layout === 'two' ? 64 : 108} stroke={layout === 'two' ? 8 : 11} />
        <div>
          <div className="w-big">{todayMin}<span className="w-unit">分</span></div>
          {liveMin > 0 && <div className="w-sub" style={{ color: '#4CAF50', marginTop: 2 }}>うち計測中 {liveMin}分</div>}
          <div className="w-sub w-sub-target" style={{ marginTop: 2 }}>目標 {target}分{state.target_locked ? '' : '（仮）'}　☕ 気分転換 {state.refresh_time_total}分</div>
          <div className="w-sub" style={{ marginTop: 2 }}>🔥 連続 {streak}日　🕐 まだ勉強できる {remainText}</div>
        </div>
      </div>
      {!state.target_locked && (
        <div className="target-box">
          <div className="caption">🎯 今日の目標を決める（確定すると今日は変えられません）</div>
          <div className="target-steppers">
            <Stepper label="時間" value={h} onChange={setH} min={0} max={16} step={1} />
            <Stepper label="分" value={m} onChange={setM} min={0} max={45} step={15} />
          </div>
          <button className="w-action" onClick={lockTarget}>✅ {h}時間{m}分 で確定する</button>
        </div>
      )}
      <div className="week-bars" style={{ marginTop: 12 }}>
        {weekDays.map((d) => (
          <div className="wb-col" key={d.key}>
            <div className="wb-val">{d.min > 0 ? d.min : ''}</div>
            <div className="wb-bar" style={{ height: `${Math.max(6, (d.min / weekMax) * 56)}px`, background: d.isToday ? '#4CAF50' : 'rgba(255,255,255,0.28)' }} />
            <div className="wb-day" style={d.isToday ? { color: '#4CAF50', fontWeight: 700 } : undefined}>{d.label}</div>
          </div>
        ))}
      </div>
      <div className="w-sub">今週 合計 {weekTotal}分</div>
      <details className="todo-fold section" open={trendOpen} onToggle={(e) => setTrendOpen(e.target.open)}>
        <summary>📈 消化率と最近14日</summary>
        {bars.map((b) => <HBar key={b.label} {...b} />)}
        {dayRates.some((d) => d.rate != null) && (
          <>
            <div className="caption" style={{ marginTop: 8 }}>🔁 習慣の達成率（直近7日）</div>
            {dayRates.map((d) => <HBar key={d.date} label={d.label} pct={d.rate} />)}
          </>
        )}
        {recent.length > 0 && (
          <>
            <div className="caption" style={{ marginTop: 8 }}>📈 勉強分（緑）・習慣達成率（青）・✓ノルマ達成・🛑停止</div>
            <TrendChart data={recent} />
          </>
        )}
      </details>
    </section>
  )
  const briefCard = (
    <>
      {brief && (
        <section className="ios-widget brief-card" aria-label="今日のまとめ">
          <div className="w-label">
            ☀️ 今日のまとめ
            {brief.holiday_name && <span className="brief-chip red">🎌 {brief.holiday_name}</span>}
            {brief.overridden && <span className="brief-chip orange">🔀 振替日程</span>}
            {brief.job_conflicts > 0 && <span className="brief-chip orange">⚠️ 就活日程の被り {brief.job_conflicts}件</span>}
          </div>
          <div className="brief-rows">
            <div className="brief-row"><span className="brief-k">🎓 授業</span>
              <span>{brief.classes.length === 0 ? 'なし' : brief.classes.map((c) => `${c.start} ${c.title}`).join('　/　')}</span></div>
            {brief.jobs.length > 0 && (
              <div className="brief-row"><span className="brief-k">💼 就活</span>
                <span>{brief.jobs.map((j) => `${j.date.slice(5).replace('-', '/')} ${j.company ?? ''} ${j.label}`.trim()).join('　/　')}</span></div>
            )}
            <div className="brief-row"><span className="brief-k">⏱ 勉強</span>
              <span>今日 {brief.study.today_min + liveMin}分 / 目標 {brief.study.target_min}分<span className="brief-sub">　昨日 {brief.study.yesterday_min}分</span></span></div>
            {brief.money.allowance != null && (
              <div className="brief-row"><span className="brief-k">💰 お金</span>
                <span style={{ color: brief.money.remaining >= 0 ? undefined : '#FF6B62' }}>
                  今月あと {brief.money.remaining?.toLocaleString()}円
                  <span className="brief-sub">　今日 {brief.money.today_spent.toLocaleString()}円・固定費 {brief.money.subs_monthly?.toLocaleString()}円/月 込み</span>
                </span></div>
            )}
            {presence?.enabled && presence.monitored_min > 0 && (
              <div className="brief-row"><span className="brief-k">📷 在席</span>
                <span>{presence.rate}%<span className="brief-sub">　在席 {presence.present_min}分／監視 {presence.monitored_min}分</span></span></div>
            )}
          </div>
          <div className="brief-plan-row">
            <button type="button" className="small" disabled={planBusy}
                    onClick={async () => {
                      setPlanBusy(true)
                      try { const x = await api.makeAiDayPlan(); setBrief({ ...brief, ai_plan: x.text }) }
                      catch (e) { showToast('⚠️ AIプランの生成に失敗しました：' + e.message) }
                      finally { setPlanBusy(false) }
                    }}>
              {planBusy ? '🤖 プランを考え中…' : brief.ai_plan ? '🤖 プランを作り直す' : '🤖 今日のプランをAIに作らせる'}
            </button>
            {brief.ai_plan && <span className="brief-sub">Googleカレンダーの「📌 今日やること」にも載ります</span>}
          </div>
          {brief.ai_plan && <div className="brief-plan">{brief.ai_plan}</div>}
        </section>
      )}
    </>
  )
  const goalsCard = (
    <>
      {goals.length > 0 && (
        <section className="ios-widget goals-card" aria-label="目標までの日数">
          <div className="w-label">🏁 目標まで</div>
          <div className="goal-row-list">
            {goals.map((g, i) => {
              const d = new Date(g.date + 'T00:00:00')
              const days = Number.isNaN(d.getTime()) ? 0 : Math.max(Math.round((d - midnight) / 86400000), 0)
              const hours = parseInt(g.hours ?? 2, 10)
              return (
                <div key={i} className="goal-row">
                  <span className="goal-name">{g.name}</span>
                  <span className="goal-days">あと <strong>{days}</strong> 日</span>
                  <span className="caption">{g.date}・残り作業 {days * hours}時間</span>
                </div>
              )
            })}
          </div>
        </section>
      )}
    </>
  )
  const todoTitle = !gate ? '📋 今日やること'
    : gate.tasks_done ? '🔓 今日やること：ノルマ達成！'
    : `📋 今日やること（あと${gate.remaining.length}件で制限解除）`
  // 📅 今日の時間軸（案C／P2 の上の帯）：時間帯のある習慣・授業・予定・Google・現在位置
  const stripItems = [
    ...gHabits.filter((x) => x.start && x.end).map((x) => ({ kind: 'habit', start: x.start, end: x.end, title: x.title, done: x.done })),
    ...(brief?.timetable ?? [])
      .filter((b) => !gHabits.some((x) => x.title === b.title))   // 習慣は上の行に出すので時間割からは除く
      .map((b) => ({ kind: (b.category === '大学' ? 'class' : 'life'), start: b.start, end: b.end, title: b.title })),
    ...events.map((e) => ({ kind: 'event', start: e.start, end: e.end, title: e.title, done: e.done })),
    ...google.filter((g) => !g.allday && g.start && g.end).map((g) => ({ kind: 'google', start: g.start, end: g.end, title: g.title })),
  ].filter((b) => b.start && b.end)
  const nextItem = stripItems.filter((b) => b.kind !== 'habit' && b.kind !== 'life' && b.start > hm).sort((a, b) => a.start.localeCompare(b.start))[0]
  const minutesUntil = (t) => { const [a, b] = t.split(':').map(Number); const [c, d] = hm.split(':').map(Number); return a * 60 + b - (c * 60 + d) }
  const nowLine = (
    <div className="caption now-line">
      {widgetLive && (
        <div className="now-live">
          {(widgetLive.task || '').startsWith('📱') ? '📱 iPhoneで計測中：' + widgetLive.task.slice(2).trim() : '🪟 小窓で計測中：' + (widgetLive.task || '（タスク未選択）')}
          　{String(Math.floor(liveSec / 60)).padStart(2, '0')}:{String(liveSec % 60).padStart(2, '0')}
        </div>
      )}
      <div>いま {hm}{nextItem ? `・次：${nextItem.start} ${nextItem.title}（あと${minutesUntil(nextItem.start)}分）` : '・この後の予定はありません'}</div>
    </div>
  )
  const strip = <DayStrip items={stripItems} now={hm} />

  // 下から出るシート（自分で選ぶ・抽選結果）。従来のホームとアジェンダ型の両方で使う
  const sheets = (
    <>
      {/* ⏱ 自分で選んで始める（下から出るシート） */}
      {pickOpen && (
        <>
          <div className="ios-sheet-backdrop" onClick={() => setPickOpen(false)} />
          <div className="ios-sheet" role="dialog" aria-label="何をやる？">
            <div className="ios-grabber" />
            <div className="sheet-head">
              <h3>⏱ 何をやる？</h3>
              <button type="button" className="sheet-close" onClick={() => setPickOpen(false)} aria-label="閉じる">✕</button>
            </div>
            <div className="caption" style={{ marginBottom: 6 }}>押すとすぐ集中モードが始まります（習慣は規定時間で自動完了）</div>
            {!pickLists && <div className="caption">読み込み中…</div>}
            {pickLists && [['🔴 今日の必須', pickLists.must], ['🔁 今日の習慣', pickLists.habits], ['🎲 ルーレット項目', pickLists.roulette]]
              .map(([label, items]) => items.length > 0 && (
                <div key={label} style={{ marginTop: 6 }}>
                  <div className="caption">{label}</div>
                  <div className="pick-list">
                    {items.map((t) => <button key={t} type="button" className="pick-item" onClick={() => startPicked(t)}>{t}</button>)}
                  </div>
                </div>
              ))}
            {pickLists && pickLists.must.length + pickLists.habits.length + pickLists.roulette.length === 0 && (
              <div className="caption">候補がありません。下に入力して始められます。</div>
            )}
            <div className="edit-row" style={{ marginTop: 10 }}>
              <input type="text" value={pickFree} placeholder="自由入力（例：レポートの下書き）" style={{ flex: 1 }}
                     onChange={(e) => setPickFree(e.target.value)}
                     onKeyDown={(e) => { if (e.key === 'Enter') startPicked(pickFree) }} />
              <button type="button" className="small" onClick={() => startPicked(pickFree)}>▶ 開始</button>
            </div>
          </div>
        </>
      )}

      {/* 抽選結果：下から出るシート */}
      {ro && (
        <>
          <div className="ios-sheet-backdrop" />
          <div className="ios-sheet" role="dialog" aria-label="今回のお題">
            <div className="ios-grabber" />
            <h3 style={{ textAlign: 'center', margin: '4px 0 14px' }}>🎲 今回のお題</h3>
            {state.force_study_only && !state.last_was_refresh && <div className="info-box">📚 今回は『勉強』のみの抽選です</div>}
            {choices.map((c) => (
              <label key={c} className={'option-label' + (selected === c ? ' selected' : '')}>
                <input type="radio" name="ios_task" checked={selected === c} onChange={() => setSelected(c)} />
                {c}
              </label>
            ))}
            <button className="big" onClick={start} disabled={!selected || busy}>集中モードへ！</button>
          </div>
        </>
      )}
    </>
  )
  // 🗓 アジェンダ型ホーム（2026-11-03）：横画面・縦置きで使う。?home=agenda で先行確認、設定 home_style で切替
  // 2026-11-04 依頼者の承認で標準に。設定 home_style='classic' で従来のホームに戻せる。?home=classic / ?home=agenda で一時的に切替
  const homeParam = new URLSearchParams(window.location.search).get('home')
  const agendaMode = !single && (homeParam === 'agenda' || (homeParam !== 'classic' && settings.home_style !== 'classic'))
  if (agendaMode) {
    return (
      <HomeAgendaView sheets={sheets} ctx={{ settings, gate, brief, state, now, widgetAlive, widgetLive, liveSec, busy, ro, showToast,
        roll, openPick, check, startHabit, refreshTodo, onOpenPage, todayMin, target, streak, presence, cam, goals,
        recordHabits, gateHabits, mustOpen, mustDone, periodic, events, google }} />
    )
  }

  return (
    <div className={'home fit-page' + (layout === 'two' ? ' home-c' : layout === 'stacked' ? ' home-p2' : '')}>
      <div className="fit-head">
      {/* 1. 見出しと状態 */}
      <div className="home-head">
        <div>
          <div className="ios-date">{dateStr}</div>
          <h1 className="ios-large-title">☕ Focus &amp; Cafe</h1>
        </div>
        {!widgetAlive && (
          <button type="button" className="small" onClick={async () => {
            try {
              await api.showWidget()
              setTimeout(() => api.getWidgetStatus().then((x) => setWidgetAlive(x.alive)).catch(() => {}), 3000)
            } catch (e) { showToast('⚠️ 小窓の起動に失敗しました: ' + e.message) }
          }}>🪟 タイマー小窓を表示</button>
        )}
      </div>
      <div className="status-row" role="group" aria-label="いまの状態">
        <StatusChip icon={gate?.site_unlocked && gate?.game_unlocked ? '🔓' : '🔒'} label={lockLabel} tone={lockTone}
                    title="制限の画面を開く" onClick={() => onOpenPage('lock')} />
        <StatusChip icon="⏱" label={`勉強 ${todayMin}/${target}分`} tone={pct >= 1 ? 'ok' : ''}
                    title="進捗へ" onClick={() => {
                      if (single) setPane('stats')
                      else document.getElementById('home-progress')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
                    }} />
        {cam?.enabled && (
          <StatusChip icon="📷" label={cam.monitor ? `在席判定中${presence?.rate != null ? `・今日 ${presence.rate}%` : ''}` : (cam.label || '在席判定')}
                      tone={cam.monitor ? 'ok' : ''} title="在席判定の画面を開く" onClick={() => onOpenPage('presence')} />
        )}
      </div>
      <div className="home-comment">💬 {comment}</div>
      {nowItems.length > 0 && (
        <div className="brief-now">▶ いまの予定：{nowItems.map((b) => `${b.start}〜${b.end} ${b.title}${b.room ? `（${b.room}）` : ''}`).join('　/　')}</div>
      )}
      {widgetLive && (
        <div className="home-live">
          {(widgetLive.task || '').startsWith('📱') ? '📱 iPhoneで計測中：' + widgetLive.task.slice(2).trim() + '　'
            : '🪟 小窓で計測中：' + (widgetLive.task || '（タスク未選択）')}
          {String(Math.floor(liveSec / 60)).padStart(2, '0')}:{String(liveSec % 60).padStart(2, '0')}
        </div>
      )}

      {!single && strip}
      {single && (
        <div className="seg home-seg2" role="tablist" aria-label="ホームの表示">
          {[['todo', '📋 やること'], ['stats', '📊 進捗・まとめ']].map(([v, lbl]) => (
            <button key={v} type="button" role="tab" aria-selected={pane === v}
                    className={'seg-btn' + (pane === v ? ' on' : '')} onClick={() => setPane(v)}>{lbl}</button>
          ))}
        </div>
      )}
      </div>

      {layout === 'two' && (
        /* ===== 案C：横タイムライン型（横幅 1000px 以上の横画面） ===== */
        <div className="home-grid fit-grid three-c">
          <div className="home-col">
            <section className="ios-widget home-action" aria-label="次にやること">
              {nowLine}
              <button className="big ios-roll" onClick={roll} disabled={busy || !!ro}>
                <span className="roll-emoji" aria-hidden="true">{busy ? '☕' : '🎲'}</span>
                <span className="roll-text">
                  <span className="roll-main">{busy ? '抽選中…' : 'ルーレットを回す'}</span>
                  <span className="roll-sub">勉強メニューを抽選して、そのまま集中モードへ</span>
                </span>
              </button>
              <button type="button" className="home-pick" onClick={openPick} disabled={busy}>⏱ 自分で選んで始める</button>
              {recordHabits.length > 0 && <div style={{ marginTop: 10 }}>{recordBox}</div>}
            </section>
          </div>
          <div className="home-col">
            <section className="ios-widget" aria-label="今日やること">
              <div className="w-label">{todoTitle}</div>
              {unlockedNote}
              {mustBlock}
              <div className="caption" style={{ marginTop: 8 }}>🔁 自由枠の習慣<span className="caption hint">　押すとタイマー開始・25分で自動完了</span></div>
              {habitChips}
              {(timedOpen.length > 0 || timedDone.length > 0) && (
                <>
                  <div className="caption" style={{ marginTop: 8 }}>⏰ 時間帯のある習慣</div>
                  {timedOpen.map(habitRow)}
                  {timedDone.map(habitRow)}
                </>
              )}
              {eventsFold}
              {dueFold}
              {kbLine}
            </section>
          </div>
          <div className="home-col stats">
            {progressCard}
            {briefCard}
          </div>
          <div className="home-col stats col4">
            {periodic.length > 0 && (
              <section className="ios-widget" aria-label="週単位">
                <div className="w-label">🔄 週単位・不定期{periodicDue > 0 && <span className="brief-chip orange" style={{ marginLeft: 6 }}>そろそろ {periodicDue}</span>}</div>
                {periodic.map((p) => (
                  <label key={p.id} className="habit-check-row" style={{ padding: '3px 8px' }}>
                    <input type="checkbox" checked={p.checkedToday} onChange={(e) => check(p.id, e.target.checked)} />
                    <span style={{ flex: 1 }} className={p.checkedToday ? 'habit-done' : ''}>{p.title}
                      <span className="caption">　{p.everyDays > 0 ? `${p.everyDays}日ごと` : '不定期'}{p.lastDone ? `・前回 ${p.daysSince}日前` : ''}</span>
                      {p.due && !p.checkedToday && <span className="brief-chip orange">そろそろ</span>}
                    </span>
                  </label>
                ))}
              </section>
            )}
            {goalsCard}
          </div>
        </div>
      )}

      {layout === 'stacked' && (
        /* ===== P2：縦置き＝時間軸＋ルーレット＋2列ボード ===== */
        <div className="home-grid fit-grid p2">
          <div className="p2-top">{actionCard}</div>
          <div className="home-col">
            {recordHabits.length > 0 && <section className="ios-widget" aria-label="記録">{recordBox}</section>}
            <section className="ios-widget" aria-label="今日の習慣">
              <div className="w-label">{todoTitle}</div>
              {unlockedNote}
              {habitsRows}
              {kbLine}
            </section>
          </div>
          <div className="home-col stats">
            <section className="ios-widget" aria-label="必須">{mustBlock}</section>
            <section className="ios-widget" aria-label="予定・週単位">{eventsFold}{dueFold}{periodicFold}</section>
            {progressCard}
            {briefCard}
            {goalsCard}
          </div>
        </div>
      )}

      {single && (
        /* ===== スマホ縦：従来どおり切替 ===== */
        <div className="home-grid fit-grid">
          <div className="home-col" hidden={pane !== 'todo'}>
            {actionCard}
            <section className="ios-widget fit-grow" aria-label="今日やること">
              <div className="w-label">{todoTitle}</div>
              <div className="fit-scroll">
                {unlockedNote}
                {recordBox}
                {mustBlock}
                {habitsRows}
                {eventsFold}
                {dueFold}
                {periodicFold}
                {kbLine}
              </div>
            </section>
          </div>
          <div className="home-col stats" hidden={pane !== 'stats'}>
            {progressCard}
            {briefCard}
            {goalsCard}
          </div>
        </div>
      )}

      {sheets}
    </div>
  )
}

export default HomeIos
