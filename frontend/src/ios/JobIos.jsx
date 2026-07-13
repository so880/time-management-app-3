// 💼 就活タブ（夏インターン・本選考の管理）
// - 応募先カード：選考状況（固定の段階）・優先度（高/中/低）・提出した内容・メモ
// - 日程：説明会/面接/インターン期間（期間ものは終了日つき）
// - 日程が被ったら上部に警告カードを表示（応募先の優先度の高い順に並ぶ）
// - Googleカレンダーには 💼 付きで自動送信される（ブリッジ接続後）
import { useEffect, useState } from 'react'
import * as api from '../api.js'

const PRIORITIES = [
  { value: 1, label: '高' },
  { value: 2, label: '中' },
  { value: 3, label: '低' },
]
const KINDS = [
  { value: 'intern', label: '夏インターン' },
  { value: 'fulltime', label: '本選考' },
]
const STATUS_COLORS = {
  '気になる': '#8e8e93', 'ES提出': '#0a84ff', 'Webテスト': '#5e5ce6',
  '面接': '#ff9f0a', '内定': '#30d158', 'お見送り': '#ff453a',
}

const emptyForm = {
  company: '', title: '', kind: 'intern', status: '気になる',
  priority: 2, submitted: '', note: '',
}
const emptyEvent = { label: '', date: '', endDate: '', start: '', end: '', choice: 0 }

// 選考状況チップ（選択中は状態色で塗って「押されている」ことが分かるように）
function StatusChips({ statuses, value, onPick }) {
  return (
    <div className="job-chip-row">
      {statuses.map((s) => {
        const on = value === s
        const c = STATUS_COLORS[s] || '#8e8e93'
        return (
          <button key={s} type="button"
                  className={'sort-chip' + (on ? ' on' : '')}
                  style={on ? { background: c, borderColor: c, color: '#fff' } : undefined}
                  onClick={() => onPick(s)}>
            {on ? '● ' : ''}{s}
          </button>
        )
      })}
    </div>
  )
}

// 「第N希望」バッジ（0=確定は表示なし）
const ChoiceBadge = ({ choice }) =>
  choice > 0 ? <span className="job-choice">第{choice}希望</span> : null

// 希望順の選択（確定＝1つに決まった日程／第1〜第4希望＝候補日）
function ChoiceSelect({ value, onChange }) {
  return (
    <select value={value} onChange={(e) => onChange(parseInt(e.target.value, 10))}
            title="候補日が複数あるときは第1希望・第2希望…を付けられます">
      <option value={0}>確定</option>
      {[1, 2, 3, 4].map((n) => <option key={n} value={n}>第{n}希望</option>)}
    </select>
  )
}

