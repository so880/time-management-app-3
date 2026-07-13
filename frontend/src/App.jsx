// アプリ本体（app.py の移植）：初期化 → 背景 → シェル選択 → 画面ルーティング
// リキッドグラスON時は iOS風シェル（タブバー）、OFF時は従来レイアウト（サイドバー）。
import { useCallback, useEffect, useState } from 'react'
import * as api from './api.js'
import Sidebar from './components/Sidebar.jsx'
import IosShell from './ios/IosShell.jsx'
import Active from './views/Active.jsx'
import Dashboard from './views/Dashboard.jsx'
import EditPanel from './views/EditPanel.jsx'
import Review from './views/Review.jsx'
import Sos from './views/Sos.jsx'

function App() {
  const [settings, setSettings] = useState(null)
  const [state, setState] = useState(null)
  const [logs, setLogs] = useState([])
  const [error, setError] = useState(null)
  const [appMode, setAppMode] = useState('use')       // 集中/編集（既存も非永続）
  const [compactMode, setCompactMode] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [toast, setToast] = useState(null)

  const showToast = useCallback((msg) => {
    setToast(msg)
    setTimeout(() => setToast(null), 2500)
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
        `url('${api.API_BASE}/bg/${encodeURIComponent(settings.bg_current_file)}')`
      body.style.backgroundColor = '#0e1117'
    } else {
      body.style.backgroundImage = `url('${settings.bg_url ?? ''}')`
      body.style.backgroundColor = '#0e1117'
    }
  }, [settings])

  // リキッドグラス（=iOS風UI）のクラス切替
  useEffect(() => {
    document.body.classList.toggle('liquid-glass', !!settings?.liquid_glass_enabled)
  }, [settings])

  if (error) {
    return (
      <div style={{ padding: '2rem' }}>
        <h1>☕ Focus &amp; Cafe Roulette</h1>
        <p style={{ color: '#ff5252' }}>
          バックエンドに接続できません：{error}<br />
          start_backend.bat が起動しているか確認してください。
        </p>
      </div>
    )
  }
  if (!settings || !state) {
    return <div style={{ padding: '2rem' }}>読み込み中…</div>
  }

  const ios = !!settings.liquid_glass_enabled
  const page = state.page ?? 'dashboard'
  const hideSidebar = page === 'active' && compactMode

  return (
    <>
      {ios ? (
        /* ===== iOS風シェル（リキッドグラスON） ===== */
        <IosShell
          settings={settings} state={state} logs={logs}
          compactMode={compactMode} setCompactMode={setCompactMode}
          onSettingsChange={setSettings} onStateChange={setState}
          onLogsChanged={reloadLogs} showToast={showToast}
        />
      ) : (
        /* ===== 従来レイアウト（サイドバー） ===== */
        <div className="app-root">
          {!sidebarOpen && !hideSidebar && (
            <div className="sidebar-strip" title="クリックでサイドバーを開く"
                 onClick={() => setSidebarOpen(true)} />
          )}

          {!hideSidebar && (
            <aside className={'sidebar' + (sidebarOpen ? '' : ' closed')}
                   onClick={(e) => {
                     if (e.target.closest('button, a, input, textarea, select, label, summary, details, iframe')) return
                     setSidebarOpen(false)
                   }}>
              <Sidebar
                settings={settings} logs={logs}
                appMode={appMode} setAppMode={setAppMode}
                onSettingsChange={setSettings} onStateChange={setState}
                onLogsChanged={reloadLogs} showToast={showToast}
              />
            </aside>
          )}

          <main className="main-area">
            <div className={'block-container' + (hideSidebar ? ' compact' : '')}>
              <div key={page + '-' + appMode} className="page-anim">
              {page === 'active' ? (
                <Active state={state} compactMode={compactMode}
                        setCompactMode={setCompactMode} onStateChange={setState} />
              ) : page === 'review' ? (
                <Review state={state} onStateChange={setState} onLogsChanged={reloadLogs} />
              ) : page === 'sos' ? (
                <Sos state={state} onStateChange={setState} />
              ) : appMode === 'edit' ? (
                <div>
                  <h1>☕ Focus &amp; Cafe Roulette</h1>
                  <EditPanel settings={settings} onSettingsChange={setSettings} showToast={showToast} />
                </div>
              ) : (
                <Dashboard settings={settings} state={state}
                           onStateChange={setState} showToast={showToast} />
              )}
              </div>
            </div>
          </main>
        </div>
      )}

      {toast && <div className="toast">{toast}</div>}
    </>
  )
}

export default App
