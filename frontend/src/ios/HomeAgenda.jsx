// 🗓 ホーム「アジェンダ型」（2026-11-03 依頼者の選択：W1「いまの行」を標準、設定で W2「ダイヤル」に切替）
// 左＝縦の時間軸（固定）、左上＝日付と時刻を横並び、右＝やることの一覧と数字。絵文字・色チップ・ガラス風カードは使わない。
// データと操作（ルーレット・選ぶ・チェック・タイマー開始・小窓）はすべて HomeIos.jsx から ctx で受け取る（ロジックの重複なし）。
import { useEffect, useMemo, useState } from 'react'
import * as api from '../api.js'
import { hmToMin, pad2 } from '../lib/format.js'

const DAY = ['月', '火', '水', '木', '金', '土', '日']

const hm2f = (hm) => hmToMin(hm) / 60   // "HH:MM" → 時（小数）

// 時間軸の中身：重なりは最大3レーンに分ける。重ならないものは全幅
function layoutItems(items) {
  const sorted = [...items].filter((x) => x.start && x.end).map((x) => ({ ...x, s: hm2f(x.start), e: Math.max(hm2f(x.end), hm2f(x.start) + 0.25) }))
    .sort((a, b) => a.s - b.s || b.e - a.e)
  const lanes = []
  for (const it of sorted) {
    let li = lanes.findIndex((end) => end <= it.s)
    if (li < 0) { if (lanes.length < 3) { lanes.push(it.e); li = lanes.length - 1 } else { li = lanes.length - 1; lanes[li] = it.e } } else lanes[li] = it.e
    it.lane = li
  }
  for (const it of sorted) it.full = !sorted.some((o) => o !== it && o.s < it.e && o.e > it.s)
  return { items: sorted, laneCount: Math.max(1, lanes.length) }
}

// 📐 縦の時間軸
function AgendaDay({ items, nowF, children }) {
  const { items: laid, laneCount } = layoutItems(items)
  const h0 = Math.min(5, ...laid.map((x) => Math.floor(x.s)))
  const h1 = Math.max(23, ...laid.map((x) => Math.ceil(x.e)))
  const pos = (f) => (f - h0) / (h1 - h0) * 100
  const hours = []
  for (let h = h0; h <= h1; h += 2) hours.push(h)
  const nowPos = Math.max(0, Math.min(100, pos(nowF)))
  return (
    <div className="ha-ag" aria-label="今日の時間軸">
      {hours.map((h) => <div key={h} className="ha-hr" style={{ top: `${pos(h)}%` }}><span>{h}:00</span></div>)}
      {laid.map((it, i) => {
        const w = it.full ? 'calc(100% - 48px)' : `calc((100% - 48px) / ${laneCount} - 4px)`
        const left = it.full ? '48px' : `calc(48px + (100% - 48px) / ${laneCount} * ${it.lane})`
        return (
          <div key={i} className={'ha-ev ' + it.kind + (it.done ? ' done' : '')} title={`${it.start}〜${it.end} ${it.title}`}
               style={{ top: `${pos(it.s)}%`, height: `${pos(it.e) - pos(it.s)}%`, left, width: w }}>{it.title}</div>
        )
      })}
      <div className="ha-now" style={{ top: `${nowPos}%` }} />
      <div className={'ha-nowcard-wrap' + (nowPos <= 0 ? ' at-top' : nowPos >= 100 ? ' at-bottom' : '')} style={{ top: `${nowPos}%` }}>{children}</div>
    </div>
  )
}

