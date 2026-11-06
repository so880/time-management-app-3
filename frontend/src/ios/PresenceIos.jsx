// 📷 在席判定・カメラ（F22・2026-11-01 夜）
// 上から：いまの状態 → 今日の在席（帯＋習慣ごとの在席率） → 直近7日 → 習慣ごとの設定（画角外・最低時間）
//        → 静止画の記録（30秒ごと・まとめ画像）
// 画像は PC の外に出ない。在席判定は「顔が映っているか」だけで、何をしているかは見ない。
import { useCallback, useState } from 'react'
import * as api from '../api.js'
import { usePolling } from '../lib/usePolling.js'
import { hmToMin as toMin } from '../lib/format.js'

const STATUS_LABEL = { P: '在席', A: '不在' }

// 07:00〜21:00 の帯（在席＝緑、不在＝灰、授業＝青）
function PresenceBar({ day }) {
  const start = 7 * 60, end = 21 * 60, span = end - start
  const pos = (hm) => Math.max(0, Math.min(100, ((toMin(hm) - start) / span) * 100))
  return (
    <div className="pr-bar" role="img" aria-label="今日の在席の帯">
      {(day.classes ?? []).map((c, i) => (
        <div key={'c' + i} className="pr-seg class" title={`授業 ${c.start}〜${c.end} ${c.title}`}
             style={{ left: `${pos(c.start)}%`, width: `${Math.max(0.5, pos(c.end) - pos(c.start))}%` }} />
      ))}
      {(day.blocks ?? []).map((b, i) => (
        <div key={i} className={'pr-seg ' + (b.status === 'P' ? 'present' : 'absent')}
             title={`${STATUS_LABEL[b.status] ?? b.status} ${b.start}〜${b.end}（${b.minutes}分）`}
             style={{ left: `${pos(b.start)}%`, width: `${Math.max(0.5, pos(b.end) - pos(b.start))}%` }} />
      ))}
      {(day.habits ?? []).map((h, i) => (
        <div key={'h' + i} className="pr-habit" title={`${h.title} ${h.start}〜${h.end}`}
             style={{ left: `${pos(h.start)}%`, width: `${Math.max(0.5, pos(h.end) - pos(h.start))}%` }} />
      ))}
      <div className="pr-ticks">{['7', '10', '13', '16', '19', '21'].map((t) => <span key={t}>{t}時</span>)}</div>
    </div>
  )
}

// 📷 「使うカメラ」の選択肢：確認で見つかった一覧（無ければ 0〜4）。いまの設定値が一覧に無くても必ず入れる
function cameraChoices(cfg) {
  const found = cfg.camera?.last?.found
  const base = found && found.length
    ? found.map((f) => ({ index: f.index, label: `番号 ${f.index}（${f.width}×${f.height}）` }))
    : [0, 1, 2, 3, 4].map((i) => ({ index: i, label: `番号 ${i}` }))
  const cur = Number(cfg.camera_index ?? 0)
  if (!base.some((c) => c.index === cur)) base.push({ index: cur, label: `番号 ${cur}（いまの設定）` })
  return base.sort((a, b) => a.index - b.index)
}

