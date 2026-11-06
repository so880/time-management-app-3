// 💰 利用明細 CSV の取り込み。MoneyIos.jsx から分けた（props・動作は同じ）
import { useState } from 'react'
import * as api from '../api.js'
import { yen } from './logic.js'
import { autoDetectColumns, buildImportItems, decodeCSVBuffer, parseCSV } from './csv.js'

/* ---------- CSV取り込み ---------- */
function CsvImport({ entries, cats, shopMap, onImported, showToast }) {
  const [state, setState] = useState(null) // {rows, cols, mapping, items}
  const [msg, setMsg] = useState('')

  const onFile = async (e) => {
    const f = e.target.files?.[0]
    if (!f) return
    const buf = await f.arrayBuffer()
    const rows = parseCSV(decodeCSVBuffer(buf))
    if (!rows.length) { setMsg('CSVを読み取れませんでした。'); setState(null); return }
    const det = autoDetectColumns(rows)
    if (det.date < 0) det.date = 0
    if (det.amount < 0) det.amount = Math.min(1, det.cols - 1)
    if (det.desc < 0) det.desc = Math.min(2, det.cols - 1)
    const mapping = { date: det.date, amount: det.amount, desc: det.desc }
    setState({ rows, cols: det.cols, mapping, items: buildImportItems(rows, mapping, entries, shopMap, cats) })
    setMsg('')
    e.target.value = ''
  }

  const remap = (key, col) => {
    const mapping = { ...state.mapping, [key]: col }
    setState({ ...state, mapping, items: buildImportItems(state.rows, mapping, entries, shopMap, cats) })
  }

  const run = async () => {
    const items = state.items.filter((it) => it.include && it.amount > 0)
      .map((it) => ({ date: it.date, amount: it.amount, category: it.category, detail: it.desc }))
    let res
    try { res = await api.bulkAddMoneyEntries(items) } catch (e) { showToast('⚠️ ' + e.message); return }
    setState(null)
    onImported()
    showToast(`${res.added}件を登録しました ✅（カテゴリの対応は次回に引き継がれます）`)
  }

  const inc = state?.items.filter((it) => it.include).length ?? 0
  const dup = state?.items.filter((it) => it.dup).length ?? 0

  return (
    <details className="ios-widget" style={{ marginBottom: 12 }}>
      <summary className="w-label" style={{ cursor: 'pointer' }}>📄 利用明細の取り込み（CSV）</summary>
      <div className="caption" style={{ margin: '6px 0' }}>
        三井住友カード（Vpass）やJCBデビット等の明細CSVをまとめて「通常の支出」として登録
        （Shift-JIS/UTF-8自動判別・列自動判定・店名からカテゴリ推定・登録済みは重複として除外）。
      </div>
      <input type="file" accept=".csv,text/csv" onChange={onFile} />
      {msg && <div className="warn-box">{msg}</div>}
      {state && (
        <>
          <div className="edit-row" style={{ marginTop: 8 }}>
            {[['date', '日付の列'], ['amount', '金額の列'], ['desc', '内容の列']].map(([k, l]) => (
              <label key={k}>{l}
                <select value={state.mapping[k]} onChange={(e) => remap(k, parseInt(e.target.value, 10))}>
                  {Array.from({ length: state.cols }, (_, c) => (
                    <option key={c} value={c}>{c + 1}列目</option>
                  ))}
                </select>
              </label>
            ))}
          </div>
          <div className="caption" style={{ margin: '6px 0' }}>
            読み取り {state.items.length}件 ／ 登録対象 {inc}件
            {dup > 0 && `（重複の疑い ${dup}件は外してあります）`}
          </div>
          <div className="m-imp-wrap">
            {state.items.slice(0, 300).map((it, i) => (
              <div key={i} className={'edit-row' + (it.include ? '' : ' m-off')}>
                <input type="checkbox" checked={it.include}
                       onChange={(e) => {
                         const items = [...state.items]
                         items[i] = { ...it, include: e.target.checked }
                         setState({ ...state, items })
                       }} />
                <span className="life-time">{it.date}</span>
                <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {it.desc || '（内容なし）'}
                </span>
                <span className="hbar-val">{yen(it.amount)}</span>
                <select value={it.category}
                        onChange={(e) => {
                          const items = [...state.items]
                          items[i] = { ...it, category: e.target.value }
                          setState({ ...state, items })
                        }}>
                  {cats.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
                {it.dup && !it.dupMail && <span className="m-badge dup">登録済みの疑い</span>}
                {it.dupMail && <span className="m-badge dup">メール登録済みの疑い</span>}
                {it.amount < 0 && <span className="m-badge dup">返金・マイナス</span>}
              </div>
            ))}
          </div>
          <button className="w-action" onClick={run} disabled={inc === 0}>
            チェックした明細をまとめて登録
          </button>
        </>
      )}
    </details>
  )
}

export default CsvImport
