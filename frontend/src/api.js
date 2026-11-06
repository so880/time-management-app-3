// バックエンド（FastAPI）との通信をここに集約する。
// データは必ずAPI経由で読み書きする（ブラウザ内には持たない）方針。
// 本体へは Vite の proxy（vite.config.js）が中継するので、URL は同じオリジンの相対パス（/api/...）で書く。
// 本体の番号（8000 など）は画面のコードに書かない。

async function request(path, options = {}) {
  // 退場したタブ（App.jsx の takeover）からは通信しない（裏で動き続けて重くなるのを防ぐ）
  if (window.fcDead) throw new Error('このタブは閉じられました')
  // JSON を送るときだけ Content-Type を付ける（FormData はブラウザが境界つきで付ける）。呼び出し側の headers は足し合わせる
  const headers = { ...(typeof options.body === 'string' ? { 'Content-Type': 'application/json' } : {}),
    ...(options.headers ?? {}) }
  let res
  try {
    res = await fetch(path, { ...options, headers })
  } catch {
    // ネットワークレベルの失敗（バックエンドが起動していない等）
    // → App.jsx がこのイベントを拾って「⚠️ サーバーに接続できていません」バナーを出す
    window.dispatchEvent(new Event('fc-net-down'))
    throw new Error('サーバーに接続できません（start_all.bat を実行してください）')
  }
  if (res.status === 502 || res.status === 504) {
    // 本体が自分で返した 502（Google 連携・AI の失敗）なら理由（detail）が JSON で入っているので、それを表示する
    let detail = null
    try {
      const j = await res.json()
      if (j?.detail) detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
    } catch { /* JSON でない＝ Vite の proxy が返したもの */ }
    if (detail) {
      window.dispatchEvent(new Event('fc-net-up'))
      throw new Error(detail)
    }
    // Vite の proxy は動いているが本体が止まっている
    window.dispatchEvent(new Event('fc-net-down'))
    throw new Error('本体に接続できません（start_all.bat を実行してください）')
  }
  window.dispatchEvent(new Event('fc-net-up'))  // 返事があった＝接続は生きている
  if (!res.ok) {
    // サーバーが返した具体的な理由（detail）があればそれを表示する
    let msg = `APIエラー: ${res.status} ${res.statusText}`
    try {
      const j = await res.json()
      if (j?.detail) msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
    } catch { /* JSONでない場合はそのまま */ }
    throw new Error(msg)
  }
  return res.json()
}

// ---------- 設定 ----------
export const getSettings = () => request('/api/settings')
export const updateSettings = (changes) =>
  request('/api/settings', { method: 'PUT', body: JSON.stringify(changes) })

// ---------- 今日の状態 ----------
export const getState = () => request('/api/state')
export const patchState = (changes) =>
  request('/api/state', { method: 'PATCH', body: JSON.stringify(changes) })

// ---------- 履歴 ----------
export const getLogs = () => request('/api/logs')

// ---------- ゲーム解放 ----------
export const getGameStatus = () => request('/api/game/status')

// ---------- ルーレット ----------
export const rollRoulette = () =>
  request('/api/roulette/roll', { method: 'POST' })
export const chooseTask = (category, task) =>
  request('/api/roulette/choose', {
    method: 'POST',
    body: JSON.stringify({ category, task }),
  })

// ---------- 集中モード ----------
export const finishTask = () => request('/api/task/finish', { method: 'POST' })
export const shortenTask = () => request('/api/task/shorten', { method: 'POST' })
export const sosTask = () => request('/api/task/sos', { method: 'POST' })
export const sosDone = () => request('/api/sos/done', { method: 'POST' })

// ---------- ふりかえり ----------
export const finishReview = (body) =>
  request('/api/review/finish', { method: 'POST', body: JSON.stringify(body) })

