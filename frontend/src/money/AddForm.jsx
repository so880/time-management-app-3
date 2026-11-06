// 💰 記録の追加フォーム（支出・固定費/サブスク・欲しい物）。MoneyIos.jsx から分けた（props・動作は同じ）
import { useState } from 'react'
import * as api from '../api.js'
import { NEED_LABEL, USAGE_LABEL, todayStr } from './logic.js'
import { Stars } from './parts.jsx'

/* ---------- 記録の追加フォーム ---------- */
function AddForm({ cats, onAdded, aiOn }) {
  const [kind, setKind] = useState('spend')
  const [amount, setAmount] = useState('')
  const [date, setDate] = useState(todayStr())
  const [category, setCategory] = useState(cats[0] ?? 'その他')
  const [detail, setDetail] = useState('')
  const [sat, setSat] = useState(0)
  const [planMonths, setPlanMonths] = useState('')
  const [usage, setUsage] = useState('weekly')
  const [reason, setReason] = useState('')
  const [need, setNeed] = useState('mid')
  const [want, setWant] = useState(0)
  const [owned, setOwned] = useState('')
  const [better, setBetter] = useState('')
  const [msg, setMsg] = useState(null)

  const TEXT = {
    spend: { amount: '金額（円）', detail: '用途の詳細（任意）', btn: '支出を記録する' },
    sub: { amount: '支払った金額（プラン全体・円）', detail: 'サブスクの名前（任意）', btn: '固定費・サブスクを記録する' },
    wish: { amount: '値段（円）', detail: '欲しいものの名前（必須）', btn: '欲しい物リストに追加する' },
  }[kind]

  const submit = async () => {
    try {
      const e = await api.addMoneyEntry({
        kind, date, amount: Number(amount), category, detail,
        satisfaction: kind === 'spend' ? (sat || null) : null,
        planMonths: kind === 'sub' ? (Number(planMonths) || null) : null,
        usage: kind === 'sub' ? usage : null,
        reason: kind === 'sub' || kind === 'wish' ? reason : '',
        need: kind === 'wish' ? need : null,
        wantLevel: kind === 'wish' ? (want || null) : null,
        ownedSimilar: kind === 'wish' ? owned : '',
        betterPoint: kind === 'wish' ? better : '',
      })
      setAmount(''); setDetail(''); setPlanMonths(''); setReason('')
      setOwned(''); setBetter(''); setSat(0); setWant(0)
      setMsg({ ok: true, text: '記録しました。' })
      onAdded()
      // AI判定が有効なら非同期で差し替え（失敗しても簡易判定が残る）
      if (aiOn) api.moneyAiJudge(e.id).then(onAdded).catch(() => {})
    } catch (err) {
      setMsg({ ok: false, text: err.message })
    }
  }

  return (
    <details className="ios-widget" style={{ marginBottom: 12 }} open>
      <summary className="w-label" style={{ cursor: 'pointer' }}>➕ 記録の追加</summary>
      <div className="seg" style={{ marginBottom: 10, marginTop: 8 }}>
        {[['spend', '通常の支出'], ['sub', '固定費・サブスク'], ['wish', '欲しい物']].map(([k, l]) => (
          <button key={k} type="button" className={'seg-btn' + (kind === k ? ' on' : '')}
                  onClick={() => setKind(k)}>{l}</button>
        ))}
      </div>
      <div className="edit-row">
        <label style={{ flex: 1 }}>{TEXT.amount}
          <input type="number" min="0" value={amount} style={{ width: '100%' }}
                 onChange={(e) => setAmount(e.target.value)} />
        </label>
        <label>日付
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        </label>
        <label>カテゴリ
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            {cats.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
      </div>
      {kind === 'sub' && (
        <div className="edit-row">
          <label>契約プラン（月数・必須）
            <input type="number" min="1" placeholder="年払いなら 12" value={planMonths}
                   style={{ width: 130 }} onChange={(e) => setPlanMonths(e.target.value)} />
          </label>
          <label>使用頻度
            <select value={usage} onChange={(e) => setUsage(e.target.value)}>
              {Object.entries(USAGE_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select>
          </label>
          <label style={{ flex: 1 }}>契約している理由（任意）
            <input type="text" value={reason} style={{ width: '100%' }}
                   onChange={(e) => setReason(e.target.value)} />
          </label>
        </div>
      )}
      {kind === 'wish' && (
        <>
          <div className="edit-row">
            <label>必要度
              <select value={need} onChange={(e) => setNeed(e.target.value)}>
                {Object.entries(NEED_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select>
            </label>
            <label>どれくらい欲しい？ <Stars value={want} onSet={setWant} /></label>
          </div>
          <div className="edit-row">
            <input type="text" placeholder="欲しい理由（任意）" value={reason}
                   onChange={(e) => setReason(e.target.value)} />
            <input type="text" placeholder="似ていて既に持っている物（任意）" value={owned}
                   onChange={(e) => setOwned(e.target.value)} />
            <input type="text" placeholder="欲しい物のどこが良いか（任意）" value={better}
                   onChange={(e) => setBetter(e.target.value)} />
          </div>
        </>
      )}
      <div className="edit-row">
        <input type="text" placeholder={TEXT.detail} value={detail} style={{ flex: 1 }}
               onChange={(e) => setDetail(e.target.value)} />
        {kind === 'spend' && <label>満足感 <Stars value={sat} onSet={setSat} /></label>}
      </div>
      <button className="w-action" onClick={submit}>{TEXT.btn}</button>
      {msg && <div className={msg.ok ? 'success-box' : 'warn-box'} style={{ marginTop: 8 }}>{msg.text}</div>}
    </details>
  )
}

export default AddForm
