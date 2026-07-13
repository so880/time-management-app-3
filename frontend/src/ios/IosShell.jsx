// iOS風シェル（リキッドグラスON時のみ使用）
// - 下部タブバーで移動。集中モード中はタブバーを隠して没入。
// - タブバーはドラッグで移動できる：左右の端に近づくと縦並び、上下の端では横並び。
//   離すと一番近い端にスナップし、位置は設定 dock_edge として保存される。
// - 設定タブは非表示でもマウントしたままにする（環境音の再生を止めないため）。
import { useRef, useState } from 'react'
import * as api from '../api.js'
import Active from '../views/Active.jsx'
import EditPanel from '../views/EditPanel.jsx'
import Review from '../views/Review.jsx'
import Sos from '../views/Sos.jsx'
import MoneyIos from '../money/MoneyIos.jsx'
import HomeIos from './HomeIos.jsx'
import JobIos from './JobIos.jsx'
import LifeIos from './LifeIos.jsx'
import SettingsIos from './SettingsIos.jsx'

// タブバー用アイコン（SF Symbols風のシンプルな線画SVG）
const HomeIcon = ({ active }) => (
  <svg viewBox="0 0 24 24" fill={active ? 'currentColor' : 'none'}
       stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round">
    <path d="M3 10.5 12 3l9 7.5" />
    <path d="M5 9.5V21h14V9.5" fill="none" />
  </svg>
)
const EditIcon = ({ active }) => (
  <svg viewBox="0 0 24 24" fill={active ? 'currentColor' : 'none'}
       stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round">
    <path d="M4 20h16" fill="none" />
    <path d="M6 16.5 16.5 6a2.1 2.1 0 0 1 3 3L9 19.5 5 20l1-3.5Z" />
  </svg>
)
const GearIcon = ({ active }) => (
  <svg viewBox="0 0 24 24" fill="none"
       stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round">
    <circle cx="12" cy="12" r="3.2" fill={active ? 'currentColor' : 'none'} />
    <path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M18.5 5.5l-1.7 1.7M7.2 16.8l-1.7 1.7" />
  </svg>
)