// ---------- 背景画像 ----------
export function uploadBackground(file) {
  const form = new FormData()
  form.append('file', file)
  // multipart は Content-Type をブラウザに任せる（request は文字列の body のときだけ JSON 用を付ける）
  return request('/api/background/upload', { method: 'POST', body: form })
}
export const deleteBackground = (fname) =>
  request(`/api/background/${encodeURIComponent(fname)}`, { method: 'DELETE' })

// ---------- 全データリセット ----------
export const resetAll = () => request('/api/reset', { method: 'POST' })

// ---------- ライフ（生活ログ） ----------
export const getBriefing = () => request('/api/briefing')
export const makeAiDayPlan = () =>
  request('/api/briefing/ai_plan', { method: 'POST' })
export const getWeekText = () => request('/api/export/week_text')
export const getStudyAverages = () => request('/api/stats/study_averages')
export const getRecentStats = (days = 14) => request(`/api/stats/recent?days=${days}`)

// ---------- 📋 やること統合（must / habit / periodic） ----------
export const getTodoToday = () => request('/api/todo/today')
export const checkTodo = (itemId, done, level = 'full') =>
  request('/api/todo/check', { method: 'POST', body: JSON.stringify({ item_id: itemId, done, level }) })
// 今日の必須を丸ごと差し替え（1行1件のプレーンテキスト。当日の完了記録は同名なら引き継ぐ）
export const replaceMust = (text) =>
  request('/api/todo/must/replace', {
    method: 'POST', headers: { 'Content-Type': 'text/plain; charset=utf-8' }, body: text,
  })

// 起動時の「今日の必須」入力画面（その日に初めて開いたときだけ。done=true なら出さない）
export const getDaySetup = () => request('/api/todo/day_setup')
// rows: [{title, tag, due, must, asg_id}]（締切が今日・明日・期限切れの行は自動で必須）
// done：起動画面で「✓ 終わった」を押した繰り越し行の key（"m12" / "a5"）
export const confirmDaySetup = (rows, done = []) =>
  request('/api/todo/day_setup', { method: 'POST', body: JSON.stringify({ rows, done }) })
export const getRouletteTags = () => request('/api/assignments/tags')

// ---------- 🔒 サイト制限ゲート（今日のノルマ） ----------
export const getGateStatus = () => request('/api/gate/status')
// 🔐 制限タブ：解除申請（AI審査）・履歴・ブロック記録
export const requestUnlock = (reason, start, end) =>
  request('/api/gate/emergency_unlock', { method: 'POST',
    body: JSON.stringify({ reason, gates: 'game+site', start, end }) })
export const getUnlockLog = () => request('/api/gate/unlock_log')
// 💼 面接などの特例（Claude 審査。2026-11-03）
export const getExemptions = () => request('/api/gate/exemptions')
export const requestExemption = (body) =>
  request('/api/gate/exemption_request', { method: 'POST', body: JSON.stringify(body) })
export const cancelExemption = (id) =>
  request(`/api/gate/exemption_request/${encodeURIComponent(id)}/cancel`, { method: 'POST' })
export const getBlockedLog = () => request('/api/gate/blocked_log')
export const setGateConfig = (body) =>
  request('/api/gate/config', { method: 'POST', body: JSON.stringify(body) })
export const setHabitMinAction = (title, text) =>
  request('/api/habits/min_action', { method: 'PUT', body: JSON.stringify({ title, text }) })

// ---------- 小窓（quick_widget）の再表示 ----------
export const getWidgetStatus = () => request('/api/widget/status')
export const showWidget = () => request('/api/widget/show', { method: 'POST' })
// 小窓にタスク名を渡してタイマーを開始させる（閉じていれば起動して最初の ping で指示）
export const widgetStart = (task) =>
  request('/api/widget/start', { method: 'POST', body: JSON.stringify({ task }) })
// いま取り組むべき習慣（時間帯内・未完了）。habit=null なら無し
export const getCurrentHabit = () => request('/api/todo/current_habit')

// ---------- 習慣 ----------
export const getHabits = () => request('/api/habits')
export const addHabit = (body) =>
  request('/api/habits', { method: 'POST', body: JSON.stringify(body) })
