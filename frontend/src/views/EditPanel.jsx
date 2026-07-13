// 編集モード（views/dashboard.py の編集モード部分の移植）
// UI は iOS の「設定」アプリと同じドリルダウン式：
//   一覧（アイコン付きリスト）→ タップで各ページへ →「‹ 編集」で戻る
// 設定はすべて即時に PUT /api/settings で保存される（既存 save_settings 相当）
import { useEffect, useState } from 'react'
import * as api from '../api.js'

const GOAL_CAP = 6 // config.py と同じ

// ---- ルーレット項目の編集（edit_list_ui の移植） ----
function EditList({ label, keyName, settings, save, showToast }) {
  const list = settings[keyName] ?? []
  const disabled = settings[`${keyName}_disabled`] ?? []
  const [newItem, setNewItem] = useState('')

  const rename = (i, nv) => {
    const lst = [...list]
    const old = lst[i]
    if (nv === old) return
    const dis = [...disabled]
    const di = dis.indexOf(old)
    if (di >= 0) dis[di] = nv
    lst[i] = nv
    save({ [keyName]: lst, [`${keyName}_disabled`]: dis })
  }

  const toggle = (item, active) => {
    let dis = [...disabled]
    if (active) dis = dis.filter((x) => x !== item)
    else if (!dis.includes(item)) dis.push(item)
    save({ [`${keyName}_disabled`]: dis })
  }

  const remove = (i) => {
    const lst = [...list]
    const item = lst[i]
    lst.splice(i, 1)
    const dis = disabled.filter((x) => x !== item)
    save({ [keyName]: lst, [`${keyName}_disabled`]: dis })
  }

  const add = (e) => {
    e.preventDefault()
    const v = newItem.trim()
    if (!v) {
      showToast('⚠️ 空欄は追加できません')
      return
    }
    save({ [keyName]: [...list, v] })
    showToast(`「${v}」を追加しました ✅`)
    setNewItem('')
  }

  return (
    <div>
      <div className="caption" style={{ marginBottom: 8 }}>
        スイッチをオフにすると『無効』になり、消さずに抽選から除外できます。🗑で削除。
      </div>
      {list.map((item, i) => (
        <div className="edit-row" key={`${i}_${item}`}>
          <input
            type="text"
            defaultValue={item}
            onBlur={(e) => rename(i, e.target.value)}
          />
          <input
            type="checkbox"
            title="有効/無効"
            checked={!disabled.includes(item)}
            onChange={(e) => toggle(item, e.target.checked)}
          />
          <button className="icon" onClick={() => remove(i)}>🗑</button>
        </div>
      ))}
      <form onSubmit={add} className="edit-row">
        <input
          type="text"
          placeholder={`新しい${label}を入力してEnter…`}
          value={newItem}
          onChange={(e) => setNewItem(e.target.value)}
        />
        <button type="submit">➕ 追加</button>
      </form>
    </div>
  )
}

