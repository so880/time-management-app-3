// ふりかえり（views/review.py の移植）：すべて任意で記録
import { useState } from 'react'
import * as api from '../api.js'

const OPTS = ['未記入', '1', '2', '3', '4', '5']

function ScaleSelect({ label, value, onChange }) {
  // iOS風セグメントコントロール（タップするだけ・説明不要）
  return (
    <div style={{ margin: '12px 0' }}>
      <div style={{ marginBottom: 6 }}>{label}</div>
      <div className="seg">
        {OPTS.map((o) => (
          <button key={o} type="button"
                  className={'seg-btn' + (value === o ? ' on' : '')}
                  onClick={() => onChange(o)}>
            {o}
          </button>
        ))}
      </div>
    </div>
  )
}

function Review({ state, onStateChange, onLogsChanged }) {
  const pr = state.pending_review ?? {}
  const [done, setDone] = useState('')
  const [progress, setProgress] = useState('未記入')
  const [focus, setFocus] = useState('未記入')
  const [sat, setSat] = useState('未記入')
  const [mustdoAns, setMustdoAns] = useState('keep')
  const [busy, setBusy] = useState(false)

  const finish = async (saveDetails) => {
    if (busy) return
    setBusy(true)
    try {
      const st = await api.finishReview({
        save_details: saveDetails,
        done_text: done,
        progress: progress === '未記入' ? '' : progress,
        focus: focus === '未記入' ? '' : focus,
        satisfaction: sat === '未記入' ? '' : sat,
        remove_mustdo: pr.mustdo ? mustdoAns === 'remove' : false,
      })
      onStateChange(st)
      onLogsChanged()
    } finally {
      setBusy(false)
    }
  }

  return (
    // review-solid：リキッドグラス時もシースルーにせず不透明にする（文字の判読性優先）
    <div className="review-solid" style={{ maxWidth: 720, margin: '0 auto' }}>
      <h2 style={{ textAlign: 'center' }}>📝 ふりかえり（すべて任意）</h2>
      <div className="caption">
        【{pr.cat ?? ''}】{pr.task ?? ''} ／ 経過 {pr.em ?? 0} 分
      </div>

      <div style={{ margin: '12px 0' }}>
        <label>
          やったこと（自由記述）
          <textarea
            style={{ width: '100%', minHeight: 90, marginTop: 6 }}
            placeholder="例）長文を3本写経した など"
            value={done}
            onChange={(e) => setDone(e.target.value)}
          />
        </label>
      </div>

      <ScaleSelect label="進捗度合い（1=少し / 5=大きく進んだ）" value={progress} onChange={setProgress} />
      <ScaleSelect label="集中度（1=散漫 / 5=没頭）" value={focus} onChange={setFocus} />
      <ScaleSelect label="満足度（1=不満 / 5=満足）" value={sat} onChange={setSat} />

      {pr.mustdo && (
        <div>
          <div className="hr" />
          <h4>🔴 『今日絶対やる』タスクの確認</h4>
          <div>「{pr.task ?? ''}」は終わりましたか？</div>
          <label style={{ display: 'block', margin: '6px 0' }}>
            <input type="radio" name="mustdo" checked={mustdoAns === 'keep'}
                   onChange={() => setMustdoAns('keep')} /> まだ（リストに残す）
          </label>
          <label style={{ display: 'block', margin: '6px 0' }}>
            <input type="radio" name="mustdo" checked={mustdoAns === 'remove'}
                   onChange={() => setMustdoAns('remove')} /> ✅ 終わったのでリストから消す
          </label>
        </div>
      )}

      <div className="two-btn">
        <button className="primary" onClick={() => finish(true)} disabled={busy}>
          💾 保存してダッシュボードへ
        </button>
        <button onClick={() => finish(false)} disabled={busy}>
          スキップ（記録のみ）
        </button>
      </div>
    </div>
  )
}

export default Review
