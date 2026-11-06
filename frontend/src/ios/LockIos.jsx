// 🔐 制限タブ：いまの制限状態・解除申請（AI審査）・申請履歴・面接などの特例・ブロック記録
// 解除は本人の一存ではできない。理由（何時から何時まで・何のため）を書いて申請し、AI の審査官が
// 「事実かつ必要」と判断したときだけ、その時間帯だけ解除される（gate_api.request_unlock）。
import { useEffect, useState } from 'react'
import * as api from '../api.js'
import { ymd } from '../lib/format.js'
import { usePolling } from '../lib/usePolling.js'

function nowHM(offsetMin = 0) {
  const d = new Date(Date.now() + offsetMin * 60000)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function tomorrowISO(days = 2) {
  const d = new Date()
  d.setDate(d.getDate() + days)   // 日付で足す（夏時間などで24時間ずれない）
  return ymd(d)
}

const EX_STATUS = { pending: '⏳ 審査待ち', approved: '✔ 承認', rejected: '✖ 却下', cancelled: '－ 取り下げ' }

// 💼 面接などの特例（Claude 審査。2026-11-03）：24時間以上前に申請 → Claude が審査 → 承認なら前後60分を全解除＋カメラ停止
function ExemptionSection({ showToast }) {
  const [data, setData] = useState(null)
  const [form, setForm] = useState({ date: tomorrowISO(2), start: '14:00', end: '15:00', company: '', kind: '面接', evidence: '' })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const load = async () => { try { setData(await api.getExemptions()) } catch { /* 表示だけ */ } }
  useEffect(() => { load() }, [])
  const rules = data?.rules ?? { min_lead_hours: 24, max_minutes: 180, margin_min: 60, week_cap: 3, kinds: ['面接', '面談', '説明会', '選考', '座談会', 'インターン', '試験', 'テスト', 'GD'] }
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))
  const submit = async () => {
    if (busy) return
    setBusy(true); setErr('')
    try {
      await api.requestExemption(form)
      showToast?.('申請しました。Claude の審査後に反映されます')
      setForm((f) => ({ ...f, company: '', evidence: '' }))
      await load()
    } catch (e) { setErr(e?.message ?? '送信できませんでした') }
    finally { setBusy(false) }
  }
  return (
    <div className="ios-widget" style={{ marginBottom: 12 }}>
      <div className="w-label">面接などの特例を申請する（Claude 審査）</div>
      <div className="caption">
        面接・面談・選考などは、<strong>開始の{rules.min_lead_hours}時間以上前</strong>に登録してください。Claude が「実在の企業の具体的な選考で、根拠がある」と判断したものだけ承認され、
        承認された時間帯の<strong>前後{rules.margin_min}分</strong>はすべての制限を外し、全画面ロックも出さず、カメラも止めます。
        1件{rules.max_minutes}分以内・週{rules.week_cap}件まで。「準備したい」「念のため」は却下されます。当日の用事は上の「解除を申請する」へ。
      </div>
      <div className="edit-row" style={{ marginTop: 8 }}>
        <input type="date" value={form.date} onChange={set('date')} />
        <input type="time" value={form.start} onChange={set('start')} />
        <span className="caption">〜</span>
        <input type="time" value={form.end} onChange={set('end')} />
        <select value={form.kind} onChange={set('kind')}>
          {(rules.kinds ?? []).map((k) => <option key={k} value={k}>{k}</option>)}
        </select>
      </div>
      <div className="edit-row">
        <input type="text" value={form.company} onChange={set('company')} placeholder="会社・団体名（正式名称）" style={{ flex: 1 }} />
      </div>
      <div className="edit-row">
        <input type="text" value={form.evidence} onChange={set('evidence')} placeholder="根拠：案内メールの件名・予約ページ・担当者名など" style={{ flex: 1 }} />
        <button type="button" className="primary" disabled={busy || form.company.trim().length < 2 || form.evidence.trim().length < 5}
                onClick={submit}>{busy ? '送信中…' : '申請する'}</button>
      </div>
      {err && <div className="info-box warn" style={{ marginTop: 6 }}>{err}</div>}
      {(data?.today ?? []).length > 0 && (
        <div className="info-box" style={{ marginTop: 8 }}>
          💼 今日の特例（承認済み）：{data.today.map((w) => `${w.start}〜${w.end} ${w.title}`).join('／')}
        </div>
      )}
      {(data?.requests ?? []).length > 0 && (
        <div style={{ marginTop: 8 }}>
          {data.requests.slice(0, 10).map((r) => (
            <div key={r.id} className="lock-log-r" style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
              <span>{EX_STATUS[r.status] ?? r.status}{r.over_cap ? '（週の上限超え・無効）' : ''}</span>
              <span>{r.date} {r.start}〜{r.end}　{r.company} {r.kind}</span>
              {r.decision?.reason && <span className="caption">→ {r.decision.reason}</span>}
              {(r.status === 'pending' || r.status === 'approved') && (
                <button type="button" className="small" onClick={async () => {
                  if (!window.confirm('この申請を取り下げますか？')) return
                  try { await api.cancelExemption(r.id); await load() } catch (e) { showToast?.('⚠️ ' + (e?.message ?? '')) }
                }}>取り下げ</button>
              )}
            </div>
          ))}
        </div>
      )}
      <div className="caption" style={{ marginTop: 6 }}>審査の手順と基準：docs/EXEMPTION_REVIEW.md（Claude に「特例の審査をして」と頼むと logs/exemption_requests.json を読んで判断します）</div>
    </div>
  )
}

