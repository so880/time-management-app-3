// iOS 風シェル（2026-11-01 夜に作り直し。iPhone 標準アプリの設計を手本にした）
//
// 方針（初めて使う人が説明なしで分かること）
// - 下のタブは 5 つだけ（ホーム／今日／カレンダー／マネー／その他）。位置は固定、ドラッグや📌入替はしない
// - それ以外の画面は「その他」の一覧から開く。開いた画面は必ず左上に「‹ 戻る」があり、
//   ブラウザの「戻る」ボタン・Esc キーでも戻れる（history を積む）
// - 同じタブをもう一度押すと、その画面の先頭（初期状態）に戻る（iPhone の挙動）
// - 集中モード・ふりかえり・SOS の間はタブを隠して没入（従来どおり）
// - 設定タブは非表示でもマウントしたまま（環境音の再生を止めないため）。習慣の通知も常時動かす
import { useCallback, useEffect, useRef, useState } from 'react'
import Active from '../views/Active.jsx'
import EditPanel from '../views/EditPanel.jsx'
import Review from '../views/Review.jsx'
import Sos from '../views/Sos.jsx'
import MoneyIos from '../money/MoneyIos.jsx'
import HabitPanel from './HabitPanel.jsx'
import HomeIos from './HomeIos.jsx'
import JobIos from './JobIos.jsx'
import LifeIos, { CalendarTab, RoulettePage, ScheduleEditor } from './LifeIos.jsx'
import LockIos from './LockIos.jsx'
import MoreIos, { MORE_PAGES } from './MoreIos.jsx'
import PresenceIos from './PresenceIos.jsx'
import SettingsIos from './SettingsIos.jsx'

// ---- タブバー用アイコン（線画 SVG） ----
const HomeIcon = ({ active }) => (
  <svg viewBox="0 0 24 24" fill={active ? 'currentColor' : 'none'}
       stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round">
    <path d="M3 10.5 12 3l9 7.5" />
    <path d="M5 9.5V21h14V9.5" fill="none" />
  </svg>
)
const DayIcon = ({ active }) => (
  <svg viewBox="0 0 24 24" fill="none"
       stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round">
    <rect x="3.5" y="5" width="17" height="16" rx="3" fill={active ? 'currentColor' : 'none'} />
    <path d="M3.5 9.5h17M8 2.8V6M16 2.8V6" />
    <path d="M12 12.5v4M12 16.5h3" stroke={active ? '#1a1f29' : 'currentColor'} />
  </svg>
)
const MonthIcon = ({ active }) => (
  <svg viewBox="0 0 24 24" fill="none"
       stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round">
    <rect x="3.5" y="5" width="17" height="16" rx="3" fill={active ? 'currentColor' : 'none'} />
    <path d="M3.5 9.5h17M8 2.8V6M16 2.8V6" />
    <path d="M7.5 13h3M13.5 13h3M7.5 17h3M13.5 17h3" stroke={active ? '#1a1f29' : 'currentColor'} />
  </svg>
)
const YenIcon = ({ active }) => (
  <svg viewBox="0 0 24 24" fill="none"
       stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round">
    <circle cx="12" cy="12" r="9.2" fill={active ? 'currentColor' : 'none'} />
    <path d="M8.5 7.5 12 12.2 15.5 7.5M12 12.2V17M9.2 13.4h5.6M9.2 15.6h5.6"
          stroke={active ? '#1a1f29' : 'currentColor'} />
  </svg>
)
const MoreIcon = ({ active }) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
    <circle cx="12" cy="12" r="9.2" fill={active ? 'currentColor' : 'none'} />
    <circle cx="7.5" cy="12" r="1.4" fill={active ? '#1a1f29' : 'currentColor'} stroke="none" />
    <circle cx="12" cy="12" r="1.4" fill={active ? '#1a1f29' : 'currentColor'} stroke="none" />
    <circle cx="16.5" cy="12" r="1.4" fill={active ? '#1a1f29' : 'currentColor'} stroke="none" />
  </svg>
)