// 🎯 ダイヤル（設定で切替）：ルーレット項目を扇形に並べ、中心に小窓の計測
function Dial({ labels, center, sub, highlight }) {
  const n = Math.max(1, labels.length)
  const R = 118, r = 74, C = 150
  const pt = (a, rr) => [C + rr * Math.cos((a * Math.PI) / 180), C + rr * Math.sin((a * Math.PI) / 180)]
  const segs = labels.map((l, i) => {
    const a0 = (360 / n) * i - 90, a1 = (360 / n) * (i + 1) - 90
    const [x0, y0] = pt(a0, R), [x1, y1] = pt(a1, R), [xi0, yi0] = pt(a0, r), [xi1, yi1] = pt(a1, r)
    const [tx, ty] = pt((a0 + a1) / 2, (R + r) / 2)
    const large = 360 / n > 180 ? 1 : 0
    const hit = highlight && l === highlight
    return (
      <g key={i}>
        <path d={`M${x0},${y0} A${R},${R} 0 ${large} 1 ${x1},${y1} L${xi1},${yi1} A${r},${r} 0 ${large} 0 ${xi0},${yi0} Z`}
              className={'ha-seg' + (hit ? ' hit' : i % 2 ? ' alt' : '')} />
        <text x={tx} y={ty} textAnchor="middle" dominantBaseline="middle" className="ha-seg-t">{l.length > 7 ? l.slice(0, 7) + '…' : l}</text>
      </g>
    )
  })
  return (
    <svg className="ha-dial" viewBox="0 0 300 300" role="img" aria-label="ルーレット">
      {segs}
      <circle cx={C} cy={C} r={r - 8} className="ha-dial-c" />
      <text x={C} y={C - 6} textAnchor="middle" className="ha-dial-main">{center}</text>
      <text x={C} y={C + 16} textAnchor="middle" className="ha-dial-sub">{sub}</text>
      <polygon points="150,20 142,6 158,6" className="ha-dial-pin" />
    </svg>
  )
}