// ---- 曜日別の勉強できる時間帯 ----
function RoutineEditor({ settings, save }) {
  const days = ['月', '火', '水', '木', '金', '土', '日']
  const routine = settings.daily_routine ?? []
  while (routine.length < 7) routine.push([{ start: '09:00', end: '22:00' }])

  const update = (di, ri, field, value) => {
    const r = routine.map((d) => d.map((iv) => ({ ...iv })))
    r[di][ri][field] = value
    save({ daily_routine: r })
  }
  const removeIv = (di, ri) => {
    const r = routine.map((d) => d.map((iv) => ({ ...iv })))
    r[di].splice(ri, 1)
    save({ daily_routine: r })
  }
  const addIv = (di) => {
    const r = routine.map((d) => d.map((iv) => ({ ...iv })))
    r[di].push({ start: '09:00', end: '12:00' })
    save({ daily_routine: r })
  }

  return (
    <div>
      <div className="caption" style={{ marginBottom: 8 }}>
        曜日ごとに『勉強できる時間帯』を複数登録できます（大学・食事の時間は除いて登録）。
        ホームの『今日まだ勉強できる時間』に反映されます。
      </div>
      {days.map((dn, di) => (
        <div key={dn} className="ios-day-block">
          <strong>{dn}曜日</strong>
          {(routine[di] ?? []).length === 0 && <div className="caption">（時間帯なし）</div>}
          {(routine[di] ?? []).map((iv, ri) => (
            <div className="edit-row" key={ri}>
              <input type="time" value={iv.start ?? '09:00'}
                     onChange={(e) => update(di, ri, 'start', e.target.value)} />
              〜
              <input type="time" value={iv.end ?? '22:00'}
                     onChange={(e) => update(di, ri, 'end', e.target.value)} />
              <button className="icon" onClick={() => removeIv(di, ri)}>🗑</button>
            </div>
          ))}
          <button className="small" onClick={() => addIv(di)}>➕ {dn}に時間帯を追加</button>
        </div>
      ))}
    </div>
  )
}

// ---- 目標の編集（名前・日付・1日の時間をまとめて1ページに） ----
function GoalsEditor({ settings, save, showToast }) {
  const goals = settings.goals ?? []
  return (
    <div>
      {goals.map((g, i) => (
        <div key={i} className="ios-goal-block">
          <div className="edit-row">
            <input type="text" defaultValue={g.name ?? ''} placeholder="目標の名前"
                   onBlur={(e) => {
                     if (e.target.value === g.name) return
                     const gs = goals.map((x) => ({ ...x }))
                     gs[i].name = e.target.value
                     save({ goals: gs })
                   }} />
            <button className="icon" onClick={() => {
              if (goals.length <= 1) { showToast('⚠️ 目標は最低1つ必要です'); return }
              save({ goals: goals.filter((_, j) => j !== i) })
            }}>🗑</button>
          </div>
          <div className="edit-row">
            <input type="date" value={g.date ?? ''}
                   onChange={(e) => {
                     const gs = goals.map((x) => ({ ...x }))
                     gs[i].date = e.target.value
                     save({ goals: gs })
                   }} />
            <label style={{ whiteSpace: 'nowrap' }}>
              1日{' '}
              <input type="number" min="1" max="24" value={parseInt(g.hours ?? 2, 10)}
                     style={{ width: 64 }}
                     onChange={(e) => {
                       const gs = goals.map((x) => ({ ...x }))
                       gs[i].hours = Math.max(1, Math.min(24, parseInt(e.target.value || 1, 10)))
                       save({ goals: gs })
                     }} />{' '}時間
            </label>
          </div>
        </div>
      ))}
      {goals.length < GOAL_CAP ? (
        <button className="small" onClick={() => {
          const today = new Date().toISOString().slice(0, 10)
          save({ goals: [...goals, { name: '新しい目標', date: today, hours: 2 }] })
        }}>➕ 目標を追加</button>
      ) : (
        <div className="caption">見やすさのため目標は最大{GOAL_CAP}個までです。</div>
      )}
    </div>
  )
}

// ---- 勉強タスクの所要時間 ----
function DurationEditor({ settings, save }) {
  const [durMax, setDurMax] = useState(parseInt(settings.study_dur_max ?? 60, 10))
  const apply = (v) => {
    const nv = Math.max(30, Math.min(600, parseInt(v || 30, 10)))
    setDurMax(nv)
    save({ study_dur_min: 30, study_dur_max: nv })
  }
  return (
    <div>
      <div className="caption" style={{ marginBottom: 8 }}>
        下限は30分で固定。上限はスライダー・±ボタン・直接入力（10刻み）で変更できます。
      </div>
      <input type="range" min="30" max="600" step="10" value={durMax}
             style={{ width: '100%' }}
             onChange={(e) => setDurMax(parseInt(e.target.value, 10))}
             onMouseUp={(e) => apply(e.target.value)}
             onTouchEnd={(e) => apply(e.target.value)} />
      <div className="edit-row">
        <button className="small" onClick={() => apply(durMax - 30)}>−30</button>
        <button className="small" onClick={() => apply(durMax - 10)}>−10</button>
        <button className="small" onClick={() => apply(durMax + 10)}>＋10</button>
        <button className="small" onClick={() => apply(durMax + 30)}>＋30</button>
        <input type="number" min="30" step="10" value={durMax} style={{ width: 90 }}
               onChange={(e) => setDurMax(parseInt(e.target.value || 30, 10))}
               onBlur={(e) => apply(e.target.value)} />
      </div>
      <div className="info-box">勉強タスクは 30分 〜 {durMax}分 の範囲でランダムになります。</div>
    </div>
  )
}

