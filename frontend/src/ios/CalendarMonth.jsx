// 🗓 月カレンダー（C1）＋ 曜日振替（C2）＋ Google連携設定（C3/C4）
// - 課題の期限・単発予定・授業コマ数・祝日/振替を月表示
// - 日をタップ → 詳細パネル：予定の追加、曜日振替（祝日扱い/◯曜日程）、タイムラインへ
// - ☁️ Google連携：Apps Script経由でGoogleカレンダーに反映（スマホでも見られる）
import { useCallback, useEffect, useState } from 'react'
import * as api from '../api.js'

const DAY_NAMES = ['月', '火', '水', '木', '金', '土', '日']
const CATEGORIES = ['予定', '大学', '生活', '娯楽', '移動', 'その他']

function fmtMonth(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

/* 日詳細パネル内の予定追加ミニフォーム */
function MiniAddEvent({ date, onDone, showToast }) {
  const [title, setTitle] = useState('')
  const [start, setStart] = useState('12:00')
  const [end, setEnd] = useState('13:00')
  const [category, setCategory] = useState('予定')
  return (
    <form className="life-form" onSubmit={async (e) => {
      e.preventDefault()
      if (!title.trim()) return
      await api.addLifeEvent({ date, start, end, title: title.trim(), category })
      setTitle('')
      onDone()
      showToast(`${date} に予定を追加しました ✅`)
    }}>
      <div className="edit-row">
        <input type="time" value={start} onChange={(e) => setStart(e.target.value)} />
        〜
        <input type="time" value={end} onChange={(e) => setEnd(e.target.value)} />
        <select value={category} onChange={(e) => setCategory(e.target.value)}>
          {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>
      <div className="edit-row">
        <input type="text" value={title} onChange={(e) => setTitle(e.target.value)}
               placeholder="予定の名前（例：バイト・美容院）" />
        <button type="submit">➕ 追加</button>
      </div>
    </form>
  )
}

/* ☁️ Google連携の設定 */
function GcalSection({ settings, onSettingsChange, showToast }) {
  const [url, setUrl] = useState(settings.gas_url ?? '')
  const [token, setToken] = useState(settings.gas_token ?? '')
  const [enabled, setEnabled] = useState(!!settings.gcal_enabled)
  const [status, setStatus] = useState(null)
  const [busy, setBusy] = useState(false)

  const refresh = async () => {
    try { setStatus(await api.gcalStatus()) } catch { /* 未接続時は無視 */ }
  }
  useEffect(() => { refresh() }, [])

  const st = status?.status ?? {}
  return (
    <details className="ios-widget" style={{ marginTop: 14 }}>
      <summary className="w-label" style={{ cursor: 'pointer' }}>
        ☁️ Google連携の設定{status?.configured ? '（設定済み）' : ''}
      </summary>
      <div className="caption" style={{ margin: '6px 0' }}>
        予定・授業・課題の期限を <strong>Googleカレンダー（FocusCafeカレンダー）</strong>に反映し、
        スマホでも見られるようにします。iPhoneショートカットからの勉強記録の受け取りも同じ設定です。
        初回のセットアップ手順は <strong>docs/SETUP_GOOGLE_SYNC.md</strong>（約5分）を見てください。
      </div>
      <div className="edit-row">
        <input type="text" placeholder="Apps ScriptのウェブアプリURL（.../exec）" value={url}
               style={{ flex: 1 }} onChange={(e) => setUrl(e.target.value)} autoComplete="off" />
        <input type="password" placeholder="合言葉（トークン）" value={token}
               style={{ width: 160 }} onChange={(e) => setToken(e.target.value)} autoComplete="off" />
        <label><input type="checkbox" checked={enabled}
                      onChange={(e) => setEnabled(e.target.checked)} /> 自動同期</label>
      </div>
      {/* 何をGoogleカレンダーへ送るか（保存後「今すぐ同期」で反映） */}
      <div className="caption" style={{ marginTop: 10 }}>📤 カレンダーに送るもの</div>
      <div className="edit-row" style={{ flexWrap: 'wrap' }}>
        <label>🎓 授業：
          <select value={settings.gcal_class_mode ?? 'summary'}
                  onChange={async (e) => {
                    onSettingsChange(await api.updateSettings({ gcal_class_mode: e.target.value }))
                  }}>
            <option value="summary">1日1件（例：🎓月曜日課・3コマ）</option>
            <option value="detail">コマごと（時間・教室つき）</option>
            <option value="none">送らない</option>
          </select>
        </label>
        {[['gcal_send_events', '📌 予定'],
          ['gcal_send_assignments', '📚 課題の期限'],
          ['gcal_send_board', '📋 課題ボード'],
          ['gcal_send_jobs', '💼 就活']].map(([key, label]) => (
          <label key={key}>
            <input type="checkbox" checked={settings[key] ?? true}
                   onChange={async (e) => {
                     onSettingsChange(await api.updateSettings({ [key]: e.target.checked }))
                   }} /> {label}
          </label>
        ))}
      </div>
      <div className="caption">
        📋 課題ボード＝未完了課題の進捗・期限・メモを「今日」の終日イベント1件にまとめたもの。
        スマホのGoogleカレンダーからいつでも課題の状態を確認できます。
      </div>
      <div className="edit-row">
        <button className="small" onClick={async () => {
          onSettingsChange(await api.updateSettings({
            gas_url: url.trim(), gas_token: token.trim(), gcal_enabled: enabled,
          }))
          showToast('Google連携の設定を保存しました ✅')
          refresh()
        }}>💾 保存</button>
        <button className="small" disabled={busy} onClick={async () => {
          setBusy(true)
          try {
            const r = await api.gcalSync()
            showToast(`📤 ${r.pushed}件を同期しました（${r.range}）`)
            refresh()
          } catch (e) {
            showToast('⚠️ ' + e.message)
          } finally { setBusy(false) }
        }}>{busy ? '同期中…' : '📤 今すぐ同期'}</button>
        <button className="small" onClick={async () => {
          try {
            const r = await api.gcalImportPhone()
            showToast(r.added > 0 ? `📱 スマホの記録を${r.added}件取り込みました` : '📱 新しいスマホ記録はありません')
          } catch (e) { showToast('⚠️ ' + e.message) }
        }}>📱 iPhone記録を取り込む</button>
      </div>
      {(st.last_sync || st.error || st.phone_imported) && (
        <div className={st.error ? 'warn-box' : 'info-box'}>
          {st.error && <div>⚠️ {st.error}</div>}
          {st.last_sync && <div className="caption">最終同期 {st.last_sync}（{st.pushed}件）・以後6時間ごとに自動同期</div>}
          {st.phone_imported && <div className="caption">📱 スマホ記録の最終取り込み {st.phone_imported}（{st.phone_added}件）</div>}
        </div>
      )}
    </details>
  )
}

function CalendarMonth({ onBack, onOpenDay, settings, onSettingsChange, showToast }) {
  const [offset, setOffset] = useState(0)   // 0=今月
  const [data, setData] = useState(null)
  const [sel, setSel] = useState(null)      // 選択中の日付 "YYYY-MM-DD"
  const [selDetail, setSelDetail] = useState(null) // 選択日の詳細（/api/life/day）

  // 日付を選ぶと、その日の時間割・予定・実績を時刻順の一覧で見られるようにする
  useEffect(() => {
    setSelDetail(null)
    if (!sel) return
    let alive = true
    api.getLifeDay(sel).then((d) => { if (alive) setSelDetail(d) }).catch(() => {})
    return () => { alive = false }
  }, [sel])

  const base = new Date()
  base.setDate(1)
  base.setMonth(base.getMonth() + offset)
  const month = fmtMonth(base)
  const todayStr = new Date().toLocaleDateString('sv-SE') // YYYY-MM-DD

  const reload = useCallback(() => {
    api.getLifeCalendar(month).then(setData).catch(() => {})
  }, [month])
  useEffect(() => { reload(); setSel(null) }, [reload])

  const days = data?.days ?? []
  const lead = days.length ? days[0].weekday : 0  // 月曜=0 起点の空白数
  const selDay = days.find((d) => d.date === sel)

  const setOverride = async (mode, weekday = null) => {
    await api.setDayOverride({ date: sel, mode, weekday })
    reload()
    showToast(mode === 'clear' ? '振替を取り消しました' : '曜日振替を設定しました ✅（Googleカレンダーは「今すぐ同期」で反映）')
  }

  return (
    <div className="page-anim">
      <button type="button" className="ios-back" onClick={onBack}>‹ ライフ</button>
      <h2 className="ios-section-title">
        <span className="r-icon" style={{ background: '#FF3B30' }}>🗓</span>
        カレンダー
      </h2>

      <div className="life-datenav">
        <button className="small" onClick={() => setOffset(offset - 1)}>‹ 前月</button>
        <div className="life-date">{base.getFullYear()}年{base.getMonth() + 1}月{offset === 0 ? '・今月' : ''}</div>
        <button className="small" onClick={() => setOffset(offset + 1)}>翌月 ›</button>
        {offset !== 0 && <button className="small" onClick={() => setOffset(0)}>今月へ</button>}
      </div>

      {/* 月グリッド */}
      <div className="cal-grid">
        {DAY_NAMES.map((dn, i) => (
          <div key={dn} className={'cal-head' + (i === 5 ? ' sat' : i === 6 ? ' sun' : '')}>{dn}</div>
        ))}
        {Array.from({ length: lead }, (_, i) => <div key={`b${i}`} className="cal-cell blank" />)}
        {days.map((d) => {
          const dayNum = parseInt(d.date.slice(8), 10)
          const red = d.weekday === 6 || d.is_holiday
          const undone = d.assignments.filter((a) => !a.done)
          return (
            <button key={d.date} type="button"
                    className={'cal-cell'
                      + (d.date === todayStr ? ' today' : '')
                      + (d.date === sel ? ' sel' : '')}
                    onClick={() => setSel(d.date === sel ? null : d.date)}>
              <span className={'cal-num' + (red ? ' sun' : d.weekday === 5 ? ' sat' : '')}>
                {dayNum}
              </span>
              {d.holiday_name && <span className="cal-holiday">{d.holiday_name}</span>}
              {d.override && (
                <span className="cal-ov">
                  {d.override.mode === 'holiday' ? '休' : `${DAY_NAMES[d.override.weekday]}曜`}
                </span>
              )}
              {d.class_count > 0 && <span className="cal-class">🎓{d.class_count}</span>}
              {undone.slice(0, 2).map((a) => (
                <span key={a.id} className="cal-asg">📚{a.title}</span>
              ))}
              {undone.length > 2 && <span className="cal-more">他{undone.length - 2}件</span>}
              {d.events.slice(0, 2).map((ev) => (
                <span key={ev.id} className="cal-ev">📌{ev.title}</span>
              ))}
              {(d.jobs ?? []).slice(0, 2).map((j) => (
                <span key={'j' + j.id} className="cal-job">💼{j.company}</span>
              ))}
            </button>
          )
        })}
      </div>

      {/* 日詳細パネル */}
      {selDay && (
        <div className="ios-widget" style={{ marginTop: 12 }}>
          <div className="w-label">
            {parseInt(sel.slice(5, 7), 10)}月{parseInt(sel.slice(8), 10)}日（{DAY_NAMES[selDay.weekday]}）
            {selDay.holiday_name && ` 🎌 ${selDay.holiday_name}`}
            {selDay.effective_weekday !== selDay.weekday &&
              ` → ${DAY_NAMES[selDay.effective_weekday]}曜日程で動作`}
          </div>

          {/* この日の一覧（時間割・予定・実績・勉強を時刻順にまとめて表示） */}
          {!selDetail && <div className="caption">読み込み中…</div>}
          {selDetail && (() => {
            const items = [
              ...(selDetail.schedule ?? []).map((b) => ({ ...b, _k: 'sch' })),
              ...(selDetail.events ?? []).map((e) => ({ ...e, _k: 'ev' })),
              ...(selDetail.entries ?? []).map((e) => ({ ...e, _k: 'en' })),
              ...(selDetail.study ?? []).map((s, i) => ({ ...s, id: 's' + i, _k: 'st' })),
            ].sort((a, b) => (a.start ?? '').localeCompare(b.start ?? ''))
            if (items.length === 0) {
              return <div className="caption">この日の予定・記録はまだありません。</div>
            }
            const CHIP = {
              sch: ['🎓', '#007AFF', '時間割'], ev: ['📌', '#AF52DE', '予定'],
              en: ['📝', '#34C759', '実績'], st: ['📖', '#4CAF50', '勉強'],
            }
            return items.map((it) => {
              const [icon, color, label] = CHIP[it._k]
              return (
                <div className="edit-row" key={it._k + it.id}>
                  <span className="life-time">{it.start}〜{it.end}</span>
                  <span style={{ flex: 1, textDecoration: it.cancelled ? 'line-through' : 'none' }}>
                    {icon} {it.title}
                    {it.room && <span className="caption">　🏫 {it.room}</span>}
                    {it.note && <span className="caption">　📝 {it.note}</span>}
                    {it.cancelled && <span className="caption">　休講</span>}
                  </span>
                  <span className="life-chip" style={{ borderColor: color, background: color + '33' }}>
                    {label}
                  </span>
                  {it._k === 'ev' && (
                    <button className="icon" onClick={async () => {
                      await api.deleteLifeEvent(it.id)
                      reload()
                      setSelDetail(await api.getLifeDay(sel))
                    }}>🗑</button>
                  )}
                </div>
              )
            })
          })()}

          {/* 課題の期限・就活の日程 */}
          {selDay.assignments.map((a) => (
            <div className="edit-row" key={a.id}>
              <span>📚 {a.title}</span>
              <span className="caption">{a.done ? '✅ 完了' : `進捗 ${a.progress}%`}</span>
            </div>
          ))}
          {(selDay.jobs ?? []).map((j) => (
            <div className="edit-row" key={'j' + j.id}>
              <span style={{ flex: 1 }}>💼 {j.company} {j.label}</span>
              <span className="caption">
                優先{j.priorityLabel}{j.start ? `・${j.start}〜${j.end}` : ''}
              </span>
            </div>
          ))}

          {/* 曜日振替（祝日・臨時休講・振替授業の日） */}
          <div className="edit-row" style={{ marginTop: 8 }}>
            <span className="caption">🔀 この日の日程：</span>
            <select
              value={selDay.override ? (selDay.override.mode === 'holiday' ? 'holiday' : `wd${selDay.override.weekday}`) : 'normal'}
              onChange={(e) => {
                const v = e.target.value
                if (v === 'normal') setOverride('clear')
                else if (v === 'holiday') setOverride('holiday')
                else setOverride('weekday', parseInt(v.slice(2), 10))
              }}>
              <option value="normal">カレンダーどおり{selDay.is_holiday ? '（祝日＝休み扱い）' : ''}</option>
              <option value="holiday">休み扱い（授業なし）</option>
              {DAY_NAMES.map((dn, i) => (
                <option key={i} value={`wd${i}`}>{dn}曜日の日程にする</option>
              ))}
            </select>
          </div>

          <MiniAddEvent date={sel} showToast={showToast}
                        onDone={async () => {
                          reload()
                          try { setSelDetail(await api.getLifeDay(sel)) } catch { /* 表示は次回選択時に更新 */ }
                        }} />

          <button className="small" style={{ marginTop: 6 }}
                  onClick={() => onOpenDay(sel)}>
            📊 この日のタイムラインを見る
          </button>
        </div>
      )}

      {/* ☁️ Google連携 */}
      <GcalSection settings={settings} onSettingsChange={onSettingsChange} showToast={showToast} />
    </div>
  )
}

export default CalendarMonth
