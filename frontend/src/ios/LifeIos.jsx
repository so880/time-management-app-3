// 📅 ライフタブ（L1：予定・実績の記録基盤）
// - 日付を前後に移動しながら「その日のスケジュール一覧」を見る
// - 時間割（曜日別の繰り返し予定）・単発予定・手入力実績を登録できる
// - 勉強アプリの記録（ルーレット・集中モード・小窓）は自動でここに合流する
// タイムライン可視化はL2、PC自動記録はL3で追加予定。
import { useCallback, useEffect, useRef, useState } from 'react'
import * as api from '../api.js'
import CalendarMonth from './CalendarMonth.jsx'
import SummaryDay from './SummaryDay.jsx'
import TimelineDay from './TimelineDay.jsx'
import WeekReport from './WeekReport.jsx'
import { ymd } from '../lib/format.js'
import { CATEGORY_COLORS, ROULETTE_TAGS } from '../lib/categories.js'

const DAY_NAMES = ['月', '火', '水', '木', '金', '土', '日']
const CATEGORIES = ['大学', '予定', '生活', '勉強', '娯楽', '睡眠', '移動', 'その他']

// カテゴリの色（タイムラインでも使う予定）

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
// 時間割エディタ（編集タブから使う。onBack を渡さなければ戻るボタンは出ない）
export function ScheduleEditor({ onBack, showToast }) {
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
        {onBack && <button type="button" className="ios-back" onClick={onBack}>‹ 戻る</button>}
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
                         .then(reload).catch((err) => showToast('⚠️ ' + err.message))
                   }} />
            <CategoryChip category={b.category} />
            <input type="checkbox" title="有効/無効" checked={b.enabled}
                   onChange={(e) => {
                     api.updateScheduleBlock(b.id, { ...b, enabled: e.target.checked })
                       .then(reload).catch((err) => showToast('⚠️ ' + err.message))
                   }} />
            <button className="icon" onClick={() => api.deleteScheduleBlock(b.id).then(reload).catch((err) => showToast('⚠️ ' + err.message))}>🗑</button>
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

// 🎲 ルーレット項目（旧・課題＋通常勉強＋重点を統合）
// - タグ（就活/大学/私用/その他）・期限（任意）・重点（抽選3倍）・有効（抽選に出す）・進捗
// - 期限のある項目はカレンダーと「今日やること」に出る。100%で完了＝抽選から外れる
// - 毎週の項目（テンプレート）から週ごとのインスタンスが自動生成される

