// 💰 マネータブの小さな部品（評価バッジ・星・AI判定の印）。MoneyIos.jsx から分けた（中身は同じ）
import { REC_LABEL, VALIDITY_LABEL } from './logic.js'

/* ---------- 小さな部品 ---------- */
export function Badge({ validity }) {
  const v = validity || 'unrated'
  return <span className={`m-badge v-${v}`}>{VALIDITY_LABEL[v]}</span>
}
export function RecBadge({ rec }) {
  const r = rec || 'consider'
  return <span className={`m-badge rec-${r}`}>{REC_LABEL[r]}</span>
}
export function Stars({ value, onSet }) {
  return (
    <span className="m-stars">
      {[1, 2, 3, 4, 5].map((i) => (
        <button key={i} type="button"
                className={'m-star' + ((value ?? 0) >= i ? ' on' : '')}
                onClick={() => onSet(value === i ? 0 : i)}>★</button>
      ))}
    </span>
  )
}
export function starText(n) {
  if (!n) return null
  return <span className="m-startext">{'★'.repeat(n)}{'☆'.repeat(5 - n)}</span>
}
export function aiTag(e) {
  return e.method === 'ai' ? <span className="ai-tag"> AI判定</span> : null
}