function HomeAgendaView({ ctx, sheets }) {
  const { settings, gate, brief, now, widgetAlive, widgetLive, liveSec, busy, ro, showToast,
          roll, openPick, check, startHabit, refreshTodo, onOpenPage, todayMin, target, streak, presence, cam, goals,
          recordHabits, gateHabits, mustOpen, mustDone, periodic, events, google } = ctx
  const dial = settings.home_roulette === 'dial'
  const d = new Date(now)
  const hm = `${pad2(d.getHours())}:${pad2(d.getMinutes())}`
  const nowF = d.getHours() + d.getMinutes() / 60
  const [pool, setPool] = useState([])
  useEffect(() => {
    if (!dial) return undefined
    let alive = true
    api.getAssignments().then((a) => { if (alive) setPool((a || []).filter((x) => !x.done && x.enabled !== false).map((x) => x.title).slice(0, 8)) }).catch(() => {})
    return () => { alive = false }
  }, [dial])

  // 時間軸に出すもの：時間帯のある習慣（記録のみ含む）・授業と生活（時間割）・予定・Google
  const habitTitles = new Set((gate?.habits ?? []).map((x) => x.title))
  const agendaItems = useMemo(() => [
    ...(gate?.habits ?? []).filter((x) => x.start && x.end).map((x) => ({ kind: 'habit', start: x.start, end: x.end, title: x.title, done: x.done })),
    ...(brief?.timetable ?? []).filter((b) => !habitTitles.has(b.title)).map((b) => ({ kind: b.category === '大学' ? 'class' : 'life', start: b.start, end: b.end, title: b.title })),
    ...events.map((e) => ({ kind: 'event', start: e.start, end: e.end, title: e.title, done: e.done })),
    // Google の予定は、時間割と同じ授業（名前を含む）なら二重に出さない
    ...google.filter((g) => !g.allday && g.start && g.end && !(brief?.timetable ?? []).some((b) => b.title && g.title && (g.title.includes(b.title) || b.title.includes(g.title))))
      .map((g) => ({ kind: 'event', start: g.start, end: g.end, title: g.title })),
  // eslint-disable-next-line react-hooks/exhaustive-deps -- habitTitles は gate から作る値なので gate の変化で足りる
  ], [gate, brief, events, google])
  const upcoming = agendaItems.filter((b) => b.kind !== 'habit' && b.kind !== 'life' && b.start > hm).sort((a, b) => a.start.localeCompare(b.start))[0]
  const minsTo = (t) => Math.round((hm2f(t) - nowF) * 60)

  const stopWidget = async () => {
    try { await api.widgetStop(); showToast('小窓のタイマーを止めて記録しました'); await refreshTodo() }
    catch (e) { showToast('⚠️ ' + (e?.message ?? '')) }
  }
  const showWidget = async () => {
    try { await api.showWidget(); showToast('小窓を表示しました') } catch (e) { showToast('⚠️ ' + (e?.message ?? '')) }
  }
  const liveTask = widgetLive ? (widgetLive.task || '').replace(/^📱 /, '') : ''
  const liveText = `${pad2(Math.floor(liveSec / 60))}:${pad2(liveSec % 60)}`

  // 「いま」の行（W1）。ダイヤルのときは小窓の状態だけ
  const nowCard = (
    <div className={'ha-nowcard' + (widgetLive ? ' running' : '')}>
      {widgetLive ? (
        <>
          <span className="ha-nc-text"><b>計測中 {liveText}</b>　{liveTask || '（タスク未選択）'}<small>小窓で計測・規定時間で自動完了</small></span>
          <button type="button" className="ha-btn o" onClick={stopWidget}>終了して記録</button>
        </>
      ) : (
        <>
          <span className="ha-nc-text">
            {widgetAlive ? <><b>小窓：待機中</b><small>何も計測していません</small></> : <><b>小窓が閉じています</b><small>タイマーを使うには表示が必要です</small></>}
          </span>
          {!widgetAlive && <button type="button" className="ha-btn o" onClick={showWidget}>小窓を表示</button>}
          {!dial && <button type="button" className="ha-btn" onClick={roll} disabled={busy || !!ro}>ルーレットを回す</button>}
          {!dial && <button type="button" className="ha-btn o" onClick={openPick} disabled={busy}>自分で選ぶ</button>}
        </>
      )}
    </div>
  )

  const lockText = !gate ? '' : gate.site_unlocked && gate.game_unlocked ? '制限なし' : gate.site_unlocked ? 'サイト解除・ゲームは条件待ち' : `制限中・あと${gate.remaining.length}件`
  const row = (key, cls, left, label, right) => (
    <div key={key} className={'ha-row ' + cls}>{left}<span className="ha-x">{label}</span><span className="ha-m">{right}</span></div>
  )
  // 完了にするときは確認してから（2026-11-04 依頼者の指示）。取り消しは確認なし
  const confirmCheck = (title, fn) => (e) => {
    const on = e.target.checked
    if (on && !window.confirm(`「${title}」を完了にしますか？`)) return   // 制御コンポーネントなので React が元の状態に戻す
    fn(on)
  }
  const cb = (checked, onChange, aria) => <input type="checkbox" className="ha-cb" checked={!!checked} onChange={onChange} aria-label={aria} />
  const [showDone, setShowDone] = useState(false)
  const doneEvents = events.filter((e) => e.done), openEvents = events.filter((e) => !e.done)
  const donePeriodic = periodic.filter((p) => p.checkedToday), openPeriodic = periodic.filter((p) => !p.checkedToday)
  const doneCount = mustDone.length + gateHabits.filter((x) => x.done).length + recordHabits.filter((x) => x.checked).length + doneEvents.length + donePeriodic.length

  return (
    <div className={'home ha fit-page' + (dial ? ' ha-dial-mode' : '')}>
      <div className="ha-wrap">
        <div className="ha-left">
          <div className="ha-head">
            <span className="ha-date">{d.getMonth() + 1}月{d.getDate()}日 {DAY[(d.getDay() + 6) % 7]}</span>
            <span className="ha-clock">{hm}</span>
            <span className="ha-next">{upcoming ? `次 ${upcoming.start} ${upcoming.title}（あと${minsTo(upcoming.start)}分）` : 'この後の予定はありません'}</span>
            <button type="button" className="ha-lock" onClick={() => onOpenPage('lock')} title="制限の画面を開く">{lockText}</button>
          </div>
          <AgendaDay items={agendaItems} nowF={nowF}>{nowCard}</AgendaDay>
        </div>
        <div className="ha-right">
          {dial && (
            <div className="ha-dialw">
              <Dial labels={pool.length ? pool : ['ルーレット項目なし']} center={widgetLive ? liveText : hm} sub={widgetLive ? liveTask : '小窓：待機中'}
                    highlight={ro ? String(ro['勉強'] || '') : ''} />
              <div className="ha-dial-btns">
                <button type="button" className="ha-btn" onClick={roll} disabled={busy || !!ro}>回す</button>
                <button type="button" className="ha-btn o" onClick={openPick} disabled={busy}>自分で選ぶ</button>
              </div>
            </div>
          )}
          {/* 右は2列：やること｜予定・週単位。完了したものは出さない（下の「完了 N件」で開ける） */}
          <div className="ha-two">
            <div className="ha-list">
              <div className="ha-h2">やること{gate ? (gate.tasks_done ? '・ノルマ達成' : `・あと${gate.remaining.length}件で解除`) : ''}</div>
              {mustOpen.length + gateHabits.filter((x) => !x.done).length + recordHabits.filter((x) => !x.checked).length === 0 && <div className="ha-empty">全部終わっています</div>}
              {mustOpen.map((x) => row(x.id, '', cb(x.checked, confirmCheck(x.title, (on) => check(x.id, on)), x.title), <>{x.title}{x.due && <span className="ha-m">　{x.due.slice(5).replace('-', '/')}</span>}</>, '必須'))}
              {gateHabits.filter((x) => !x.done).map((x) => row(x.id, '',
                <button type="button" className="ha-start" onClick={() => startHabit(x)} title="小窓のタイマーで開始">開始</button>,
                <>{x.title}{x.forced && <span className="ha-m ha-warn">　必須扱い</span>}</>, x.start && x.end ? `${x.start}–${x.end}` : '25分'))}
              {recordHabits.filter((x) => !x.checked).map((x) => row(x.id, '', cb(false, confirmCheck(x.title, (on) => check(x.id, on)), x.title), <>{x.title}<span className="ha-m">　記録</span></>, x.start && x.end ? `${x.start}–${x.end}` : ''))}
              {showDone && (
                <>
                  {mustDone.map((x) => row(x.id, 'done', cb(true, (e) => check(x.id, e.target.checked), x.title), x.title, '必須'))}
                  {gateHabits.filter((x) => x.done).map((x) => row(x.id, 'done', <span className="ha-cb on" aria-hidden="true" />, x.title, x.start && x.end ? `${x.start}–${x.end}` : '25分'))}
                  {recordHabits.filter((x) => x.checked).map((x) => row(x.id, 'done', cb(true, (e) => check(x.id, e.target.checked), x.title), <>{x.title}<span className="ha-m">　記録</span></>, ''))}
                </>
              )}
            </div>
            <div className="ha-list">
              <div className="ha-h2">予定</div>
              {openEvents.length + google.length === 0 && <div className="ha-empty">予定はありません</div>}
              {openEvents.map((e) => row('e' + e.id, '', cb(false, confirmCheck(e.title, async (on) => { await api.toggleLifeEventDone(e.id, on); await refreshTodo() }), e.title), e.title, `${e.start}–${e.end}`))}
              {google.map((g, i) => row('g' + i, 'ro', <span className="ha-dot" />, g.title, g.allday ? '終日' : `${g.start}–${g.end}`))}
              {showDone && doneEvents.map((e) => row('e' + e.id, 'done', cb(true, async (ev) => { await api.toggleLifeEventDone(e.id, ev.target.checked); await refreshTodo() }, e.title), e.title, `${e.start}–${e.end}`))}
              <div className="ha-h2 ha-gap">週単位</div>
              {openPeriodic.length === 0 && <div className="ha-empty">なし</div>}
              {openPeriodic.map((p) => row(p.id, '', cb(false, confirmCheck(p.title, (on) => check(p.id, on)), p.title),
                <>{p.title}{p.due && <span className="ha-m ha-warn">　そろそろ</span>}</>, p.everyDays > 0 ? `${p.everyDays}日ごと` : '不定期'))}
              {showDone && donePeriodic.map((p) => row(p.id, 'done', cb(true, (e) => check(p.id, e.target.checked), p.title), p.title, p.everyDays > 0 ? `${p.everyDays}日ごと` : '不定期'))}
            </div>
          </div>
          <button type="button" className="ha-fold" onClick={() => setShowDone((v) => !v)}>
            完了 {doneCount}件 {showDone ? '隠す ▴' : '表示 ▾'}
          </button>
          <div className={'ha-stats' + (dial ? ' compact' : '')}>
            <div><div className="ha-k">勉強</div><div className="ha-v">{todayMin}<small> / {target}分</small></div></div>
            {cam?.enabled ? <div><div className="ha-k">在席</div><div className="ha-v">{presence?.rate != null ? `${presence.rate}%` : '–'}</div></div>
                           : <div><div className="ha-k">連続</div><div className="ha-v">{streak}<small> 日</small></div></div>}
            {brief?.money?.allowance != null && <div><div className="ha-k">今月あと</div><div className="ha-v">¥{(brief.money.remaining ?? 0).toLocaleString()}</div></div>}
            {goals.slice(0, 2).map((g, i) => {
              const gd = new Date(g.date + 'T00:00:00'); const days = Number.isNaN(gd.getTime()) ? 0 : Math.max(Math.round((gd - new Date(new Date().setHours(0, 0, 0, 0))) / 86400000), 0)
              return <div key={i}><div className="ha-k">{g.name}</div><div className="ha-v">{days}<small> 日</small></div></div>
            })}
          </div>
        </div>
      </div>
      {sheets}
    </div>
  )
}

export default HomeAgendaView
