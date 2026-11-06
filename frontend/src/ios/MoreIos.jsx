// 「その他」タブ：iPhone の「設定」アプリと同じ、グループ分けされた一覧。
// 一覧の行を押すとその画面が開く（左上「‹ その他」とブラウザの戻る・Esc で戻れる）。
// 画面の中身は IosShell.renderSub が描く。ここは「何がどこにあるか」だけを担当する。
import { useState } from 'react'
import * as api from '../api.js'
import { usePolling } from '../lib/usePolling.js'

// id → 画面名（IosShell の PageHeader と戻るラベルにも使う）
export const MORE_PAGES = {
  job: { icon: '💼', color: '#AF52DE', label: '就活', sub: '応募状況・日程・提出物' },
  lock: { icon: '🔐', color: '#FF3B30', label: '制限', sub: 'いまの状態・解除の申請・記録' },
  presence: { icon: '📷', color: '#0A84FF', label: '在席判定・カメラ', sub: 'Webカメラで在席を判定して習慣を完了に' },
  gate: { icon: '🔒', color: '#FF9500', label: '制限の設定', sub: 'サイト制限のキーワードなど' },
  gameblock: { icon: '🎮', color: '#8E8E93', label: 'ゲームブロック', sub: '止めるゲームの一覧' },
  habits: { icon: '🔁', color: '#34C759', label: '習慣', sub: '曜日・時間帯の登録、達成率' },
  roulette: { icon: '🎲', color: '#FF9500', label: 'ルーレット項目', sub: '抽選に出す勉強（タグ・期限・重点）' },
  refresh: { icon: '☕', color: '#34C759', label: '気分転換の候補', sub: '抽選に出る休憩メニュー' },
  timetable: { icon: '🗓', color: '#007AFF', label: '時間割', sub: '毎週の授業・バイト' },
  goals: { icon: '🏁', color: '#AF52DE', label: '目標の日付', sub: '試験日などまでの残り日数' },
  routine: { icon: '🕐', color: '#FF9F0A', label: '勉強できる時間帯', sub: '曜日ごと。残り時間の計算に使う' },
  duration: { icon: '⏱️', color: '#5856D6', label: '勉強1回の長さ', sub: 'ルーレットで決まる時間の範囲' },
  bgurl: { icon: '🖼️', color: '#64D2FF', label: '背景画像のURL', sub: '' },
  settings: { icon: '⚙️', color: '#8E8E93', label: '設定', sub: '環境音・背景・履歴・見た目' },
}

const GROUPS = [
  { title: '毎日使う', ids: ['job', 'lock'] },
  { title: 'やることの登録', ids: ['habits', 'roulette', 'refresh', 'timetable'] },
  { title: '制限とカメラ', ids: ['presence', 'gate', 'gameblock'] },
  { title: '勉強の設定', ids: ['goals', 'routine', 'duration'] },
  { title: 'アプリ', ids: ['settings', 'bgurl'] },
]

function Row({ id, right, onClick }) {
  const p = MORE_PAGES[id]
  return (
    <button type="button" className="ios-row more-row-btn" onClick={onClick}>
      <span className="r-icon" style={{ background: p.color }}>{p.icon}</span>
      <span className="r-label">
        {p.label}
        {p.sub && <span className="r-sub">{p.sub}</span>}
      </span>
      {right != null && <span className="r-right">{right}</span>}
      <span className="r-chevron">›</span>
    </button>
  )
}

function MoreIos({ onOpen, settings, onKbHelp }) {
  const [gate, setGate] = useState(null)
  const [cam, setCam] = useState(null)
  // 右端の「ロック中／オン」などの表示用に1分ごとに読む
  usePolling((isAlive) => {
    api.getGateStatus().then((g) => { if (isAlive()) setGate(g) }).catch(() => {})
    api.getPresenceConfig().then((c) => { if (isAlive()) setCam(c) }).catch(() => {})
  }, 60000, [])

  const rightOf = (id) => {
    if (id === 'lock' && gate) return gate.site_unlocked && gate.game_unlocked ? '解放中' : 'ロック中'
    if (id === 'presence' && cam) return cam.enabled ? 'オン' : 'オフ'
    if (id === 'gameblock') return settings?.block_enabled ? 'オン' : 'オフ'
    if (id === 'goals') return `${(settings?.goals ?? []).length}件`
    return null
  }

  return (
    <div className="more-page">
      <h1 className="ios-large-title">その他</h1>
      {GROUPS.map((g) => (
        <div key={g.title}>
          <div className="ios-group-title">{g.title}</div>
          <div className="ios-list">
            {g.ids.map((id) => <Row key={id} id={id} right={rightOf(id)} onClick={() => onOpen(id)} />)}
          </div>
        </div>
      ))}
      <div className="ios-group-title">ヘルプ</div>
      <div className="ios-list">
        <button type="button" className="ios-row more-row-btn" onClick={onKbHelp}>
          <span className="r-icon" style={{ background: '#636366' }}>⌨️</span>
          <span className="r-label">キーボードで操作する<span className="r-sub">1〜5 でタブ、Esc で戻る など</span></span>
          <span className="r-chevron">›</span>
        </button>
      </div>
      <div className="caption more-foot">
        iPhone からは Apps Script のページ（カレンダータブ › Google 連携の設定に URL）を使います。
      </div>
    </div>
  )
}

export default MoreIos