function LockIos({ showToast }) {
  const [gate, setGate] = useState(null)
  const [log, setLog] = useState(null)
  const [blocked, setBlocked] = useState([])
  const [reason, setReason] = useState('')
  const [start, setStart] = useState(nowHM(0))
  const [end, setEnd] = useState(nowHM(60))
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)

  const load = async () => {
    try {
      const [g, l, b] = await Promise.all([api.getGateStatus(), api.getUnlockLog(), api.getBlockedLog()])
      setGate(g); setLog(l); setBlocked(b.lines ?? [])
    } catch (e) { showToast?.('⚠️ ' + (e?.message ?? '')) }
  }
  // 最初の表示から30秒ごとに読む（load の作り直しでは張り直さない）
  usePolling(load, 30000, [])

  const submit = async () => {
    if (busy) return
    setBusy(true)
    setResult(null)
    try {
      const r = await api.requestUnlock(reason.trim(), start, end)
      setResult(r)
      showToast?.(r.approved ? `✔ 承認：${start}〜${end} の間だけ解除されます` : '✖ 却下されました')
      if (r.approved) setReason('')
      load()
    } catch (e) {
      setResult({ approved: false, judge: e?.message ?? '送信できませんでした' })
    } finally { setBusy(false) }
  }

  const minChars = log?.min_chars ?? 60
  const gw = gate?.game_window ?? { start: '07:00', end: '21:00' }

  return (
    <div>
      <h1 className="ios-large-title">🔐 制限</h1>

      {/* いまの状態 */}
      <div className="ios-widget" style={{ marginBottom: 12 }}>
        <div className="w-label">いまの状態</div>
        {!gate && <div className="caption">読み込み中…</div>}
        {gate && (
          <>
            <div className="lock-row">
              <span>🎮 ゲーム制限</span>
              <strong style={{ color: gate.game_unlocked ? '#4CAF50' : '#FF6B62' }}>
                {gate.game_unlocked ? '解放中' : 'ロック中'}
              </strong>
            </div>
            <div className="lock-row">
              <span>🔒 サイト制限</span>
              <strong style={{ color: gate.site_unlocked ? '#4CAF50' : '#FF6B62' }}>
                {gate.site_unlocked ? '解放中' : 'ロック中'}
              </strong>
            </div>
            <div className="caption" style={{ marginTop: 6 }}>
              解放の条件：必須＋今日の習慣がすべて完了（{gate.tasks_done ? '達成' : `あと${gate.remaining?.length ?? '?'}件`}）
              ／ゲームはさらに 勉強目標の達成 と {gw.start}〜{gw.end}（固定）
            </div>
            {gate.exempt && (
              <div className="info-box" style={{ marginTop: 8 }}>
                💼 特例中：「{gate.exempt.title}」{gate.exempt.start}〜{gate.exempt.end}（すべての制限を外しています）
              </div>
            )}
            {gate.unlock_window && (
              <div className="info-box" style={{ marginTop: 8 }}>
                ✔ 承認された解除：{gate.unlock_window.start}〜{gate.unlock_window.end}
              </div>
            )}
            {(log?.exemptions_today ?? []).length > 0 && (
              <div className="caption" style={{ marginTop: 6 }}>
                今日の特例（Googleカレンダーの面接など。24時間以上前に作成されたもの）：
                {log.exemptions_today.map((w) => ` ${w.start}〜${w.end} ${w.title}`).join(' ／')}
              </div>
            )}
          </>
        )}
      </div>

      {/* 解除申請 */}
      <div className="ios-widget" style={{ marginBottom: 12 }}>
        <div className="w-label">解除を申請する（AI 審査）</div>
        <div className="caption">
          何時から何時まで・何のために必要かを、事実にもとづいて{minChars}文字以上で書いてください。
          申請どおりか却下の二択です。娯楽・気分転換・「少しだけ」は却下されます。目的に対して長すぎる時間も却下されます。
        </div>
        <div className="edit-row" style={{ marginTop: 8 }}>
          <span className="caption">開始</span>
          <input type="time" value={start} onChange={(e) => setStart(e.target.value)} />
          <span className="caption">終了</span>
          <input type="time" value={end} onChange={(e) => setEnd(e.target.value)} />
        </div>
        <textarea className="day-setup-text" style={{ minHeight: 100, marginTop: 6 }} value={reason}
                  placeholder={'例）14:00〜15:30、A社の二次面接の事前課題として提出する動画（YouTube非公開リンク）を視聴し、感想を提出する必要がある。提出期限は本日17:00。'}
                  onChange={(e) => setReason(e.target.value)} />
        <div className="edit-row">
          <button type="button" className="primary" disabled={busy || reason.trim().length < minChars}
                  onClick={submit}>{busy ? '審査中…（最大1分）' : '申請する'}</button>
          <span className="caption">{reason.trim().length} / {minChars} 文字</span>
        </div>
        {result && (
          <div className={'info-box' + (result.approved ? '' : ' warn')} style={{ marginTop: 8 }}>
            {result.approved ? '✔ 承認' : '✖ 却下'}：{result.judge}
          </div>
        )}
      </div>

      {/* 💼 面接などの特例（Claude 審査） */}
      <ExemptionSection showToast={showToast} />

      {/* 申請履歴 */}
      <div className="ios-widget" style={{ marginBottom: 12 }}>
        <div className="w-label">申請の履歴</div>
        {log && log.logs.length === 0 && <div className="caption">まだありません</div>}
        {(log?.logs ?? []).map((l, i) => (
          <div key={i} className="lock-log">
            <div className="lock-log-h">
              <span className="caption">{l.ts}</span>
              <strong style={{ color: l.approved ? '#4CAF50' : '#FF6B62' }}>{l.approved ? '承認' : '却下'}</strong>
              {l.start && <span className="caption">{l.start}〜{l.end}</span>}
            </div>
            <div className="lock-log-r">{l.reason}</div>
            {l.judge && <div className="caption">審査官：{l.judge}</div>}
          </div>
        ))}
      </div>

      {/* ブロックの記録 */}
      <div className="ios-widget">
        <div className="w-label">ブロックで止めたもの（直近）</div>
        {blocked.length === 0 && <div className="caption">記録なし</div>}
        {blocked.map((x, i) => <div key={i} className="caption" style={{ fontFamily: 'monospace' }}>{x}</div>)}
      </div>
    </div>
  )
}

export default LockIos
