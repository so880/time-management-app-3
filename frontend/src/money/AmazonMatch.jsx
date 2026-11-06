// 💰 Amazon 注文の突き合わせ。MoneyIos.jsx から分けた（props・動作は同じ）
import { useState } from 'react'
import * as api from '../api.js'
import { yen } from './logic.js'
import { matchAmazonOrders, parseAmazonOrders, suggestAmazonCategory } from './amazon.js'

/* ---------- 📦 Amazon注文の突き合わせ ---------- */
function AmazonMatch({ entries, cats, onChanged, showToast }) {
  const [text, setText] = useState('')
  const [result, setResult] = useState(null) // {matches:[{order,entry,category,apply}], unmatched, candidates}
  const amazonCount = entries.filter((e) =>
    e.kind === 'spend' && /amazon|アマゾン|amzn/i.test(String(e.detail || ''))).length

  const analyze = () => {
    const orders = parseAmazonOrders(text)
    if (!orders.length) {
      // 何が足りないかを具体的に伝える（自己診断できるように）
      const t = String(text || '').normalize('NFKC')
      const nDates = (t.match(/20\d{2}年\s*\d{1,2}月\s*\d{1,2}日/g) || []).length
      const nTotals = (t.match(/合計|注文合計|請求額/g) || []).length
      showToast(nDates === 0
        ? '⚠️ 注文日（◯年◯月◯日）が見つかりません。注文履歴ページをCtrl+Aで全選択してコピーしてください'
        : nTotals === 0
          ? `⚠️ 日付は${nDates}件見つかりましたが「合計」が見つかりません。ページの表示を崩さずそのままコピーしてください`
          : '⚠️ 注文の形を読み取れませんでした。貼り付けた文章の一部（1注文分）を私に見せてもらえれば対応します')
      return
    }
    const r = matchAmazonOrders(orders, entries)
    setResult({
      ...r,
      matches: r.matches.map((m) => ({
        ...m,
        // 商品名専用のキーワード辞書でカテゴリを推定（食品・日用品・本など）
        category: suggestAmazonCategory(m.order.title, cats),
        title: m.order.title,
        apply: m.order.title !== '（商品名を読み取れず）',
      })),
    })
  }

  const applyAll = async () => {
    let n = 0
    try {
      for (const m of result.matches) {
        if (!m.apply) continue
        await api.patchMoneyEntry(m.entry.id, {
          detail: `Amazon: ${m.title}`.slice(0, 100),
          category: m.category,
        })
        n++
      }
    } catch (e) {
      // 途中で失敗したら、そこまでに反映した件数と理由を出す（一覧は読み直す）
      onChanged()
      showToast(`⚠️ ${n}件を反映したところで失敗しました：${e.message}`)
      return
    }
    setResult(null)
    setText('')
    onChanged()
    showToast(`📦 ${n}件のAmazon記録に商品名とカテゴリを反映しました ✅`)
  }

  return (
    <details className="ios-widget" style={{ marginBottom: 12 }}>
      <summary className="w-label" style={{ cursor: 'pointer' }}>
        📦 Amazon注文の突き合わせ{amazonCount > 0 ? `（AMAZON記録 ${amazonCount}件）` : ''}
      </summary>
      <div className="caption" style={{ margin: '6px 0' }}>
        カード明細では「AMAZON」としか分からない買い物に、<strong>商品名とカテゴリ</strong>を付けます。<br />
        ① ブラウザで <strong>amazon.co.jp → 注文履歴</strong> を開く（期間を選べます）<br />
        ② ページを <strong>Ctrl+A（全選択）→ Ctrl+C（コピー）</strong><br />
        ③ 下に貼り付けて「解析」→ 同じ金額（±5日）の記録と自動で突き合わせます
      </div>
      <textarea style={{ width: '100%', minHeight: 90 }}
                placeholder="ここに注文履歴ページを丸ごと貼り付け…"
                value={text} onChange={(e) => setText(e.target.value)} />
      <div className="edit-row" style={{ marginTop: 6 }}>
        <button className="small" onClick={analyze}>🔍 解析して突き合わせ</button>
        <button className="small" onClick={async () => {
          if (!window.confirm('突き合わせで付けた商品名・カテゴリをすべて取り消して「AMAZON.CO.JP／その他」に戻します。金額と日付は残ります。よろしいですか？')) return
          try {
            const r = await api.resetAmazonEnrichment()
            onChanged()
            showToast(`↩ ${r.reset}件のAmazon記録を元に戻しました`)
          } catch (e) { showToast('⚠️ ' + e.message) }
        }}>↩ 突き合わせを全部取り消す</button>
      </div>

      {result && (
        <div style={{ marginTop: 10 }}>
          <div className="caption">
            注文 {result.matches.length + result.unmatched.length}件を読み取り
            （金額は「合計」行のみから取得）／記録と一致 {result.matches.length}件
          </div>
          {result.unmatched.length > 0 && (
            <details style={{ margin: '6px 0' }}>
              <summary className="caption" style={{ cursor: 'pointer' }}>
                ⚠️ 一致する記録が見つからなかった注文 {result.unmatched.length}件（内容を確認）
              </summary>
              {result.unmatched.map((o, i) => (
                <div key={i} className="caption" style={{ paddingLeft: 12 }}>
                  {o.date}・{yen(o.amount)}・{o.title}
                </div>
              ))}
              <div className="caption" style={{ paddingLeft: 12 }}>
                ※コンビニ受け取り・ギフト券払い・別カード払いなどは記録側に存在しないため一致しません
              </div>
            </details>
          )}
          {result.matches.map((m, i) => (
            <div key={i} className={'edit-row' + (m.apply ? '' : ' m-off')} style={{ flexWrap: 'wrap' }}>
              <input type="checkbox" checked={m.apply}
                     onChange={(e) => {
                       const ms = [...result.matches]
                       ms[i] = { ...m, apply: e.target.checked }
                       setResult({ ...result, matches: ms })
                     }} />
              <span className="life-time">{m.entry.date}</span>
              <span className="hbar-val">{yen(m.entry.amount)}</span>
              <span className="caption" style={{ maxWidth: 130, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                    title={m.entry.detail}>← {m.entry.detail}</span>
              <input type="text" value={m.title} style={{ flex: 1, minWidth: 180 }}
                     onChange={(e) => {
                       const ms = [...result.matches]
                       ms[i] = { ...m, title: e.target.value }
                       setResult({ ...result, matches: ms })
                     }} />
              <select value={m.category}
                      onChange={(e) => {
                        const ms = [...result.matches]
                        ms[i] = { ...m, category: e.target.value }
                        setResult({ ...result, matches: ms })
                      }}>
                {cats.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
          ))}
          {result.matches.length > 0 && (
            <button className="w-action" onClick={applyAll}>
              ✅ チェックした{result.matches.filter((m) => m.apply).length}件に商品名とカテゴリを反映
            </button>
          )}
        </div>
      )}
    </details>
  )
}

export default AmazonMatch
