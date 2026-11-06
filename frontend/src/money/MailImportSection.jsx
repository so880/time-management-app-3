// 💰 利用通知メールの自動取り込み（設定・操作）。MoneyIos.jsx から分けた（props・動作は同じ）
import { useEffect, useState } from 'react'
import * as api from '../api.js'

/* ---------- 📧 利用通知メールの自動取り込み（設定・操作） ---------- */
function MailImportSection({ settings, onSettingsChange, onImported, showToast }) {
  const [user, setUser] = useState(settings.mail_user ?? '')
  // パスワードは本体から中身が返らない（secrets_set で設定済みかだけ分かる）。入力したときだけ上書きする
  const [pw, setPw] = useState('')
  const pwSet = !!settings.secrets_set?.mail_app_password
  const [enabled, setEnabled] = useState(!!settings.mail_import_enabled)
  const [since, setSince] = useState('2025-04-01')
  const [status, setStatus] = useState(null)
  const [busy, setBusy] = useState(false)

  const refreshStatus = async () => {
    try { setStatus(await api.moneyMailStatus()) } catch { /* 未接続時は無視 */ }
  }
  useEffect(() => { refreshStatus() }, [])

  const save = async () => {
    try {
      onSettingsChange(await api.updateSettings({
        mail_user: user.trim(),
        mail_app_password: pw.trim(),
        mail_import_enabled: enabled,
      }))
      setPw('')
      showToast('メール取り込み設定を保存しました ✅')
    } catch (e) { showToast('⚠️ ' + e.message) }
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
          <input type="password" value={pw} style={{ flex: 1 }}
                 placeholder={pwSet ? '設定済み（変えるときだけ入力）' : 'アプリパスワード（16文字）'}
                 onChange={(e) => setPw(e.target.value)} autoComplete="new-password" />
          <button className="small" onClick={save}>💾 保存</button>
        </div>
        {pwSet && <div className="caption">✅ アプリパスワードは保存済みです（変えるときだけ入力してください）</div>}
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

export default MailImportSection