// ---- ゲームブロック ----
function GameBlockEditor({ settings, save, showToast }) {
  const [game, setGame] = useState(null)
  const [blockTxt, setBlockTxt] = useState((settings.block_process_list ?? []).join('\n'))
  const [blockOn, setBlockOn] = useState(!!settings.block_enabled)
  useEffect(() => {
    api.getGameStatus().then(setGame).catch(() => {})
  }, [])
  return (
    <div>
      {game && (game.unlocked ? (
        <div className="success-box">現在: 🔓 解放中（ゲームはブロックされません）</div>
      ) : (
        <div className="warn-box">現在: 🔒 未解放（対象ゲームは起動しても終了させられます）</div>
      ))}
      <div className="caption">
        ブロックしたいゲームの実行ファイル名を1行に1つ入力（例: ShadowverseWB.exe）。
        名前は タスクマネージャー(Ctrl+Shift+Esc) の『詳細』タブで確認できます。大文字小文字は区別しません。
      </div>
      <textarea style={{ width: '100%', minHeight: 110, margin: '8px 0' }}
                value={blockTxt} onChange={(e) => setBlockTxt(e.target.value)} />
      <label style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
        <input type="checkbox" checked={blockOn}
               onChange={(e) => setBlockOn(e.target.checked)} /> ブロックを有効にする
      </label>
      <button onClick={() => {
        save({
          block_process_list: blockTxt.split('\n').map((x) => x.trim()).filter(Boolean),
          block_enabled: blockOn,
        })
        showToast('ゲームブロック設定を保存しました ✅')
      }}>💾 保存</button>
    </div>
  )
}

// ---- 背景画像URL ----
function BgUrlEditor({ settings, save, showToast }) {
  const [bgUrl, setBgUrl] = useState(settings.bg_url ?? '')
  return (
    <div>
      <div className="caption" style={{ marginBottom: 8 }}>
        「カフェ画像」モードで使う背景画像のURL（画像アドレス）を設定します。
      </div>
      <input type="text" style={{ width: '100%', marginBottom: 8 }}
             value={bgUrl} onChange={(e) => setBgUrl(e.target.value)}
             placeholder="https://…（画像のアドレス）" />
      <button onClick={() => { save({ bg_url: bgUrl }); showToast('保存しました ✅') }}>💾 保存</button>
    </div>
  )
}

// ---- 一覧の1行 ----
function MenuRow({ icon, color, label, right, onClick }) {
  return (
    <button type="button" className="ios-row" onClick={onClick}>
      <span className="r-icon" style={{ background: color }}>{icon}</span>
      <span className="r-label">{label}</span>
      {right != null && <span className="r-right">{right}</span>}
      <span className="r-chevron">›</span>
    </button>
  )
}

