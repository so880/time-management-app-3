// 💰 マネータブ（旧 ikaseru の全機能を移植）
// まとめ／収支／月別使用率／見直しポイント（＋AIレビュー）／集計と傾向／
// 記録の追加（支出・サブスク・欲しい物）／CSV取り込み／3つの一覧／
// カテゴリ編集／AI設定／バックアップ（旧アプリのJSONを取り込める）
import { useCallback, useEffect, useState } from 'react'
import * as api from '../api.js'
import {
  NEED_LABEL, REC_LABEL, USAGE_LABEL, VALIDITY_LABEL,
  breakdown, buildInsights, monthlyOf, monthlyUsageSeries, periodTotal,
  seriesForPeriod, statsThisMonth, subStats, subs, spends, wishes,
  thisYM, todayStr, yen, yenShort,
} from './logic.js'
import { autoDetectColumns, buildImportItems, decodeCSVBuffer, parseCSV, suggestCategory } from './csv.js'
import { matchAmazonOrders, parseAmazonOrders, suggestAmazonCategory } from './amazon.js'

/* ---------- 小さな部品 ---------- */
function Badge({ validity }) {
  const v = validity || 'unrated'
  return <span className={`m-badge v-${v}`}>{VALIDITY_LABEL[v]}</span>
}
function RecBadge({ rec }) {
  const r = rec || 'consider'
  return <span className={`m-badge rec-${r}`}>{REC_LABEL[r]}</span>
}
function Stars({ value, onSet }) {
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
function starText(n) {
  if (!n) return null
  return <span className="m-startext">{'★'.repeat(n)}{'☆'.repeat(5 - n)}</span>
}
function aiTag(e) {
  return e.method === 'ai' ? <span className="ai-tag"> AI判定</span> : null
}

/* ---------- 折れ線グラフ（旧 chartSVG） ---------- */
function LineChart({ series }) {
  const { values: vals, labels } = series
  const w = 640; const h = 210; const pl = 56; const pr = 14; const pt = 16; const pb = 30
  const iw = w - pl - pr; const ih = h - pt - pb
  let max = 1
  vals.forEach((v) => { if (v > max) max = v })
  const x = (i) => (vals.length <= 1 ? pl + iw / 2 : pl + (iw * i) / (vals.length - 1))
  const y = (v) => pt + ih - (v / max) * ih
  const pts = vals.map((v, i) => `${x(i)},${y(v)}`).join(' ')
  const idxs = vals.length > 2 ? [0, Math.floor((vals.length - 1) / 2), vals.length - 1]
    : vals.map((_, i) => i)
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="m-chart" role="img">
      {[0, 0.5, 1].map((f) => {
        const gy = pt + ih - f * ih
        return (
          <g key={f}>
            <line x1={pl} y1={gy} x2={w - pr} y2={gy} stroke="rgba(255,255,255,0.12)" />
            <text x={pl - 6} y={gy + 4} textAnchor="end" fontSize="11" fill="#8a8f98">
              {yenShort(max * f)}
            </text>
          </g>
        )
      })}
      <polyline points={pts} fill="none" stroke="#4CAF50" strokeWidth="2" />
      {vals.map((v, i) => (v > 0
        ? <circle key={i} cx={x(i)} cy={y(v)} r="3" fill="#4CAF50"><title>{labels[i]} {yen(v)}</title></circle>
        : null))}
      {[...new Set(idxs)].map((i) => (
        <text key={i} x={x(i)} y={h - 8} textAnchor="middle" fontSize="11" fill="#8a8f98">
          {labels[i]}
        </text>
      ))}
    </svg>
  )
}

/* ---------- 月別使用率のドーナツ（旧 usageDonutSVG） ---------- */
function UsageDonut({ pct }) {
  const r = 30; const c = 38; const sw = 10
  const C = 2 * Math.PI * r
  const p = Math.max(0, Math.min(pct, 100))
  const color = pct > 100 ? '#FF3B30' : pct >= 80 ? '#FF9F0A' : '#4CAF50'
  return (
    <svg viewBox="0 0 76 76" width="76" height="76">
      <circle cx={c} cy={c} r={r} fill="none" stroke="rgba(255,255,255,0.15)" strokeWidth={sw} />
      {p > 0 && (
        <circle cx={c} cy={c} r={r} fill="none" stroke={color} strokeWidth={sw}
                strokeLinecap="round" strokeDasharray={`${(p / 100) * C} ${C}`}
                transform={`rotate(-90 ${c} ${c})`} />
      )}
      <text x={c} y={c + 5} textAnchor="middle" fontSize="16" fontWeight="800" fill="#fff">
        {Math.round(pct)}%
      </text>
    </svg>
  )
}

