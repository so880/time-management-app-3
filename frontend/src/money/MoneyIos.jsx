// 💰 マネータブ（旧 ikaseru の全機能を移植）
// まとめ／収支／月別使用率／見直しポイント（＋AIレビュー）／集計と傾向／
// 記録の追加（支出・サブスク・欲しい物）／CSV取り込み／3つの一覧／
// カテゴリ編集／AI設定／バックアップ（旧アプリのJSONを取り込める）
import { useCallback, useEffect, useState } from 'react'
import * as api from '../api.js'
import {
  NEED_LABEL, USAGE_LABEL,
  breakdown, buildInsights, monthlyOf, monthlyUsageSeries, periodTotal,
  seriesForPeriod, statsThisMonth, subStats, subs, spends, wishes,
  thisYM, todayStr, yen,
} from './logic.js'
import { Badge, RecBadge, Stars, aiTag, starText } from './parts.jsx'
import { LineChart, UsageDonut } from './charts.jsx'
import AddForm from './AddForm.jsx'
import CsvImport from './CsvImport.jsx'
import SortUncategorized from './SortUncategorized.jsx'
import AmazonMatch from './AmazonMatch.jsx'
import MailImportSection from './MailImportSection.jsx'

/* ---------- マネータブ本体 ---------- */
function MoneyIos({ settings, onSettingsChange, showToast, resetTick }) {
  const [entries, setEntries] = useState([])
  const [open, setOpen] = useState({})
  const [period, setPeriod] = useState('month')
  const [allowanceIn, setAllowanceIn] = useState(settings.money_allowance ?? '')
  const [aiReviewText, setAiReviewText] = useState(null)
  const [aiBusy, setAiBusy] = useState(false)
  // API キーは本体から中身が返らない（secrets_set で設定済みかだけ分かる）。入力したときだけ上書きする
  const [aiKey, setAiKey] = useState('')
  const aiKeySet = !!settings.secrets_set?.money_api_key
  const [aiModel, setAiModel] = useState(settings.money_ai_model && !settings.money_ai_model.startsWith('claude') && !settings.money_ai_model.startsWith('gemini-2.0') && !settings.money_ai_model.startsWith('gemini-1.') ? settings.money_ai_model : 'gemini-3.5-flash-lite')
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
    try {
      await api.deleteMoneyEntry(e.id)
      reload()
    } catch (err) { showToast('⚠️ ' + err.message) }
  }
  const buy = async (e) => {
    if (!window.confirm(`「${e.detail || 'この欲しい物'}」を、今日買ったものとして通常の支出に記録しますか？`)) return
    let r
    try {
      r = await api.buyMoneyWish(e.id)
      reload()
    } catch (err) { showToast('⚠️ ' + err.message); return }
    // AI判定は裏で差し替えるだけ（失敗しても簡易判定が残るので知らせない）
    if (aiOn && aiKeySet) api.moneyAiJudge(r.id).then(reload).catch(() => {})
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
        {!aiKeySet && <div className="caption" style={{ marginTop: 4 }}>APIキーを設定すると、AIによる月次レビューが使えます（未設定でも上の自動チェックは動きます）。</div>}
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
      <AddForm cats={cats} onAdded={reload} showToast={showToast} aiOn={aiOn && aiKeySet} />
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
                          onSet={(v) => api.patchMoneyEntry(e.id, { sat_month: ym, sat_value: v }).then(reload).catch((err) => showToast('⚠️ ' + err.message))} />
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
                                api.patchMoneyEntry(e.id, { detail: ev.target.value }).then(reload).catch((err) => showToast('⚠️ ' + err.message))
                            }} />
                     <span className="caption">カテゴリ：</span>
                     <select value={e.category}
                             onChange={(ev) => api.patchMoneyEntry(e.id, { category: ev.target.value })
                               .then(async () => { reload(); onSettingsChange(await api.getSettings()) })
                               .catch((err) => showToast('⚠️ ' + err.message))}>
                       {cats.map((c) => <option key={c} value={c}>{c}</option>)}
                     </select>
                   </div>
                   <div className="edit-row">
                     <span className="caption">満足感：</span>
                     <Stars value={e.satisfaction ?? 0}
                            onSet={(v) => api.patchMoneyEntry(e.id, { satisfaction: v }).then(reload).catch((err) => showToast('⚠️ ' + err.message))} />
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
          Google の <strong>Gemini APIキー</strong>（Google AI Studio で無料発行）を設定すると、
          妥当性判定・欲しい物の評価・月次レビュー・ホームの「今日のプランをAIに作らせる」が使えます。
          キーが無くても簡易判定で全機能が使えます。キーはこのPCのデータベースにのみ保存され、
          AI実行時にバックエンドから Google の API へ送られる以外、外部には送信されません。
        </div>
        <div className="edit-row">
          <input type="password" value={aiKey} style={{ flex: 1 }}
                 placeholder={aiKeySet ? '設定済み（変えるときだけ入力）' : 'AQ.… または AIza…（AI Studio で発行したキー）'}
                 onChange={(e) => setAiKey(e.target.value)} autoComplete="new-password" />
          <input type="text" placeholder="gemini-3.5-flash-lite（空で既定）" value={aiModel}
                 style={{ width: 220 }} onChange={(e) => setAiModel(e.target.value)} />
          <label><input type="checkbox" checked={aiOn} onChange={(e) => setAiOn(e.target.checked)} /> AI判定を使う</label>
        </div>
        {aiKeySet && <div className="caption">✅ APIキーは保存済みです（変えるときだけ入力してください）</div>}
        <div className="edit-row">
          <button className="small" onClick={async () => {
            try {
              await saveSettings({
                money_api_key: aiKey.trim(),
                money_ai_model: aiModel.trim() || 'gemini-3.5-flash-lite',
                money_ai_enabled: aiOn,
              })
              const hasKey = aiKeySet || aiKey.trim() !== ''
              setAiKey('')
              setAiStatus(aiOn && hasKey ? '保存しました。以後の記録はAI判定になります（過去の記録は変わりません）。'
                : '保存しました。現在は簡易判定で動作します。')
            } catch (e) { setAiStatus('保存に失敗しました：' + e.message) }
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
    <div className="money fit-page">
      <div className="fit-head">
      <h1 className="ios-large-title">💰 マネー</h1>

      {/* 最上部：見る／入力・確認 の切り替え（タブと同じ感覚で押すだけ）＋並び替え */}
      <div className="m-topbar">
        <div className="seg" style={{ flex: 1, maxWidth: 380 }}>
          {[['view', '📊 まとめ'], ['input', '✍️ 入力']].map(([m2, l]) => (
            <button key={m2} type="button" className={'seg-btn' + (mode === m2 ? ' on' : '')}
                    onClick={() => {
                      // 選択中のモードをもう一度押したら、そのモードの初期状態に戻す
                      setMode(m2)
                      setReorder(false)
                      if (mode === m2) {
                        setListPage(1)
                        setOpen({})
                        window.scrollTo({ top: 0 })
                        document.querySelector('.money .fit-body')?.scrollTo({ top: 0 })
                      }
                    }}>{l}</button>
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
      </div>

      {/* セクションは内側でスクロール（F23：ページ全体はスクロールしない） */}
      <div className="fit-body">
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
    </div>
  )
}

export default MoneyIos