// タブは 5 つ固定。名前は「中身がそのまま分かる言葉」
export const TABS = [
  { id: 'home', label: 'ホーム', Icon: HomeIcon },
  { id: 'life', label: '今日', Icon: DayIcon },
  { id: 'cal', label: 'カレンダー', Icon: MonthIcon },
  { id: 'money', label: 'マネー', Icon: YenIcon },
  { id: 'more', label: 'その他', Icon: MoreIcon },
]

// 画面上部の「‹ 戻る ＋ タイトル」（その他から開いた画面すべてに共通）
export function PageHeader({ title, backLabel, onBack, right }) {
  return (
    <div className="pg-header">
      <button type="button" className="pg-back" onClick={onBack} aria-label="戻る">
        <span className="pg-chev">‹</span>{backLabel || '戻る'}
      </button>
      <div className="pg-title">{title}</div>
      <div className="pg-right">{right}</div>
    </div>
  )
}

function IosShell({ settings, state, logs, compactMode, setCompactMode,
                    onSettingsChange, onStateChange, onLogsChanged, showToast }) {
  const [tab, setTab] = useState('home')
  // 同じタブをもう一度押したときだけ +1 → 子画面が初期状態（先頭・今日）に戻る
  const [resetTicks, setResetTicks] = useState({})
  // 🗓 カレンダーで日付をタップ → 「今日」タブでその日を開く
  const [lifeJump, setLifeJump] = useState({ date: null, tick: 0 })
  // その他から開いた画面のスタック（['job', 'presence', ...]）。history と同期する
  const [stack, setStack] = useState([])
  const [kbHelp, setKbHelp] = useState(false)
  const tabRef = useRef('home')
  const stackRef = useRef([])
  stackRef.current = stack

  const page = state.page ?? 'dashboard'
  const inFlow = page !== 'dashboard' // 集中モード・ふりかえり・SOS 中はタブより優先

  // ◐ テーマ（黒／白）：設定 ui_theme を html[data-theme] に反映（CSS 変数で色が変わる。2026-11-03）
  useEffect(() => {
    const t = settings?.ui_theme === 'light' ? 'light' : 'dark'
    document.documentElement.dataset.theme = t
  }, [settings?.ui_theme])

  // ---- 画面スタック（ブラウザの戻る・Esc と同期） ----
  // F23：ページ全体はスクロールしない（.tab-pane の中だけ）ので、先頭へ戻すのも表示中の .tab-pane
  const scrollTop = () => {
    window.scrollTo({ top: 0 })
    document.querySelectorAll('.tab-pane:not([hidden]), .fit-body, .fit-scroll').forEach((el) => { el.scrollTop = 0 })
  }
  const push = useCallback((id) => {
    if (!MORE_PAGES[id]) return
    const next = [...stackRef.current, id]
    setStack(next)
    try { window.history.pushState({ fcStack: next.length }, '') } catch { /* 無視 */ }
    scrollTop()
  }, [])
  const pop = useCallback(() => {
    if (stackRef.current.length === 0) return
    // history に積んであれば back() → popstate で縮める。無ければ直接縮める
    if (window.history.state && window.history.state.fcStack === stackRef.current.length) {
      window.history.back()
    } else {
      setStack((s) => s.slice(0, -1))
    }
  }, [])
  useEffect(() => {
    const onPop = (e) => {
      const depth = (e.state && typeof e.state.fcStack === 'number') ? e.state.fcStack : 0
      setStack((s) => (s.length > depth ? s.slice(0, depth) : s))
      scrollTop()
    }
    window.addEventListener('popstate', onPop)
    try { window.history.replaceState({ fcStack: 0 }, '') } catch { /* 無視 */ }
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  const selectTab = useCallback((id) => {
    if (tabRef.current === id && stackRef.current.length === 0) {
      // 同じタブをもう一度 → 先頭・初期状態へ（iPhone と同じ）
      setResetTicks((t) => ({ ...t, [id]: (t[id] ?? 0) + 1 }))
    }
    setTab(id)
    tabRef.current = id
    if (stackRef.current.length > 0) {
      setStack([])
      try { window.history.replaceState({ fcStack: 0 }, '') } catch { /* 無視 */ }
    }
    scrollTop()
  }, [])

  // ホームなどから「その他の画面」を直接開く（例：制限チップ → 制限画面）
  const openPage = useCallback((id) => {
    if (TABS.some((t) => t.id === id)) { selectTab(id); return }
    if (tabRef.current !== 'more') { setTab('more'); tabRef.current = 'more' }
    setStack([])
    try { window.history.replaceState({ fcStack: 0 }, '') } catch { /* 無視 */ }
    push(id)
  }, [push, selectTab])

  // ---- ⌨️ キーボード：1〜5=タブ / ?=ヘルプ / Esc=戻る・閉じる / ←→・T は表示中のタブへ ----
  useEffect(() => {
    const onKey = (e) => {
      const el = e.target
      const typing = el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA'
        || el.tagName === 'SELECT' || el.isContentEditable)
      if (typing || e.ctrlKey || e.metaKey || e.altKey) return
      if (e.key === '?') { setKbHelp((v) => !v); return }
      if (e.key === 'Escape') {
        if (kbHelp) { setKbHelp(false); return }
        if (stackRef.current.length > 0) pop()
        return
      }
      const n = parseInt(e.key, 10)
      if (n >= 1 && n <= TABS.length) { selectTab(TABS[n - 1].id); return }
      if (['ArrowLeft', 'ArrowRight', 't', 'T'].includes(e.key)) {
        window.dispatchEvent(new CustomEvent('fc-key', { detail: { key: e.key, tab: tabRef.current } }))
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [kbHelp, pop, selectTab])
  useEffect(() => {
    const h = () => setKbHelp(true)
    window.addEventListener('fc-kb-open', h)
    return () => window.removeEventListener('fc-kb-open', h)
  }, [])

  // ---- その他 › 各画面の中身 ----
  const renderSub = (id) => {
    const common = { settings, onSettingsChange, showToast }
    switch (id) {
      case 'job': return <JobIos showToast={showToast} resetTick={0} />
      case 'lock': return <LockIos showToast={showToast} />
      case 'habits': return <HabitPanel {...common} part="habits" />
      case 'gate': return <HabitPanel {...common} part="gate" />
      case 'presence': return <PresenceIos showToast={showToast} />
      case 'roulette': return <RoulettePage showToast={showToast} />
      case 'timetable': return <ScheduleEditor showToast={showToast} />
      case 'refresh': return <EditPanel {...common} only="refresh" />
      case 'goals': return <EditPanel {...common} only="goals" />
      case 'duration': return <EditPanel {...common} only="duration" />
      case 'routine': return <EditPanel {...common} only="routine" />
      case 'gameblock': return <EditPanel {...common} only="gameblock" />
      case 'bgurl': return <EditPanel {...common} only="bgurl" />
      case 'settings': return null // 常時マウント（下）
      default: return null
    }
  }
  const top = stack[stack.length - 1] || null
  const backLabel = stack.length > 1 ? (MORE_PAGES[stack[stack.length - 2]]?.label ?? '戻る') : 'その他'

  return (
    <div className="ios-shell">
      <div className="ios-content">
        {inFlow && (
          <div key={page} className="page-anim tab-pane">
            {page === 'active' ? (
              <Active state={state} compactMode={compactMode}
                      setCompactMode={setCompactMode} onStateChange={onStateChange} />
            ) : page === 'review' ? (
              <Review state={state} onStateChange={onStateChange} onLogsChanged={onLogsChanged} />
            ) : (
              <Sos state={state} onStateChange={onStateChange} />
            )}
          </div>
        )}

        {/* 各タブ：非表示でもマウントしたまま（入力途中・スクロール位置を保つ）。
            同じタブをもう一度押したときだけ key が変わり初期状態へ */}
        <div className="tab-pane" hidden={inFlow || tab !== 'home'}>
          <HomeIos key={`h${resetTicks.home ?? 0}`}
                   settings={settings} state={state} logs={logs}
                   onStateChange={onStateChange} onSettingsChange={onSettingsChange}
                   resetTick={resetTicks.home ?? 0} showToast={showToast}
                   onOpenPage={openPage} />
        </div>
        <div className="tab-pane" hidden={inFlow || tab !== 'life'}>
          <LifeIos key={`l${resetTicks.life ?? 0}`}
                   settings={settings} onSettingsChange={onSettingsChange} showToast={showToast}
                   resetTick={resetTicks.life ?? 0}
                   jumpDate={lifeJump.date} jumpTick={lifeJump.tick} />
        </div>
        <div className="tab-pane" hidden={inFlow || tab !== 'cal'}>
          <CalendarTab key={`c${resetTicks.cal ?? 0}`}
                       settings={settings} onSettingsChange={onSettingsChange} showToast={showToast}
                       onOpenDay={(d) => {
                         setLifeJump((j) => ({ date: d, tick: j.tick + 1 }))
                         setTab('life')
                         tabRef.current = 'life'
                         window.scrollTo({ top: 0 })
                       }} />
        </div>
        <div className="tab-pane" hidden={inFlow || tab !== 'money'}>
          <MoneyIos key={`m${resetTicks.money ?? 0}`}
                    settings={settings} onSettingsChange={onSettingsChange} showToast={showToast}
                    resetTick={resetTicks.money ?? 0} />
        </div>

        {/* その他：一覧 ⇄ 各画面（スタック） */}
        <div className="tab-pane" hidden={inFlow || tab !== 'more'}>
          <div hidden={stack.length > 0}>
            <MoreIos onOpen={push} settings={settings} onKbHelp={() => setKbHelp(true)} />
          </div>
          {top && top !== 'settings' && (
            <div key={`${top}-${stack.length}`} className="page-anim sub-page">
              <PageHeader title={MORE_PAGES[top]?.label ?? ''} backLabel={backLabel} onBack={pop} />
              {renderSub(top)}
            </div>
          )}
          {/* 設定は環境音を止めないため常時マウント（表示だけ切替） */}
          <div hidden={top !== 'settings'} className="sub-page">
            {top === 'settings' && <PageHeader title="設定" backLabel={backLabel} onBack={pop} />}
            <SettingsIos settings={settings} logs={logs}
                         onSettingsChange={onSettingsChange} onStateChange={onStateChange}
                         onLogsChanged={onLogsChanged} showToast={showToast} />
          </div>
        </div>
        {/* 🔔 習慣の開始通知（画面には何も出さない。どのタブでも動く） */}
        <HabitPanel settings={settings} onSettingsChange={onSettingsChange} showToast={showToast} part="notify" />
      </div>

      {kbHelp && (
        <div className="kb-help" onClick={() => setKbHelp(false)}>
          <div className="kb-help-box" onClick={(e) => e.stopPropagation()}>
            <div className="w-label">⌨️ キーボード操作</div>
            <div className="kb-row"><kbd>1</kbd>〜<kbd>5</kbd> タブ切替（ホーム／今日／カレンダー／マネー／その他）</div>
            <div className="kb-row"><kbd>←</kbd><kbd>→</kbd> 今日＝前日/翌日・カレンダー＝前月/翌月</div>
            <div className="kb-row"><kbd>T</kbd> 今日（今月）へ戻る</div>
            <div className="kb-row"><kbd>Esc</kbd> 前の画面へ戻る／このヘルプを閉じる　<kbd>?</kbd> このヘルプ</div>
            <div className="caption" style={{ marginTop: 6 }}>入力欄にカーソルがあるときは無効（普通に文字が打てます）</div>
          </div>
        </div>
      )}

      {!inFlow && (
        <nav className="ios-tabbar" aria-label="メインタブ">
          {TABS.map(({ id, label, Icon }) => (
            <button key={id} type="button"
                    className={'ios-tab' + (tab === id ? ' active' : '')}
                    aria-current={tab === id ? 'page' : undefined}
                    onClick={() => selectTab(id)}>
              <Icon active={tab === id} />
              <span className="t-label">{label}</span>
            </button>
          ))}
        </nav>
      )}
    </div>
  )
}

export default IosShell
