// iOS「設定」アプリ風の設定画面（リキッドグラスON時のみ使用）
// 内容は components/Sidebar.jsx と同一（環境音・背景・見た目・履歴・リセット）。
import { useRef, useState } from 'react'
import * as api from '../api.js'
import BgmPlayer from '../components/BgmPlayer.jsx'

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

// iOS設定アプリの1行（アイコン角丸タイル＋ラベル＋開閉シェブロン）
function Row({ icon, color, label, children, right }) {
  return (
    <details className="ios-row-details">
      <summary className="ios-row">
        <span className="r-icon" style={{ background: color }}>{icon}</span>
        <span className="r-label">{label}</span>
        {right != null && <span className="r-right">{right}</span>}
        <span className="r-chevron">›</span>
      </summary>
      <div className="ios-row-body">{children}</div>
    </details>
  )
}

function SettingsIos({ settings, logs, onSettingsChange, onStateChange, onLogsChanged, showToast }) {
  const [cafe, setCafe] = useState(settings.snd_cafe_url ?? '')
  const [chat, setChat] = useState(settings.snd_chat_url ?? '')
  const [relax, setRelax] = useState(settings.snd_relax_url ?? '')
  const fileRef = useRef(null)

  const save = async (changes) => {
    const s = await api.updateSettings(changes)
    onSettingsChange(s)
  }

  const downloadCsv = () => {
    const blob = new Blob(['﻿' + toCsv(logs)], { type: 'text/csv;charset=utf-8' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = 'activity_log.csv'
    a.click()
    URL.revokeObjectURL(a.href)
  }

  const resetAll = async () => {
    if (!window.confirm('全データリセットを実行しますか？（履歴と今日の状態が消えます）')) return
    onStateChange(await api.resetAll())
    onLogsChanged()
    showToast('全データをリセットしました')
  }

  const upload = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    try {
      await api.uploadBackground(file)
      onSettingsChange(await api.getSettings())
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
      <h1 className="ios-large-title">⚙️ 設定</h1>

      <div className="ios-list">
        <Row icon="🎧" color="#34C759" label="環境音（YouTube）">
          <BgmPlayer cafeId={settings.snd_cafe_url} chatId={settings.snd_chat_url}
                     relaxId={settings.snd_relax_url} />
          <div className="caption" style={{ margin: '8px 0 4px' }}>ボタンのURL/IDを変更：</div>
          {[['☕ カフェ', cafe, setCafe], ['🗣️ 雑踏', chat, setChat], ['🐋 波と鯨', relax, setRelax]]
            .map(([lbl, val, set]) => (
              <div className="edit-row" key={lbl}>
                <span style={{ whiteSpace: 'nowrap' }}>{lbl}</span>
                <input type="text" value={val} onChange={(e) => set(e.target.value)} />
              </div>
            ))}
          <button className="small" onClick={() => {
            save({
              snd_cafe_url: cafe.trim() || settings.snd_cafe_url,
              snd_chat_url: chat.trim() || settings.snd_chat_url,
              snd_relax_url: relax.trim() || settings.snd_relax_url,
            })
            showToast('環境音のURLを保存しました ✅')
          }}>💾 保存</button>
        </Row>

        <Row icon="🖼️" color="#007AFF" label="背景" right={bgMode}>
          {['カフェ画像', '黒画面', 'アップロード画像'].map((mode) => (
            <label key={mode} className={'option-label' + (bgMode === mode ? ' selected' : '')}
                   style={{ padding: '12px 14px', fontSize: '1rem' }}>
              <input type="radio" name="ios_bg" checked={bgMode === mode}
                     onChange={() => save({ bg_mode: mode })} />
              {mode}
            </label>
          ))}
          {bgMode === 'アップロード画像' && (
            <div>
              <input ref={fileRef} type="file" accept=".png,.jpg,.jpeg"
                     onChange={upload} style={{ width: '100%' }} />
              {hist.length > 0 && (
                <div style={{ marginTop: 6 }}>
                  <select style={{ width: '100%' }} value={settings.bg_current_file ?? ''}
                          onChange={(e) => save({ bg_current_file: e.target.value })}>
                    {hist.map((f) => <option key={f} value={f}>{f}</option>)}
                  </select>
                  <button className="small" style={{ marginTop: 6 }} onClick={async () => {
                    const cur = settings.bg_current_file
                    if (!cur) return
                    await api.deleteBackground(cur)
                    onSettingsChange(await api.getSettings())
                    showToast('履歴から削除しました')
                  }}>🗑 この画像を削除</button>
                </div>
              )}
            </div>
          )}
        </Row>

        <div className="ios-row ios-row-static">
          <span className="r-icon" style={{ background: '#AF52DE' }}>✨</span>
          <span className="r-label">リキッドグラス風UI</span>
          <input type="checkbox" checked={!!settings.liquid_glass_enabled}
                 onChange={(e) => {
                   save({ liquid_glass_enabled: e.target.checked })
                   showToast('見た目を切り替えました ✨')
                 }} />
        </div>

        <Row icon="📁" color="#8E8E93" label="履歴" right={`${logs.length}件`}>
          <div className="caption" style={{ marginBottom: 6 }}>
            ふりかえり・中断などの全記録（{logs.length}件）をCSVで保存できます。
          </div>
          <button className="small" onClick={downloadCsv} disabled={logs.length === 0}>
            ⬇️ 履歴をダウンロード
          </button>
        </Row>
      </div>

      <div className="ios-list" style={{ marginTop: 16 }}>
        <button className="ios-row ios-row-danger" onClick={resetAll}>
          <span className="r-icon" style={{ background: '#FF3B30' }}>🗑</span>
          <span className="r-label">全データリセット</span>
        </button>
      </div>
      <div className="caption" style={{ margin: '8px 4px' }}>
        履歴と今日の状態を消去します（リスト等の設定は残ります）。
      </div>
    </div>
  )
}

export default SettingsIos
