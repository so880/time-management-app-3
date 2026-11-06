// 起動時の「今日やること」入力画面：その日に初めて開いたとき全画面で出す。
// - 昨日までの未完了（必須＋期限つきルーレット項目）を1件ずつ行にして先頭に並べる
// - 各行：必須チェック／タイトル／タグ（選択 or 新規記入）／締切（任意）
// - 締切が今日・明日・期限切れ → 必須に自動格上げ（固定）。締切がその先 → ルーレット項目
// - 「今日を始める」で確定（空でも可）。settings.day_setup_date に今日が入り、同じ日は二度と出ない
import { useMemo, useState } from 'react'
import * as api from '../api.js'

const NEW_TAG = '__new__'

function fmtDate(s) {
  if (!s) return ''
  const [, m, d] = s.split('-')
  return `${parseInt(m, 10)}/${parseInt(d, 10)}`
}

function daysLeft(due, today) {
  if (!due) return null
  const a = new Date(due + 'T00:00:00')
  const b = new Date(today + 'T00:00:00')
  return Math.round((a - b) / 86400000)
}

function dueLabel(due, today) {
  const n = daysLeft(due, today)
  if (n === null) return ''
  if (n < 0) return `期限切れ（${-n}日前）`
  if (n === 0) return '今日が締切'
  if (n === 1) return '明日が締切'
  return `あと${n}日`
}

/* 1行（1件） */
function SetupRow({ row, tags, today, tomorrow, onChange, onRemove, onDone }) {
  const [typing, setTyping] = useState(false)   // 新しいタグを記入中
  const [draft, setDraft] = useState('')
  const forced = !!row.due && row.due <= tomorrow
  const isMust = forced || row.must
  const tagKnown = tags.some((t) => t.name === row.tag)
  const icon = (name) => tags.find((t) => t.name === name)?.icon ?? '🏷'

  const commitTag = () => {
    const v = draft.trim()
    if (v) onChange({ ...row, tag: v })
    setTyping(false)
    setDraft('')
  }

  const srcLabel = row.source === 'past_must' ? `↩ ${fmtDate(row.from_date)} の必須`
    : row.source === 'asg' ? '🎲 ルーレット項目'
    : row.source === 'today' ? '今日の必須（登録済み）'
    : '新規'

  return (
    <div className={'ds-row' + (isMust ? ' must' : '') + (forced ? ' forced' : '')}>
      <div className="ds-row-top">
        <label className="ds-must" title={forced ? '締切が近いため必須（変更できません）' : '今日の必須に入れる'}>
          <input type="checkbox" checked={isMust} disabled={forced}
                 onChange={(e) => onChange({ ...row, must: e.target.checked })} />
          <span>{isMust ? '🔴 必須' : '🎲 項目'}</span>
        </label>
        <input type="text" className="ds-title" value={row.title}
               placeholder="やること（例：ESを提出する）"
               onChange={(e) => onChange({ ...row, title: e.target.value })} />
        <span className="ds-src">{srcLabel}</span>
        {onDone && (
          <button type="button" className="small ds-done-btn" title="もう終わっている（完了にして、明日からも出さない）"
                  onClick={onDone}>✓ 終わった</button>
        )}
        <button type="button" className="icon"
                title={onDone ? '今日はやらない（未完了のままなので、明日また表示されます）' : 'この行を外す'}
                onClick={onRemove}>🗑</button>
      </div>
      <div className="ds-row-bottom">
        <span className="caption">タグ</span>
        {typing ? (
          <input type="text" className="ds-tag-input" value={draft} autoFocus
                 placeholder="新しいタグ名" onChange={(e) => setDraft(e.target.value)}
                 onBlur={commitTag}
                 onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); commitTag() } if (e.key === 'Escape') { setTyping(false); setDraft('') } }} />
        ) : (
          <select className="ds-tag" value={row.tag || ''}
                  onChange={(e) => {
                    if (e.target.value === NEW_TAG) { setTyping(true); return }
                    onChange({ ...row, tag: e.target.value })
                  }}>
            <option value="">（なし）</option>
            {tags.map((t) => <option key={t.name} value={t.name}>{t.icon} {t.name}</option>)}
            {row.tag && !tagKnown && <option value={row.tag}>🏷 {row.tag}</option>}
            <option value={NEW_TAG}>＋ 新しいタグを記入…</option>
          </select>
        )}
        <span className="caption" style={{ marginLeft: 8 }}>締切</span>
        <input type="date" className="ds-due" value={row.due || ''}
               onChange={(e) => onChange({ ...row, due: e.target.value })} />
        {row.due && (
          <button type="button" className="icon" title="締切を消す"
                  onClick={() => onChange({ ...row, due: '' })}>✕</button>
        )}
        {row.due && (
          <span className={'ds-due-label' + (forced ? ' hot' : '')}>
            {icon(row.tag)} {dueLabel(row.due, today)}
          </span>
        )}
        {forced && <span className="ds-forced">⚠ 締切が近いので必須に固定</span>}
        {!forced && row.due && !row.must && <span className="caption">→ ルーレット項目として登録</span>}
      </div>
    </div>
  )
}