export function RoulettePage({ onBack, showToast }) {
  const [items, setItems] = useState([])
  const [recurring, setRecurring] = useState([])
  // タグ一覧（既定4つ＋起動画面で記入した追加タグ）。取れないときは既定4つ
  const [tagList, setTagList] = useState(ROULETTE_TAGS)
  const [title, setTitle] = useState('')
  const [due, setDue] = useState('')
  const [tag, setTag] = useState('その他')
  const [focus, setFocus] = useState(false)
  const [filterCat, setFilterCat] = useState('all') // 一覧の絞り込み
  const [showDone, setShowDone] = useState(false)
  const [recTitle, setRecTitle] = useState('')
  const [recWd, setRecWd] = useState(0)

  const reload = useCallback(() => {
    api.getAssignments().then(setItems).catch(() => {})
    api.getRecurringAssignments().then(setRecurring).catch(() => {})
    api.getRouletteTags().then((ts) => setTagList(ts.map((t) => [t.name, t.icon]))).catch(() => {})
  }, [])
  useEffect(() => { reload() }, [reload])

  const addRecurring = async (e) => {
    e.preventDefault()
    if (!recTitle.trim()) return
    await api.addRecurringAssignment({ title: recTitle.trim(), weekday: recWd })
    setRecTitle('')
    reload()
    showToast('毎週の項目を登録しました 🔁')
  }

  const add = async (e) => {
    e.preventDefault()
    if (!title.trim()) return
    try {
      await api.addAssignment({ title: title.trim(), due_date: due, category: tag, focus, enabled: true })
      setTitle(''); setDue(''); setFocus(false)
      reload()
      showToast('追加しました ✅')
    } catch (err) { showToast('⚠️ ' + err.message) }
  }

  const save = async (it, changes) => {
    try {
      await api.updateAssignment(it.id, {
        title: it.title, due_date: it.due_date, progress: it.progress, note: it.note,
        category: it.category ?? 'その他', focus: !!it.focus, enabled: it.enabled !== false,
        ...changes,
      })
      reload()
    } catch (err) { showToast('⚠️ ' + err.message) }
  }

  const visible = items
    .filter((it) => filterCat === 'all' || (it.category ?? 'その他') === filterCat)
    .filter((it) => showDone || !it.done)

  return (
    <div className="page-anim">
      {onBack && <button type="button" className="ios-back" onClick={onBack}>‹ 戻る</button>}
      <h2 className="ios-section-title">
        <span className="r-icon" style={{ background: '#FF9500' }}>🎲</span>
        ルーレット項目
      </h2>
      <div className="caption" style={{ marginBottom: 10 }}>
        勉強の抽選はここから出ます（未完了で有効なもの。<strong>重点は3倍</strong>出やすい）。
        期限をつけるとカレンダーと「今日やること」に出ます。100%にすると完了＝抽選から外れます。
        今日の必須に未完了があるときは、そちらが優先されます。
      </div>

      {/* 🔁 毎週の項目（テンプレート） */}
      <details className="ios-row-details life-form" style={{ marginBottom: 12 }}>
        <summary className="ios-row" style={{ padding: '6px 4px' }}>
          <span className="r-icon" style={{ background: '#5856D6' }}>🔁</span>
          <span className="r-label">毎週の項目（{recurring.length}件）</span>
          <span className="r-chevron">›</span>
        </summary>
        <div className="caption" style={{ margin: '6px 0' }}>
          毎週同じ曜日が期限のもの（授業の課題など）。週ごとに自動で下の一覧に追加されます。
        </div>
        {recurring.map((r) => (
          <div className="edit-row" key={r.id}>
            <input type="text" defaultValue={r.title}
                   onBlur={(e) => {
                     if (e.target.value !== r.title)
                       api.updateRecurringAssignment(r.id, { ...r, title: e.target.value }).then(reload).catch((err) => showToast('⚠️ ' + err.message))
                   }} />
            <select value={r.weekday}
                    onChange={(e) => api.updateRecurringAssignment(r.id, { ...r, weekday: parseInt(e.target.value, 10) }).then(reload).catch((err) => showToast('⚠️ ' + err.message))}>
              {DAY_NAMES.map((dn, i) => <option key={i} value={i}>毎週{dn}曜まで</option>)}
            </select>
            <input type="checkbox" title="有効/無効" checked={r.enabled}
                   onChange={(e) => api.updateRecurringAssignment(r.id, { ...r, enabled: e.target.checked }).then(reload).catch((err) => showToast('⚠️ ' + err.message))} />
            <button className="icon" onClick={async () => {
              if (!window.confirm(`毎週の項目「${r.title}」を削除しますか？`)) return
              try {
                await api.deleteRecurringAssignment(r.id)
                reload()
              } catch (err) { showToast('⚠️ ' + err.message) }
            }}>🗑</button>
          </div>
        ))}
        <form onSubmit={addRecurring} className="edit-row">
          <input type="text" value={recTitle} onChange={(e) => setRecTitle(e.target.value)}
                 placeholder="毎週の項目名（例：OS 小テスト）" />
          <select value={recWd} onChange={(e) => setRecWd(parseInt(e.target.value, 10))}>
            {DAY_NAMES.map((dn, i) => <option key={i} value={i}>毎週{dn}曜まで</option>)}
          </select>
          <button type="submit">➕ 登録</button>
        </form>
      </details>

      {/* 追加フォーム：タグ＋名前＋期限（任意）＋重点 */}
      <form onSubmit={add} className="life-form" style={{ marginBottom: 8 }}>
        <div className="edit-row" style={{ flexWrap: 'wrap' }}>
          <select value={tag} onChange={(e) => setTag(e.target.value)} title="タグ">
            {tagList.map(([c, ic]) => <option key={c} value={c}>{ic} {c}</option>)}
          </select>
          <input type="text" value={title} onChange={(e) => setTitle(e.target.value)}
                 style={{ flex: 1, minWidth: 180 }}
                 placeholder="項目名（例：Santa Part7長文の写経／A社のES下書き）" />
          <input type="date" value={due} onChange={(e) => setDue(e.target.value)} title="期限（任意）" />
          {due && <button type="button" className="icon" title="期限を外す" onClick={() => setDue('')}>✕</button>}
          <label title="重点＝抽選で3倍出やすい">
            <input type="checkbox" checked={focus} onChange={(e) => setFocus(e.target.checked)} /> 🔥重点
          </label>
          <button type="submit">➕ 追加</button>
        </div>
      </form>

      {/* 絞り込み */}
      <div className="edit-row" style={{ marginBottom: 8, flexWrap: 'wrap' }}>
        {[['all', '🗂 すべて'], ...tagList.map(([c, ic]) => [c, `${ic} ${c}`])].map(([v, l]) => (
          <button key={v} type="button"
                  className={'sort-chip' + (filterCat === v ? ' on' : '')}
                  onClick={() => setFilterCat(v)}>{l}</button>
        ))}
        <label className="caption" style={{ marginLeft: 'auto' }}>
          <input type="checkbox" checked={showDone} onChange={(e) => setShowDone(e.target.checked)} /> 完了も表示
        </label>
      </div>

      <div className="ios-list">
        {visible.length === 0 && (
          <div className="ios-row ios-row-static" style={{ cursor: 'default' }}>
            <span className="r-label caption">まだありません。上のフォームから追加できます。</span>
          </div>
        )}
        {visible.map((it) => (
          <div key={it.id} className={'asg-row' + (it.done ? ' done' : '') + (it.enabled === false ? ' off' : '')}>
            <div className="asg-main">
              <select value={it.category ?? 'その他'} title="タグ"
                      onChange={(e) => save(it, { category: e.target.value })}>
                {tagList.map(([c, ic]) => <option key={c} value={c}>{ic}</option>)}
              </select>
              {it.recurring && <span title="毎週の項目（自動生成）">🔁</span>}
              <input className="asg-title" type="text" defaultValue={it.title}
                     onBlur={(e) => { if (e.target.value !== it.title) save(it, { title: e.target.value }) }} />
              {it.due_date
                ? <DueBadge daysLeft={it.days_left} dueDate={it.due_date} />
                : <span className="caption">期限なし</span>}
              <input type="date" value={it.due_date || ''} title="期限（空で期限なし）"
                     onChange={(e) => save(it, { due_date: e.target.value })} />
              {it.due_date && (
                <button className="icon" title="期限を外す" onClick={() => save(it, { due_date: '' })}>✕</button>
              )}
              <label title="重点＝抽選で3倍">
                <input type="checkbox" checked={!!it.focus} onChange={(e) => save(it, { focus: e.target.checked })} /> 🔥
              </label>
              <label title="抽選に出す／出さない">
                <input type="checkbox" checked={it.enabled !== false} onChange={(e) => save(it, { enabled: e.target.checked })} /> 抽選
              </label>
              <select value={String(it.progress)}
                      onChange={(e) => save(it, { progress: parseInt(e.target.value, 10) })}>
                {[0, 25, 50, 75, 100].map((p) => (
                  <option key={p} value={p}>{p === 100 ? '✅ 完了' : `進捗 ${p}%`}</option>
                ))}
              </select>
              <button className="icon" onClick={async () => {
                if (!window.confirm(`「${it.title}」を削除しますか？`)) return
                try {
                  await api.deleteAssignment(it.id)
                  reload()
                } catch (err) { showToast('⚠️ ' + err.message) }
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


// 🗓 カレンダータブ（タブバーの同列タブ。月の予定だけに絞りスクロールなしで全体が見える）
export function CalendarTab({ settings, onSettingsChange, showToast, onOpenDay }) {
  return (
    <div className="cal-tab">
      <div className="ios-title-row" style={{ marginBottom: 4 }}>
        <h1 className="ios-large-title">🗓 カレンダー</h1>
        <button className="small"
                title="今日から7日分の予定と期限つき項目を、そのまま貼れるテキストでコピー"
                onClick={async () => {
                  try {
                    const r = await api.getWeekText()
                    await navigator.clipboard.writeText(r.text)
                    showToast('📋 週間予定と期限つき項目をコピーしました（そのまま貼り付けOK）')
                  } catch (e) { showToast('コピーに失敗しました: ' + e.message) }
                }}>
          📋 週間コピー
        </button>
      </div>
      <CalendarMonth
        settings={settings} onSettingsChange={onSettingsChange} showToast={showToast}
        onOpenDay={onOpenDay} />
    </div>
  )
}

function LifeIos({ settings, onSettingsChange, showToast, resetTick, jumpDate, jumpTick }) {
  const [offset, setOffset] = useState(0)  // 0=今日, -1=昨日 ...
  const [day, setDay] = useState(null)
  const [presence, setPresence] = useState(null) // 📷 その日の在席（F22。オフなら enabled=false）
  const [adding, setAdding] = useState(null) // 'entry' | 'event' | null
  const [page, setPage] = useState('main')   // 'main' | 'week'
  const [view, setView] = useState('timeline') // 'timeline' | 'list' | 'summary'
  const [filterCat, setFilterCat] = useState('all') // 📋一覧のカテゴリ絞り込み

  // ⌨️ キーボード操作（ライフタブ表示中のみ）：←→=前日/翌日・T=今日へ
  useEffect(() => {
    const h = (e) => {
      if (e.detail?.tab !== 'life') return
      if (e.detail.key === 'ArrowLeft') setOffset((o) => o - 1)
      if (e.detail.key === 'ArrowRight') setOffset((o) => o + 1)
      if (e.detail.key === 't' || e.detail.key === 'T') setOffset(0)
    }
    window.addEventListener('fc-key', h)
    return () => window.removeEventListener('fc-key', h)
  }, [])

  const d = new Date()
  d.setDate(d.getDate() + offset)
  const date = ymd(d)

  const reload = useCallback(() => {
    api.getLifeDay(date).then(setDay).catch(() => {})
    api.getPresenceDay(date).then(setPresence).catch(() => setPresence(null))
  }, [date])
  useEffect(() => { reload() }, [reload])

  // タブバーの「ライフ」を押すたびに初期状態（今日）へ戻す
  useEffect(() => {
    if (!resetTick) return // 初回マウント時は何もしない
    setPage('main')
    setAdding(null)
    setOffset(0)
  }, [resetTick])

  // 🗓 カレンダータブで日付を選んだとき、その日をここで開く
  // （ref で「新しいジャンプ要求のときだけ」動かす：タブ押下の作り直し時に古い日付へ飛ばないため）
  const jumpRef = useRef(jumpTick)
  useEffect(() => {
    if (jumpTick === jumpRef.current || !jumpDate) return
    jumpRef.current = jumpTick
    const t = new Date(); t.setHours(0, 0, 0, 0)
    const target = new Date(jumpDate + 'T00:00:00')
    if (!Number.isNaN(target.getTime())) {
      setOffset(Math.round((target - t) / 86400000))
      setPage('main')
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps -- 新しいジャンプ要求（jumpTick）のときだけ動かす
  }, [jumpTick])

  if (page === 'week') {
    return <WeekReport onBack={() => setPage('main')} />
  }

  // ---- 📖 その日の履歴（タイムライン・一覧・サマリー）と実績・予定の入力 ----

  // 予定（時間割＋単発）と実績（手入力＋勉強記録）を1本のリストに統合して時刻順に
  const items = []
  for (const b of day?.schedule ?? []) {
    items.push({ ...b, kind: 'schedule', label: '時間割' })
  }
  for (const ev of day?.events ?? []) {
    items.push({ ...ev, kind: 'event', label: '予定' })
  }
  // Googleメインカレンダー（読み取り専用：削除・休講などの操作なし）
  for (const [i, g] of (day?.google ?? []).entries()) {
    items.push({
      ...g, id: 'g' + (g.id || i), kind: 'google', label: 'Google',
      category: 'Google', start: g.allday ? '' : g.start, end: g.allday ? '終日' : g.end,
    })
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
    <div className="life fit-page">
      <div className="fit-head">
      <h1 className="ios-large-title">📖 今日</h1>

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
        <button className="small" onClick={() => setOffset(offset + 1)}>翌日 ›</button>
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
        <button onClick={() => setPage('week')}>
          📈 週次レポート
        </button>
      </div>
      {/* 表示切替：タイムライン（帯グラフ）⇄ 一覧 ⇄ サマリー */}
      <div className="seg" style={{ maxWidth: 520, margin: '10px 0 8px' }}>
        {[['timeline', '📊 タイムライン'], ['list', '📋 一覧'], ['summary', '📈 サマリー']].map(([v, lbl]) => (
          <button key={v} type="button"
                  className={'seg-btn' + (view === v ? ' on' : '')}
                  onClick={() => setView(v)}>
            {lbl}
          </button>
        ))}
      </div>
      </div>

      {/* ここから下は内側でスクロール（F23：ページ全体はスクロールしない） */}
      <div className="fit-body">
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

      {view === 'timeline' && (
        <TimelineDay day={day} date={date} isToday={offset === 0} presence={presence} />
      )}

      {view === 'summary' && (
        <SummaryDay date={date} settings={settings}
                    onSettingsChange={onSettingsChange} showToast={showToast} />
      )}

      {/* 📋一覧のカテゴリ絞り込み（その日の記録をカテゴリ別に見る） */}
      {view === 'list' && (() => {
        const cats = [...new Set(items.map((it) => it.category).filter(Boolean))]
        if (cats.length < 2) return null
        return (
          <div className="edit-row" style={{ flexWrap: 'wrap', margin: '2px 0 6px' }}>
            <button type="button" className={'sort-chip' + (filterCat === 'all' ? ' on' : '')}
                    onClick={() => setFilterCat('all')}>全部</button>
            {cats.map((c) => (
              <button key={c} type="button" className={'sort-chip' + (filterCat === c ? ' on' : '')}
                      onClick={() => setFilterCat(filterCat === c ? 'all' : c)}>{c}</button>
            ))}
          </div>
        )
      })()}

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
        {items.filter((it) => filterCat === 'all' || it.category === filterCat).map((it, i) => (
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
                        try {
                          await api.toggleCancellation(date, it.id)
                          reload()
                        } catch (err) { showToast('⚠️ ' + err.message) }
                      }}>
                {it.cancelled ? '↩' : '休講'}
              </button>
            )}
            {(it.kind === 'event' || it.kind === 'entry') && (
              <button className="icon" onClick={async () => {
                // 削除は必ず確認（誤タップ対策。アプリ全体で統一）
                if (!window.confirm(`「${it.title}」を削除しますか？`)) return
                try {
                  if (it.kind === 'event') await api.deleteLifeEvent(it.id)
                  else await api.deleteLifeEntry(it.id)
                  reload()
                  showToast('削除しました 🗑')
                } catch (err) { showToast('⚠️ ' + err.message) }
              }}>🗑</button>
            )}
          </div>
        ))}
      </div>
      <div className="caption" style={{ margin: '10px 4px' }}>
        💡 休講・削除などの操作は「📋 一覧」から。月の予定は「カレンダー」タブ、ルーレット項目と時間割は「その他」にあります。
        💻PCの自動記録は pc_tracker（start_all.bat で自動起動）が動いている間だけ記録されます。
      </div>
      </div>
    </div>
  )
}

export default LifeIos