export const deleteHabit = (title) =>
  request(`/api/habits/${encodeURIComponent(title)}`, { method: 'DELETE' })
export const getHabitHistory = (days = 14) => request(`/api/habits/history?days=${days}`)
export const getHabitDailyRates = (days = 7) => request(`/api/habits/daily_rates?days=${days}`)
export const getLifeDay = (date) => request(`/api/life/day?date=${date}`)

export const getSchedule = () => request('/api/life/schedule')
export const addScheduleBlock = (body) =>
  request('/api/life/schedule', { method: 'POST', body: JSON.stringify(body) })
export const updateScheduleBlock = (id, body) =>
  request(`/api/life/schedule/${id}`, { method: 'PUT', body: JSON.stringify(body) })
export const deleteScheduleBlock = (id) =>
  request(`/api/life/schedule/${id}`, { method: 'DELETE' })

export const addLifeEvent = (body) =>
  request('/api/life/events', { method: 'POST', body: JSON.stringify(body) })
export const deleteLifeEvent = (id) =>
  request(`/api/life/events/${id}`, { method: 'DELETE' })
export const toggleLifeEventDone = (id, done) =>
  request(`/api/life/events/${id}/done`, { method: 'POST', body: JSON.stringify({ done }) })

export const addLifeEntry = (body) =>
  request('/api/life/entries', { method: 'POST', body: JSON.stringify(body) })
export const deleteLifeEntry = (id) =>
  request(`/api/life/entries/${id}`, { method: 'DELETE' })

// 休講の切り替え
export const toggleCancellation = (date, blockId) =>
  request('/api/life/cancel_toggle', {
    method: 'POST',
    body: JSON.stringify({ date, block_id: blockId }),
  })

// ---------- 課題（Notion風） ----------
export const getAssignments = () => request('/api/assignments')
export const addAssignment = (body) =>
  request('/api/assignments', { method: 'POST', body: JSON.stringify(body) })
export const updateAssignment = (id, body) =>
  request(`/api/assignments/${id}`, { method: 'PUT', body: JSON.stringify(body) })
export const deleteAssignment = (id) =>
  request(`/api/assignments/${id}`, { method: 'DELETE' })

// 毎週の課題（テンプレート）
export const getRecurringAssignments = () => request('/api/assignments/recurring')
export const addRecurringAssignment = (body) =>
  request('/api/assignments/recurring', { method: 'POST', body: JSON.stringify(body) })
export const updateRecurringAssignment = (id, body) =>
  request(`/api/assignments/recurring/${id}`, { method: 'PUT', body: JSON.stringify(body) })
export const deleteRecurringAssignment = (id) =>
  request(`/api/assignments/recurring/${id}`, { method: 'DELETE' })

// 集計（日次サマリー・週次レポート）
export const getLifeSummary = (date) => request(`/api/life/summary?date=${date}`)
export const getLifeWeek = (date) => request(`/api/life/week?date=${date}`)

// 月カレンダー・曜日振替
export const getLifeCalendar = (month) => request(`/api/life/calendar?month=${month}`)
export const setDayOverride = (body) =>
  request('/api/life/override', { method: 'POST', body: JSON.stringify(body) })

// ---------- 就活（夏インターン・本選考） ----------
export const getJobs = () => request('/api/jobs')
export const addJob = (body) =>
  request('/api/jobs', { method: 'POST', body: JSON.stringify(body) })
export const updateJob = (id, body) =>
  request(`/api/jobs/${id}`, { method: 'PUT', body: JSON.stringify(body) })
export const deleteJob = (id) =>
  request(`/api/jobs/${id}`, { method: 'DELETE' })
export const addJobEvent = (body) =>
  request('/api/jobs/events', { method: 'POST', body: JSON.stringify(body) })
export const deleteJobEvent = (id) =>
  request(`/api/jobs/events/${id}`, { method: 'DELETE' })
export const addJobDoc = (body) =>
  request('/api/jobs/docs', { method: 'POST', body: JSON.stringify(body) })
