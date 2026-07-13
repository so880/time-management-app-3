// 日次サマリー（L4）：カテゴリ別内訳・自由時間の使い方・昨日比コメント・
// マイルール（目標との比較アラート）・PCアプリ上位
import { useEffect, useState } from 'react'
import * as api from '../api.js'
import { CATEGORY_COLORS } from './LifeIos.jsx'

function fmtMin(m) {
  const h = Math.floor(m / 60)
  return h > 0 ? `${h}時間${m % 60 > 0 ? `${m % 60}分` : ''}` : `${m}分`
}

// 横棒（カテゴリ内訳・PCアプリ共用）
function HBar({ label, minutes, max, color }) {
  return (
    <div className="hbar-row">
      <span className="hbar-label">{label}</span>
      <div className="hbar-track">
        <div className="hbar-fill"
             style={{ width: `${Math.max(2, (minutes / Math.max(max, 1)) * 100)}%`,
                      background: color ?? '#64D2FF' }} />
      </div>
      <span className="hbar-val">{fmtMin(minutes)}</span>
    </div>
  )
}

// マイルールの判定（カテゴリ / PCアプリ名の部分一致 / 1日の支出上限）
function checkRules(rules, stats) {
  const results = []
  for (const r of rules ?? []) {
    const max = parseInt(r.max_minutes, 10) || 0
    if (max <= 0) continue
    let used = 0
    if (r.kind === 'money_day') {
      used = Math.round(stats.money?.total ?? 0)   // 円
    } else if (r.kind === 'pc_app') {
      if (!r.key) continue
      for (const a of stats.pc_apps ?? []) {
        if (a.app.toLowerCase().includes(String(r.key).toLowerCase())) used += a.minutes
      }
    } else {
      if (!r.key) continue
      used = stats.categories?.[r.key] ?? 0
    }
    results.push({ ...r, used, max, over: used > max, isMoney: r.kind === 'money_day' })
  }
  return results
}

// ルールベースの日次コメント
function buildComments(today, yesterday, ruleResults) {
  const out = []
  const diff = today.study_minutes - yesterday.study_minutes
  if (today.study_minutes > 0 || yesterday.study_minutes > 0) {
    if (diff > 0) out.push(`📚 勉強は昨日より ${fmtMin(diff)} 多い！その調子 🔥`)
    else if (diff < 0) out.push(`📚 勉強は昨日より ${fmtMin(-diff)} 少なめ。夜にもう1本どう？`)
    else out.push('📚 勉強時間は昨日と同じペースです')
  }
  if (today.unrecorded_minutes >= 120) {
    out.push(`❓ 未記録の自由時間が ${fmtMin(today.unrecorded_minutes)} あります。「➕実績を記録」で埋めてみましょう`)
  } else if (today.free_minutes > 0 && today.unrecorded_minutes <= 30) {
    out.push('✅ 今日の自由時間はほぼ記録済み。ふりかえりが捗ります')
  }
  for (const r of ruleResults) {
    if (r.over) {
      out.push(r.isMoney
        ? `🚨 今日の支出が上限 ¥${r.max.toLocaleString()} を超えています（¥${r.used.toLocaleString()}）`
        : `🚨 「${r.label || r.key}」が上限 ${fmtMin(r.max)} を超えています（${fmtMin(r.used)}）`)
    }
  }
  // 💰 支出のコメント（昨日比）
  const mT = Math.round(today.money?.total ?? 0)
  const mY = Math.round(yesterday.money?.total ?? 0)
  if (mT > 0 || mY > 0) {
    const d = mT - mY
    out.push(`💰 今日の支出は ¥${mT.toLocaleString()}（昨日${d >= 0 ? '+' : '−'}¥${Math.abs(d).toLocaleString()}）`)
  }
  if (out.length === 0) out.push('今日はまだデータが少なめです。記録が増えるとコメントも増えます')
  return out
}

