// 💰 未分類（その他）の仕分け。MoneyIos.jsx から分けた（props・動作は同じ）
import * as api from '../api.js'
import { yen } from './logic.js'

/* ---------- 🧹 未分類の仕分け（「その他」をタップで高速分類） ---------- */
function SortUncategorized({ entries, cats, onChanged, showToast }) {
  const targets = entries
    .filter((e) => e.kind === 'spend' && e.category === 'その他')
    .sort((a, b) => (a.date < b.date ? 1 : -1))
  if (targets.length === 0) return null
  return (
    <details className="ios-widget" style={{ marginBottom: 12 }}>
      <summary className="w-label" style={{ cursor: 'pointer' }}>
        🧹 未分類の仕分け（{targets.length}件）— タップするだけ
      </summary>
      <div className="caption" style={{ margin: '6px 0' }}>
        自動取り込みで「その他」になった記録です。カテゴリをタップすると即保存され、
        <strong>同じお店は次回から自動で正しく分類</strong>されます（Amazonは下の「📦突き合わせ」が便利）。
      </div>
      {targets.slice(0, 30).map((e) => (
        <div key={e.id} className="sort-row">
          <div className="sort-head">
            <span className="life-time">{e.date}</span>
            <span className="m-title">{e.detail || '（内容なし）'}</span>
            <span className="m-amount">{yen(e.amount)}</span>
          </div>
          <div className="sort-chips">
            {cats.filter((c) => c !== 'その他').map((c) => (
              <button key={c} type="button" className="sort-chip"
                      onClick={async () => {
                        try {
                          await api.patchMoneyEntry(e.id, { category: c })
                          onChanged()
                        } catch (err) { showToast('⚠️ ' + err.message) }
                      }}>{c}</button>
            ))}
          </div>
        </div>
      ))}
      {targets.length > 30 && <div className="caption">まず30件を表示中（仕分けると次が出ます）</div>}
    </details>
  )
}

export default SortUncategorized