let seq = 0
const newKey = () => `n${Date.now()}-${seq++}`

function DaySetup({ setup, onDone, showToast }) {
  // 初期値だけ setup から取る（30秒ごとの再取得で入力中の内容が消えないように）
  const [rows, setRows] = useState(() => (setup.rows ?? []).map((r) => ({ ...r })))
  const [tags, setTags] = useState(setup.tags ?? [])
  const [paste, setPaste] = useState(false)
  const [pasteText, setPasteText] = useState('')
  const [busy, setBusy] = useState(false)
  const today = setup.date
  const tomorrow = setup.tomorrow

  const update = (key, next) => {
    setRows((rs) => rs.map((r) => (r.key === key ? next : r)))
    // 記入した新しいタグは、他の行の選択肢にもすぐ出す
    if (next.tag && !tags.some((t) => t.name === next.tag)) {
      setTags((ts) => [...ts, { name: next.tag, icon: '🏷' }])
    }
  }
  const remove = (key) => setRows((rs) => rs.filter((r) => r.key !== key))
  // 繰り越し行（昨日までの必須・期限つきルーレット項目）を「もう終わった」にする。確定時に完了として記録
  const [doneRows, setDoneRows] = useState([])
  const isCarried = (r) => r.source === 'past_must' || r.source === 'asg'
  const markDone = (r) => {
    setRows((rs) => rs.filter((x) => x.key !== r.key))
    setDoneRows((ds) => [...ds, r])
  }
  const undoDone = (r) => {
    setDoneRows((ds) => ds.filter((x) => x.key !== r.key))
    setRows((rs) => [r, ...rs])
  }
  const addRow = () => setRows((rs) => [...rs, {
    key: newKey(), source: 'new', title: '', tag: '', due: '', must: true, forced: false, asg_id: null,
  }])
  const addPasted = () => {
    const lines = pasteText.split('\n').map((s) => s.trim()).filter(Boolean)
    if (lines.length === 0) return
    setRows((rs) => [...rs, ...lines.map((title) => ({
      key: newKey(), source: 'new', title, tag: '', due: '', must: true, forced: false, asg_id: null,
    }))])
    setPasteText('')
    setPaste(false)
  }

  // 表示は3グループ：締切が近い（固定）／今日の必須／ルーレット項目へ
  const groups = useMemo(() => {
    const valid = rows
    const forced = valid.filter((r) => r.due && r.due <= tomorrow)
    const must = valid.filter((r) => !(r.due && r.due <= tomorrow) && r.must)
    const rest = valid.filter((r) => !(r.due && r.due <= tomorrow) && !r.must)
    return { forced, must, rest }
  }, [rows, tomorrow])
  const nMust = rows.filter((r) => r.title.trim() && ((r.due && r.due <= tomorrow) || r.must)).length
  const nRoulette = rows.filter((r) => r.title.trim() && r.due).length

  const confirm = async () => {
    if (busy) return
    setBusy(true)
    try {
      const body = rows
        .filter((r) => r.title.trim())
        .map((r) => ({ title: r.title.trim(), tag: r.tag || '', due: r.due || '',
                       must: !!r.must, asg_id: r.asg_id ?? null }))
      const r = await api.confirmDaySetup(body, doneRows.map((d) => d.key))
      onDone(r)
      showToast?.(`今日を開始：必須 ${r.result?.must ?? nMust} 件・ルーレット項目 ${r.result?.roulette ?? nRoulette} 件`
        + (doneRows.length ? `・完了にした ${r.result?.done ?? doneRows.length} 件` : ''))
    } catch (e) {
      showToast?.('確定できませんでした：' + (e?.message ?? ''))
    } finally {
      setBusy(false)
    }
  }

  const renderGroup = (title, list, hint) => (
    <div className="ds-group">
      <div className="ds-group-h">{title}<span className="caption">　{hint}</span></div>
      {list.length === 0 && <div className="caption ds-empty">なし</div>}
      {list.map((r) => (
        <SetupRow key={r.key} row={r} tags={tags} today={today} tomorrow={tomorrow}
                  onChange={(next) => update(r.key, next)} onRemove={() => remove(r.key)}
                  onDone={isCarried(r) ? () => markDone(r) : null} />
      ))}
    </div>
  )

  return (
    <div className="day-setup">
      <div className="day-setup-card">
        <h2 style={{ margin: '0 0 4px' }}>🌅 今日やることを決める</h2>
        <div className="caption" style={{ marginBottom: 12 }}>
          {today}　昨日までの未完了（{setup.carry_count ?? 0}件）を先頭に並べています。
          締切が<strong>今日・明日・期限切れ</strong>のものは自動で必須になります（固定）。
          締切がその先のものは🎲ルーレット項目として登録され、カレンダーと「今日やること」に出ます。
        </div>

        {renderGroup('⚠ 締切が近い（必須に固定）', groups.forced, '期限切れ・今日・明日')}
        {renderGroup('🔴 今日の必須', groups.must, 'チェックを外すと必須から外れます')}
        {renderGroup('🎲 ルーレット項目へ（必須にしない）', groups.rest, '締切を入れるとカレンダーに出ます')}
        {doneRows.length > 0 && (
          <div className="ds-group ds-done-list">
            <div className="ds-group-h">✓ 終わったもの（{doneRows.length}件）<span className="caption">　「今日を始める」で完了として記録し、明日からは出しません</span></div>
            {doneRows.map((r) => (
              <div key={r.key} className="day-setup-row">
                <span className="habit-done">{r.title}</span>
                <button type="button" className="small" onClick={() => undoDone(r)}>元に戻す</button>
              </div>
            ))}
          </div>
        )}

        <div className="edit-row" style={{ marginTop: 10, flexWrap: 'wrap' }}>
          <button type="button" className="small" onClick={addRow}>＋ 行を追加</button>
          <button type="button" className="small" onClick={() => setPaste(!paste)}>
            📋 まとめて貼り付け（1行1件）
          </button>
        </div>
        {paste && (
          <div style={{ marginTop: 6 }}>
            <textarea className="day-setup-text" style={{ minHeight: 110 }} value={pasteText}
                      placeholder={'例）\nESを提出する\n履修登録を済ませる'}
                      onChange={(e) => setPasteText(e.target.value)} spellCheck={false} />
            <div className="edit-row">
              <button type="button" className="small" onClick={addPasted}>行に追加する</button>
              <span className="caption">追加後にタグ・締切を1件ずつ付けられます</span>
            </div>
          </div>
        )}

        <div className="day-setup-cols">
          <div>
            <div className="day-setup-h">🔁 今日の習慣（{(setup.habits ?? []).length}）</div>
            {(setup.habits ?? []).length === 0 && <div className="caption">なし</div>}
            {(setup.habits ?? []).map((h) => (
              <div key={h.id} className="day-setup-row">
                <span>{h.title}</span>
                <span className="caption">
                  {h.start}{h.end ? `〜${h.end}` : ''}{h.forced ? '　必須扱い' : ''}
                </span>
              </div>
            ))}
          </div>
          <div>
            <div className="day-setup-h">📅 週単位・不定期（{(setup.periodic ?? []).length}）</div>
            {(setup.periodic ?? []).length === 0 && <div className="caption">なし</div>}
            {(setup.periodic ?? []).map((p) => (
              <div key={p.id} className="day-setup-row">
                <span>{p.title}</span>
                <span className="caption">
                  {p.everyDays > 0 ? `${p.everyDays}日ごと` : '不定期'}
                  {p.due ? '　⏰ そろそろ' : ''}
                </span>
              </div>
            ))}
          </div>
        </div>

        <button className="primary day-setup-go" onClick={confirm} disabled={busy}>
          ▶ 今日を始める（必須 {nMust} 件・ルーレット項目 {nRoulette} 件）
        </button>
        <div className="caption" style={{ textAlign: 'center', marginTop: 6 }}>
          空のまま始めることもできます。確定後の変更は「その他 › 制限の設定」「その他 › ルーレット項目」から
        </div>
      </div>
    </div>
  )
}

export default DaySetup