// ---- 編集モード本体（一覧 ⇄ 各ページのドリルダウン） ----
function EditPanel({ settings, onSettingsChange, showToast }) {
  const [section, setSection] = useState(null)

  const save = async (changes) => {
    const s = await api.updateSettings(changes)
    onSettingsChange(s)
  }

  const activeCount = (keyName) => {
    const dis = settings[`${keyName}_disabled`] ?? []
    return (settings[keyName] ?? []).filter((t) => !dis.includes(t)).length
  }

  const SECTIONS = {
    mustdo: {
      icon: '🔴', color: '#FF3B30', label: '今日絶対やる',
      right: `${activeCount('mustdo_list')}件`,
      note: 'ここに項目があると、勉強の抽選はこのリストだけから出ます。空になると通常勉強に戻ります。タスク終了後に『消す』と答えると自動で消えます。',
      body: <EditList label="今日絶対やる" keyName="mustdo_list" settings={settings} save={save} showToast={showToast} />,
    },
    study: {
      icon: '📘', color: '#007AFF', label: '通常勉強',
      right: `${activeCount('study_list')}件`,
      body: <EditList label="通常勉強" keyName="study_list" settings={settings} save={save} showToast={showToast} />,
    },
    focus: {
      icon: '🔥', color: '#FF9500', label: '重点（出やすさ3倍）',
      right: `${activeCount('focus_study_list')}件`,
      body: <EditList label="重点" keyName="focus_study_list" settings={settings} save={save} showToast={showToast} />,
    },
    refresh: {
      icon: '☕', color: '#34C759', label: '気分転換',
      right: `${activeCount('refresh_list')}件`,
      body: <EditList label="気分転換" keyName="refresh_list" settings={settings} save={save} showToast={showToast} />,
    },
    goals: {
      icon: '🏁', color: '#AF52DE', label: '目標（名前・日付・1日の時間）',
      right: `${(settings.goals ?? []).length}個`,
      body: <GoalsEditor settings={settings} save={save} showToast={showToast} />,
    },
    duration: {
      icon: '⏱️', color: '#5856D6', label: '勉強タスクの所要時間',
      right: `30〜${parseInt(settings.study_dur_max ?? 60, 10)}分`,
      body: <DurationEditor settings={settings} save={save} />,
    },
    routine: {
      icon: '🕐', color: '#FF9F0A', label: '勉強できる時間帯（曜日別）',
      body: <RoutineEditor settings={settings} save={save} />,
    },
    gameblock: {
      icon: '🎮', color: '#8E8E93', label: 'ゲームブロック',
      right: settings.block_enabled ? 'オン' : 'オフ',
      body: <GameBlockEditor settings={settings} save={save} showToast={showToast} />,
    },
    bgurl: {
      icon: '🖼️', color: '#64D2FF', label: '背景画像のURL',
      body: <BgUrlEditor settings={settings} save={save} showToast={showToast} />,
    },
  }

  // ---- 各ページ（ドリルダウン先） ----
  if (section && SECTIONS[section]) {
    const s = SECTIONS[section]
    return (
      <div key={section} className="page-anim">
        <button type="button" className="ios-back" onClick={() => setSection(null)}>
          ‹ 編集
        </button>
        <h2 className="ios-section-title">
          <span className="r-icon" style={{ background: s.color }}>{s.icon}</span>
          {s.label}
        </h2>
        {s.note && <div className="caption" style={{ marginBottom: 10 }}>{s.note}</div>}
        <div className="ios-section-body">{s.body}</div>
      </div>
    )
  }

  // ---- 一覧（メニュー） ----
  const rows = (ids) => ids.map((id) => (
    <MenuRow key={id} icon={SECTIONS[id].icon} color={SECTIONS[id].color}
             label={SECTIONS[id].label} right={SECTIONS[id].right}
             onClick={() => setSection(id)} />
  ))

  return (
    <div className="edit-panel">
      <div className="ios-group-title">📝 ルーレット項目</div>
      <div className="ios-list">{rows(['mustdo', 'study', 'focus', 'refresh'])}</div>

      <div className="ios-group-title">⚙️ アプリ設定</div>
      <div className="ios-list">{rows(['goals', 'duration', 'routine', 'gameblock', 'bgurl'])}</div>
    </div>
  )
}

export default EditPanel