function PresenceIos({ showToast }) {
  const [cfg, setCfg] = useState(null)
  const [day, setDay] = useState(null)
  const [week, setWeek] = useState(null)
  const [opts, setOpts] = useState([])
  const [webcam, setWebcam] = useState([])
  const [busy, setBusy] = useState(false)
  const [rateDraft, setRateDraft] = useState(null)
  const [testing, setTesting] = useState(false)   // 📷 カメラ確認の結果待ち（最長約25秒）

  const load = useCallback(async () => {
    try {
      const [c, d, w, o, wc] = await Promise.all([
        api.getPresenceConfig(), api.getPresenceDay(), api.getPresenceWeek(), api.getHabitOptions(), api.getWebcamDays(),
      ])
      setCfg(c); setDay(d); setWeek(w); setOpts(o); setWebcam(wc)
    } catch (e) { showToast?.('⚠️ ' + (e?.message ?? '')) }
  }, [showToast])
  // 30秒ごとに読み直す（load が作り直されたら張り直してすぐ読む）
  usePolling(load, 30000, [load])

  // 📷 カメラを確認：ワーカーに1回撮らせて、明るさ・顔の数を表示する（結果が来るまで3秒ごとに読む）
  const testCamera = async () => {
    if (testing) return
    setTesting(true)
    try {
      await api.requestCameraTest()
      for (let i = 0; i < 12; i++) {
        await new Promise((r) => setTimeout(r, 3000))
        const c = await api.getPresenceConfig()
        setCfg(c)
        if (c.camera?.last && !c.camera.test_pending) break
      }
    } catch (e) { showToast?.('⚠️ ' + (e?.message ?? '')) }
    finally { setTesting(false) }
  }

  const save = async (body) => {
    if (busy) return
    setBusy(true)
    try { setCfg(await api.setPresenceConfig(body)); await load() }
    catch (e) { showToast?.('⚠️ ' + (e?.message ?? '')) }
    finally { setBusy(false) }
  }

  const saveOpt = async (o, offCamera, minMinutes, recordOnly = !!o.record_only, cameraOff = !!o.camera_off) => {
    try {
      const r = await api.setHabitOption(o.title, offCamera, minMinutes, recordOnly, cameraOff)
      showToast?.(r.pending ? `「${o.title}」の変更は明日（${r.since}）から有効になります` : `「${o.title}」を保存しました`)
      await load()
    } catch (e) { showToast?.('⚠️ ' + (e?.message ?? '')) }
  }

  if (!cfg) return <div className="caption">読み込み中…</div>
  const wl = cfg.webcam_log ?? {}

  return (
    <div className="presence-page">
      {/* いまの状態 */}
      <div className="ios-widget">
        <div className="w-label">いまの状態</div>
        <div className="lock-row">
          <span>📷 在席判定</span>
          <label className="switch-row">
            <span className="caption">{cfg.enabled ? 'オン' : 'オフ'}</span>
            <input type="checkbox" checked={!!cfg.enabled} disabled={busy}
                   onChange={(e) => save({ presence_enabled: e.target.checked })} />
          </label>
        </div>
        <div className="caption" style={{ marginTop: 4 }}>
          {cfg.enabled ? `いま：${cfg.label}` : 'オンにすると、07:00〜21:00（授業・面接の特例を除く）の間だけ Webカメラで「顔が映っているか」を判定します。'}
        </div>
        {(cfg.camera_off_windows ?? []).length > 0 && (
          <div className="caption">📷 今日カメラを止める時間：{cfg.camera_off_windows.map((w) => `${w.start}〜${w.end} ${w.title}`).join('、')}</div>
        )}
        <div className="caption">画像は保存・送信しません（静止画の記録は下で別にオンにしたときだけ）。何をしているかは判定しません。</div>
        <div className="edit-row" style={{ marginTop: 8 }}>
          <button type="button" className="small" disabled={testing} onClick={testCamera}>
            {testing ? '📷 確認中…（最長25秒）' : '📷 カメラを確認する'}
          </button>
          <span className="caption">カメラを1回開いて、映っているか・顔が検出できるかを調べます</span>
        </div>
        {cfg.camera?.last && (
          <div className={'info-box' + (cfg.camera.last.ok && (cfg.camera.last.brightness ?? 0) >= 10 && cfg.camera.last.faces > 0 ? '' : ' warn')} style={{ marginTop: 6 }}>
            {cfg.camera.last.at}：{cfg.camera.last.ok
              ? `映像 ${cfg.camera.last.width || '?'}×${cfg.camera.last.height || '?'}（${cfg.camera.last.backend || '-'}）・明るさ ${cfg.camera.last.brightness ?? '?'}/255・顔 ${cfg.camera.last.faces} 人`
              : `失敗：${cfg.camera.last.error || ''}`}
            <div className="caption" style={{ marginTop: 4 }}>{cfg.camera.note}</div>
          </div>
        )}
        {!cfg.camera?.last && cfg.camera?.test_pending && <div className="caption" style={{ marginTop: 6 }}>ワーカーの返事を待っています…</div>}
        {/* 📷 使うカメラの番号（settings.camera_index）。「カメラを確認する」で見つかった一覧から選ぶ */}
        <div className="lock-row" style={{ marginTop: 8 }}>
          <span>使うカメラ</span>
          <select value={cfg.camera_index ?? 0} disabled={busy}
                  onChange={(e) => save({ camera_index: Number(e.target.value) })}>
            {cameraChoices(cfg).map((c) => (
              <option key={c.index} value={c.index}>{c.label}</option>
            ))}
          </select>
        </div>
        {cfg.camera?.last?.found && (
          <div className="caption">
            {cfg.camera.last.found.length
              ? `見つかったカメラ：${cfg.camera.last.found.map((f) => `番号 ${f.index}（${f.width}×${f.height}・${f.backend || '-'}）`).join('、')}`
              : '番号 0〜4 に開けるカメラが見つかりませんでした'}
          </div>
        )}
        <div className="caption">番号を変えたあとは、次の確認（最長20秒）から新しいカメラを使います。環境変数 FC_CAMERA_INDEX が設定されているときはそちらが優先されます。</div>
        <div className="lock-row" style={{ marginTop: 10 }}>
          <span>完了とみなす在席率</span>
          <span>
            <strong>{cfg.rate_min}%</strong>
            {cfg.rate_min_pending != null && <span className="caption">　→ {cfg.rate_min_pending}%（{cfg.rate_min_since} から）</span>}
          </span>
        </div>
        <div className="edit-row">
          <input type="range" min="50" max="100" step="5" value={rateDraft ?? cfg.rate_min} aria-label="在席率の基準"
                 onChange={(e) => setRateDraft(parseInt(e.target.value, 10))} />
          <span className="caption" style={{ minWidth: 40 }}>{rateDraft ?? cfg.rate_min}%</span>
          {rateDraft != null && rateDraft !== cfg.rate_min && (
            <button type="button" className="small" disabled={busy}
                    onClick={async () => { await save({ presence_rate_min: rateDraft }); setRateDraft(null) }}>保存</button>
          )}
        </div>
        <div className="caption">習慣の時間帯のうち、この割合以上の分で在席していれば完了になります。下げる変更は翌日から有効です（当日の抜け道にしないため）。</div>
      </div>

      {/* 今日の在席 */}
      <div className="ios-widget">
        <div className="w-label">今日の在席</div>
        {day && day.monitored_min === 0 && <div className="caption">まだ記録がありません{cfg.enabled ? '（監視時間になると自動で始まります）' : ''}</div>}
        {day && day.monitored_min > 0 && (
          <>
            <div className="pr-summary">
              <span className="w-big">{day.rate}<span className="w-unit">%</span></span>
              <span className="w-sub">在席 {day.present_min}分 ／ 不在 {day.absent_min}分 ／ 監視 {day.monitored_min}分</span>
            </div>
            <PresenceBar day={day} />
            <div className="pr-legend">
              <span><i className="present" />在席</span><span><i className="absent" />不在</span>
              <span><i className="class" />授業（監視しない）</span><span><i className="habit" />習慣の時間帯</span>
            </div>
          </>
        )}
        {day && (day.habits ?? []).length > 0 && (
          <div className="pr-habits">
            {day.habits.map((h) => (
              <div key={h.title} className="pr-habit-row">
                <span className="pr-habit-name">{h.done ? '✅' : '⏳'} {h.title}<span className="caption">　{h.start}〜{h.end}</span>{h.record_only && <span className="brief-chip">記録のみ</span>}</span>
                {h.record_only ? (
                  <span className="caption">記録だけ（解放条件に入りません）</span>
                ) : h.off_camera ? (
                  <span className="caption">画角外：小窓のタイマーで {h.min_minutes}分以上</span>
                ) : (
                  <span className="caption">在席 {h.present_min}／必要 {h.need_min}分{h.rate != null ? `（${h.rate}%）` : ''}{h.by_presence ? '・在席率で完了' : ''}</span>
                )}
              </div>
            ))}
          </div>
        )}
        <div className="caption" style={{ marginTop: 6 }}>不在＝サボりとは限りません（トイレ・来客・画角外の作業など）。記録の確認用です。</div>
      </div>

      {/* 直近7日 */}
      {week && (
        <div className="ios-widget">
          <div className="w-label">直近7日の在席率</div>
          <div className="week-bars">
            {week.days.map((d) => (
              <div className="wb-col" key={d.date}>
                <div className="wb-val">{d.rate != null ? `${d.rate}%` : ''}</div>
                <div className="wb-bar" style={{ height: `${Math.max(6, ((d.rate ?? 0) / 100) * 56)}px`,
                                                 background: d.rate == null ? 'rgba(255,255,255,0.12)' : d.rate >= week.rate_min ? '#4CAF50' : '#FF9F0A' }} />
                <div className="wb-day">{d.label}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 習慣ごとの設定 */}
      <div className="ios-widget">
        <div className="w-label">習慣ごとの完了のしかた</div>
        <div className="caption" style={{ marginBottom: 6 }}>
          ふつうの習慣：時間帯の長さ以上タイマーで計測 または 在席率が基準以上 で完了。
          画角外の習慣（筋トレなど）：小窓のタイマーで「最低時間」以上やったときだけ完了（在席率は使いません）。
          「記録のみ」の習慣：解放条件（ゲーム・サイト制限の解除）に入れず、全画面ロックも出しません。チェックで記録できます。
          「📷 カメラ停止」：その時間帯はカメラを開きません（AI面接の練習など）。面接・面談・選考などの予定（Google とアプリの予定）の前後60分も自動でカメラを止めます。
          弱める変更（画角外にする・最低時間を短くする・記録のみにする）は翌日から有効です。
        </div>
        {opts.length === 0 && <div className="caption">習慣がまだありません（その他 › 習慣 で登録）</div>}
        {opts.map((o) => (
          <div key={o.title} className="pr-opt-row">
            <span className="pr-opt-name">{o.title}<span className="caption">　{o.start && o.end ? `${o.start}〜${o.end}` : '時間帯なし'}（{o.window_minutes}分）</span>{o.record_only && <span className="brief-chip">記録のみ</span>}</span>
            <label className="pr-opt-ctl">
              <input type="checkbox" checked={!!o.record_only}
                     onChange={(e) => saveOpt(o, false, 0, e.target.checked)} />
              記録のみ
            </label>
            {!o.record_only && (
              <label className="pr-opt-ctl">
                <input type="checkbox" checked={!!o.off_camera}
                       onChange={(e) => saveOpt(o, e.target.checked, e.target.checked ? (o.min_minutes || Math.min(o.window_minutes, 20)) : 0)} />
                画角外
              </label>
            )}
            {o.start && o.end && (
              <label className="pr-opt-ctl" title="この時間帯はカメラを開きません（AI面接の練習など、他のアプリがカメラを使うとき）">
                <input type="checkbox" checked={!!o.camera_off}
                       onChange={(e) => saveOpt(o, !!o.off_camera, o.min_minutes || 0, !!o.record_only, e.target.checked)} />
                📷 カメラ停止
              </label>
            )}
            {o.off_camera && (
              <label className="pr-opt-ctl">
                最低
                <input type="number" min="10" max={o.window_minutes} step="5" defaultValue={o.min_minutes || o.window_minutes}
                       style={{ width: 70 }} aria-label="最低時間（分）"
                       onBlur={(e) => { const v = parseInt(e.target.value, 10); if (v && v !== o.min_minutes) saveOpt(o, true, v) }} />
                分
              </label>
            )}
            {o.pending && <span className="caption">→ {o.since} から {o.pending.record_only ? '記録のみ' : o.pending.off_camera ? `画角外・${o.pending.min_minutes}分` : 'ふつう'}</span>}
          </div>
        ))}
      </div>

      {/* 静止画の記録 */}
      <div className="ios-widget">
        <div className="w-label">静止画の記録（作業の見える化）</div>
        <div className="lock-row">
          <span>📸 {wl.interval_sec ?? 30}秒ごとに時刻入りの静止画を保存</span>
          <label className="switch-row">
            <span className="caption">{wl.enabled ? 'オン' : 'オフ'}</span>
            <input type="checkbox" checked={!!wl.enabled} disabled={busy}
                   onChange={(e) => save({ webcam_log_enabled: e.target.checked })} />
          </label>
        </div>
        <div className="caption">
          保存先は logs/webcam/日付/。{wl.keep_days ?? 14}日より古いものは自動で消えます。監視時間（07:00〜21:00、授業・特例を除く）だけ撮ります。PC の外には出ません。
        </div>
        <div className="edit-row" style={{ marginTop: 6 }}>
          <span className="caption">間隔</span>
          <select value={wl.interval_sec ?? 30} onChange={(e) => save({ webcam_log_interval_sec: parseInt(e.target.value, 10) })}>
            {[15, 30, 60, 120, 300].map((s) => <option key={s} value={s}>{s}秒</option>)}
          </select>
          <span className="caption">残す日数</span>
          <select value={wl.keep_days ?? 14} onChange={(e) => save({ webcam_log_keep_days: parseInt(e.target.value, 10) })}>
            {[3, 7, 14, 30].map((s) => <option key={s} value={s}>{s}日</option>)}
          </select>
        </div>
        {webcam.length > 0 && (
          <div className="pr-days">
            {webcam.map((d) => (
              <div key={d.date} className="pr-day-row">
                <span>{d.date}<span className="caption">　{d.count}枚</span></span>
                <span className="edit-row" style={{ margin: 0 }}>
                  {d.summary && <a className="small-link" href={d.summary} target="_blank" rel="noreferrer">まとめ画像を見る</a>}
                  <button type="button" className="small" disabled={busy || d.count === 0}
                          onClick={async () => {
                            setBusy(true)
                            try { const x = await api.makeWebcamSummary(d.date); showToast?.(x.ok ? 'まとめ画像を作りました' : '作成に失敗しました'); await load() }
                            catch (e) { showToast?.('⚠️ ' + (e?.message ?? '')) }
                            finally { setBusy(false) }
                          }}>{d.summary ? '作り直す' : 'まとめ画像を作る'}</button>
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default PresenceIos