function JobIos({ showToast, resetTick }) {
  const [apps, setApps] = useState([])
  const [statuses, setStatuses] = useState(['気になる', 'ES提出', 'Webテスト', '面接', '内定', 'お見送り'])
  const [conflicts, setConflicts] = useState([])
  const [standalone, setStandalone] = useState([]) // 会社に紐づかない就活予定
  const [sheet, setSheet] = useState(null)   // null / {mode:'new'} / {mode:'edit', app}
  const [form, setForm] = useState(emptyForm)
  const [openId, setOpenId] = useState(null) // 詳細を開いている応募先ID
  const [evForm, setEvForm] = useState(emptyEvent)
  const [saForm, setSaForm] = useState(emptyEvent)   // 単独予定の入力
  const [quick, setQuick] = useState({ company: '', note: '' }) // 気になる企業のサッと追加

  const reload = async () => {
    try {
      const r = await api.getJobs()
      setApps(r.applications)
      setStatuses(r.statuses)
      setConflicts(r.conflicts)
      setStandalone(r.standalone ?? [])
    } catch (e) {
      showToast?.(String(e.message || e))
    }
  }
  useEffect(() => { reload() }, [])

  // タブバーの「就活」を押すたびに初期状態（一覧を閉じた状態）へ戻す
  useEffect(() => {
    if (!resetTick) return
    setSheet(null)
    setOpenId(null)
    setEvForm(emptyEvent)
    setSaForm(emptyEvent)
    reload() // 最新の状態も取り直す
  }, [resetTick])

  // 会社名だけで「気になる」に追加（応募を考えている企業のメモ）
  const quickAdd = async () => {
    if (!quick.company.trim()) { showToast?.('会社名を入力してください'); return }
    try {
      await api.addJob({ ...emptyForm, company: quick.company.trim(),
                         status: '気になる', note: quick.note.trim() })
      setQuick({ company: '', note: '' })
      await reload()
      showToast?.('「気になる」に追加しました ✅')
    } catch (e) { showToast?.(String(e.message || e)) }
  }

  // 会社に紐づかない就活予定（合同説明会など）
  const addStandalone = async () => {
    if (!saForm.date) { showToast?.('日付を入力してください'); return }
    if (!saForm.label.trim()) { showToast?.('予定の名前を入力してください'); return }
    try {
      await api.addJobEvent({ applicationId: 0, ...saForm })
      setSaForm(emptyEvent)
      await reload()
    } catch (e) { showToast?.(String(e.message || e)) }
  }

  const openNew = () => { setForm(emptyForm); setSheet({ mode: 'new' }) }
  const openEdit = (a) => {
    setForm({ company: a.company, title: a.title, kind: a.kind, status: a.status,
              priority: a.priority, submitted: a.submitted, note: a.note })
    setSheet({ mode: 'edit', app: a })
  }

  const save = async () => {
    try {
      if (sheet.mode === 'new') await api.addJob(form)
      else await api.updateJob(sheet.app.id, form)
      setSheet(null)
      await reload()
      showToast?.('保存しました')
    } catch (e) { showToast?.(String(e.message || e)) }
  }

  const remove = async (a) => {
    if (!window.confirm(`「${a.company}」を日程ごと削除しますか？`)) return
    try { await api.deleteJob(a.id); await reload() } catch (e) { showToast?.(String(e.message || e)) }
  }

  const quickStatus = async (a, status) => {
    try {
      await api.updateJob(a.id, { company: a.company, title: a.title, kind: a.kind,
        status, priority: a.priority, submitted: a.submitted, note: a.note })
      await reload()
    } catch (e) { showToast?.(String(e.message || e)) }
  }

  const addEvent = async (a) => {
    if (!evForm.date) { showToast?.('日付を入力してください'); return }
    try {
      await api.addJobEvent({ applicationId: a.id, ...evForm })
      setEvForm(emptyEvent)
      await reload()
    } catch (e) { showToast?.(String(e.message || e)) }
  }

  const removeEvent = async (id) => {
    try { await api.deleteJobEvent(id); await reload() } catch (e) { showToast?.(String(e.message || e)) }
  }

  const fmtSpan = (e) =>
    e.endDate && e.endDate !== e.date
      ? `${e.date} 〜 ${e.endDate}`
      : e.date + (e.start ? ` ${e.start}${e.end ? `〜${e.end}` : ''}` : '')

  const interns = apps.filter((a) => a.kind === 'intern')
  const fulls = apps.filter((a) => a.kind === 'fulltime')

  const renderCard = (a) => (
    <div key={a.id} className="job-card">
      <button type="button" className="job-head"
              onClick={() => setOpenId(openId === a.id ? null : a.id)}>
        <div className="job-titles">
          <div className="job-company">
            {a.company}
            <span className={'job-pri p' + a.priority}>優先{a.priorityLabel}</span>
          </div>
          {a.title && <div className="job-role">{a.title}</div>}
        </div>
        <span className="job-status" style={{ background: STATUS_COLORS[a.status] || '#8e8e93' }}>
          {a.status}
        </span>
      </button>

      {/* 次の日程（閉じていても見える） */}
      {a.events.length > 0 && (
        <div className="job-next">
          📅 {a.events[0].label || '日程'}：{fmtSpan(a.events[0])}
          {a.events.length > 1 && ` ほか${a.events.length - 1}件`}
        </div>
      )}

      {openId === a.id && (
        <div className="job-detail">
          {/* 選考状況をその場で進める（選択中は色付き＋●） */}
          <div className="caption">選考状況（タップで変更・色が付いているのが今の状況）</div>
          <StatusChips statuses={statuses} value={a.status}
                       onPick={(s) => quickStatus(a, s)} />

          {a.submitted && (
            <div className="job-block">
              <div className="caption">📄 提出した内容</div>
              <div className="job-block-body">{a.submitted}</div>
            </div>
          )}
          {a.note && (
            <div className="job-block">
              <div className="caption">📝 メモ</div>
              <div className="job-block-body">{a.note}</div>
            </div>
          )}

          <div className="job-block">
            <div className="caption">
              📅 日程（期間ものは終了日も。候補日が複数あるときは「第N希望」を付けると希望順に並びます）
            </div>
            {a.events.map((e) => (
              <div key={e.id} className="job-event-row">
                <span>
                  {e.label || '日程'}｜{fmtSpan(e)} <ChoiceBadge choice={e.choice} />
                </span>
                <button type="button" className="icon" onClick={() => removeEvent(e.id)}>✕</button>
              </div>
            ))}
            <div className="edit-row">
              <input type="text" placeholder="例: 一次面接 / インターン本番"
                     value={evForm.label}
                     onChange={(e) => setEvForm({ ...evForm, label: e.target.value })} />
              <ChoiceSelect value={evForm.choice}
                            onChange={(v) => setEvForm({ ...evForm, choice: v })} />
            </div>
            <div className="edit-row">
              <input type="date" value={evForm.date}
                     onChange={(e) => setEvForm({ ...evForm, date: e.target.value })} />
              <span>〜</span>
              <input type="date" value={evForm.endDate}
                     onChange={(e) => setEvForm({ ...evForm, endDate: e.target.value })} />
            </div>
            <div className="edit-row">
              <input type="time" value={evForm.start}
                     onChange={(e) => setEvForm({ ...evForm, start: e.target.value })} />
              <span>〜</span>
              <input type="time" value={evForm.end}
                     onChange={(e) => setEvForm({ ...evForm, end: e.target.value })} />
              <button type="button" className="small" onClick={() => addEvent(a)}>＋ 追加</button>
            </div>
          </div>

          <div className="job-actions">
            <button type="button" className="small" onClick={() => openEdit(a)}>✏️ 編集</button>
            <button type="button" className="small job-danger" onClick={() => remove(a)}>🗑 削除</button>
          </div>
        </div>
      )}
    </div>
  )

  return (
    <div className="job-ios">
      <h1 className="ios-large-title">💼 就活</h1>

      {/* 日程の被り警告（応募先の優先度の高い順） */}
      {conflicts.map((c, i) => (
        <div key={i} className="job-conflict">
          <div className="job-conflict-title">⚠️ 日程が被っています（{c.dates}）</div>
          {c.events.map((e, j) => (
            <div key={e.id} className="job-conflict-row">
              <span className={'job-pri p' + (e.priority ?? 2)}>{j + 1}位 優先{e.priorityLabel}</span>
              <span>{e.company || '（就活予定）'} {e.label}（{fmtSpan(e)}）<ChoiceBadge choice={e.choice} /></span>
            </div>
          ))}
          <div className="caption">↑ 上を優先する想定の並びです（優先度は各カードの✏️編集で変更）</div>
        </div>
      ))}

      {/* 応募を考えている企業をサッとメモ（会社名だけでOK → 気になるに入る） */}
      <div className="job-card">
        <div className="caption">🔖 応募を考えている企業をメモ（会社名だけでOK・「気になる」に入ります）</div>
        <div className="edit-row">
          <input type="text" placeholder="会社名" value={quick.company} style={{ width: 160 }}
                 onChange={(e) => setQuick({ ...quick, company: e.target.value })} />
          <input type="text" placeholder="メモ（例: 夏インターン締切7/25・友達の紹介）" value={quick.note}
                 style={{ flex: 1 }}
                 onChange={(e) => setQuick({ ...quick, note: e.target.value })} />
          <button type="button" className="small" onClick={quickAdd}>＋ 追加</button>
        </div>
      </div>

      <button type="button" className="primary job-add" onClick={openNew}>＋ 応募先を追加</button>

      {/* 会社に紐づかない就活予定（合同説明会・就活イベントなど） */}
      <h2 className="ios-section-title">📅 就活の予定（会社に紐づかないもの・{standalone.length}）</h2>
      <div className="job-card">
        {standalone.length === 0 && <div className="caption">合同説明会・就活イベントなどはここに追加できます。</div>}
        {standalone.map((e) => (
          <div key={e.id} className="job-event-row">
            <span>{e.label || '予定'}｜{fmtSpan(e)} <ChoiceBadge choice={e.choice} /></span>
            <button type="button" className="icon" onClick={() => removeEvent(e.id)}>✕</button>
          </div>
        ))}
        <div className="edit-row">
          <input type="text" placeholder="例: 合同説明会（長野）" value={saForm.label} style={{ flex: 1 }}
                 onChange={(e) => setSaForm({ ...saForm, label: e.target.value })} />
          <ChoiceSelect value={saForm.choice}
                        onChange={(v) => setSaForm({ ...saForm, choice: v })} />
        </div>
        <div className="edit-row">
          <input type="date" value={saForm.date}
                 onChange={(e) => setSaForm({ ...saForm, date: e.target.value })} />
          <span>〜</span>
          <input type="date" value={saForm.endDate}
                 onChange={(e) => setSaForm({ ...saForm, endDate: e.target.value })} />
          <input type="time" value={saForm.start}
                 onChange={(e) => setSaForm({ ...saForm, start: e.target.value })} />
          <span>〜</span>
          <input type="time" value={saForm.end}
                 onChange={(e) => setSaForm({ ...saForm, end: e.target.value })} />
          <button type="button" className="small" onClick={addStandalone}>＋ 追加</button>
        </div>
      </div>

      <h2 className="ios-section-title">☀️ 夏インターン（{interns.length}）</h2>
      {interns.length === 0 && <div className="caption job-empty">まだ登録がありません</div>}
      {interns.map(renderCard)}

      <h2 className="ios-section-title">🏢 本選考（{fulls.length}）</h2>
      {fulls.length === 0 && <div className="caption job-empty">まだ登録がありません</div>}
      {fulls.map(renderCard)}

      {/* 追加・編集シート */}
      {sheet && (
        <div className="ios-sheet-backdrop" onClick={() => setSheet(null)}>
          <div className="ios-sheet job-sheet" onClick={(e) => e.stopPropagation()}>
            <div className="ios-grabber" />
            <h3>{sheet.mode === 'new' ? '応募先を追加' : `${sheet.app.company} を編集`}</h3>

            <div className="caption">会社名（必須）</div>
            <div className="edit-row">
              <input type="text" value={form.company}
                     onChange={(e) => setForm({ ...form, company: e.target.value })} />
            </div>

            <div className="caption">職種・コース名</div>
            <div className="edit-row">
              <input type="text" value={form.title} placeholder="例: エンジニア職 5daysインターン"
                     onChange={(e) => setForm({ ...form, title: e.target.value })} />
            </div>

            <div className="caption">種別</div>
            <div className="seg">
              {KINDS.map((k) => (
                <button key={k.value} type="button"
                        className={'seg-btn' + (form.kind === k.value ? ' on' : '')}
                        onClick={() => setForm({ ...form, kind: k.value })}>{k.label}</button>
              ))}
            </div>

            <div className="caption">選考状況（色が付いているのが選択中）</div>
            <StatusChips statuses={statuses} value={form.status}
                         onPick={(s) => setForm({ ...form, status: s })} />

            <div className="caption">優先度（日程が被ったときに優先する順）</div>
            <div className="seg">
              {PRIORITIES.map((p) => (
                <button key={p.value} type="button"
                        className={'seg-btn' + (form.priority === p.value ? ' on' : '')}
                        onClick={() => setForm({ ...form, priority: p.value })}>{p.label}</button>
              ))}
            </div>

            <div className="caption">提出した内容（ES・ポートフォリオなど）</div>
            <div className="edit-row">
              <textarea rows={4} value={form.submitted}
                        placeholder="例: 6/20 ES提出（ガクチカ=時間管理アプリ開発 / 志望動機=…）"
                        onChange={(e) => setForm({ ...form, submitted: e.target.value })} />
            </div>

            <div className="caption">メモ</div>
            <div className="edit-row">
              <textarea rows={2} value={form.note}
                        onChange={(e) => setForm({ ...form, note: e.target.value })} />
            </div>

            <div className="job-actions">
              <button type="button" className="primary" onClick={save}>保存</button>
              <button type="button" className="small" onClick={() => setSheet(null)}>キャンセル</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default JobIos
