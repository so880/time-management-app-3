// 習慣の時間帯の全画面ロック：「いまは○○の時間です」
// その習慣が未完了のあいだアプリは使えない。できることは「小窓でタイマー開始」（画角外の習慣は「終了」も）だけ。
// 完了のしかた（F22・2026-11-01 夜）
//   ふつうの習慣 … 小窓で規定時間（時間帯の長さ）やる、または 在席率が基準以上（📷 在席判定がオンのとき）
//   画角外の習慣 … 小窓で「最低時間」以上やって ■ 終了 を押す（最低時間に達した時点で自動完了にもなる）
import { useEffect, useRef, useState } from 'react'
import * as api from '../api.js'
import { usePolling } from '../lib/usePolling.js'

function HabitLock({ info, onChanged, showToast }) {
  const h = info.habit
  const [busy, setBusy] = useState(false)
  const [widget, setWidget] = useState(null)
  // 定期読み込みの中から「いま表示中の習慣の分数」と「最新の onChanged」を読むための参照
  // （表示中に習慣が切り替わっても、古い分数で判定し続けないように）
  const latest = useRef({ minutes: info.minutes, onChanged })
  useEffect(() => {
    latest.current = { minutes: info.minutes, onChanged }
  }, [info.minutes, onChanged])

  // 小窓の計測状態を5秒ごとに読む
  usePolling((isAlive) => {
    api.getWidgetStatus().then((w) => {
      if (!isAlive()) return
      setWidget(w)
      // 規定時間に達したら（サーバー側で自動完了済みのはず）すぐ再判定してロックを解く
      const { minutes, onChanged: changed } = latest.current
      if (w?.running && Math.floor((w.elapsed_sec ?? 0) / 60) >= (minutes ?? 25)) changed?.()
    }).catch(() => {})
  }, 5000, [])

  const run = async (fn, msg) => {
    if (busy) return
    setBusy(true)
    try {
      await fn()
      if (msg) showToast?.(msg)
      onChanged?.()
    } catch (e) {
      showToast?.('⚠️ ' + (e?.message ?? ''))
    } finally {
      setBusy(false)
    }
  }

  const running = widget?.running && widget?.task?.replace(/^📱 /, '') === h.title
  const elapsedMin = running ? Math.floor((widget.elapsed_sec ?? 0) / 60) : 0
  const need = info.minutes ?? 25
  const offCamera = !!info.off_camera
  const pr = info.presence   // 在席判定がオンで、ふつうの習慣のときだけ入る
  const prPct = pr && pr.need_min > 0 ? Math.min(100, Math.round(pr.present_min / pr.need_min * 100)) : 0

  return (
    <div className="habit-lock">
      <div className="habit-lock-card">
        <div className="caption">{info.now}　習慣の時間です</div>
        <h1 className="habit-lock-title">いまは「{h.title}」の時間です</h1>
        <div className="habit-lock-sub">
          {h.start}〜{h.end}
          {offCamera ? `（画角外・最低 ${need}分）` : `（${need}分）`}
          {h.record_only && <span className="brief-chip" style={{ marginLeft: 8 }}>記録のみ</span>}
          {h.forced && <span className="brief-chip red" style={{ marginLeft: 8 }}>必須扱い（2日連続未完了）</span>}
        </div>

        {running ? (
          <div className="habit-lock-run">
            ⏱ 計測中 {elapsedMin} 分 / {need} 分
            <div className="habit-lock-bar"><div style={{ width: `${Math.min(100, elapsedMin / need * 100)}%` }} /></div>
            <div className="caption">
              {need}分に達すると自動で完了になります
              {offCamera ? `。${need}分より前に終了すると記録だけ残り、完了にはなりません` : ''}
            </div>
          </div>
        ) : (
          <div className="caption" style={{ marginTop: 10 }}>
            {offCamera
              ? `画角外の習慣です。小窓でタイマーを回し、${need}分以上やってから「終了」を押すと完了になります。`
              : `終わるまでアプリは使えません。小窓でタイマーを回してください（${need}分で自動完了。チェックだけでは完了になりません）。`}
          </div>
        )}

        {pr && (
          <div className="habit-lock-run" style={{ marginTop: 10 }}>
            📷 在席 {pr.present_min} 分 / 必要 {pr.need_min} 分（基準 {pr.rate_min}%）
            <div className="habit-lock-bar"><div style={{ width: `${prPct}%` }} /></div>
            <div className="caption">
              {pr.monitor?.monitor ? '在席判定中。在席の分が必要分に達すると自動で完了になります' : `いまは判定していません（${pr.monitor?.label ?? ''}）`}
            </div>
          </div>
        )}

        <div className="habit-lock-btns">
          {!running && (
            <button className="primary" disabled={busy}
                    onClick={() => run(() => api.widgetStart(h.title), 'タイマー（小窓）で開始しました ⏱')}>
              ⏱ タイマーを開始（デスクトップの小窓）
            </button>
          )}
          {running && offCamera && (
            <button className={elapsedMin >= need ? 'primary' : ''} disabled={busy}
                    title={elapsedMin >= need ? '記録して完了にする' : `まだ ${need - elapsedMin} 分足りません（押すと記録はされますが完了にはなりません）`}
                    onClick={() => run(() => api.widgetStop(), '小窓のタイマーを止めて記録しました')}>
              ■ 終了して記録{elapsedMin < need ? `（あと${need - elapsedMin}分）` : ''}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

export default HabitLock
