// 🔁 習慣パネル（編集タブ）
// - 習慣の登録：名前＋時間＋曜日（複数選択）→ 時間割（category=習慣）として自動登録
//   → タイムライン・カレンダー・ホームの「いまの予定」に自動で出る
// - 今日のチェックリスト＋7日/30日の達成率バー
// - 通知：開始5分前と開始時刻にブラウザ通知（マナーモードで一時停止できる）
import { useEffect, useRef, useState } from 'react'
import * as api from '../api.js'

const DAY_NAMES = ['月', '火', '水', '木', '金', '土', '日']

function RateBar({ label, rate }) {
  return (
    <div className="habit-rate">
      <span className="habit-rate-label">{label}</span>
      <div className="habit-rate-track">
        <div className="habit-rate-fill"
             style={{ width: `${rate.rate ?? 0}%`,
                      background: (rate.rate ?? 0) >= 70 ? '#4CAF50' : (rate.rate ?? 0) >= 40 ? '#FF9F0A' : '#FF6B62' }} />
      </div>
      <span className="habit-rate-val">
        {rate.rate == null ? '—' : `${rate.rate}%（${rate.done}/${rate.expected}日）`}
      </span>
    </div>
  )
}

// 🔒 解放ゲートの設定（制限キーワード・必須タスク・週単位タスク・今週の3つ）
function GateSettings({ showToast }) {
  const [gate, setGate] = useState(null)
  const [kw, setKw] = useState('')
  const [reqText, setReqText] = useState('')
  const [periodicText, setPeriodicText] = useState('')  // 1行1つ「タイトル,日数」
  const [kbText, setKbText] = useState('')

  const load = () => api.getGateStatus().then((g) => {
    setGate(g)
    setReqText(g.required.map((t) => t.title).join('\n'))
    setPeriodicText((g.periodic ?? []).map((p) => `${p.title},${p.everyDays}`).join('\n'))
    setKbText(g.keyboardWeekly ?? '')
  }).catch(() => {})
  useEffect(() => { load() }, [])

  if (!gate) return null
  const lines = (s) => s.split('\n').map((x) => x.trim()).filter(Boolean)
  // 「タイトル,日数」→ {title, every_days}（日数が無い/不正なら 0＝不定期）
  const parsePeriodic = (s) => lines(s).map((line) => {
    const i = line.lastIndexOf(',')
    if (i < 0) return { title: line, every_days: 0 }
    const n = parseInt(line.slice(i + 1).trim(), 10)
    return { title: line.slice(0, i).trim(), every_days: Number.isNaN(n) ? 0 : Math.max(0, n) }
  }).filter((p) => p.title)

  return (
    <details className="ios-widget" style={{ marginTop: 14 }} open>
      <summary className="w-label" style={{ cursor: 'pointer' }}>
        🔒 解放条件の設定{gate.enabled ? '' : '（サイト制限オフ）'}
      </summary>
      <div className="caption" style={{ margin: '6px 0' }}>
        「必須タスク」と「今日の習慣」がすべて完了するとサイト制限が解除されます。
        ゲームはこれに加えて勉強目標の達成と 07:00〜21:00（固定）が必要です。習慣はタイマー（規定時間以上）か
        📷在席率でだけ完了になります。制限中は、制限を弱める変更（オフ・一覧からの削除）はできません。
      </div>
      <div className="edit-row">
        <label>
          <input type="checkbox" checked={gate.enabled}
                 onChange={async (e) => {
                   try { setGate(await api.setGateConfig({ enabled: e.target.checked })) }
                   catch (err) { showToast('⚠️ ' + err.message) }
                 }} />
          サイト制限を使う
        </label>
      </div>

      <div className="caption" style={{ marginTop: 8 }}>🚫 制限キーワード（ウィンドウタイトルで判定・タップで削除）</div>
      <div className="job-chip-row">
        {gate.keywords.map((k) => (
          <button key={k} type="button" className="sort-chip"
                  onClick={async () => {
                    try { setGate(await api.setGateConfig({ keywords: gate.keywords.filter((x) => x !== k) })) }
                    catch (e) { showToast('⚠️ ' + e.message) }
                  }}>{k} ✕</button>
        ))}
      </div>
      <div className="edit-row">
        <input type="text" value={kw} placeholder="追加するキーワード（例: YouTube）"
               onChange={(e) => setKw(e.target.value)} />
        <button type="button" className="small" onClick={async () => {
          if (!kw.trim()) return
          try {
            setGate(await api.setGateConfig({ keywords: [...gate.keywords, kw.trim()] }))
            setKw('')
          } catch (e) { showToast('⚠️ ' + e.message) }
        }}>＋ 追加</button>
      </div>

      <div className="caption" style={{ marginTop: 10 }}>
        🔴 今日の必須（1行に1つ・先頭に記号なし。「今日の必須を差し替え」で当日分を丸ごと入れ替え。
        同じタイトルの完了記録は引き継がれます。翌日には繰り越しません）
      </div>
      <div className="edit-row">
        <textarea rows={5} value={reqText} onChange={(e) => setReqText(e.target.value)}
                  placeholder={'就活の返信・回答の未処理をゼロにする\n当日締切のES・申請の提出\n面接・面談の前日準備'} />
      </div>
      <div className="edit-row">
        <button type="button" className="small" onClick={async () => {
          try {
            await api.replaceMust(reqText)
            showToast('今日の必須を差し替えました 🔴')
            load()
          } catch (e) { showToast('⚠️ ' + e.message) }
        }}>🔴 今日の必須を差し替え</button>
      </div>
      <div className="caption">📅 週単位・不定期タスク（1行に「タイトル,日数」。0=不定期。記録のみで解放条件には入らない）</div>
      <div className="edit-row">
        <textarea rows={3} value={periodicText} onChange={(e) => setPeriodicText(e.target.value)}
                  placeholder={'就活メールの棚卸し,3\n秋冬インターン締切チェック,7\nGitHub app-3更新,0'} />
      </div>
      <div className="caption">⌨️ キーボード操作「今週の3つ」（メモ。ホームのノルマに表示）</div>
      <div className="edit-row">
        <input type="text" value={kbText} placeholder="例：Ctrl+E / Alt+Tab / Win+V"
               onChange={(e) => setKbText(e.target.value)} style={{ flex: 1 }} />
      </div>
      <div className="edit-row">
        <button type="button" className="small" onClick={async () => {
          try {
            setGate(await api.setGateConfig({
              periodic: parsePeriodic(periodicText), keyboardWeekly: kbText,
            }))
            showToast('週単位タスク・今週の3つを保存しました 🔒')
          } catch (e) { showToast('⚠️ ' + e.message) }
        }}>💾 週単位・今週の3つを保存</button>
      </div>
    </details>
  )
}

