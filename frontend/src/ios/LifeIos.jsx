// 📅 ライフタブ（L1：予定・実績の記録基盤）
// - 日付を前後に移動しながら「その日のスケジュール一覧」を見る
// - 時間割（曜日別の繰り返し予定）・単発予定・手入力実績を登録できる
// - 勉強アプリの記録（ルーレット・集中モード・小窓）は自動でここに合流する
// タイムライン可視化はL2、PC自動記録はL3で追加予定。
import { useCallback, useEffect, useState } from 'react'
import * as api from '../api.js'
import CalendarMonth from './CalendarMonth.jsx'
import SummaryDay from './SummaryDay.jsx'
import TimelineDay from './TimelineDay.jsx'
import WeekReport from './WeekReport.jsx'

const DAY_NAMES = ['月', '火', '水', '木', '金', '土', '日']
const CATEGORIES = ['大学', '予定', '生活', '勉強', '娯楽', '睡眠', '移動', 'その他']

// カテゴリの色（タイムラインでも使う予定）
export const CATEGORY_COLORS = {
  '大学': '#007AFF', '予定': '#AF52DE', '生活': '#34C759', '勉強': '#4CAF50',
  '気分転換': '#FF9F0A', '娯楽': '#FF375F', '睡眠': '#5E5CE6', '移動': '#8E8E93',
  'その他': '#64D2FF', '中断': '#FF9500',
}