function SummaryDay({ date, settings, onSettingsChange, showToast }) {
  const [data, setData] = useState(null)
  const [ruleKind, setRuleKind] = useState('category')
  const [ruleKey, setRuleKey] = useState('娯楽')
  const [ruleMax, setRuleMax] = useState(120)

  useEffect(() => {
    api.getLifeSummary(date).then(setData).catch(() => {})
  }, [date])

  if (!data) return <div className="caption">集計中…</div>
  const t = data.today
  const rules = settings.life_rules ?? []
  const ruleResults = checkRules(rules, t)
  const comments = buildComments(t, data.yesterday, ruleResults)

  const cats = Object.entries(t.categories).sort((a, b) => b[1] - a[1])
  const maxCat = Math.max(...cats.map(([, m]) => m), 1)

  const saveRules = async (newRules) => {
    onSettingsChange(await api.updateSettings({ life_rules: newRules }))
  }

  return (
    <div>
      {/* 目標との比較アラート */}
      {ruleResults.filter((r) => r.over).map((r, i) => (
        <div className="warn-box" key={i}>
          🚨 <strong>{r.isMoney ? '1日の支出' : (r.label || r.key)}</strong>：
          上限 {r.isMoney ? `¥${r.max.toLocaleString()}` : fmtMin(r.max)} のところ
          すでに <strong>{r.isMoney ? `¥${r.used.toLocaleString()}` : fmtMin(r.used)}</strong> 使っています
        </div>
      ))}

      {/* 日次コメント */}
      <div className="ios-widget" style={{ marginBottom: 12 }}>
        <div className="w-label">💬 今日のコメント</div>
        {comments.map((c, i) => <div key={i} style={{ margin: '4px 0' }}>{c}</div>)}
      </div>

      {/* 自由時間の使い方 */}
      <div className="ios-widget" style={{ marginBottom: 12 }}>
        <div className="w-label">🕐 自由時間の使い方（予定・睡眠を除く {fmtMin(t.free_minutes)}）</div>
        <HBar label="記録済み" minutes={t.recorded_free_minutes} max={t.free_minutes} color="#4CAF50" />
        <HBar label="未記録" minutes={t.unrecorded_minutes} max={t.free_minutes} color="#8E8E93" />
      </div>

      {/* カテゴリ別内訳 */}
      <div className="ios-widget" style={{ marginBottom: 12 }}>
        <div className="w-label">📊 カテゴリ別（予定＋実績＋勉強記録）</div>
        {cats.length === 0 && <div className="caption">まだ記録がありません</div>}
        {cats.map(([c, m]) => (
          <HBar key={c} label={c} minutes={m} max={maxCat} color={CATEGORY_COLORS[c]} />
        ))}
      </div>

      {/* 今日の支出（マネー連動） */}
      <div className="ios-widget" style={{ marginBottom: 12 }}>
        <div className="w-label">💰 今日の支出（合計 ¥{Math.round(t.money?.total ?? 0).toLocaleString()}・{t.money?.count ?? 0}件）</div>
        {(t.money?.items ?? []).length === 0 && (
          <div className="caption">今日の支出はまだ記録されていません（マネータブから記録できます）</div>
        )}
        {(t.money?.items ?? []).map((m, i) => (
          <div className="hbar-row" key={i}>
            <span className="hbar-label" style={{ width: 150 }}>{m.detail}</span>
            <div className="hbar-track">
              <div className="hbar-fill"
                   style={{ width: `${Math.max(2, (m.amount / Math.max(t.money.items[0]?.amount ?? 1, 1)) * 100)}%`,
                            background: '#FFD60A' }} />
            </div>
            <span className="hbar-val">¥{Math.round(m.amount).toLocaleString()}</span>
          </div>
        ))}
      </div>

      {/* PCアプリ上位 */}
      <div className="ios-widget" style={{ marginBottom: 12 }}>
        <div className="w-label">💻 PC使用（合計 {fmtMin(t.pc_total_minutes)}）</div>
        {(t.pc_apps ?? []).length === 0 && (
          <div className="caption">記録なし（pc_tracker 起動中に自動で貯まります）</div>
        )}
        {(t.pc_apps ?? []).map((a) => (
          <HBar key={a.app} label={a.app} minutes={a.minutes}
                max={t.pc_apps[0]?.minutes ?? 1} />
        ))}
      </div>

      {/* マイルール（目標）編集 */}
      <details className="ios-widget">
        <summary className="w-label" style={{ cursor: 'pointer' }}>
          ⚙️ マイルール（{rules.length}件）— 例：娯楽は1日2時間まで
        </summary>
        {rules.map((r, i) => (
          <div className="edit-row" key={i}>
            <span className="life-chip" style={{ borderColor: '#8E8E93', background: '#8E8E9333' }}>
              {r.kind === 'pc_app' ? 'PCアプリ' : 'カテゴリ'}
            </span>
            <span style={{ flex: 1 }}>{r.key}</span>
            <span className="caption">上限 {fmtMin(parseInt(r.max_minutes, 10) || 0)}/日</span>
            <button className="icon" onClick={() => saveRules(rules.filter((_, j) => j !== i))}>🗑</button>
          </div>
        ))}
        <div className="edit-row" style={{ marginTop: 8 }}>
          <select value={ruleKind} onChange={(e) => setRuleKind(e.target.value)}>
            <option value="category">カテゴリ</option>
            <option value="pc_app">PCアプリ名</option>
            <option value="money_day">1日の支出（円）</option>
          </select>
          {ruleKind === 'money_day' ? (
            <span className="caption">1日に使うお金の上限</span>
          ) : ruleKind === 'category' ? (
            <select value={ruleKey} onChange={(e) => setRuleKey(e.target.value)}>
              {['娯楽', '気分転換', '生活', '移動', 'その他'].map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          ) : (
            <input type="text" value={ruleKey} onChange={(e) => setRuleKey(e.target.value)}
                   placeholder="例：steam / chrome" style={{ width: 130 }} />
          )}
          <input type="number" min="10" step="10" value={ruleMax} style={{ width: 90 }}
                 onChange={(e) => setRuleMax(parseInt(e.target.value || 0, 10))} />
          <span className="caption">{ruleKind === 'money_day' ? '円/日まで' : '分/日まで'}</span>
          <button className="small" onClick={() => {
            if (ruleKind !== 'money_day' && !ruleKey) return
            saveRules([...rules, {
              kind: ruleKind,
              key: ruleKind === 'money_day' ? '支出' : ruleKey,
              max_minutes: ruleMax,
            }])
            showToast('マイルールを追加しました ✅')
          }}>➕</button>
        </div>
      </details>
    </div>
  )
}

export default SummaryDay
