// バックエンド（FastAPI）との通信をここに集約する。
// データは必ずAPI経由で読み書きする（ブラウザ内には持たない）方針。

export const API_BASE = 'http://127.0.0.1:8000'

async function request(path, options = {}) {
  const res = await fetch(API_BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    // サーバーが返した具体的な理由（detail）があればそれを表示する
    let msg = `APIエラー: ${res.status} ${res.statusText}`
    try {
      const j = await res.json()
      if (j?.detail) msg = String(j.detail)
    } catch { /* JSONでない場合はそのまま */ }
    throw new Error(msg)
  }
  return res.json()
}

// ---------- 基本 ----------
export const getHealth = () => request('/api/health')

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
export const addLog = (body) =>
  request('/api/logs', { method: 'POST', body: JSON.stringify(body) })

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
export async function uploadBackground(file) {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(API_BASE + '/api/background/upload', {
    method: 'POST',
    body: form, // multipart は Content-Type をブラウザに任せる
  })
  if (!res.ok) throw new Error(`APIエラー: ${res.status}`)
  return res.json()
}
export const deleteBackground = (fname) =>
  request(`/api/background/${encodeURIComponent(fname)}`, { method: 'DELETE' })

// ---------- 全データリセット ----------
export const resetAll = () => request('/api/reset', { method: 'POST' })

// ---------- ライフ（生活ログ） ----------
export const getBriefing = () => request('/api/briefing')
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

// Google連携（Apps Script中継）
export const gcalSync = () => request('/api/gcal/sync', { method: 'POST' })
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
