// 🗓 月カレンダー（C1）＋ 曜日振替（C2）＋ Google連携設定（C3/C4）
// - 課題の期限・単発予定・授業コマ数・祝日/振替を月表示
// - 日をタップ → 詳細パネル：予定の追加、曜日振替（祝日扱い/◯曜日程）、タイムラインへ
// - ☁️ Google連携：Apps Script経由でGoogleカレンダーに反映（スマホでも見られる）
import { useCallback, useEffect, useState } from 'react'
import * as api from '../api.js'
import { ymd } from '../lib/format.js'
import { tagIcon } from '../lib/categories.js'

// 📐 F23：横幅が広い横画面では 月グリッド｜その日の予定 の2列、それ以外は上下。ページ全体はスクロールしない
const MQ_TWO = '(min-width: 1000px) and (orientation: landscape)'
function useTwoColumns() {
  const [two, setTwo] = useState(() => !!(window.matchMedia && window.matchMedia(MQ_TWO).matches))
  useEffect(() => {
    if (!window.matchMedia) return undefined
    const mq = window.matchMedia(MQ_TWO)
    const h = () => setTwo(mq.matches)
    mq.addEventListener('change', h)
    return () => mq.removeEventListener('change', h)
  }, [])
  return two
}

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
function GcalSection({ settings, onSettingsChange, showToast, onPulled }) {
  const [url, setUrl] = useState(settings.gas_url ?? '')
  // 合言葉は本体から中身が返らない（secrets_set で設定済みかだけ分かる）。入力したときだけ上書きする
  const [token, setToken] = useState('')
  const tokenSet = !!settings.secrets_set?.gas_token
  const [enabled, setEnabled] = useState(!!settings.gcal_enabled)
  const [status, setStatus] = useState(null)
  const [busy, setBusy] = useState(false)

  const refresh = async () => {
    try { setStatus(await api.gcalStatus()) } catch { /* 未接続時は無視 */ }
  }
  useEffect(() => { refresh() }, [])

  const st = status?.status ?? {}
  // 入力欄が保存済みの値と違うか（違うまま「同期」「読み取り」を押すと、保存してから実行する）
  const dirty = url.trim() !== (settings.gas_url ?? '').trim()
    || token.trim() !== '' || enabled !== !!settings.gcal_enabled
  const saveIfDirty = async () => {
    if (!dirty) return
    onSettingsChange(await api.updateSettings({
      gas_url: url.trim(), gas_token: token.trim(), gcal_enabled: enabled,
    }))
    setToken('')
    showToast('入力内容を保存してから実行します 💾')
  }
  return (
    <details className="ios-widget" style={{ marginTop: 14 }}>
      <summary className="w-label" style={{ cursor: 'pointer' }}>
        ☁️ Google連携の設定{status?.configured ? '（設定済み）' : ''}
      </summary>
      <div className="caption" style={{ margin: '6px 0' }}>
        予定・授業・期限つき項目を <strong>Googleカレンダー（FocusCafeカレンダー）</strong>に反映し、
        スマホでも見られるようにします。iPhoneショートカットからの勉強記録の受け取りも同じ設定です。
        初回のセットアップ手順は <strong>docs/SETUP_GOOGLE_SYNC.md</strong>（約5分）を見てください。
      </div>
      <div className="edit-row">
        <input type="text" placeholder="Apps ScriptのウェブアプリURL（.../exec）" value={url}
               style={{ flex: 1 }} onChange={(e) => setUrl(e.target.value)} autoComplete="off" />
        <input type="password" placeholder={tokenSet ? '設定済み（変えるときだけ入力）' : '合言葉（トークン）'}
               value={token} autoComplete="new-password"
               style={{ width: 160 }} onChange={(e) => setToken(e.target.value)} />
        <label><input type="checkbox" checked={enabled}
                      onChange={(e) => setEnabled(e.target.checked)} /> 自動同期</label>
      </div>
      {tokenSet && <div className="caption">✅ 合言葉は保存済みです（変えるときだけ入力してください）</div>}
      {/* 何をGoogleカレンダーへ送るか（保存後「今すぐ同期」で反映） */}
      <div className="caption" style={{ marginTop: 10 }}>📤 カレンダーに送るもの</div>
      <div className="edit-row" style={{ flexWrap: 'wrap' }}>
        <label>🎓 授業：
          <select value={settings.gcal_class_mode ?? 'summary'}
                  onChange={async (e) => {
                    try { onSettingsChange(await api.updateSettings({ gcal_class_mode: e.target.value })) }
                    catch (err) { showToast('⚠️ ' + err.message) }
                  }}>
            <option value="summary">1日1件（例：🎓月曜日課・3コマ）</option>
            <option value="detail">コマごと（時間・教室つき）</option>
            <option value="none">送らない</option>
          </select>
        </label>
        {[['gcal_send_events', '📌 予定'],
          ['gcal_send_assignments', '📌 期限つき項目'],
          ['gcal_send_board', '📋 期限ボード'],
          ['gcal_send_jobs', '💼 就活']].map(([key, label]) => (
          <label key={key}>
            <input type="checkbox" checked={settings[key] ?? true}
                   onChange={async (e) => {
                     try { onSettingsChange(await api.updateSettings({ [key]: e.target.checked })) }
                     catch (err) { showToast('⚠️ ' + err.message) }
                   }} /> {label}
          </label>
        ))}
      </div>
      <div className="caption">
        📋 期限ボード＝期限のある未完了項目の進捗・期限・メモを「今日」の終日イベント1件にまとめたもの。
        スマホのGoogleカレンダーからいつでも状態を確認できます。
      </div>
      <div className="edit-row">
        <button className="small" onClick={async () => {
          try {
            onSettingsChange(await api.updateSettings({
              gas_url: url.trim(), gas_token: token.trim(), gcal_enabled: enabled,
            }))
            setToken('')
            showToast('Google連携の設定を保存しました ✅')
            refresh()
          } catch (e) { showToast('⚠️ ' + e.message) }
        }}>💾 保存</button>
        <button className="small" disabled={busy} onClick={async () => {
          setBusy(true)
          try {
            await saveIfDirty()
            const r = await api.gcalSync()
            showToast(`📤 ${r.pushed}件を同期しました（${r.range}）`)
            refresh()
          } catch (e) {
            showToast('⚠️ ' + e.message)
          } finally { setBusy(false) }
        }}>{busy ? '同期中…' : '📤 今すぐ同期'}</button>
        <button className="small" disabled={busy} onClick={async () => {
          setBusy(true)
          try {
            await saveIfDirty()
            const r = await api.gcalPull()
            showToast(`📥 Googleカレンダー「${r.calendar}」から${r.pulled}件を読み取りました`)
            refresh()
            onPulled?.()
          } catch (e) {
            showToast('⚠️ ' + e.message)
          } finally { setBusy(false) }
        }}>📥 Googleの予定を今すぐ読み取る</button>
        <button className="small" onClick={async () => {
          try {
            const r = await api.gcalImportPhone()
            showToast(r.added > 0 ? `📱 スマホの記録を${r.added}件取り込みました` : '📱 新しいスマホ記録はありません')
          } catch (e) { showToast('⚠️ ' + e.message) }
        }}>📱 iPhone記録を取り込む</button>
      </div>
      {status && (
        <div className="caption">
          💾 保存済み：URL 末尾 <code>{status.url_tail || '（未設定）'}</code>／合言葉 {status.token_len} 文字
          {dirty && <strong style={{ color: '#ffb84d' }}>　⚠ 入力欄が保存済みと違います（保存を押すか、同期/読み取りで自動保存）</strong>}
        </div>
      )}
      <div className="caption">
        📥 メインカレンダーの予定は<strong>読み取り専用</strong>で5分ごとに取り込み、カレンダー・今日・ホームに
        「G」付きで表示します（アプリから変更はしません。FocusCafeカレンダーは送信専用）。
      </div>
      {(st.last_sync || st.error || st.phone_imported || st.last_pull || st.pull_error) && (
        <div className={(st.error || st.pull_error) ? 'warn-box' : 'info-box'}>
          {st.error && <div>⚠️ {st.error}</div>}
          {st.pull_error && <div>⚠️ 読み取り：{st.pull_error}</div>}
          {st.last_sync && <div className="caption">最終同期 {st.last_sync}（{st.pushed}件）・以後6時間ごとに自動同期</div>}
          {st.last_pull && <div className="caption">📥 Googleの予定の最終読み取り {st.last_pull}（{st.pulled}件）・5分ごとに自動</div>}
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
  const two = useTwoColumns()

  // 日付を選ぶと、その日の時間割・予定・実績を時刻順の一覧で見られるようにする
  useEffect(() => {
    setSelDetail(null)
    if (!sel) return
    let alive = true
    api.getLifeDay(sel).then((d) => { if (alive) setSelDetail(d) }).catch(() => {})
    return () => { alive = false }
  }, [sel])

  // ⌨️ キーボード操作（カレンダータブ表示中のみ）：←→=前月/翌月・T=今月へ
  useEffect(() => {
    const h = (e) => {
      if (e.detail?.tab !== 'cal') return
      if (e.detail.key === 'ArrowLeft') setOffset((o) => o - 1)
      if (e.detail.key === 'ArrowRight') setOffset((o) => o + 1)
      if (e.detail.key === 't' || e.detail.key === 'T') setOffset(0)
    }
    window.addEventListener('fc-key', h)
    return () => window.removeEventListener('fc-key', h)
  }, [])

  const base = new Date()
  base.setDate(1)
  base.setMonth(base.getMonth() + offset)
  const month = fmtMonth(base)
  const todayStr = ymd()

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
    <div className="page-anim cal-page fit-page">
      <div className="fit-head">
      {onBack && <button type="button" className="ios-back" onClick={onBack}>‹ 戻る</button>}
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

      </div>

      {/* 上（広い横画面では左）＝月グリッド：残りの高さに合わせて縮む。下（右）＝その日の予定・Google：内側スクロール */}
      <div className={'cal-body' + (two ? ' two' : '')}>
      {/* 月グリッド（左右の縦ボタンで前月/翌月へ。中身は各日2件までに絞って全体が見える） */}
      <div className="cal-wrap">
        <button type="button" className="cal-side" title="前の月へ（←キーでも可）"
                onClick={() => setOffset(offset - 1)}>‹</button>
        <div className="cal-grid">
          {DAY_NAMES.map((dn, i) => (
            <div key={dn} className={'cal-head' + (i === 5 ? ' sat' : i === 6 ? ' sun' : '')}>{dn}</div>
          ))}
          {Array.from({ length: lead }, (_, i) => <div key={`b${i}`} className="cal-cell blank" />)}
          {days.map((d) => {
            const dayNum = parseInt(d.date.slice(8), 10)
            const red = d.weekday === 6 || d.is_holiday
            const undone = d.assignments.filter((a) => !a.done)
            // 中身のチップは全種まとめて最大2件＋「他N件」（読みやすさ優先）
            const chips = [
              ...undone.map((a) => ({ key: 'a' + a.id, cls: 'cal-asg', text: `${tagIcon(a.category, '📌')}${a.title}` })),
              ...d.events.map((ev) => ({ key: 'e' + ev.id, cls: 'cal-ev', text: `📌${ev.title}` })),
              // Googleメインカレンダー（読み取り専用）
              ...(d.google ?? []).map((g, i) => ({ key: 'g' + (g.id || i), cls: 'cal-google', text: `G ${g.title}` })),
              ...(d.jobs ?? []).map((j) => ({
                key: 'j' + j.id,
                cls: 'cal-job' + (j.status === '内定' ? ' done' : ''),
                text: `💼${j.company || j.label}`,
              })),
            ]
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
                {chips.slice(0, 2).map((c) => (
                  <span key={c.key} className={c.cls}>{c.text}</span>
                ))}
                {chips.length > 2 && <span className="cal-more">他{chips.length - 2}件</span>}
              </button>
            )
          })}
        </div>
        <button type="button" className="cal-side" title="次の月へ（→キーでも可）"
                onClick={() => setOffset(offset + 1)}>›</button>
      </div>

      <div className="cal-detail">
      {!selDay && <div className="caption" style={{ margin: '4px 6px' }}>日付を押すと、その日の予定・期限・就活日程をここに表示します。</div>}
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
              // Googleメインカレンダー（読み取り専用：チェック・削除なし。終日は先頭）
              ...(selDetail.google ?? []).map((g, i) => ({
                ...g, id: 'g' + (g.id || i), _k: 'gc',
                start: g.allday ? '' : g.start, end: g.allday ? '終日' : g.end,
              })),
              ...(selDetail.entries ?? []).map((e) => ({ ...e, _k: 'en' })),
              ...(selDetail.study ?? []).map((s, i) => ({ ...s, id: 's' + i, _k: 'st' })),
            ].sort((a, b) => (a.start ?? '').localeCompare(b.start ?? ''))
            if (items.length === 0) {
              return <div className="caption">この日の予定・記録はまだありません。</div>
            }
            const CHIP = {
              sch: ['🎓', '#007AFF', '時間割'], ev: ['📌', '#AF52DE', '予定'],
              gc: ['G', '#9AA0A6', 'Google'],
              en: ['📝', '#34C759', '実績'], st: ['📖', '#4CAF50', '勉強'],
            }
            return items.map((it) => {
              const [icon, color, label] = CHIP[it._k]
              return (
                <div className="edit-row" key={it._k + it.id}>
                  {/* 予定は完了チェックできる（ホームの消化率バーに反映） */}
                  {it._k === 'ev' && (
                    <input type="checkbox" checked={!!it.done}
                           onChange={async (e) => {
                             try {
                               await api.toggleLifeEventDone(it.id, e.target.checked)
                               setSelDetail(await api.getLifeDay(sel))
                             } catch (err) { showToast('⚠️ ' + err.message) }
                           }} />
                  )}
                  <span className="life-time">{it.start}〜{it.end}</span>
                  <span style={{ flex: 1,
                                 textDecoration: it.cancelled ? 'line-through' : 'none',
                                 opacity: it._k === 'ev' && it.done ? 0.55 : 1 }}>
                    {icon} {it.title}
                    {it._k === 'ev' && it.done && ' ✅'}
                    {it.room && <span className="caption">　🏫 {it.room}</span>}
                    {it._k === 'gc' && it.location && <span className="caption">　📍 {it.location}</span>}
                    {it.note && <span className="caption">　📝 {it.note}</span>}
                    {it.cancelled && <span className="caption">　休講</span>}
                  </span>
                  <span className="life-chip" style={{ borderColor: color, background: color + '33' }}>
                    {label}
                  </span>
                  {it._k === 'ev' && (
                    <button className="icon" onClick={async () => {
                      // 削除は必ず確認（誤タップ対策。アプリ全体で統一）
                      if (!window.confirm(`「${it.title}」を削除しますか？`)) return
                      try {
                        await api.deleteLifeEvent(it.id)
                        reload()
                        setSelDetail(await api.getLifeDay(sel))
                        showToast('削除しました 🗑')
                      } catch (e) { showToast('⚠️ ' + e.message) }
                    }}>🗑</button>
                  )}
                </div>
              )
            })
          })()}

          {/* 期限つき項目・就活の日程 */}
          {selDay.assignments.map((a) => (
            <div className="edit-row" key={a.id}>
              <span>{tagIcon(a.category, '📌')} {a.title}</span>
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

          <div className="caption" style={{ marginTop: 8 }}>
            ➕ この日に予定を追加（カテゴリも選べます。削除は上の一覧の 🗑）
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
      <GcalSection settings={settings} onSettingsChange={onSettingsChange} showToast={showToast}
                   onPulled={reload} />
      </div>
      </div>
    </div>
  )
}

export default CalendarMonth
