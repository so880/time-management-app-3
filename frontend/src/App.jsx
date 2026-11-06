// アプリ本体：初期化 → 背景 → iOS風シェル → 画面ルーティング
// 画面は iOS 風シェル（IosShell：下のタブ5つ＋その他）だけ。全画面（DaySetup/HabitLock）はそのまま。
// 2026-11-06：従来レイアウト（サイドバー＋Dashboard）と切替設定 liquid_glass_enabled を廃止した。
import { useCallback, useEffect, useRef, useState } from 'react'
import * as api from './api.js'
import IosShell from './ios/IosShell.jsx'
import DaySetup from './views/DaySetup.jsx'
import HabitLock from './views/HabitLock.jsx'

function App() {
  const [settings, setSettings] = useState(null)
  const [state, setState] = useState(null)
  const [logs, setLogs] = useState([])
  const [error, setError] = useState(null)
  const [compactMode, setCompactMode] = useState(false)
  const [toast, setToast] = useState(null)
  const [netDown, setNetDown] = useState(false)  // ⚠️ バックエンドに繋がらない状態
  // 起動時の「今日の必須」入力画面（null=未確認、done=false なら全画面で出す）
  const [daySetup, setDaySetup] = useState(null)
  const [setupForced, setSetupForced] = useState(false)  // ?daysetup=1 で開いた画面を確定したら閉じる
  // 習慣の時間帯の全画面ロック（habit が入っていれば表示。30秒ごと＋操作後に再取得）
  const [habitNow, setHabitNow] = useState(null)

  // 前のトーストのタイマーは消してから出す（続けて出したとき、新しい方が早く消えないように）
  const toastTimer = useRef(null)
  const showToast = useCallback((msg) => {
    setToast(msg)
    clearTimeout(toastTimer.current)
    toastTimer.current = setTimeout(() => setToast(null), 2500)
  }, [])

  // 小窓・iPhone・別タブからの記録を、リロードなしで画面に反映する：
  // 30秒ごと＋ウィンドウをアクティブにしたときに state と記録を取り直す
  // （日付が変わったら「今日の必須」入力画面が出るよう day_setup も取り直す）
  useEffect(() => {
    const refresh = () => {
      api.getState().then(setState).catch(() => {})
      api.getLogs().then(setLogs).catch(() => {})
      api.getDaySetup().then(setDaySetup).catch(() => {})
      api.getCurrentHabit().then(setHabitNow).catch(() => {})
    }
    const id = setInterval(refresh, 30000)
    const onVisible = () => { if (document.visibilityState === 'visible') refresh() }
    window.addEventListener('focus', refresh)
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      clearInterval(id)
      window.removeEventListener('focus', refresh)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [])

  // API通信の生死をバナーで見えるようにする（api.js が投げるイベントを拾う）
  useEffect(() => {
    const down = () => setNetDown(true)
    const up = () => setNetDown(false)
    window.addEventListener('fc-net-down', down)
    window.addEventListener('fc-net-up', up)
    return () => {
      window.removeEventListener('fc-net-down', down)
      window.removeEventListener('fc-net-up', up)
    }
  }, [])

  const reloadLogs = useCallback(() => {
    api.getLogs().then(setLogs).catch(() => {})
  }, [])

  // 初期化（init_session 相当：サーバー側で日付またぎリセットも行われる）
  useEffect(() => {
    Promise.all([api.getSettings(), api.getState(), api.getLogs()])
      .then(([s, st, lg]) => {
        setSettings(s)
        setState(st)
        setLogs(lg)
      })
      .catch((e) => setError(e.message))
    // 「今日の必須」入力画面が必要か（取れなければ画面は出さず通常どおり進む）
    api.getDaySetup().then(setDaySetup).catch(() => setDaySetup({ done: true }))
    api.getCurrentHabit().then(setHabitNow).catch(() => {})
  }, [])

  const refreshHabitNow = useCallback(() => {
    api.getCurrentHabit().then(setHabitNow).catch(() => {})
    api.getState().then(setState).catch(() => {})
    window.dispatchEvent(new Event('fc-todo-changed'))
  }, [])

  // 「今日を始める」を押したあと：やること系ウィジェットに再取得を促す
  const finishDaySetup = useCallback((r) => {
    setDaySetup(r)
    setSetupForced(true)
    api.getState().then(setState).catch(() => {})
    window.dispatchEvent(new Event('fc-todo-changed'))
  }, [])

  // 同じアプリのタブを2枚開いてしまったら「古い方」を閉じ、新しく開いたタブを残す。
  // （start_all.bat で開いた最新のタブが必ず使える。古いタブは案内を出して退場）
  // ※以前は新しい方を閉じていたが、「閉じてください」表示の残骸タブまで返事をして
  //   新しいタブを閉じ続ける不具合があったため、方式を逆にした。
  useEffect(() => {
    if (typeof BroadcastChannel === 'undefined') return undefined
    const bc = new BroadcastChannel('focuscafe-tab')
    let closed = false
    const bootAt = Date.now()  // 自分が開いた時刻
    const closeSelf = () => {
      if (closed) return
      closed = true
      bc.close()  // 退場後は一切応答しない（残骸タブが悪さをしない）
      window.close()  // スクリプトから開かれたタブなら閉じられる
      // 閉じられなかった場合の案内（履歴があるタブはブラウザ仕様で閉じられない）
      setTimeout(() => {
        // 2026-11-02：退場したタブが裏で動き続けて重くなるのを止める。
        // 画面を差し替えても React のタイマー（30秒ごとの再取得・1秒ごとの時計など）は生きていたため、
        // 全タイマーを止め、以後の API 通信も api.js 側で止める（fcDead）。環境音の iframe も消える
        window.fcDead = true
        try { window.stop() } catch { /* 無視 */ }
        const last = window.setTimeout(() => {}, 0)
        for (let i = 1; i <= last; i++) { window.clearTimeout(i); window.clearInterval(i) }
        document.body.innerHTML =
          '<div style="display:flex;height:100vh;align-items:center;justify-content:center;' +
          'color:#e8eaed;background:#14181f;font-size:18px;text-align:center;padding:20px">' +
          'このアプリは新しいタブで開き直されました。<br>このタブは閉じてください。</div>'
      }, 400)
    }
    bc.onmessage = (ev) => {
      const d = ev.data
      // 新しいタブから「引き継ぐよ」の合図。開いた時刻を比べて「古い方」が必ず退場する
      // → 同時に2枚開いた場合でも必ず1枚だけが残る（以前の「2秒ルール」では両方残ることがあった）
      if (d && typeof d === 'object' && d.t === 'takeover' && d.boot > bootAt) closeSelf()
    }
    bc.postMessage({ t: 'takeover', boot: bootAt })
    // かなり古いバージョンのコードで開かれたままのタブを退場させる（互換用の合図）
    bc.postMessage('alive')
    return () => { if (!closed) bc.close() }
  }, [])

  // 背景の適用（components/background.py 相当）
  useEffect(() => {
    if (!settings) return
    const mode = settings.bg_mode ?? 'カフェ画像'
    const body = document.body
    if (mode === '黒画面') {
      body.style.backgroundImage = 'none'
      body.style.backgroundColor = '#000000'
    } else if (mode === 'アップロード画像' && settings.bg_current_file) {
      body.style.backgroundImage =
        `url('/bg/${encodeURIComponent(settings.bg_current_file)}')`
      body.style.backgroundColor = '#0e1117'
    } else {
      body.style.backgroundImage = `url('${settings.bg_url ?? ''}')`
      body.style.backgroundColor = '#0e1117'
    }
  }, [settings])

  // リキッドグラス（=iOS風UI）のクラス（index.css の body.liquid-glass 系が使う。従来レイアウト廃止で常に付ける）
  useEffect(() => {
    document.body.classList.add('liquid-glass')
  }, [])

  if (error) {
    return (
      <div style={{ padding: '2rem' }}>
        <h1>☕ Focus &amp; Cafe Roulette</h1>
        <p style={{ color: '#ff5252' }}>
          バックエンドに接続できません：{error}<br />
          start_all.bat を実行してください。
        </p>
      </div>
    )
  }
  if (!settings || !state || daySetup === null) {
    return <div style={{ padding: '2rem' }}>読み込み中…</div>
  }

  // その日に初めて開いたとき：今日の必須を決めるまでアプリは使えない（空でも確定できる）
  // URL に ?daysetup=1 を付けると確定済みでももう一度この画面を開ける（見直し・やり直し用）
  const forceSetup = new URLSearchParams(window.location.search).get('daysetup') === '1'
  if (!daySetup.done || (forceSetup && !setupForced)) {
    return (
      <>
        <DaySetup key={daySetup.date} setup={daySetup} onDone={finishDaySetup} showToast={showToast} />
        {toast && <div className="toast">{toast}</div>}
        {netDown && (
          <div className="net-banner">
            ⚠️ サーバーに接続できていません。start_all.bat が動いているか確認してください
            （復帰すると自動で消えます）
          </div>
        )}
      </>
    )
  }

  // 習慣の時間帯（未完了）：全画面でロック。完了・5分着手・小窓で開始 だけできる
  if (habitNow?.habit) {
    return (
      <>
        <HabitLock key={habitNow.habit.id} info={habitNow} onChanged={refreshHabitNow} showToast={showToast} />
        {toast && <div className="toast">{toast}</div>}
      </>
    )
  }

  return (
    <>
      <IosShell
        settings={settings} state={state} logs={logs}
        compactMode={compactMode} setCompactMode={setCompactMode}
        onSettingsChange={setSettings} onStateChange={setState}
        onLogsChanged={reloadLogs} showToast={showToast}
      />

      {toast && <div className="toast">{toast}</div>}
      {netDown && (
        <div className="net-banner">
          ⚠️ サーバーに接続できていません。start_all.bat が動いているか確認してください
          （復帰すると自動で消えます）
        </div>
      )}
    </>
  )
}

export default App
