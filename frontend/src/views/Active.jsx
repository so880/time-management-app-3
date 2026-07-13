// 集中モード（views/active.py の移植）
// - タイマーは start_time(Unix秒) 基準：再読み込みしても継続
// - 気分転換：残り時間カウントダウン表示／勉強：達成まで終了ボタンが出ない
// - 終了時にアラーム（ビープ）＋ブラウザ通知、タブタイトルにも残り時間を表示
// - 没入(コンパクト)モードあり
import { useEffect, useRef, useState } from 'react'
import * as api from '../api.js'
import { notify } from '../components/notify.js'
import Sf6Trainer from '../components/Sf6Trainer.jsx'
import { playBeep, useNow } from '../components/useNow.js'

const SHORT_TASK_THRESHOLD = 40 // config.py と同じ（これ以下(分)は「短い課題」）
const BASE_TITLE = 'Focus & Cafe Roulette'

function fmt(ms) {
  const m = Math.floor(ms / 60000)
  const s = Math.floor((ms % 60000) / 1000)
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

function Active({ state, compactMode, setCompactMode, onStateChange }) {
  const now = useNow(200)
  const playedRef = useRef(false)
  const [busy, setBusy] = useState(false)

  const t = state.current_task
  const showTimer = t?.['カテゴリ'] === '気分転換'
  const isShort = t?.['カテゴリ'] === '勉強' && t?.duration <= SHORT_TASK_THRESHOLD
  const startMs = (state.start_time ?? Date.now() / 1000) * 1000
  const endMs = startMs + (t?.duration ?? 0) * 60000
  const remain = Math.max(0, endMs - now)
  const finished = t ? now >= endMs : false

  // タブタイトル（他の作業中でも残り時間が分かる）
  const title = !t
    ? BASE_TITLE
    : showTimer
      ? (finished ? `⏰ 終了！ | ${BASE_TITLE}` : `☕ ${fmt(remain)} | ${t['タスク']}`)
      : (finished ? `✅ 達成！ | ${BASE_TITLE}` : `📚 集中モード実行中 | ${BASE_TITLE}`)
  useEffect(() => {
    document.title = title
  }, [title])
  useEffect(() => () => { document.title = BASE_TITLE }, []) // 画面を離れたら戻す

  // 終了時刻を過ぎた瞬間に1回だけ：アラーム＋（タブが裏なら）ブラウザ通知
  useEffect(() => {
    if (finished && !playedRef.current) {
      playedRef.current = true
      if (showTimer || !compactMode) playBeep()
      if (document.hidden) {
        notify('⏰ 終了時間です！', t?.['タスク'] ?? '')
      }
    }
  }, [finished, showTimer, compactMode, t])

  if (!t) {
    // タスクが無いのにこの画面に来た場合の保険
    return (
      <div>
        <p>実行中のタスクがありません。</p>
        <button onClick={async () => onStateChange(await api.patchState({ page: 'dashboard' }))}>
          ダッシュボードへ戻る
        </button>
      </div>
    )
  }

  const guard = (fn) => async () => {
    if (busy) return
    setBusy(true)
    try {
      onStateChange(await fn())
    } finally {
      setBusy(false)
    }
  }
  const doFinish = guard(() => api.finishTask())
  const doShorten = guard(() => api.shortenTask())
  const doSos = guard(() => api.sosTask())

  // ===== 没入(コンパクト)モード =====
  if (compactMode) {
    return (
      <div>
        <button className="small" onClick={() => setCompactMode(false)}
                title="終了する場合はここを押して元の画面に戻ってください">
          🗖 拡大表示に戻す
        </button>
        <div className="compact-panel">
          <div className="compact-task">{t['タスク']}</div>
          {showTimer ? (
            finished ? (
              <div className="compact-alarm">⏰ 終了！拡大して記録してください</div>
            ) : (
              <div className="compact-timer">{fmt(remain)}</div>
            )
          ) : finished ? (
            <div className="compact-alarm">✅ 達成！拡大して記録</div>
          ) : (
            <div className="compact-stoic">集中モード実行中...</div>
          )}
        </div>
      </div>
    )
  }

  // ===== 通常表示（フルサイズ） =====
  return (
    <div>
      <button className="small" onClick={() => setCompactMode(true)} title="没入表示（背景メイン）にする">
        🗕
      </button>
      <h1 className="active-title">{t['タスク']}</h1>

      {t['タスク'].includes('スト6') && <Sf6Trainer />}

      {showTimer ? (
        finished ? (
          <div className="alarm-banner">⏰ 終了時間です！</div>
        ) : (
          <div className="timer-big">{fmt(remain)}</div>
        )
      ) : finished ? (
        <div className="timer-done">{'✅ 規定時間が終了しました！\n記録して終了できます。'}</div>
      ) : (
        <div className="timer-stoic">
          {'予定時間: ？？？ 分\n（見事達成するまで終了ボタンは出現しません）'}
        </div>
      )}

      <div className="hr" />

      {isShort && (
        <div className="info-box">
          🟡 これは短い課題です。途中でも『🔁 修了してもう1回抽選』を押せます
          （規定の時間ぶん、もう一度だけ抽選します）。
        </div>
      )}

      <div className="two-btn">
        {/* 勉強は達成まで終了ボタンを出さない（気分転換は常に出す） */}
        {(showTimer || finished) ? (
          <button className="primary" onClick={doFinish} disabled={busy}>
            ■ 終了して記録する
          </button>
        ) : (
          <div />
        )}
        {isShort ? (
          <button onClick={doShorten} disabled={busy}>🔁 修了してもう1回抽選する</button>
        ) : t['カテゴリ'] === '勉強' ? (
          <button onClick={doSos} disabled={busy}>🚨 集中切れ！(SOS)</button>
        ) : (
          <div />
        )}
      </div>

      {/* 短い課題でもSOSは使えるように別行で用意（既存と同じ） */}
      {isShort && (
        <div style={{ marginTop: 12 }}>
          <button style={{ width: '100%' }} onClick={doSos} disabled={busy}>
            🚨 集中切れ！(SOS)
          </button>
        </div>
      )}
    </div>
  )
}

export default Active
