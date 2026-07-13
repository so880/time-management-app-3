// SOS（views/sos.py の移植）：5分タイマー＋アラーム＋ブラウザ通知
// 既存と同じく sessionStorage を使う（開始時刻の保持のみ。データは持たない）
import { useEffect, useRef } from 'react'
import * as api from '../api.js'
import { notify } from '../components/notify.js'
import { playBeep, useNow } from '../components/useNow.js'

const SOS_MS = 5 * 60 * 1000
const BASE_TITLE = 'Focus & Cafe Roulette'

function Sos({ state, onStateChange }) {
  const now = useNow(250)
  const playedRef = useRef(false)

  if (!sessionStorage.getItem('sosStart')) {
    sessionStorage.setItem('sosStart', String(Date.now()))
  }
  const end = parseInt(sessionStorage.getItem('sosStart'), 10) + SOS_MS
  const rem = Math.max(0, end - now)
  const over = now >= end

  const m = String(Math.floor(rem / 60000)).padStart(2, '0')
  const s = String(Math.floor((rem % 60000) / 1000)).padStart(2, '0')

  // タブタイトルにも残り時間を表示
  const title = over ? `⏰ 戻りましょう | ${BASE_TITLE}` : `⛑ ${m}:${s} SOS休憩 | ${BASE_TITLE}`
  useEffect(() => {
    document.title = title
  }, [title])
  useEffect(() => () => { document.title = BASE_TITLE }, [])

  useEffect(() => {
    if (over && !playedRef.current && !sessionStorage.getItem('sosPlayed')) {
      playedRef.current = true
      sessionStorage.setItem('sosPlayed', 'true')
      playBeep()
      if (document.hidden) {
        notify('⏰ 5分経過！', 'そろそろ机に戻りましょう')
      }
    }
  }, [over])

  const back = async () => {
    sessionStorage.removeItem('sosStart')
    sessionStorage.removeItem('sosPlayed')
    onStateChange(await api.sosDone())
  }

  return (
    <div className={over ? 'sos-flash' : ''} style={{ borderRadius: 12, padding: 8 }}>
      <div className="warn-box">
        集中力が切れましたね。自分を責めず、一旦リセットしましょう！（5分間だけ）
      </div>
      <h2 style={{ textAlign: 'center' }}>緊急指令：【{state.sos_task ?? ''}】</h2>
      <div style={{ textAlign: 'center', marginTop: 10 }}>
        {over ? (
          <div className="sos-alarm">⏰ 5分経過！そろそろ机に戻りましょう</div>
        ) : (
          <div className="sos-timer">{m}:{s}</div>
        )}
      </div>
      <div style={{ marginTop: 16 }}>
        <button style={{ width: '100%' }} onClick={back}>ダッシュボードへ戻る</button>
      </div>
    </div>
  )
}

export default Sos