// 完了時刻のずれの表示（予定19:00に対して19:05なら「＋5分」）
function fmtDiff(diffMin) {
  if (diffMin == null) return ''
  if (diffMin === 0) return 'ぴったり'
  return diffMin > 0 ? `＋${diffMin}分` : `−${-diffMin}分`
}

// part（2026-11-01 夜）: 'habits'=習慣の登録と達成率 / 'gate'=制限の設定（GateSettings） / 'notify'=通知だけ（画面なし）
// 省略時は従来どおり両方（従来レイアウトの編集モード用）
function HabitPanel({ settings, onSettingsChange, showToast, part = 'all' }) {
  const [habits, setHabits] = useState([])
  const [history, setHistory] = useState({})   // 習慣名 → 完了時刻の履歴（直近14日）
  const [form, setForm] = useState({ title: '', start: '19:00', end: '19:30', weekdays: [] })
  const firedRef = useRef(new Set())   // 同じ通知を2回出さないための記録

  const notifyOn = settings.habit_notify ?? true
  const silent = !!settings.habit_silent   // マナーモード

  const reload = () => {
    api.getHabits().then(setHabits).catch(() => {})
    api.getHabitHistory(14).then(setHistory).catch(() => {})
  }
  useEffect(() => { reload() }, [])

  const saveSetting = async (changes) => {
    onSettingsChange(await api.updateSettings(changes))
  }

  // ---- 通知：開始5分前＆開始時刻（1分ごとに判定。タブが開いている間動く） ----
  useEffect(() => {
    if (!notifyOn || silent) return undefined
    const tick = async () => {
      let brief
      try { brief = await api.getBriefing() } catch { return }
      const now = new Date()
      const nowMin = now.getHours() * 60 + now.getMinutes()
      const today = brief.date
      for (const b of brief.timetable ?? []) {
        if (b.category !== '習慣') continue
        const [h, m] = b.start.split(':').map(Number)
        const startMin = h * 60 + m
        const diff = startMin - nowMin
        const stage = diff === 5 ? 'pre' : diff === 0 ? 'now' : null
        if (!stage) continue
        const key = `${today}|${b.start}|${b.title}|${stage}`
        if (firedRef.current.has(key)) continue
        firedRef.current.add(key)
        if (Notification.permission === 'granted') {
          new Notification(
            stage === 'pre' ? `🔁 5分後に「${b.title}」` : `🔁 「${b.title}」の時間です`,
            { body: `${b.start}〜${b.end}${stage === 'now' ? '　小窓でタイマーを回すと自動で完了になります' : ''}` })
        }
      }
    }
    tick()
    const id = setInterval(tick, 60000)
    return () => clearInterval(id)
  }, [notifyOn, silent])

  const toggleNotify = async (on) => {
    if (on && Notification.permission !== 'granted') {
      const p = await Notification.requestPermission()
      if (p !== 'granted') {
        showToast('ブラウザの通知が許可されていません')
        return
      }
    }
    saveSetting({ habit_notify: on })
  }

  const toggleWd = (wd) => {
    setForm((f) => ({
      ...f,
      weekdays: f.weekdays.includes(wd)
        ? f.weekdays.filter((x) => x !== wd)
        : [...f.weekdays, wd],
    }))
  }

  const add = async (e) => {
    e.preventDefault()
    try {
      await api.addHabit(form)
      setForm({ title: '', start: form.start, end: form.end, weekdays: [] })
      reload()
      showToast('習慣を登録しました 🔁（時間割・カレンダーにも反映）')
    } catch (err) { showToast(String(err.message || err)) }
  }

  const todays = habits.filter((h) => h.dueToday)

  if (part === 'notify') return null          // 通知の useEffect だけ動かす（IosShell が常時マウント）
  if (part === 'gate') return <GateSettings showToast={showToast} />

  return (
    <>
    <details className="ios-widget" style={{ marginTop: part === 'habits' ? 0 : 14 }} open>
      <summary className="w-label" style={{ cursor: 'pointer' }}>
        🔁 習慣（{habits.length}件）
      </summary>

      {/* 通知の設定 */}
      <div className="edit-row" style={{ marginTop: 8 }}>
        <label>
          <input type="checkbox" checked={notifyOn}
                 onChange={(e) => toggleNotify(e.target.checked)} /> 🔔 開始5分前と開始時刻に通知
        </label>
        <label title="オンの間は通知を出しません（設定は消えません）">
          <input type="checkbox" checked={silent}
                 onChange={(e) => saveSetting({ habit_silent: e.target.checked })} /> 🔕 マナーモード
        </label>
      </div>
      {silent && <div className="caption">マナーモード中：通知は出ません</div>}

      {/* 今日のチェックリスト */}
      {todays.length > 0 && (
        <div className="habit-today">
          <div className="caption">✅ 今日の習慣（完了は自己申告ではなく、時間帯の長さ以上タイマーで計測したとき、または📷在席率が基準以上のときだけ）</div>
          {todays.map((h) => (
            <div key={h.id ?? h.title} className="habit-check-row" style={{ cursor: 'default' }}>
              <span style={{ width: 24, textAlign: 'center' }}>{h.checkedToday ? '✅' : '⬜'}</span>
              <span className={h.checkedToday ? 'habit-done' : ''} style={{ flex: 1 }}>
                {h.title}
                <span className="caption">　{Object.values(h.times)[0]}</span>
                {h.record_only && <span className="brief-chip">記録のみ</span>}
                {h.forced && <span className="brief-chip red">必須扱い（2日連続未完了）</span>}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* 一覧と達成率 */}
      {habits.map((h) => (
        <div key={h.title} className="habit-row">
          <div className="habit-head">
            <strong>{h.title}</strong>
            <span className="caption">
              {h.weekdays.map((w) => DAY_NAMES[w]).join('・')}曜
              ／{[...new Set(Object.values(h.times))].join(' / ')}
            </span>
            <button type="button" className="icon" onClick={async () => {
              if (!window.confirm(`習慣「${h.title}」を削除しますか？（時間割からも消えます）`)) return
              // 制限中は本体が 423 で断るので、その理由を見えるようにする
              try {
                await api.deleteHabit(h.title)
                reload()
              } catch (e) { showToast('⚠️ ' + e.message) }
            }}>🗑</button>
          </div>
          {/* 「最小単位」メモ（空欄なら未設定。ロック画面などの表示用） */}
          <div className="edit-row">
            <span className="caption" style={{ whiteSpace: 'nowrap' }}>最小単位</span>
            <input type="text" defaultValue={h.minAction || ''} style={{ flex: 1 }}
                   placeholder="例：問題を1問だけ解く（5分）"
                   onBlur={async (e) => {
                     if (e.target.value.trim() === (h.minAction || '')) return
                     await api.setHabitMinAction(h.title, e.target.value)
                     reload()
                     showToast('最小単位を保存しました')
                   }} />
          </div>
          <RateBar label="7日" rate={h.rate7} />
          <RateBar label="30日" rate={h.rate30} />
          {/* ⏰ 完了時刻の履歴：予定どおりの時間にできているかを確認できる */}
          {(history[h.title] ?? []).length > 0 && (
            <details className="habit-history">
              <summary className="caption" style={{ cursor: 'pointer' }}>
                ⏰ 完了時刻の履歴（直近14日）
              </summary>
              {(history[h.title] ?? []).slice(0, 14).map((r) => (
                <div key={r.date} className="caption" style={{ paddingLeft: 12 }}>
                  {r.date.slice(5).replace('-', '/')}
                  {r.at ? `✅ ${r.at}に完了` : '✅ 完了（時刻の記録なし）'}
                  {r.planned && `（予定 ${r.planned}${r.diffMin != null ? `・${fmtDiff(r.diffMin)}` : ''}）`}
                </div>
              ))}
            </details>
          )}
        </div>
      ))}
      {habits.length === 0 && (
        <div className="caption" style={{ margin: '8px 0' }}>
          まだ習慣がありません。下のフォームから登録すると、時間割・カレンダー・
          ホームの「いまの予定」・通知の対象に自動でなります。
        </div>
      )}

      {/* 追加フォーム */}
      <form onSubmit={add} className="life-form" style={{ marginTop: 10 }}>
        <div className="edit-row">
          <input type="text" value={form.title} placeholder="習慣の名前（例：筋トレ）"
                 onChange={(e) => setForm({ ...form, title: e.target.value })} />
          <input type="time" value={form.start}
                 onChange={(e) => setForm({ ...form, start: e.target.value })} />
          〜
          <input type="time" value={form.end}
                 onChange={(e) => setForm({ ...form, end: e.target.value })} />
        </div>
        <div className="edit-row" style={{ flexWrap: 'wrap' }}>
          {DAY_NAMES.map((dn, wd) => (
            <button key={dn} type="button"
                    className={'sort-chip' + (form.weekdays.includes(wd) ? ' on' : '')}
                    onClick={() => toggleWd(wd)}>{dn}</button>
          ))}
          <button type="submit">➕ 習慣を登録</button>
        </div>
      </form>
    </details>

    {/* 🔒 サイト制限の設定（従来レイアウトでは習慣の下に続けて表示。新しい画面では「その他 › 制限の設定」） */}
    {part === 'all' && <GateSettings showToast={showToast} />}
    </>
  )
}

export default HabitPanel