/* ---------- 記録の追加フォーム ---------- */
function AddForm({ cats, onAdded, showToast, aiOn }) {
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
    const res = await api.bulkAddMoneyEntries(items)
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
                        await api.patchMoneyEntry(e.id, { category: c })
                        onChanged()
                      }}>{c}</button>
            ))}
          </div>
        </div>
      ))}
      {targets.length > 30 && <div className="caption">まず30件を表示中（仕分けると次が出ます）</div>}
    </details>
  )
}

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
    for (const m of result.matches) {
      if (!m.apply) continue
      await api.patchMoneyEntry(m.entry.id, {
        detail: `Amazon: ${m.title}`.slice(0, 100),
        category: m.category,
      })
      n++
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
          const r = await api.resetAmazonEnrichment()
          onChanged()
          showToast(`↩ ${r.reset}件のAmazon記録を元に戻しました`)
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

/* ---------- 📧 利用通知メールの自動取り込み（設定・操作） ---------- */
function MailImportSection({ settings, onSettingsChange, onImported, showToast }) {
  const [user, setUser] = useState(settings.mail_user ?? '')
  const [pw, setPw] = useState(settings.mail_app_password ?? '')
  const [enabled, setEnabled] = useState(!!settings.mail_import_enabled)
  const [since, setSince] = useState('2025-04-01')
  const [status, setStatus] = useState(null)
  const [busy, setBusy] = useState(false)

  const refreshStatus = async () => {
    try { setStatus(await api.moneyMailStatus()) } catch { /* 未接続時は無視 */ }
  }
  useEffect(() => { refreshStatus() }, [])

  const save = async () => {
    onSettingsChange(await api.updateSettings({
      mail_user: user.trim(),
      mail_app_password: pw.trim(),
      mail_import_enabled: enabled,
    }))
    showToast('メール取り込み設定を保存しました ✅')
  }

  const checkNow = async () => {
    setBusy(true)
    try {
      const r = await api.moneyMailCheck()
      showToast(r.note || `チェック完了：通知${r.checked}件から${r.added}件を登録`)
      onImported()
      refreshStatus()
    } catch (e) {
      showToast('⚠️ ' + e.message)
    } finally {
      setBusy(false)
    }
  }

  const backfill = async () => {
    if (!window.confirm(`${since} 以降のカード利用通知メールをすべて取り込みます。よろしいですか？`)) return
    setBusy(true)
    try {
      const r = await api.moneyMailBackfill(since)
      showToast(r.note || '取り込みを開始しました')
      refreshStatus()
    } catch (e) {
      showToast('⚠️ ' + e.message)
    } finally {
      setBusy(false)
    }
  }

  const st = status?.status ?? {}
  // 各ステップの完了判定（✓を付けて、いま何をすべきかを分かりやすく）
  const s1 = !!(status?.user && status?.has_password)
  const s2 = !!status?.initialized
  const s3 = (st.added_total ?? 0) > 0 || String(st.note ?? '').includes('完了')
  const s4 = !!status?.enabled

  const Step = ({ n, done, active, title, children }) => (
    <div className={'mail-step' + (done ? ' done' : '') + (active ? ' active' : '')}>
      <span className="step-num">{done ? '✓' : n}</span>
      <div className="step-body">
        <div className="step-title">{title}{active && !done && <span className="step-now">← 次はこれ</span>}</div>
        {children}
      </div>
    </div>
  )

  return (
    <details className="ios-widget" style={{ marginBottom: 12 }}>
      <summary className="w-label" style={{ cursor: 'pointer' }}>
        📧 利用通知メールの自動取り込み
        {s4 ? '（自動チェック：オン）' : s2 ? '（設定済み）' : ''}
      </summary>
      <div className="caption" style={{ margin: '6px 0' }}>
        カードの利用通知メール（Gmail）から支出を自動登録します。上から順に1回ずつ設定すればOKです。
      </div>

      <Step n="1" done={s1} active={!s1} title="Gmailの接続情報を保存する">
        <div className="edit-row">
          <input type="text" placeholder="Gmailアドレス" value={user} style={{ flex: 1 }}
                 onChange={(e) => setUser(e.target.value)} autoComplete="off" />
          <input type="password" placeholder="アプリパスワード（16文字）" value={pw} style={{ flex: 1 }}
                 onChange={(e) => setPw(e.target.value)} autoComplete="off" />
          <button className="small" onClick={save}>💾 保存</button>
        </div>
        <div className="caption">
          パスワードはGoogleの「アプリパスワード」（myaccount.google.com/apppasswords）。
          空白入りのまま貼ってOK（自動除去）。このPCにのみ保存されます。
        </div>
      </Step>

      <Step n="2" done={s2} active={s1 && !s2} title="接続テスト＆初期化（1回だけ）">
        <div className="edit-row">
          <button className="small" onClick={checkNow} disabled={busy || !s1}>📥 今すぐチェック</button>
          <span className="caption">1回目は「初期化」され、以後の新着メールが自動取り込みの対象になります</span>
        </div>
      </Step>

      <Step n="3" done={s3} active={s2 && !s3} title="過去のメールをさかのぼって取り込む（1回だけ）">
        <div className="edit-row">
          <input type="date" value={since} onChange={(e) => setSince(e.target.value)} />
          <button className="small" onClick={backfill} disabled={busy || !s2 || status?.backfill_running}>
            {status?.backfill_running ? '取り込み実行中…' : '🕰 この日以降を取り込む'}
          </button>
          <button className="small" onClick={refreshStatus}>🔄 状態を更新</button>
        </div>
        <div className="caption">実行中は「🔄状態を更新」で進行状況（◯/◯件）が見られます。途中で止まっても再実行すれば続きから入ります（二重登録なし）。</div>
      </Step>

      <Step n="4" done={s4} active={s3 && !s4} title="自動チェックをオンにする（以後は全自動）">
        <div className="edit-row">
          <label><input type="checkbox" checked={enabled}
                        onChange={(e) => setEnabled(e.target.checked)} /> 5分ごとに新着を自動チェック</label>
          <button className="small" onClick={save}>💾 保存</button>
        </div>
      </Step>

      {(st.note || st.last_check || st.error) && (
        <div className={st.error ? 'warn-box' : 'info-box'} style={{ marginTop: 6 }}>
          {st.error && <div>⚠️ {st.error}</div>}
          {st.note && <div>{st.note}</div>}
          {st.last_check && (
            <div className="caption">
              最終チェック {st.last_check}
              {st.checked != null && `／通知${st.checked}件・登録${st.added}件`}
              {st.added_total != null && `（累計${st.added_total}件）`}
            </div>
          )}
          {(st.unparsed ?? []).length > 0 && (
            <div className="caption">
              ⚠️ 金額を読み取れなかった通知：{st.unparsed.join(' / ')}<br />
              → そのメールを開いて<strong>本文をコピーして私（Claude）に貼ってください</strong>。
              読み取りパターンを追加します（対応後に再取り込みすれば拾われます）。
            </div>
          )}
        </div>
      )}
    </details>
  )
}

/* ---------- マネータブ本体 ---------- */
function MoneyIos({ settings, onSettingsChange, showToast, resetTick }) {
  const [entries, setEntries] = useState([])
  const [open, setOpen] = useState({})
  const [period, setPeriod] = useState('month')
  const [allowanceIn, setAllowanceIn] = useState(settings.money_allowance ?? '')
  const [aiReviewText, setAiReviewText] = useState(null)
  const [aiBusy, setAiBusy] = useState(false)
  const [aiKey, setAiKey] = useState(settings.money_api_key ?? '')
  const [aiModel, setAiModel] = useState(settings.money_ai_model ?? 'claude-haiku-4-5-20251001')
  const [aiOn, setAiOn] = useState(!!settings.money_ai_enabled)
  const [aiStatus, setAiStatus] = useState('')
  const [newCat, setNewCat] = useState('')
  // 記録一覧の表示方法：'paged'=10件ずつページ表示 / 'all'=全部一気に（設定に保存して次回も同じ表示）
  const [listMode, setListMode] = useState(settings.money_list_mode ?? 'paged')
  const [listPage, setListPage] = useState(1)
  // 画面モード：'view'=見るだけ（まとめ・グラフ） / 'input'=入力・確認（追加・一覧・設定）
  const [mode, setMode] = useState('view')
  const [reorder, setReorder] = useState(false) // セクション並び替えモード

  const cats = settings.money_categories ?? ['その他']
  const shopMap = settings.money_shopmap ?? {}
  const allowance = settings.money_allowance

  const reload = useCallback(() => {
    api.getMoneyEntries().then(setEntries).catch(() => {})
  }, [])
  useEffect(() => { reload() }, [reload])

  const saveSettings = async (changes) => {
    onSettingsChange(await api.updateSettings(changes))
  }

  // タブバーの「マネー」を押すたびに初期状態（見るモードの先頭）へ戻す
  useEffect(() => {
    if (!resetTick) return
    setMode('view')
    setReorder(false)
    setListPage(1)
    setOpen({})
  }, [resetTick])

  // ---- セクションの並び順（設定に保存。「↕並び替え」で変更できる）----
  const VIEW_IDS = ['summary', 'usage', 'insights', 'trend']
  const INPUT_IDS = ['add', 'sort', 'amazon', 'csv', 'wish', 'subs', 'list', 'cats', 'mail', 'ai', 'backup']
  const normOrder = (saved, ids) => {
    const s = Array.isArray(saved) ? saved.filter((x) => ids.includes(x)) : []
    return [...s, ...ids.filter((x) => !s.includes(x))] // 新しいセクションは末尾に足す
  }
  const orderView = normOrder(settings.money_order_view, VIEW_IDS)
  const orderInput = normOrder(settings.money_order_input, INPUT_IDS)
  const moveSec = (id, dir) => {
    const key = mode === 'view' ? 'money_order_view' : 'money_order_input'
    const cur = [...(mode === 'view' ? orderView : orderInput)]
    const i = cur.indexOf(id)
    const j = i + dir
    if (i < 0 || j < 0 || j >= cur.length) return
    ;[cur[i], cur[j]] = [cur[j], cur[i]]
    saveSettings({ [key]: cur })
  }
  const secTitle = {
    summary: '📊 今月のまとめ', usage: '🍩 月ごとの使用率', insights: '🔍 見直しポイント',
    trend: '📈 集計と傾向', add: '➕ 記録の追加', sort: '🧹 未分類の仕分け',
    amazon: '📦 Amazon突き合わせ', csv: '📄 CSV取り込み', wish: '🎁 欲しい物リスト',
    subs: '🔁 固定費・サブスク', list: '🧾 記録一覧', cats: '🏷 カテゴリの編集',
    mail: '📧 メール自動取り込み', ai: '🤖 AI判定の設定', backup: '💾 バックアップ',
  }
  const secNode = {}

  const st = statsThisMonth(entries)
  const ss = subStats(entries)
  const total = st.total + ss.monthly
  const bal = allowance != null && allowance !== '' ? Number(allowance) - total : null
  const insights = buildInsights(entries, allowance)
  const usage = monthlyUsageSeries(entries, allowance)
  const bd = breakdown(entries, period)
  const bdMax = bd[0]?.amount || 1
  const ym = thisYM()

  const toggle = (id) => setOpen({ ...open, [id]: !open[id] })

  const del = async (e) => {
    if (!window.confirm('この記録を削除しますか？（元に戻せません）')) return
    await api.deleteMoneyEntry(e.id)
    reload()
  }
  const buy = async (e) => {
    if (!window.confirm(`「${e.detail || 'この欲しい物'}」を、今日買ったものとして通常の支出に記録しますか？`)) return
    const r = await api.buyMoneyWish(e.id)
    reload()
    if (aiOn && aiKey) api.moneyAiJudge(r.id).then(reload).catch(() => {})
  }

  const runAiReview = async () => {
    setAiBusy(true)
    try {
      const r = await api.moneyAiReview()
      setAiReviewText(r.text || 'レビューを取得できませんでした。')
    } catch (e) {
      setAiReviewText('AIレビューに失敗しました：' + e.message)
    } finally {
      setAiBusy(false)
    }
  }

  const onBackupFile = async (ev) => {
    const f = ev.target.files?.[0]
    if (!f) return
    try {
      const obj = JSON.parse(await f.text())
      if (obj.app !== 'ikaseru' || !Array.isArray(obj.entries)) {
        showToast('⚠️ ikaseru のバックアップではありません')
        return
      }
      if (!window.confirm(`現在のデータをバックアップの内容（記録${obj.entries.length}件）で置き換えます。よろしいですか？`)) return
      const r = await api.importMoneyBackup(obj)
      onSettingsChange(await api.getSettings())
      reload()
      showToast(`バックアップを読み込みました（${r.imported}件）✅`)
    } catch (e) {
      showToast('読み込みに失敗しました: ' + e.message)
    } finally {
      ev.target.value = ''
    }
  }

  const exportBackup = async () => {
    const obj = await api.exportMoneyBackup()
    const blob = new Blob([JSON.stringify(obj, null, 2)], { type: 'application/json' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `ikaseru-backup-${todayStr()}.json`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  /* ---- 一覧の1行（共通の開閉行） ---- */
  const Row = ({ e, head, body }) => (
    <div className="m-row">
      <div className="m-row-head" onClick={() => toggle(e.id)}>{head}</div>
      {open[e.id] && <div className="m-row-body">{body}</div>}
    </div>
  )

  // ---- 各セクションの中身（id → JSX。並び順は orderView / orderInput が決める）----
  secNode.summary = (
    <details className="ios-widget" style={{ marginBottom: 12 }} open key="summary">
      <summary className="w-label" style={{ cursor: 'pointer' }}>📊 今月のまとめ</summary>
      <div className="ios-widget-grid" style={{ marginTop: 8 }}>
        <div className="ios-widget">
          <div className="w-label">今月の通常支出</div>
          <div className="w-big">{yen(st.total)}</div>
          <div className="w-sub">{st.count}件{st.high ? `・うち「高め」判定 ${st.high}件` : ''}</div>
        </div>
        <div className="ios-widget">
          <div className="w-label">固定費・サブスク（月あたり）</div>
          <div className="w-big">{yen(ss.monthly)}<span className="w-unit">/月</span></div>
          <div className="w-sub">{ss.count}件・年額換算 {yen(ss.yearly)}</div>
        </div>
        <div className="ios-widget">
          <div className="w-label">💴 今月の収支（仕送り比）</div>
          {bal == null ? (
            <div className="w-sub">仕送りを入力すると収支が出ます</div>
          ) : (
            <>
              <div className="w-big" style={{ color: bal >= 0 ? '#4CAF50' : '#FF6B62' }}>
                {bal >= 0 ? '黒字' : '赤字'} {yen(Math.abs(bal))}
              </div>
              <div className="w-sub">
                {bal >= 0 ? `今月あと使える目安：${yen(bal)}` : `使いすぎ分：${yen(-bal)}`}
              </div>
            </>
          )}
          <div className="edit-row" style={{ marginTop: 8 }}>
            <input type="number" min="0" placeholder="毎月の仕送り（円）" value={allowanceIn}
                   style={{ width: 140 }} onChange={(e) => setAllowanceIn(e.target.value)} />
            <button className="small" onClick={() => {
              const v = allowanceIn === '' ? null : Math.max(0, Number(allowanceIn))
              saveSettings({ money_allowance: v })
              showToast('仕送りを保存しました ✅')
            }}>保存</button>
          </div>
        </div>
      </div>
    </details>
  )

  secNode.usage = (
    <details className="ios-widget" style={{ marginBottom: 12 }} open key="usage">
      <summary className="w-label" style={{ cursor: 'pointer' }}>🍩 月ごとの使用率（仕送りに対して・右端が今月）</summary>
        {usage.allowance == null ? (
          <div className="caption">仕送りを保存すると、月ごとの使用率が円グラフで表示されます。</div>
        ) : (
          <div className="m-usage-row">
            {usage.months.map((o) => (
              <div key={o.ym} className={'m-usage-item' + (o.ym === ym ? ' now' : '')}>
                <UsageDonut pct={o.pct || 0} />
                <div className="w-sub">{o.label}</div>
                <div style={{ fontWeight: 700 }}>{yen(o.total)}</div>
                <div className="w-sub">
                  {(o.pct || 0) <= 100 ? `残り ${yen(usage.allowance - o.total)}` : `超過 ${yen(o.total - usage.allowance)}`}
                </div>
              </div>
            ))}
          </div>
        )}
    </details>
  )

  secNode.insights = (
    <details className="ios-widget" style={{ marginBottom: 12 }} open key="insights">
      <summary className="w-label" style={{ cursor: 'pointer' }}>🔍 今月の見直しポイント</summary>
        {insights.map((it, i) => (
          <div key={i} className={it.type === 'warn' ? 'warn-box' : it.type === 'good' ? 'success-box' : 'info-box'}>
            {it.text}
          </div>
        ))}
        <button className="small" onClick={runAiReview} disabled={aiBusy}>
          {aiBusy ? 'AIがレビューを作成中…' : '🤖 AIに今月のレビューを頼む'}
        </button>
        {!aiKey && <div className="caption" style={{ marginTop: 4 }}>APIキーを設定すると、AIによる月次レビューが使えます（未設定でも上の自動チェックは動きます）。</div>}
        {aiReviewText && <div className="m-ai-out">{aiReviewText}</div>}
    </details>
  )

  secNode.trend = (
    <details className="ios-widget" style={{ marginBottom: 12 }} open key="trend">
      <summary className="w-label" style={{ cursor: 'pointer' }}>📈 集計と傾向</summary>
        <div className="seg" style={{ maxWidth: 300, marginBottom: 8 }}>
          {[['month', '今月'], ['year', '今年'], ['all', '全期間']].map(([p, l]) => (
            <button key={p} type="button" className={'seg-btn' + (period === p ? ' on' : '')}
                    onClick={() => setPeriod(p)}>{l}</button>
          ))}
        </div>
        <div className="w-sub" style={{ marginBottom: 6 }}>
          期間の合計（通常支出）：<strong style={{ color: '#fff' }}>{yen(periodTotal(entries, period))}</strong>
        </div>
        <LineChart series={seriesForPeriod(entries, period)} />
        {bd.length > 0 && (
          <div style={{ marginTop: 8 }}>
            {bd.map((b) => (
              <div className="hbar-row" key={b.category}>
                <span className="hbar-label">{b.category}</span>
                <div className="hbar-track">
                  <div className="hbar-fill" style={{ width: `${Math.max(2, (b.amount / bdMax) * 100)}%`, background: '#4CAF50' }} />
                </div>
                <span className="hbar-val">{yen(b.amount)}（{Math.round(b.pct)}%）</span>
              </div>
            ))}
          </div>
        )}
    </details>
  )

  secNode.add = (
    <div key="add">
      <AddForm cats={cats} onAdded={reload} showToast={showToast} aiOn={aiOn && !!aiKey} />
    </div>
  )
  secNode.sort = (
    <div key="sort">
      <SortUncategorized entries={entries} cats={cats} onChanged={reload} showToast={showToast} />
    </div>
  )
  secNode.amazon = (
    <div key="amazon">
      <AmazonMatch entries={entries} cats={cats} onChanged={reload} showToast={showToast} />
    </div>
  )
  secNode.csv = (
    <div key="csv">
      <CsvImport entries={entries} cats={cats} shopMap={shopMap}
                 onImported={async () => { reload(); onSettingsChange(await api.getSettings()) }}
                 showToast={showToast} />
    </div>
  )

  secNode.wish = (
    <details className="ios-widget" style={{ marginBottom: 12 }} open key="wish">
      <summary className="w-label" style={{ cursor: 'pointer' }}>🎁 欲しい物リスト（{wishes(entries).length}件）</summary>
        {wishes(entries).sort((a, b) => (b.createdAt || 0) - (a.createdAt || 0)).map((e) => (
          <Row key={e.id} e={e}
               head={<>
                 <span className="life-chip" style={{ borderColor: '#AF52DE', background: '#AF52DE33' }}>{e.category}</span>
                 <RecBadge rec={e.recommendation} />
                 <span className="m-title">{e.detail || '（名前なし）'}</span>
                 {starText(e.wantLevel)}
                 <span className="m-amount">{yen(e.amount)}</span>
               </>}
               body={<>
                 <div className="caption">必要度：{NEED_LABEL[e.need] ?? ''}　{e.reason && `理由：${e.reason}`}</div>
                 {e.ownedSimilar && <div className="caption">似ていて持っている物：{e.ownedSimilar}</div>}
                 {e.betterPoint && <div className="caption">良い点：{e.betterPoint}</div>}
                 <p className="m-advice">{e.advice}{aiTag(e)}</p>
                 <div className="edit-row">
                   <button className="small" onClick={() => buy(e)}>🛒 買った → 支出に記録する</button>
                   <button className="icon" onClick={() => del(e)}>🗑</button>
                 </div>
               </>} />
        ))}
    </details>
  )

  secNode.subs = (
    <details className="ios-widget" style={{ marginBottom: 12 }} open key="subs">
      <summary className="w-label" style={{ cursor: 'pointer' }}>🔁 固定費・サブスク（月あたりの高い順）</summary>
        {subs(entries).sort((a, b) => monthlyOf(b) - monthlyOf(a)).map((e) => (
          <Row key={e.id} e={e}
               head={<>
                 <span className="life-chip" style={{ borderColor: '#5856D6', background: '#5856D633' }}>{e.category}</span>
                 <Badge validity={e.validity} />
                 <span className="m-title">{e.detail || '（名前なし）'}
                   <span className="caption">　支払 {yen(e.amount)}／{e.planMonths}ヶ月／{USAGE_LABEL[e.usage] ?? '頻度未設定'}</span>
                 </span>
                 <span className="m-amount">{yen(monthlyOf(e))}/月</span>
               </>}
               body={<>
                 {e.reason && <div className="caption">契約理由：{e.reason}</div>}
                 <p className="m-advice">{e.advice}{aiTag(e)}</p>
                 <div className="edit-row">
                   <span className="caption">今月（{ym}）の満足度：</span>
                   <Stars value={e.satLog?.[ym] ?? 0}
                          onSet={(v) => api.patchMoneyEntry(e.id, { sat_month: ym, sat_value: v }).then(reload)} />
                   <button className="icon" onClick={() => del(e)}>🗑</button>
                 </div>
               </>} />
        ))}
    </details>
  )

  // 記録一覧：10件ずつの「ページ表示」と「全部表示」の2種類
  const spendSorted = spends(entries)
    .sort((a, b) => (a.date !== b.date ? (a.date < b.date ? 1 : -1) : (b.createdAt || 0) - (a.createdAt || 0)))
  const PAGE_SIZE = 10
  const pageMax = Math.max(1, Math.ceil(spendSorted.length / PAGE_SIZE))
  const pageCur = Math.min(listPage, pageMax)
  const pageStart = Math.max(1, Math.min(pageCur - 3, pageMax - 6))
  const pageNums = []
  for (let p = pageStart; p <= Math.min(pageMax, pageStart + 6); p++) pageNums.push(p)

  secNode.list = (
    <details className="ios-widget" style={{ marginBottom: 12 }} open key="list">
      <summary className="w-label" style={{ cursor: 'pointer' }}>
        🧾 記録一覧（通常の支出・新しい順・全{spendSorted.length}件）
      </summary>
      <div className="edit-row" style={{ margin: '8px 0' }}>
        <div className="seg" style={{ maxWidth: 260 }}>
          {[['paged', '10件ずつ'], ['all', '全部表示']].map(([m2, l]) => (
            <button key={m2} type="button" className={'seg-btn' + (listMode === m2 ? ' on' : '')}
                    onClick={() => {
                      setListMode(m2)
                      setListPage(1) // 切り替えたら1ページ目から
                      saveSettings({ money_list_mode: m2 }) // 次回も同じ表示に
                    }}>{l}</button>
          ))}
        </div>
        {listMode === 'paged' && (
          <span className="caption">{pageCur} / {pageMax} ページ</span>
        )}
      </div>
        {(listMode === 'all' ? spendSorted : spendSorted.slice((pageCur - 1) * PAGE_SIZE, pageCur * PAGE_SIZE))
          .map((e) => (
            <Row key={e.id} e={e}
                 head={<>
                   <span className="life-time">{e.date}</span>
                   <span className="life-chip" style={{ borderColor: '#4CAF50', background: '#4CAF5033' }}>{e.category}</span>
                   <Badge validity={e.validity} />
                   <span className="m-title">{e.detail}</span>
                   {starText(e.satisfaction)}
                   <span className="m-amount">{yen(e.amount)}</span>
                 </>}
                 body={<>
                   <div className="edit-row">
                     <span className="caption">内容：</span>
                     <input type="text" defaultValue={e.detail} style={{ flex: 1 }}
                            onBlur={(ev) => {
                              if (ev.target.value !== e.detail)
                                api.patchMoneyEntry(e.id, { detail: ev.target.value }).then(reload)
                            }} />
                     <span className="caption">カテゴリ：</span>
                     <select value={e.category}
                             onChange={(ev) => api.patchMoneyEntry(e.id, { category: ev.target.value })
                               .then(async () => { reload(); onSettingsChange(await api.getSettings()) })}>
                       {cats.map((c) => <option key={c} value={c}>{c}</option>)}
                     </select>
                   </div>
                   <div className="edit-row">
                     <span className="caption">満足感：</span>
                     <Stars value={e.satisfaction ?? 0}
                            onSet={(v) => api.patchMoneyEntry(e.id, { satisfaction: v }).then(reload)} />
                   </div>
                   <p className="m-advice">{e.advice}{aiTag(e)}</p>
                   <button className="icon" onClick={() => del(e)}>🗑 削除</button>
                 </>} />
          ))}
        {listMode === 'paged' && pageMax > 1 && (
          <div className="m-pagenav">
            <button type="button" className="small" disabled={pageCur <= 1}
                    onClick={() => setListPage(pageCur - 1)}>‹ 前</button>
            {pageNums.map((p) => (
              <button key={p} type="button"
                      className={'m-page' + (p === pageCur ? ' on' : '')}
                      onClick={() => setListPage(p)}>{p}</button>
            ))}
            <button type="button" className="small" disabled={pageCur >= pageMax}
                    onClick={() => setListPage(pageCur + 1)}>次 ›</button>
          </div>
        )}
    </details>
  )

  secNode.cats = (
    <details className="ios-widget" style={{ marginBottom: 12 }} key="cats">
      <summary className="w-label" style={{ cursor: 'pointer' }}>🏷 カテゴリの編集</summary>
        <div className="caption" style={{ margin: '6px 0' }}>
          名前をクリックで改名、×で選択肢から外せます（過去の記録は消えません。改名は過去の記録にも反映）。
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {cats.map((c) => (
            <span key={c} className="life-chip" style={{ borderColor: '#8E8E93', background: '#8E8E9333', cursor: 'pointer' }}>
              <span onClick={async () => {
                const nv = window.prompt('新しいカテゴリ名を入力してください。', c)
                if (!nv || nv.trim() === c) return
                try {
                  await api.renameMoneyCategory(c, nv.trim())
                  onSettingsChange(await api.getSettings())
                  reload()
                } catch (e) { showToast(e.message) }
              }}>{c}</span>
              {' '}
              <span style={{ color: '#FF6B62' }} onClick={() => {
                if (!window.confirm(`カテゴリ「${c}」を選択肢から外しますか？（過去の記録は消えません）`)) return
                const next = cats.filter((x) => x !== c)
                saveSettings({ money_categories: next.length ? next : ['その他'] })
              }}>×</span>
            </span>
          ))}
        </div>
        <div className="edit-row" style={{ marginTop: 8 }}>
          <input type="text" placeholder="新しいカテゴリ名" value={newCat}
                 onChange={(e) => setNewCat(e.target.value)} />
          <button className="small" onClick={() => {
            const v = newCat.trim()
            if (!v) return
            if (cats.includes(v)) { showToast('同じ名前のカテゴリがすでにあります'); return }
            saveSettings({ money_categories: [...cats, v] })
            setNewCat('')
          }}>追加</button>
        </div>
    </details>
  )

  secNode.mail = (
    <div key="mail">
      <MailImportSection settings={settings} onSettingsChange={onSettingsChange}
                         onImported={reload} showToast={showToast} />
    </div>
  )

  secNode.ai = (
    <details className="ios-widget" style={{ marginBottom: 12 }} key="ai">
      <summary className="w-label" style={{ cursor: 'pointer' }}>🤖 AI判定の設定（任意）</summary>
        <div className="caption" style={{ margin: '6px 0' }}>
          Anthropic（Claude）のAPIキーを設定すると、妥当性判定・欲しい物の評価・月次レビューをAIが行います。
          キーが無くても簡易判定で全機能が使えます。キーはこのPCのデータベースにのみ保存され、
          AI判定の実行時にバックエンドからAnthropicのAPIへ送られる以外、外部には送信されません。
        </div>
        <div className="edit-row">
          <input type="password" placeholder="sk-ant-..." value={aiKey} style={{ flex: 1 }}
                 onChange={(e) => setAiKey(e.target.value)} autoComplete="off" />
          <input type="text" placeholder="claude-haiku-4-5-20251001" value={aiModel}
                 style={{ width: 220 }} onChange={(e) => setAiModel(e.target.value)} />
          <label><input type="checkbox" checked={aiOn} onChange={(e) => setAiOn(e.target.checked)} /> AI判定を使う</label>
        </div>
        <div className="edit-row">
          <button className="small" onClick={() => {
            saveSettings({
              money_api_key: aiKey.trim(),
              money_ai_model: aiModel.trim() || 'claude-haiku-4-5-20251001',
              money_ai_enabled: aiOn,
            })
            setAiStatus(aiOn && aiKey ? '保存しました。以後の記録はAI判定になります（過去の記録は変わりません）。'
              : '保存しました。現在は簡易判定で動作します。')
          }}>保存</button>
          <button className="small" onClick={async () => {
            setAiStatus('接続を確認しています…')
            try {
              await api.moneyAiTest()
              setAiStatus('接続に成功しました。AI判定が使えます。')
            } catch (e) {
              setAiStatus('接続に失敗しました：' + e.message + '（キーやチャージ残高をご確認ください）')
            }
          }}>接続テスト</button>
        </div>
        {aiStatus && <div className="caption">{aiStatus}</div>}
    </details>
  )

  secNode.backup = (
    <details className="ios-widget" style={{ marginBottom: 12 }} key="backup">
      <summary className="w-label" style={{ cursor: 'pointer' }}>💾 バックアップ</summary>
        <div className="caption" style={{ marginBottom: 8 }}>
          旧アプリ（ikaseru）の「バックアップを書き出す」で作ったJSONをここで読み込むと、
          記録・カテゴリ・店名学習・仕送り設定をすべて引き継げます（旧形式と互換）。
        </div>
        <div className="edit-row">
          <button className="small" onClick={exportBackup}>⬇️ バックアップを書き出す</button>
          <label className="small" style={{ cursor: 'pointer' }}>
            <span className="caption">📂 バックアップを読み込む：</span>
            <input type="file" accept=".json,application/json" onChange={onBackupFile} />
          </label>
        </div>
    </details>
  )

  return (
    <div>
      <h1 className="ios-large-title">💰 マネー</h1>

      {/* 最上部：見る／入力・確認 の切り替え（タブと同じ感覚で押すだけ）＋並び替え */}
      <div className="m-topbar">
        <div className="seg" style={{ flex: 1, maxWidth: 380 }}>
          {[['view', '👀 見る'], ['input', '✍️ 入力・確認']].map(([m2, l]) => (
            <button key={m2} type="button" className={'seg-btn' + (mode === m2 ? ' on' : '')}
                    onClick={() => { setMode(m2); setReorder(false) }}>{l}</button>
          ))}
        </div>
        <button type="button" className="small" onClick={() => setReorder(!reorder)}>
          {reorder ? '✅ 並び替えを終了' : '↕ 並び替え'}
        </button>
      </div>

      {reorder && (
        <div className="caption" style={{ marginBottom: 8 }}>
          ↑↓ でセクションの順番を変えられます（「{mode === 'view' ? '見る' : '入力・確認'}」画面の並びとして保存されます）。
        </div>
      )}

      {(mode === 'view' ? orderView : orderInput).map((id, idx, arr) =>
        reorder ? (
          <div key={id} className="ios-widget m-ord-row">
            <span className="w-label" style={{ flex: 1, margin: 0 }}>{secTitle[id]}</span>
            <button type="button" className="small" disabled={idx === 0}
                    onClick={() => moveSec(id, -1)}>↑</button>
            <button type="button" className="small" disabled={idx === arr.length - 1}
                    onClick={() => moveSec(id, 1)}>↓</button>
          </div>
        ) : secNode[id]
      )}
    </div>
  )
}

export default MoneyIos