export const updateJobDoc = (id, body) =>
  request(`/api/jobs/docs/${id}`, { method: 'PUT', body: JSON.stringify(body) })
export const deleteJobDoc = (id) =>
  request(`/api/jobs/docs/${id}`, { method: 'DELETE' })

// Google連携（Apps Script中継）
export const gcalSync = () => request('/api/gcal/sync', { method: 'POST' })
// Googleメインカレンダーの読み取り（表示専用。5分ごとに自動でも行われる）
export const gcalPull = () => request('/api/gcal/pull', { method: 'POST' })
export const gcalStatus = () => request('/api/gcal/status')
export const gcalImportPhone = () =>
  request('/api/gcal/import_phone', { method: 'POST' })

// ---------- 金銭管理（マネー） ----------
export const getMoneyEntries = () => request('/api/money/entries')
export const addMoneyEntry = (body) =>
  request('/api/money/entries', { method: 'POST', body: JSON.stringify(body) })
export const patchMoneyEntry = (id, body) =>
  request(`/api/money/entries/${id}`, { method: 'PATCH', body: JSON.stringify(body) })
export const buyMoneyWish = (id) =>
  request(`/api/money/entries/${id}/buy`, { method: 'POST' })
export const deleteMoneyEntry = (id) =>
  request(`/api/money/entries/${id}`, { method: 'DELETE' })
export const bulkAddMoneyEntries = (items) =>
  request('/api/money/entries/bulk', { method: 'POST', body: JSON.stringify({ items }) })
export const renameMoneyCategory = (oldName, newName) =>
  request('/api/money/categories/rename', {
    method: 'POST', body: JSON.stringify({ old: oldName, new: newName }),
  })
export const importMoneyBackup = (obj) =>
  request('/api/money/backup/import', { method: 'POST', body: JSON.stringify(obj) })
export const exportMoneyBackup = () => request('/api/money/backup/export')
export const resetAmazonEnrichment = () =>
  request('/api/money/amazon/reset', { method: 'POST' })
// 利用通知メールの自動取り込み
export const moneyMailCheck = () =>
  request('/api/money/mail/check', { method: 'POST' })
export const moneyMailStatus = () => request('/api/money/mail/status')
export const moneyMailBackfill = (since) =>
  request('/api/money/mail/backfill', { method: 'POST', body: JSON.stringify({ since }) })

export const moneyAiTest = () => request('/api/money/ai/test', { method: 'POST' })
export const moneyAiJudge = (id) =>
  request(`/api/money/ai/judge/${id}`, { method: 'POST' })
export const moneyAiReview = () => request('/api/money/ai/review', { method: 'POST' })

// ---------- 📷 Webカメラ在席判定・静止画記録（F22・2026-11-01 夜） ----------
export const getPresenceConfig = () => request('/api/presence/config')
export const setPresenceConfig = (body) =>
  request('/api/presence/config', { method: 'POST', body: JSON.stringify(body) })
export const getPresenceDay = (date = '') => request(`/api/presence/day?date=${date}`)
export const getPresenceWeek = (date = '') => request(`/api/presence/week?date=${date}`)
export const getHabitOptions = () => request('/api/presence/habit_options')
export const setHabitOption = (title, offCamera, minMinutes, recordOnly = false, cameraOff = false) =>
  request('/api/presence/habit_options', { method: 'PUT',
    body: JSON.stringify({ title, off_camera: offCamera, min_minutes: minMinutes, record_only: recordOnly, camera_off: cameraOff }) })
export const requestCameraTest = () => request('/api/presence/camera_test', { method: 'POST' })
export const getWebcamDays = () => request('/api/webcam/days')
export const makeWebcamSummary = (date = '') =>
  request('/api/webcam/summary', { method: 'POST', body: JSON.stringify({ date }) })
// 小窓のタイマーを止めて記録させる（画角外の習慣の「終了」ボタン）
export const widgetStop = () => request('/api/widget/stop', { method: 'POST' })