const CalendarIcon = ({ active }) => (
  <svg viewBox="0 0 24 24" fill="none"
       stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round">
    <rect x="3.5" y="5" width="17" height="16" rx="3"
          fill={active ? 'currentColor' : 'none'} />
    <path d="M3.5 9.5h17M8 2.8V6M16 2.8V6" />
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

const BriefcaseIcon = ({ active }) => (
  <svg viewBox="0 0 24 24" fill="none"
       stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round">
    <rect x="3.5" y="7.5" width="17" height="13" rx="3"
          fill={active ? 'currentColor' : 'none'} />
    <path d="M9 7.5V5.8A1.8 1.8 0 0 1 10.8 4h2.4A1.8 1.8 0 0 1 15 5.8v1.7M3.5 12.5h17"
          stroke={active ? 'currentColor' : 'currentColor'} />
  </svg>
)

const TABS = [
  { id: 'home', label: 'ホーム', Icon: HomeIcon },
  { id: 'life', label: 'ライフ', Icon: CalendarIcon },
  { id: 'job', label: '就活', Icon: BriefcaseIcon },
  { id: 'money', label: 'マネー', Icon: YenIcon },
  { id: 'edit', label: '編集', Icon: EditIcon },
  { id: 'settings', label: '設定', Icon: GearIcon },
]

const EDGE_MARGIN = 150 // この距離まで左右の端に近づくと縦並びになる

function IosShell({ settings, state, logs, compactMode, setCompactMode,
                    onSettingsChange, onStateChange, onLogsChanged, showToast }) {
  const [tab, setTab] = useState('home')
  // タブを押すたびに+1して子タブへ伝える → 子側はこれを見て初期画面に戻る
  // （カレンダーを開いたまま「ライフ」を押すとライフの最初の画面に戻る、iPhoneと同じ動き）
  const [resetTicks, setResetTicks] = useState({})
  const [dockEdge, setDockEdge] = useState(settings.dock_edge ?? 'bottom')
  const [dragPos, setDragPos] = useState(null) // ドラッグ中のポインタ位置
  const movedRef = useRef(false)
  const startRef = useRef(null)

  const page = state.page ?? 'dashboard'
  const inFlow = page !== 'dashboard' // 集中モード・ふりかえり・SOS中はタブより優先

  // ---- タブバーのドラッグ移動 ----
  const onPointerDown = (e) => {
    startRef.current = { x: e.clientX, y: e.clientY }
    movedRef.current = false
    // ここでは setPointerCapture しない！
    // 押した瞬間にキャプチャすると click がボタンに届かなくなる（タブが反応しない）ため、
    // 「実際に動かし始めてから」（下の onPointerMove で）キャプチャする。
  }
  const onPointerMove = (e) => {
    if (!startRef.current) return
    const dx = e.clientX - startRef.current.x
    const dy = e.clientY - startRef.current.y
    if (!movedRef.current && Math.hypot(dx, dy) < 10) return // 誤タップ防止のしきい値
    if (!movedRef.current) {
      movedRef.current = true
      // ドラッグ開始が確定した時点でキャプチャ（バーの外に出ても追従させる）
      try { e.currentTarget.setPointerCapture(e.pointerId) } catch { /* 対応外環境は無視 */ }
    }
    setDragPos({ x: e.clientX, y: e.clientY })
  }
  const onPointerUp = async (e) => {
    startRef.current = null
    if (!movedRef.current) return
    // 一番近い端にスナップ
    const w = window.innerWidth
    const hgt = window.innerHeight
    const dists = [
      ['left', e.clientX], ['right', w - e.clientX],
      ['top', e.clientY], ['bottom', hgt - e.clientY],
    ]
    dists.sort((a, b) => a[1] - b[1])
    const edge = dists[0][0]
    setDockEdge(edge)
    setDragPos(null)
    // クリック抑止フラグは次のフレームで解除
    setTimeout(() => { movedRef.current = false }, 0)
    try {
      onSettingsChange(await api.updateSettings({ dock_edge: edge })) // 位置を保存
    } catch { /* 保存失敗しても表示は維持 */ }
  }

  const selectTab = (id) => {
    if (movedRef.current) return // ドラッグ直後のクリックは無視
    setTab(id)
    setResetTicks((t) => ({ ...t, [id]: (t[id] ?? 0) + 1 })) // 押すたびに初期状態へ
  }

  // ドラッグ中は左右の端に近づいたら縦並びのプレビューにする
  const dragVertical = dragPos
    ? (dragPos.x < EDGE_MARGIN || dragPos.x > window.innerWidth - EDGE_MARGIN)
    : false
  const dockedVertical = dockEdge === 'left' || dockEdge === 'right'

  const barClass = 'ios-tabbar'
    + (dragPos
      ? ' dragging' + (dragVertical ? ' vertical' : '')
      : ` edge-${dockEdge}` + (dockedVertical ? ' vertical' : ''))
  const barStyle = dragPos
    ? { left: dragPos.x + 'px', top: dragPos.y + 'px', right: 'auto', bottom: 'auto',
        transform: 'translate(-50%, -50%)' }
    : undefined

  return (
    <div className={`ios-shell dock-${dockEdge}`}>
      <div className="ios-content">
        {/* 集中フロー（タブバーは隠れる＝iPhoneのフルスクリーン操作と同じ） */}
        {inFlow && (
          <div key={page} className="page-anim">
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

        {/* タブの中身（非表示でもマウントしたまま＝環境音が途切れない） */}
        <div style={{ display: !inFlow && tab === 'home' ? 'block' : 'none' }}>
          <HomeIos settings={settings} state={state} logs={logs}
                   onStateChange={onStateChange} onSettingsChange={onSettingsChange}
                   resetTick={resetTicks.home ?? 0} />
        </div>
        <div style={{ display: !inFlow && tab === 'life' ? 'block' : 'none' }}>
          <LifeIos settings={settings} onSettingsChange={onSettingsChange} showToast={showToast}
                   resetTick={resetTicks.life ?? 0} />
        </div>
        <div style={{ display: !inFlow && tab === 'job' ? 'block' : 'none' }}>
          <JobIos showToast={showToast} resetTick={resetTicks.job ?? 0} />
        </div>
        <div style={{ display: !inFlow && tab === 'money' ? 'block' : 'none' }}>
          <MoneyIos settings={settings} onSettingsChange={onSettingsChange} showToast={showToast}
                    resetTick={resetTicks.money ?? 0} />
        </div>
        <div style={{ display: !inFlow && tab === 'edit' ? 'block' : 'none' }}>
          <h1 className="ios-large-title">🛠️ 編集</h1>
          <EditPanel settings={settings} onSettingsChange={onSettingsChange} showToast={showToast} />
        </div>
        <div style={{ display: !inFlow && tab === 'settings' ? 'block' : 'none' }}>
          <SettingsIos settings={settings} logs={logs}
                       onSettingsChange={onSettingsChange} onStateChange={onStateChange}
                       onLogsChanged={onLogsChanged} showToast={showToast} />
        </div>
      </div>

      {!inFlow && (
        <nav className={barClass} style={barStyle}
             onPointerDown={onPointerDown}
             onPointerMove={onPointerMove}
             onPointerUp={onPointerUp}>
          {TABS.map(({ id, label, Icon }) => (
            <button key={id} type="button"
                    className={'ios-tab' + (tab === id ? ' active' : '')}
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