function fmtDate(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function CategoryChip({ category }) {
  return (
    <span className="life-chip"
          style={{ background: (CATEGORY_COLORS[category] ?? '#8E8E93') + '33',
                   borderColor: CATEGORY_COLORS[category] ?? '#8E8E93' }}>
      {category}
    </span>
  )
}

// 追加フォーム（実績／単発予定 共用）
// 日付を変えれば「将来の特定の日」の予定も、過去日の実績も入れられる
function AddForm({ kind, date, onDone, onCancel }) {
  const [targetDate, setTargetDate] = useState(date)
  const [start, setStart] = useState('12:00')
  const [end, setEnd] = useState('13:00')
  const [title, setTitle] = useState('')
  const [note, setNote] = useState('')
  const [category, setCategory] = useState(kind === 'event' ? '予定' : '生活')

  const submit = async (e) => {
    e.preventDefault()
    if (!title.trim()) return
    const body = { date: targetDate, start, end, title: title.trim(), category }
    if (kind === 'event') await api.addLifeEvent({ ...body, note: note.trim() })
    else await api.addLifeEntry(body)
    onDone(targetDate)
  }

  return (
    <form onSubmit={submit} className="life-form">
      <div className="edit-row">
        <input type="date" value={targetDate} onChange={(e) => setTargetDate(e.target.value)} />
        <input type="time" value={start} onChange={(e) => setStart(e.target.value)} />
        〜
        <input type="time" value={end} onChange={(e) => setEnd(e.target.value)} />
        <select value={category} onChange={(e) => setCategory(e.target.value)}>
          {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>
      <div className="edit-row">
        <input type="text" autoFocus value={title} onChange={(e) => setTitle(e.target.value)}
               placeholder={kind === 'event' ? '予定の名前（例：バイト）' : '何をした？（例：夕食・風呂）'} />
        {kind === 'event' && (
          <input type="text" value={note} onChange={(e) => setNote(e.target.value)}
                 placeholder="メモ（場所など・Googleカレンダーにも出ます）" />
        )}
        <button type="submit">追加</button>
        <button type="button" className="icon" onClick={onCancel}>✕</button>
      </div>
    </form>
  )
}

// 時間割（曜日別・繰り返し）の編集ページ
// まず曜日を選び、その曜日だけを編集する2段階式
function ScheduleEditor({ onBack, showToast }) {
  const [blocks, setBlocks] = useState([])
  const [adding, setAdding] = useState(null) // 追加中の曜日
  const [selDay, setSelDay] = useState(null) // 選択中の曜日（null=曜日選択画面）

  const reload = useCallback(() => {
    api.getSchedule().then(setBlocks).catch(() => {})
  }, [])
  useEffect(() => { reload() }, [reload])

  const AddBlockForm = ({ weekday }) => {
    const [start, setStart] = useState('09:00')
    const [end, setEnd] = useState('10:30')
    const [title, setTitle] = useState('')
    const [room, setRoom] = useState('')
    const [category, setCategory] = useState('大学')
    return (
      <form className="life-form" onSubmit={async (e) => {
        e.preventDefault()
        if (!title.trim()) return
        await api.addScheduleBlock({ weekday, start, end, title: title.trim(),
                                     category, room: room.trim() })
        setAdding(null)
        reload()
        showToast('時間割に追加しました ✅')
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
          <input type="text" autoFocus value={title} onChange={(e) => setTitle(e.target.value)}
                 placeholder="予定の名前（例：応用プログラミング言語）" />
          <input type="text" value={room} onChange={(e) => setRoom(e.target.value)}
                 style={{ width: 150 }}
                 placeholder="教室（例：W2-301）" />
          <button type="submit">追加</button>
          <button type="button" className="icon" onClick={() => setAdding(null)}>✕</button>
        </div>
      </form>
    )
  }

  // ---- 1段階目：曜日を選ぶ ----
  if (selDay === null) {
    return (
      <div className="page-anim">
        <button type="button" className="ios-back" onClick={onBack}>‹ ライフ</button>
        <h2 className="ios-section-title">
          <span className="r-icon" style={{ background: '#007AFF' }}>🗓</span>
          時間割（毎週の繰り返し予定）
        </h2>
        <div className="caption" style={{ marginBottom: 10 }}>
          編集したい曜日を選んでください。大学の授業・バイトなど「毎週決まっている予定」を
          曜日ごとに登録でき、該当する曜日のスケジュールに自動で表示されます。
        </div>
        <div className="day-grid">
          {DAY_NAMES.map((dn, wd) => {
            const n = blocks.filter((b) => b.weekday === wd).length
            return (
              <button key={dn} type="button" className="day-card"
                      onClick={() => { setSelDay(wd); setAdding(null) }}>
                <span className="d-name">{dn}</span>
                <span className="d-count">{n > 0 ? `${n}件の予定` : '予定なし'}</span>
              </button>
            )
          })}
        </div>
      </div>
    )
  }

  // ---- 2段階目：選んだ曜日だけを編集 ----
  const dn = DAY_NAMES[selDay]
  const dayBlocks = blocks.filter((b) => b.weekday === selDay)
  return (
    <div className="page-anim" key={selDay}>
      <button type="button" className="ios-back" onClick={() => setSelDay(null)}>‹ 曜日選択</button>
      <h2 className="ios-section-title">
        <span className="r-icon" style={{ background: '#007AFF' }}>🗓</span>
        {dn}曜日の時間割
      </h2>
      <div className="ios-section-body">
        {dayBlocks.length === 0 && <div className="caption">まだ予定がありません。下から追加できます。</div>}
        {dayBlocks.map((b) => (
          <div className="edit-row" key={b.id}>
            <span className="life-time">{b.start}〜{b.end}</span>
            <span style={{ flex: 1 }}>{b.title}</span>
            <input type="text" defaultValue={b.room || ''} placeholder="教室"
                   style={{ width: 110 }} title="教室などのメモ（Googleカレンダーにも出ます）"
                   onBlur={(e) => {
                     if (e.target.value !== (b.room || ''))
                       api.updateScheduleBlock(b.id, { ...b, room: e.target.value.trim() })
                         .then(reload)
                   }} />
            <CategoryChip category={b.category} />
            <input type="checkbox" title="有効/無効" checked={b.enabled}
                   onChange={(e) => {
                     api.updateScheduleBlock(b.id, { ...b, enabled: e.target.checked })
                       .then(reload)
                   }} />
            <button className="icon" onClick={() => api.deleteScheduleBlock(b.id).then(reload)}>🗑</button>
          </div>
        ))}
        {adding === selDay
          ? <AddBlockForm weekday={selDay} />
          : <button className="small" onClick={() => setAdding(selDay)}>➕ {dn}曜に追加</button>}
      </div>
      <div className="caption" style={{ marginTop: 8 }}>
        スイッチをオフにすると、その予定を消さずに一時的に無効化できます。
      </div>
    </div>
  )
}

// 期限バッジ（あとN日/今日/期限切れ）
function DueBadge({ daysLeft, dueDate }) {
  let text, cls
  if (daysLeft == null) { text = dueDate; cls = '' }
  else if (daysLeft < 0) { text = `期限切れ ${-daysLeft}日`; cls = ' overdue' }
  else if (daysLeft === 0) { text = '今日まで！'; cls = ' urgent' }
  else if (daysLeft <= 2) { text = `あと${daysLeft}日`; cls = ' urgent' }
  else { text = `あと${daysLeft}日` ; cls = '' }
  return <span className={'due-badge' + cls}>📅 {dueDate.slice(5).replace('-', '/')}・{text}</span>
}

// 課題ページ（Notion風：期限・進捗・コメント。毎週の課題テンプレート付き）
function AssignmentsPage({ onBack, showToast }) {
  const [items, setItems] = useState([])
  const [recurring, setRecurring] = useState([])
  const [title, setTitle] = useState('')
  const [due, setDue] = useState(fmtDate(new Date()))
  const [asgCat, setAsgCat] = useState('大学')   // 追加フォームの種類
  const [filterCat, setFilterCat] = useState('all') // 一覧の絞り込み
  const [recTitle, setRecTitle] = useState('')
  const [recWd, setRecWd] = useState(0)

  // 課題の種類（大学の課題だけでなく、私生活のやること・就活タスクも同じ仕組みで管理）
  const ASG_CATS = [
    ['大学', '🎓'], ['私生活', '🏠'], ['就活', '💼'],
  ]
  const catIcon = (c) => (ASG_CATS.find(([name]) => name === c)?.[1] ?? '🎓')

  const reload = useCallback(() => {
    api.getAssignments().then(setItems).catch(() => {})
    api.getRecurringAssignments().then(setRecurring).catch(() => {})
  }, [])
  useEffect(() => { reload() }, [reload])

  const addRecurring = async (e) => {
    e.preventDefault()
    if (!recTitle.trim()) return
    await api.addRecurringAssignment({ title: recTitle.trim(), weekday: recWd })
    setRecTitle('')
    reload()
    showToast('毎週の課題を登録しました 🔁')
  }

  const add = async (e) => {
    e.preventDefault()
    if (!title.trim()) return
    await api.addAssignment({ title: title.trim(), due_date: due, category: asgCat })
    setTitle('')
    reload()
    showToast('追加しました ✅')
  }

  const save = async (it, changes) => {
    await api.updateAssignment(it.id, {
      title: it.title, due_date: it.due_date, progress: it.progress, note: it.note,
      category: it.category ?? '大学',
      ...changes,
    })
    reload()
  }

  return (
    <div className="page-anim">
      <button type="button" className="ios-back" onClick={onBack}>‹ ライフ</button>
      <h2 className="ios-section-title">
        <span className="r-icon" style={{ background: '#FF9500' }}>📚</span>
        課題
      </h2>
      <div className="caption" style={{ marginBottom: 10 }}>
        期限が<strong>2日以内</strong>になった課題は、期限が近い順で
        ホームの<strong>「今日絶対やる」に自動で追加</strong>されます
        （ふりかえりで「終わった」と答えるか、進捗を100%にすると外れます）。
      </div>

      {/* 🔁 毎週の課題（テンプレート）：先に登録しておくと週ごとに自動で出てくる */}
      <details className="ios-row-details life-form" style={{ marginBottom: 12 }} open={recurring.length === 0}>
        <summary className="ios-row" style={{ padding: '6px 4px' }}>
          <span className="r-icon" style={{ background: '#5856D6' }}>🔁</span>
          <span className="r-label">毎週の課題（{recurring.length}件）</span>
          <span className="r-chevron">›</span>
        </summary>
        <div className="caption" style={{ margin: '6px 0' }}>
          毎週同じ曜日が期限の課題はここに登録。週ごとに自動で下の一覧に追加されるので、
          今週分を「絶対にやる」で消して完了しても、<strong>翌週分はまた自動で出てきます</strong>。
        </div>
        {recurring.map((r) => (
          <div className="edit-row" key={r.id}>
            <input type="text" defaultValue={r.title}
                   onBlur={(e) => {
                     if (e.target.value !== r.title)
                       api.updateRecurringAssignment(r.id, { ...r, title: e.target.value }).then(reload)
                   }} />
            <select value={r.weekday}
                    onChange={(e) => api.updateRecurringAssignment(r.id, { ...r, weekday: parseInt(e.target.value, 10) }).then(reload)}>
              {DAY_NAMES.map((dn, i) => <option key={i} value={i}>毎週{dn}曜まで</option>)}
            </select>
            <input type="checkbox" title="有効/無効" checked={r.enabled}
                   onChange={(e) => api.updateRecurringAssignment(r.id, { ...r, enabled: e.target.checked }).then(reload)} />
            <button className="icon" onClick={async () => {
              if (!window.confirm(`毎週の課題「${r.title}」を削除しますか？`)) return
              await api.deleteRecurringAssignment(r.id)
              reload()
            }}>🗑</button>
          </div>
        ))}
        <form onSubmit={addRecurring} className="edit-row">
          <input type="text" value={recTitle} onChange={(e) => setRecTitle(e.target.value)}
                 placeholder="毎週の課題名（例：OS 小テスト）" />
          <select value={recWd} onChange={(e) => setRecWd(parseInt(e.target.value, 10))}>
            {DAY_NAMES.map((dn, i) => <option key={i} value={i}>毎週{dn}曜まで</option>)}
          </select>
          <button type="submit">➕ 登録</button>
        </form>
      </details>

      {/* 単発の課題・やること（大学／私生活／就活） */}
      <form onSubmit={add} className="life-form" style={{ marginBottom: 8 }}>
        <div className="edit-row">
          <select value={asgCat} onChange={(e) => setAsgCat(e.target.value)}
                  title="種類（大学の課題／私生活のやること／就活のタスク）">
            {ASG_CATS.map(([c, ic]) => <option key={c} value={c}>{ic} {c}</option>)}
          </select>
          <input type="text" value={title} onChange={(e) => setTitle(e.target.value)}
                 placeholder={asgCat === '大学' ? '課題名（例：ネットワーク レポート2）'
                   : asgCat === '私生活' ? 'やること（例：役所で住民票・美容院の予約）'
                   : '就活タスク（例：A社のES下書き）'} />
          <input type="date" value={due} onChange={(e) => setDue(e.target.value)} />
          <button type="submit">➕ 追加</button>
        </div>
      </form>

      {/* 種類での絞り込み */}
      <div className="edit-row" style={{ marginBottom: 8 }}>
        {[['all', '🗂 すべて'], ...ASG_CATS.map(([c, ic]) => [c, `${ic} ${c}`])].map(([v, l]) => (
          <button key={v} type="button"
                  className={'sort-chip' + (filterCat === v ? ' on' : '')}
                  onClick={() => setFilterCat(v)}>{l}</button>
        ))}
      </div>

      <div className="ios-list">
        {items.length === 0 && (
          <div className="ios-row ios-row-static" style={{ cursor: 'default' }}>
            <span className="r-label caption">まだありません。上のフォームから追加できます。</span>
          </div>
        )}
        {items
          .filter((it) => filterCat === 'all' || (it.category ?? '大学') === filterCat)
          .map((it) => (
          <div key={it.id} className={'asg-row' + (it.done ? ' done' : '')}>
            <div className="asg-main">
              <span title={it.category ?? '大学'}>{catIcon(it.category ?? '大学')}</span>
              {it.recurring && <span title="毎週の課題（自動生成）">🔁</span>}
              <input className="asg-title" type="text" defaultValue={it.title}
                     onBlur={(e) => { if (e.target.value !== it.title) save(it, { title: e.target.value }) }} />
              <DueBadge daysLeft={it.days_left} dueDate={it.due_date} />
              <input type="date" value={it.due_date}
                     onChange={(e) => save(it, { due_date: e.target.value })} />
              <select value={String(it.progress)}
                      onChange={(e) => save(it, { progress: parseInt(e.target.value, 10) })}>
                {[0, 25, 50, 75, 100].map((p) => (
                  <option key={p} value={p}>{p === 100 ? '✅ 完了' : `進捗 ${p}%`}</option>
                ))}
              </select>
              <button className="icon" onClick={async () => {
                if (!window.confirm(`「${it.title}」を削除しますか？`)) return
                await api.deleteAssignment(it.id)
                reload()
              }}>🗑</button>
            </div>
            <div className="asg-progress"><div style={{ width: `${it.progress}%` }} /></div>
            <details className="asg-note">
              <summary>💬 コメント{it.note ? '（あり）' : ''}</summary>
              <textarea defaultValue={it.note} placeholder="メモ・気づき・参考リンクなど"
                        onBlur={(e) => { if (e.target.value !== it.note) save(it, { note: e.target.value }) }} />
            </details>
          </div>
        ))}
      </div>
    </div>
  )
}

function LifeIos({ settings, onSettingsChange, showToast, resetTick }) {
  const [offset, setOffset] = useState(0)  // 0=今日, -1=昨日 ...
  const [day, setDay] = useState(null)
  const [assignments, setAssignments] = useState([])
  const [adding, setAdding] = useState(null) // 'entry' | 'event' | null
  const [page, setPage] = useState('main')   // 'main' | 'schedule' | 'assignments'
  const [view, setView] = useState('timeline') // 'timeline' | 'list'

  const d = new Date()
  d.setDate(d.getDate() + offset)
  const date = fmtDate(d)

  const reload = useCallback(() => {
    api.getLifeDay(date).then(setDay).catch(() => {})
    api.getAssignments().then(setAssignments).catch(() => {})
  }, [date])
  useEffect(() => { reload() }, [reload])

  // タブバーの「ライフ」を押すたびに初期状態（今日・メイン画面）へ戻す
  useEffect(() => {
    if (!resetTick) return // 初回マウント時は何もしない
    setPage('main')
    setAdding(null)
    setOffset(0)
  }, [resetTick])

  if (page === 'schedule') {
    return <ScheduleEditor onBack={() => { setPage('main'); reload() }} showToast={showToast} />
  }
  if (page === 'assignments') {
    return <AssignmentsPage onBack={() => { setPage('main'); reload() }} showToast={showToast} />
  }
  if (page === 'week') {
    return <WeekReport onBack={() => setPage('main')} />
  }
  if (page === 'calendar') {
    return <CalendarMonth
      onBack={() => { setPage('main'); reload() }}
      settings={settings} onSettingsChange={onSettingsChange} showToast={showToast}
      onOpenDay={(d) => {
        // カレンダーで選んだ日をタイムラインで開く（日数差からoffsetを計算）
        const t = new Date(); t.setHours(0, 0, 0, 0)
        const target = new Date(d + 'T00:00:00')
        setOffset(Math.round((target - t) / 86400000))
        setPage('main')
      }} />
  }
  const openAssignments = assignments.filter((a) => !a.done).length

  // 予定（時間割＋単発）と実績（手入力＋勉強記録）を1本のリストに統合して時刻順に
  const items = []
  for (const b of day?.schedule ?? []) {
    items.push({ ...b, kind: 'schedule', label: '時間割' })
  }
  for (const ev of day?.events ?? []) {
    items.push({ ...ev, kind: 'event', label: '予定' })
  }
  for (const en of day?.entries ?? []) {
    items.push({ ...en, kind: 'entry', label: '実績' })
  }
  for (const st of day?.study ?? []) {
    items.push({ ...st, kind: 'study', label: '勉強アプリ' })
  }
  items.sort((a, b) => (a.start ?? '').localeCompare(b.start ?? ''))

  const dateLabel = `${d.getMonth() + 1}月${d.getDate()}日（${DAY_NAMES[(d.getDay() + 6) % 7]}）`

  return (
    <div>
      <h1 className="ios-large-title">📅 ライフ</h1>

      {/* 日付ナビ */}
      <div className="life-datenav">
        <button className="small" onClick={() => setOffset(offset - 1)}>‹ 前日</button>
        <div className="life-date">
          {dateLabel}{offset === 0 ? '・今日' : ''}
        </div>
        {day?.holiday_name && (
          <span className="life-chip" style={{ borderColor: '#FF3B30', background: '#FF3B3033' }}>
            🎌 {day.holiday_name}
          </span>
        )}
        {day && day.effective_weekday !== day.weekday && (
          <span className="life-chip" style={{ borderColor: '#FF9F0A', background: '#FF9F0A33' }}>
            🔀 {DAY_NAMES[day.effective_weekday]}曜日程
          </span>
        )}
        <button className="small" onClick={() => setOffset(offset + 1)} disabled={offset >= 0}>翌日 ›</button>
        {offset !== 0 && (
          <button className="small" onClick={() => setOffset(0)}>今日へ</button>
        )}
      </div>

      {/* 追加アクション */}
      <div className="life-actions">
        <button onClick={() => setAdding(adding === 'entry' ? null : 'entry')}>
          ➕ 実績を記録
        </button>
        <button onClick={() => setAdding(adding === 'event' ? null : 'event')}>
          🗓 単発予定を追加
        </button>
        <button onClick={() => setPage('schedule')}>
          🗓 時間割の編集
        </button>
        <button onClick={() => setPage('assignments')}>
          📚 課題{openAssignments > 0 ? `（${openAssignments}）` : ''}
        </button>
        <button onClick={() => setPage('week')}>
          📈 週次レポート
        </button>
        <button onClick={() => setPage('calendar')}>
          🗓 カレンダー
        </button>
      </div>
      {adding && (
        <AddForm kind={adding} date={date}
                 onDone={(usedDate) => {
                   setAdding(null)
                   reload()
                   showToast(usedDate !== date
                     ? `${usedDate} に追加しました ✅（日付を移動すると確認できます）`
                     : '追加しました ✅')
                 }}
                 onCancel={() => setAdding(null)} />
      )}

      {/* 表示切替：タイムライン（帯グラフ）⇄ 一覧 ⇄ サマリー */}
      <div className="seg" style={{ maxWidth: 420, margin: '14px 0 10px' }}>
        {[['timeline', '📊 タイムライン'], ['list', '📋 一覧'], ['summary', '📈 サマリー']].map(([v, lbl]) => (
          <button key={v} type="button"
                  className={'seg-btn' + (view === v ? ' on' : '')}
                  onClick={() => setView(v)}>
            {lbl}
          </button>
        ))}
      </div>

      {view === 'timeline' && (
        <TimelineDay day={day} date={date} isToday={offset === 0} />
      )}

      {view === 'summary' && (
        <SummaryDay date={date} settings={settings}
                    onSettingsChange={onSettingsChange} showToast={showToast} />
      )}

      {/* その日のスケジュール一覧（予定＋実績を時刻順に） */}
      <div className="ios-list" style={{ marginTop: 4, display: view === 'list' ? 'block' : 'none' }}>
        {items.length === 0 && (
          <div className="ios-row ios-row-static" style={{ cursor: 'default' }}>
            <span className="r-label caption">
              まだ記録がありません。「➕実績を記録」から今日やったことを追加できます。
              勉強アプリでの記録は自動でここに表示されます。
            </span>
          </div>
        )}
        {items.map((it, i) => (
          <div className={'ios-row ios-row-static life-row' + (it.cancelled ? ' life-cancelled' : '')}
               key={`${it.kind}-${it.id ?? i}`}>
            <span className="life-time">{it.start}〜{it.end}</span>
            <span className="r-label">{it.title}</span>
            {it.cancelled && <span className="life-chip" style={{ background: '#FF3B3033', borderColor: '#FF3B30' }}>休講</span>}
            <CategoryChip category={it.category} />
            <span className="r-right">{it.label}</span>
            {/* 大学の授業（時間割由来）はその日だけの休講にできる */}
            {it.kind === 'schedule' && it.category === '大学' && (
              <button className="icon" title="この日だけ休講にする/戻す"
                      onClick={async () => {
                        await api.toggleCancellation(date, it.id)
                        reload()
                      }}>
                {it.cancelled ? '↩' : '休講'}
              </button>
            )}
            {(it.kind === 'event' || it.kind === 'entry') && (
              <button className="icon" onClick={async () => {
                if (it.kind === 'event') await api.deleteLifeEvent(it.id)
                else await api.deleteLifeEntry(it.id)
                reload()
              }}>🗑</button>
            )}
          </div>
        ))}
      </div>
      <div className="caption" style={{ margin: '10px 4px' }}>
        💡 休講・削除などの操作は「📋 一覧」から。💻PCの自動記録は
        pc_tracker（start_all.bat で自動起動）が動いている間だけ記録されます。
      </div>
    </div>
  )
}

export default LifeIos
