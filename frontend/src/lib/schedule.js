// 時間割（settings.daily_routine）から今日の「勉強できる時間帯」を求める（2026-11-06：旧 views/Dashboard.jsx から移動）
// 従来レイアウト（サイドバー＋Dashboard）を廃止したため、iOS版ホーム（ios/HomeIos.jsx）が使うこの関数だけを残した。

// 今日の「勉強できる時間帯」を [開始ms, 終了ms] のリストにする（既存 today_intervals_ms と同じ）
export function todayIntervalsMs(settings) {
  const routine = settings.daily_routine ?? []
  const jsDay = new Date().getDay() // 日=0 ... 土=6
  const wd = (jsDay + 6) % 7        // 月=0 ... 日=6（既存Pythonの weekday() に合わせる）
  const blocks = routine[wd] ?? []
  const out = []
  for (const b of blocks) {
    try {
      const [sh, sm] = String(b.start ?? '09:00').split(':').map(Number)
      const [eh, em] = String(b.end ?? '22:00').split(':').map(Number)
      const s = new Date(); s.setHours(sh, sm, 0, 0)
      const e = new Date(); e.setHours(eh, em, 0, 0)
      if (e > s) out.push([s.getTime(), e.getTime()])
    } catch { /* 形式が壊れた行は無視 */ }
  }
  return out
}
