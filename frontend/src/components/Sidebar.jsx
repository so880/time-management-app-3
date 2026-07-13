// サイドバー（app.py のサイドバー部分の移植）
// 🎧環境音 / 🖼️背景 / 🔄モード切替 / ✨リキッドグラス / 記録数・履歴DL / 全データリセット
import { useRef, useState } from 'react'
import * as api from '../api.js'
import BgmPlayer from './BgmPlayer.jsx'

const LOG_COLUMNS = ['日付', 'カテゴリ', '内容', 'BGM', '経過時間(分)',
  'やったこと', '進捗度合い', '集中度', '満足度', 'メモ']

function toCsv(logs) {
  const esc = (v) => {
    const s = String(v ?? '')
    return /[",\n]/.test(s) ? '"' + s.replaceAll('"', '""') + '"' : s
  }
  const lines = [LOG_COLUMNS.join(',')]
  for (const log of logs) lines.push(LOG_COLUMNS.map((c) => esc(log[c])).join(','))
  return lines.join('\n')
}

function Sidebar({ settings, logs, appMode, setAppMode,
                   onSettingsChange, onStateChange, onLogsChanged, showToast }) {
  const [editSnd, setEditSnd] = useState(false)
  const [cafe, setCafe] = useState(settings.snd_cafe_url ?? 'e_04ZrNroTo')
  const [chat, setChat] = useState(settings.snd_chat_url ?? 'bZ2XhA_kXYQ')
  const [relax, setRelax] = useState(settings.snd_relax_url ?? 'vPhg6sc1Mk4')
  const fileRef = useRef(null)

  const save = async (changes) => {
    const s = await api.updateSettings(changes)
    onSettingsChange(s)
  }

  const downloadCsv = () => {
    // 既存と同じく utf-8-sig（BOM付き）でダウンロード
    const blob = new Blob(['﻿' + toCsv(logs)], { type: 'text/csv;charset=utf-8' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = 'activity_log.csv'
    a.click()
    URL.revokeObjectURL(a.href)
  }

  const resetAll = async () => {
    if (!window.confirm('全データリセットを実行しますか？（履歴と今日の状態が消えます）')) return
    const st = await api.resetAll()
    onStateChange(st)
    onLogsChanged()
    showToast('全データをリセットしました')
  }

  const upload = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    try {
      await api.uploadBackground(file)
      const s = await api.getSettings()
      onSettingsChange(s)
      showToast('背景画像をアップロードしました ✅')
    } catch (err) {
      showToast(`アップロード失敗: ${err.message}`)
    } finally {
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const bgMode = settings.bg_mode ?? 'カフェ画像'
  const hist = settings.bg_history ?? []

  return (
    <div>
      <details open>
        <summary>🎧 環境音コントロール</summary>
        <BgmPlayer
          cafeId={settings.snd_cafe_url}
          chatId={settings.snd_chat_url}
          relaxId={settings.snd_relax_url}
        />
        <label style={{ display: 'block', margin: '8px 0' }}>
          <input type="checkbox" checked={editSnd}
                 onChange={(e) => setEditSnd(e.target.checked)} />{' '}
          ⚙️ ボタン(カフェ/雑踏/波)のURLを変更
        </label>
        {editSnd && (
          <div>
            <label>☕ カフェ のURL/ID
              <input type="text" style={{ width: '100%' }} value={cafe}
                     onChange={(e) => setCafe(e.target.value)} />
            </label>
            <label>🗣️ 雑踏 のURL/ID
              <input type="text" style={{ width: '100%' }} value={chat}
                     onChange={(e) => setChat(e.target.value)} />
            </label>
            <label>🐋 波と鯨 のURL/ID
              <input type="text" style={{ width: '100%' }} value={relax}
                     onChange={(e) => setRelax(e.target.value)} />
            </label>
            <button className="small" style={{ marginTop: 6 }} onClick={() => {
              save({
                snd_cafe_url: cafe.trim() || settings.snd_cafe_url,
                snd_chat_url: chat.trim() || settings.snd_chat_url,
                snd_relax_url: relax.trim() || settings.snd_relax_url,
              })
              showToast('環境音のURLを保存しました ✅')
            }}>💾 環境音のURLを保存</button>
          </div>
        )}
      </details>

      <details>
        <summary>🖼️ 背景</summary>
        {['カフェ画像', '黒画面', 'アップロード画像'].map((m) => (
          <label key={m} style={{ display: 'block', margin: '6px 0' }}>
            <input type="radio" name="bg_mode" checked={bgMode === m}
                   onChange={() => save({ bg_mode: m })} /> {m}
          </label>
        ))}
        {bgMode === 'アップロード画像' && (
          <div>
            <input ref={fileRef} type="file" accept=".png,.jpg,.jpeg" onChange={upload}
                   style={{ width: '100%' }} />
            {hist.length > 0 ? (
              <div style={{ marginTop: 6 }}>
                <label>📚 履歴から選ぶ
                  <select style={{ width: '100%' }}
                          value={settings.bg_current_file ?? ''}
                          onChange={(e) => save({ bg_current_file: e.target.value })}>
                    {hist.map((h) => <option key={h} value={h}>{h}</option>)}
                  </select>
                </label>
                <button className="small" style={{ marginTop: 6 }} onClick={async () => {
                  const cur = settings.bg_current_file
                  if (!cur) return
                  await api.deleteBackground(cur)
                  const s = await api.getSettings()
                  onSettingsChange(s)
                  showToast('履歴から削除しました')
                }}>🗑 履歴から削除</button>
                <div className="caption">🖼️ 現在: {settings.bg_current_file || '(なし)'}</div>
              </div>
            ) : (
              <div className="caption">まだ画像がありません。上からアップロードしてください。</div>
            )}
          </div>
        )}
        {bgMode === '黒画面' && <div className="caption">⬛ 画像を消して集中しやすい黒背景にします。</div>}
        {bgMode === 'カフェ画像' && <div className="caption">☕ カフェ画像（URLは編集モードで変更可）。</div>}
      </details>

      <details open>
        <summary>🔄 モード切替</summary>
        {[['use', '🚀 集中モード (Use)'], ['edit', '🛠️ 編集モード (Edit)']].map(([v, lbl]) => (
          <label key={v}
                 className={'option-label' + (appMode === v ? ' selected' : '')}
                 style={{ padding: '10px 12px', fontSize: '1rem' }}>
            <input type="radio" name="app_mode" checked={appMode === v}
                   onChange={() => setAppMode(v)} style={{ marginRight: 8 }} />
            {lbl}
          </label>
        ))}
      </details>

      <details>
        <summary>✨ 見た目（リキッドグラス）</summary>
        <label style={{ display: 'block', margin: '6px 0' }}>
          <input type="checkbox" checked={!!settings.liquid_glass_enabled}
                 onChange={(e) => {
                   save({ liquid_glass_enabled: e.target.checked })
                   showToast('見た目を切り替えました ✨')
                 }} /> リキッドグラス風UIをオンにする
        </label>
        <div className="caption">
          透明感・ぼかし・ホバー/押下の動き・登場アニメが全体に付きます。オフで従来UIに戻ります。
        </div>
      </details>

      <div className="hr" />
      <div>📁 記録数: {logs.length}件</div>
      {logs.length > 0 && (
        <button className="small" style={{ marginTop: 6 }} onClick={downloadCsv}>
          履歴ダウンロード
        </button>
      )}
      {appMode === 'edit' && (
        <div style={{ marginTop: 10 }}>
          <button className="primary small" onClick={resetAll}>全データリセット</button>
        </div>
      )}
    </div>
  )
}

export default Sidebar
