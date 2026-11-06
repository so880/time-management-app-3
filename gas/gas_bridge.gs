/**
 * FocusCafe ↔ Google 連携ブリッジ（Google Apps Script）
 * 貼り方は docs/SETUP_GOOGLE_SYNC.md を参照。
 *
 * 役割：
 *  1. sync_events … アプリから送られた予定を専用カレンダー「FocusCafe」に反映
 *     （説明欄の fcid: タグ付きイベントだけを入れ替えるので、手動の予定は消えない）
 *  2. add … スマホ用ページからの記録（勉強・支出・予定）を受け取り箱に追記
 *     （PC が phone_sync で30秒ごとに取りに来る。Gドライブ同期には依存しない）
 *  3. list_events … メインカレンダーの予定を読み取り専用で返す
 *     （アプリのカレンダー・今日タブに表示。アプリ側からは変更しない）
 *  4. timer_start / timer_stop / phone_sync … iPhone のタイマーを PC に即反映
 *  5. doGet … スマホ用ページ（URL を Safari で開くだけ。ショートカット不要）
 */

// ★ここを自分だけの合言葉に変える（アプリ側の設定と同じ文字列にする）
const TOKEN = 'CHANGE_ME';
const SCRIPT_VERSION = '2026-11-07a';  // 貼り直し・再デプロイが反映されたかの確認用（エラー文に出る）
const CAL_NAME = 'FocusCafe';
const FOLDER_NAME = 'FocusCafeSync';
const FILE_NAME = 'phone_inbox.json';

function doPost(e) {
  let body;
  try {
    body = JSON.parse(e.postData.contents);
  } catch (err) {
    return out({ ok: false, error: 'invalid json' });
  }
  return out(handle(body));
}

/** ショートカットからの POST と、スマホ用ページ（doGet）の両方がここを通る */
const MAX_FAILS_PER_HOUR = 20;  // 合言葉の総当たり対策：1時間に失敗がこれを超えたら以降は全部拒否

function handle(body) {
  body = body || {};
  const cache = CacheService.getScriptCache();
  const fails = Number(cache.get('token_fails') || 0);
  if (fails >= MAX_FAILS_PER_HOUR) {
    return { ok: false, error: 'too many failed attempts. try again later (script ' + SCRIPT_VERSION + ')' };
  }
  if (body.token !== TOKEN) {
    cache.put('token_fails', String(fails + 1), 3600);
    // 合言葉が違う。どのバージョンが動いているかだけ返す（合言葉の長さやヒントは返さない）
    return { ok: false, error: 'bad token (script ' + SCRIPT_VERSION + ')' };
  }
  if (body.action === 'sync_events') return syncEvents(body);
  if (body.action === 'add') return appendItem(body);
  if (body.action === 'get_choices') return readChoices();
  if (body.action === 'list_events') return listEvents(body);
  if (body.action === 'timer_start') return timerStart(body);
  if (body.action === 'timer_stop') return timerStop(body);
  if (body.action === 'timer_state') return timerState();
  if (body.action === 'phone_sync') return phoneSync(body);
  if (body.action === 'pc_stop') return pcStop();
  return { ok: false, error: 'unknown action' };
}

/* ===== スマホ用ページ（ショートカットを作らなくても使える） =====
 * ウェブアプリの URL を iPhone の Safari で開くだけ。合言葉を1回入れると端末に記憶される。
 * できること：タイマーのスタート/ストップ（選択肢は PC の小窓と同じ）、習慣の完了/5分着手、支出・予定の追加。
 * Safari の共有 →「ホーム画面に追加」でアプリのように使える。 */
function doGet(e) {
  // セキュリティ：URL に合言葉を付ける方式（?token=）は廃止（ブラウザ履歴に残るため）。初回に画面で入力する
  const html = PHONE_PAGE.replace('__PRE_TOKEN__', '""');
  return HtmlService.createHtmlOutput(html)
    .setTitle('Focus & Cafe')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1, maximum-scale=1');
}

const PHONE_PAGE = `<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8">
<style>
  :root{--sp:cubic-bezier(.34,1.56,.64,1);--ease:cubic-bezier(.22,1,.36,1)}
  *{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
  body{margin:0;background:#000;color:#f2f4f7;font-family:-apple-system,"Hiragino Sans",sans-serif;padding:0 14px 40px;min-height:100vh}
  .caption{color:#9aa0a8;font-size:.85rem}
  /* ===== ダイナミックアイランド ===== */
  .island-wrap{position:sticky;top:0;z-index:50;padding:10px 0 6px;display:flex;justify-content:center;background:linear-gradient(#000 70%,transparent)}
  .island{background:#0b0b0d;color:#fff;border-radius:999px;padding:10px 18px;min-width:150px;max-width:100%;display:flex;align-items:center;justify-content:center;gap:10px;
    box-shadow:0 8px 30px rgba(0,0,0,.6),inset 0 0 0 1px rgba(255,255,255,.08);
    transition:min-width .55s var(--sp),padding .55s var(--sp),border-radius .55s var(--sp),transform .35s var(--sp);cursor:pointer;user-select:none;text-align:center}
  .island:active{transform:scale(.96)}
  .island.run{min-width:290px;padding:12px 22px}
  .island.busy{min-width:220px;padding:12px 22px}
  .island .dot{width:10px;height:10px;border-radius:50%;background:#34C759;box-shadow:0 0 12px #34C759;animation:pulse 1.4s ease-in-out infinite}
  .island.busy .dot{background:#FF9F0A;box-shadow:0 0 12px #FF9F0A;animation:spin1 .9s linear infinite;border-radius:3px}
  .island .t{font-weight:700;font-size:1rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:200px}
  .island .e{font-variant-numeric:tabular-nums;color:#34C759;font-weight:800;font-size:1.05rem}
  @keyframes pulse{0%,100%{transform:scale(1);opacity:1}50%{transform:scale(.7);opacity:.6}}
  @keyframes spin1{to{transform:rotate(360deg)}}
  /* ===== 3つの大ボタン ===== */
  .big{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;width:100%;
    background:#151519;color:#fff;border:1px solid rgba(255,255,255,.08);border-radius:24px;padding:22px 16px;margin:12px 0;
    font-size:1.25rem;font-weight:800;transition:transform .35s var(--sp),background .2s;text-align:center}
  .big:active{transform:scale(.95)}
  .big .ic{font-size:2.2rem;line-height:1}
  .big .sub{font-size:.85rem;color:#9aa0a8;font-weight:500}
  .big.start{background:linear-gradient(135deg,#1d2a1f,#0f1a12);border-color:rgba(52,199,89,.45)}
  .big.stop{background:linear-gradient(135deg,#3a1414,#1d0c0c);border-color:rgba(255,69,58,.5)}
  /* ===== 習慣チェック ===== */
  .habits{background:#151519;border:1px solid rgba(255,255,255,.08);border-radius:24px;padding:14px 16px;margin:12px 0}
  .habits h2{font-size:.95rem;margin:0 0 6px;color:#9aa0a8;font-weight:600}
  .hrow{display:flex;align-items:center;gap:14px;padding:12px 4px;border-bottom:1px solid rgba(255,255,255,.06)}
  .hrow:last-child{border-bottom:0}
  .chk{width:30px;height:30px;border-radius:50%;border:2px solid rgba(255,255,255,.3);display:flex;align-items:center;justify-content:center;flex:none;
    transition:background .3s,border-color .3s,transform .5s var(--sp);font-size:1rem}
  .hrow.on .chk{background:#34C759;border-color:#34C759;transform:scale(1.15)}
  .hrow .name{flex:1;font-size:1.05rem;transition:opacity .3s}
  .hrow.on .name{opacity:.45;text-decoration:line-through}
  .hrow .tm{color:#9aa0a8;font-size:.85rem;font-variant-numeric:tabular-nums}
  .hrow:active .chk{transform:scale(.85)}
  /* ===== シート（下から出る） ===== */
  .scrim{position:fixed;inset:0;background:rgba(0,0,0,.55);opacity:0;pointer-events:none;transition:opacity .35s;z-index:80}
  .scrim.on{opacity:1;pointer-events:auto}
  .sheet{position:fixed;left:0;right:0;bottom:0;background:#151519;border-radius:28px 28px 0 0;padding:10px 16px 34px;max-height:82vh;overflow:auto;z-index:90;
    transform:translateY(110%);transition:transform .6s var(--sp);box-shadow:0 -10px 40px rgba(0,0,0,.6)}
  .sheet.on{transform:translateY(0)}
  .grab{width:44px;height:5px;border-radius:3px;background:rgba(255,255,255,.25);margin:0 auto 12px}
  .sheet h3{margin:6px 0 10px;font-size:1.1rem}
  .opt{display:block;width:100%;background:#22232a;color:#fff;border:1px solid rgba(255,255,255,.08);border-radius:16px;padding:14px;font-size:1rem;margin:8px 0;text-align:left;transition:transform .3s var(--sp)}
  .opt:active{transform:scale(.97)}
  .opt .tm{color:#9aa0a8;font-size:.85rem;margin-left:8px}
  .sec{color:#9aa0a8;font-size:.8rem;margin:14px 0 2px;letter-spacing:.06em}
  input{width:100%;background:#0e0e11;color:#fff;border:1px solid rgba(255,255,255,.14);border-radius:14px;padding:14px;font-size:1.05rem;margin:6px 0}
  .row{display:flex;gap:8px}.row>*{flex:1}
  .go{display:block;width:100%;background:#f2f4f7;color:#111;border:0;border-radius:16px;padding:16px;font-size:1.05rem;font-weight:800;margin-top:10px;transition:transform .3s var(--sp)}
  .go:active{transform:scale(.96)}
  .msg{text-align:center;color:#FF9F0A;min-height:1.3em;font-size:.9rem;margin:4px 0 8px;transition:opacity .3s}
  /* 処理中のロック：全体に触れなくする */
  body.busy .big,body.busy .habits,body.busy .sheet,body.busy .mini{pointer-events:none;filter:saturate(.6)}
  #login{margin-top:30vh}
  /* 右上の再読み込み */
  .reload{position:fixed;top:12px;right:12px;z-index:60;width:40px;height:40px;border-radius:50%;background:#151519;color:#fff;border:1px solid rgba(255,255,255,.12);font-size:1.2rem;display:flex;align-items:center;justify-content:center;transition:transform .35s var(--sp)}
  .reload:active{transform:scale(.88)}
  .reload.spin{animation:spin1 .8s linear infinite}
  /* 小さめのボタン（予定・課題を見る） */
  .mini{display:block;width:100%;background:#151519;color:#fff;border:1px solid rgba(255,255,255,.08);border-radius:18px;padding:14px;font-size:1rem;font-weight:700;margin:12px 0;transition:transform .3s var(--sp)}
  .mini:active{transform:scale(.97)}
  /* 予定・課題シートの行 */
  .li{display:flex;gap:10px;align-items:baseline;padding:10px 2px;border-bottom:1px solid rgba(255,255,255,.06)}
  .li:last-child{border-bottom:0}
  .li .w{flex:none;min-width:88px;color:#9aa0a8;font-size:.85rem;font-variant-numeric:tabular-nums}
  .li .n{flex:1}
  .li.done .n{opacity:.45;text-decoration:line-through}
  .li .hot{color:#FF453A;font-weight:700}
  /* 計測中の全画面 */
  .full{position:fixed;inset:0;z-index:120;background:radial-gradient(circle at 50% 35%,#0f2414,#000 70%);display:flex;flex-direction:column;align-items:center;justify-content:center;padding:30px 20px;text-align:center;
    opacity:0;pointer-events:none;transform:scale(1.05);transition:opacity .4s var(--ease),transform .6s var(--sp)}
  .full.on{opacity:1;pointer-events:auto;transform:scale(1)}
  .full .fsrc{color:#9aa0a8;font-size:.9rem;margin-bottom:10px}
  .full .ftask{font-size:1.35rem;font-weight:800;max-width:100%;word-break:break-all}
  .full .ftime{font-size:4.6rem;font-weight:800;color:#34C759;font-variant-numeric:tabular-nums;margin:26px 0 34px;letter-spacing:.02em}
  .full .fstop{width:170px;height:170px;border-radius:50%;background:#FF453A;color:#fff;border:0;font-size:1.4rem;font-weight:800;box-shadow:0 10px 40px rgba(255,69,58,.45);transition:transform .35s var(--sp)}
  .full .fstop:active{transform:scale(.92)}
  .full .fnote{color:#9aa0a8;font-size:.85rem;margin-top:16px;min-height:1.2em}
  .full .fmin{margin-top:26px;background:transparent;color:#9aa0a8;border:1px solid rgba(255,255,255,.18);border-radius:999px;padding:10px 20px;font-size:.95rem}
  /* 処理中の全画面（何も押せない） */
  .load{position:fixed;inset:0;z-index:200;background:rgba(0,0,0,.82);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:18px;opacity:0;pointer-events:none;transition:opacity .25s}
  .load.on{opacity:1;pointer-events:auto}
  .load .sp{width:54px;height:54px;border-radius:50%;border:5px solid rgba(255,255,255,.15);border-top-color:#fff;animation:spin1 .8s linear infinite}
  .load .lt{font-size:1.05rem;font-weight:700}
</style></head><body>
<div class="island-wrap"><div id="island" class="island" onclick="islandTap()"><span class="dot" id="dot" style="display:none"></span><span class="t" id="isText">停止中</span><span class="e" id="isTime"></span></div></div>
<button class="reload" id="reload" onclick="manualReload()" aria-label="再読み込み">⟳</button>
<div class="msg" id="msg"></div>

<div class="full" id="full">
  <div class="fsrc" id="fSrc">📱 スマホで計測中</div>
  <div class="ftask" id="fTask"></div>
  <div class="ftime" id="fTime">0:00</div>
  <button class="fstop" onclick="stopTimer()">■ ストップ</button>
  <div class="fnote" id="fNote"></div>
  <button class="fmin" onclick="hideFull()">ほかの操作をする</button>
</div>
<div class="load" id="load"><div class="sp"></div><div class="lt" id="loadText">処理しています…</div></div>

<div id="login" style="display:none">
  <div class="caption" style="text-align:center;margin-bottom:8px">合言葉（Apps Script の TOKEN）を入れてください。この端末に記憶されます。</div>
  <input id="tok" type="password" placeholder="合言葉">
  <button class="go" onclick="saveTok()">保存して開く</button>
</div>

<div id="app" style="display:none">
  <button id="btnStart" class="big start" onclick="openStart()"><span class="ic">▶</span>スタート<span class="sub">何をやるか選んでタイマー開始</span></button>
  <button id="btnStop" class="big stop" onclick="stopTimer()" style="display:none"><span class="ic">■</span>ストップ<span class="sub" id="stopSub">記録して終了</span></button>
  <button class="big" onclick="openSheet('money')"><span class="ic">💸</span>支出<span class="sub">金額を記録</span></button>
  <button class="big" onclick="openSheet('event')"><span class="ic">📌</span>予定<span class="sub">カレンダーに追加</span></button>
  <button class="mini" onclick="openSheet('plan')">📋 今日の予定・必須・課題を見る</button>
  <div class="habits"><h2>今日の習慣</h2><div id="habits"><div class="caption">読み込み中…</div></div></div>
  <div class="caption" style="text-align:center;margin-top:16px"><a href="#" onclick="try{localStorage.removeItem('fc_tok')}catch(e){};location.reload();return false;" style="color:#666">合言葉を入れ直す</a></div>
</div>

<div class="scrim" id="scrim" onclick="closeSheet()"></div>
<div class="sheet" id="sheet"><div class="grab"></div><div id="sheetBody"></div></div>

<script>
  var PRE = __PRE_TOKEN__;
  var TOK = '';
  try { TOK = localStorage.getItem('fc_tok') || ''; } catch (e) {}
  if (PRE) { TOK = PRE; try { localStorage.setItem('fc_tok', TOK); } catch (e) {} }
  var choices = null, timer = null, tick = null, busyN = 0, fullN = 0, sheetKind = null;
  var fullHidden = false, lastTimerKey = '', loadedDate = '';
  function $(id){ return document.getElementById(id); }
  function esc(s){ return String(s).replace(/[&<>"]/g, function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
  function msg(t){ $('msg').textContent = t || ''; }
  function todayStr(){ var d = new Date(); return d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0'); }
  var LABEL = { timer_start: '開始しています', timer_stop: '記録しています', pc_stop: 'PC に送っています', add: '送信しています', get_choices: '読み込み中', timer_state: '確認中' };
  /* 読み込み中（アイランドだけで表示。ボタンは押せなくする） */
  function setBusy(on, text){
    busyN += on ? 1 : -1; if (busyN < 0) busyN = 0;
    document.body.classList.toggle('busy', busyN > 0);
    $('reload').classList.toggle('spin', busyN > 0);
    if (busyN > 0) { $('island').classList.add('busy'); $('dot').style.display = ''; $('isText').textContent = (text || '処理中') + '…'; $('isTime').textContent = ''; }
    else renderIsland();
  }
  /* 書き込み中（全画面で何も押せなくする）。終わるまで holdFull / releaseFull で挟む */
  function holdFull(text){ fullN += 1; $('loadText').textContent = (text || '処理しています') + '…'; $('load').classList.add('on'); }
  function releaseFull(){ fullN -= 1; if (fullN <= 0) { fullN = 0; $('load').classList.remove('on'); } }
  /* quiet=true は裏での再読み込み（表示を変えない） */
  function call(body, cb, fail, quiet){
    body.token = TOK;
    if (!quiet) setBusy(true, LABEL[body.action]);
    google.script.run
      .withSuccessHandler(function(r){ if (!quiet) setBusy(false); cb(r || {}); })
      .withFailureHandler(function(e){ if (!quiet) setBusy(false); if (!quiet) msg('エラー: ' + e.message); if (fail) fail(e); })
      .handle(body);
  }
  function saveTok(){ TOK = $('tok').value.trim(); try { localStorage.setItem('fc_tok', TOK); } catch (e) {} boot(); }
  function boot(){
    if (!TOK) { $('login').style.display = 'block'; $('app').style.display = 'none'; return; }
    $('login').style.display = 'none'; $('app').style.display = 'block';
    refresh();
  }
  /* 状態と一覧を読み直す。done は2つとも終わったら呼ぶ */
  function refresh(done, quiet){
    var left = 2;
    var fin = function(){ left -= 1; if (left === 0 && done) done(); };
    call({action:'timer_state'}, function(r){
      if (!r.ok) { msg(r.error || ''); if (/bad token/.test(r.error || '')) { try { localStorage.removeItem('fc_tok'); } catch (e) {} TOK = ''; boot(); } fin(); return; }
      timer = r; renderIsland(); fin();
    }, fin, quiet);
    call({action:'get_choices'}, function(r){
      if (!r.ok) { $('habits').innerHTML = '<div class="caption">選択肢がまだありません（' + esc(r.error || '') + '）</div>'; choices = {must:[],habits:[],roulette:[]}; fin(); return; }
      choices = r; loadedDate = todayStr(); renderHabits();
      if (sheetKind === 'plan') openSheet('plan');
      fin();
    }, fin, quiet);
  }
  function manualReload(){ if (busyN > 0 || fullN > 0) return; msg(''); refresh(); }
  /* 画面に戻ってきたとき・日付が変わったとき・1分ごとに、裏で読み直す */
  function quietRefresh(){ if (!TOK || busyN > 0 || fullN > 0 || document.visibilityState !== 'visible') return; refresh(null, true); }
  document.addEventListener('visibilitychange', function(){ if (document.visibilityState === 'visible') quietRefresh(); });
  window.addEventListener('pageshow', function(ev){ if (ev.persisted) quietRefresh(); });
  setInterval(function(){ if (loadedDate && loadedDate !== todayStr()) msg('日付が変わりました'); quietRefresh(); }, 60000);
  /* ---- アイランドと全画面タイマー ---- */
  function fmtElapsed(s){ var h = Math.floor(s/3600), m = Math.floor((s%3600)/60), x = s%60; return (h > 0 ? h + ':' + String(m).padStart(2,'0') : String(m)) + ':' + String(x).padStart(2,'0'); }
  function renderIsland(){
    if (tick) { clearInterval(tick); tick = null; }
    var il = $('island'); il.classList.remove('busy');
    if (timer && timer.running) {
      var pc = timer.source === 'pc';
      var key = (timer.source || '') + '|' + timer.started;
      if (key !== lastTimerKey) { lastTimerKey = key; fullHidden = false; }  // 新しく始まった計測は全画面で出す
      il.classList.add('run'); $('dot').style.display = '';
      $('isText').textContent = (pc ? '🖥 ' : '') + timer.task;
      var started = timer.started;
      var upd = function(){ var s = Math.max(0, Math.floor((Date.now() - started) / 1000)); var f = fmtElapsed(s); $('isTime').textContent = f; $('fTime').textContent = f; };
      upd(); tick = setInterval(upd, 1000);
      $('btnStart').style.display = 'none'; $('btnStop').style.display = '';
      var note = pc ? (timer.stop_requested ? '停止をPCに送信済み（最大30秒）' : 'PC の計測を止めて記録') : '記録して終了';
      $('stopSub').textContent = note;
      $('fSrc').textContent = pc ? '🖥 PC で計測中' : '📱 スマホで計測中';
      $('fTask').textContent = timer.task || '';
      $('fNote').textContent = pc && timer.stop_requested ? '停止を PC に送信済みです（最大30秒で記録されます）' : '';
      $('full').classList.toggle('on', !fullHidden);
    } else {
      lastTimerKey = '';
      il.classList.remove('run'); $('dot').style.display = 'none';
      $('isText').textContent = '停止中'; $('isTime').textContent = '';
      $('btnStart').style.display = ''; $('btnStop').style.display = 'none';
      $('full').classList.remove('on');
    }
  }
  function hideFull(){ fullHidden = true; $('full').classList.remove('on'); }
  function islandTap(){
    if (busyN > 0 || fullN > 0) return;
    if (timer && timer.running) { fullHidden = false; $('full').classList.add('on'); }
    else openStart();
  }
  /* ---- 習慣チェック ---- */
  function renderHabits(){
    var hs = (choices && choices.habits) || [];
    if (!hs.length) { $('habits').innerHTML = '<div class="caption">今日の習慣はありません</div>'; return; }
    var h = '';
    hs.forEach(function(x){
      h += '<div class="hrow' + (x.done ? ' on' : '') + '" data-t="' + esc(x.title) + '" onclick="toggleHabit(this)"><div class="chk">' + (x.done ? '✓' : '') + '</div><div class="name">' + esc(x.title) + '</div><div class="tm">' + esc(x.start) + '〜' + esc(x.end) + '</div></div>';
    });
    $('habits').innerHTML = h;
  }
  function toggleHabit(el){
    if (busyN > 0 || fullN > 0 || el.classList.contains('on')) return;
    var title = el.dataset.t;
    el.classList.add('on'); el.querySelector('.chk').textContent = '✓';
    holdFull('送信しています');
    call({action:'add', type:'habit_done', title:title, level:'full'}, function(r){
      releaseFull();
      if (r.ok) { msg('「' + title + '」を完了にしました（PC に30秒以内に反映）'); }
      else { el.classList.remove('on'); el.querySelector('.chk').textContent = ''; msg(r.error); }
    }, function(){ releaseFull(); el.classList.remove('on'); el.querySelector('.chk').textContent = ''; });
  }
  /* ---- シート ---- */
  function leftLabel(n){ if (n === null || n === undefined) return ''; if (n < 0) return '<span class="hot">期限切れ</span>'; if (n === 0) return '<span class="hot">今日</span>'; if (n === 1) return '<span class="hot">明日</span>'; return 'あと' + n + '日'; }
  function planHtml(){
    var c = choices || {};
    var b = '<h3>📋 今日の予定・必須・課題</h3>';
    var mustAll = c.must_all || (c.must || []).map(function(t){ return {title:t, done:false}; });
    b += '<div class="sec">🔴 今日の必須</div>';
    if (!mustAll.length) b += '<div class="caption">なし</div>';
    mustAll.forEach(function(m){ b += '<div class="li' + (m.done ? ' done' : '') + '"><span class="w">' + (m.done ? '✓ 完了' : '○ 未完了') + '</span><span class="n">' + esc(m.title) + '</span></div>'; });
    var evs = c.events || [];
    var t = todayStr();
    b += '<div class="sec">📅 今日・明日の予定</div>';
    if (!evs.length) b += '<div class="caption">なし</div>';
    evs.forEach(function(e){
      var day = e.date === t ? '今日' : '明日';
      var tm = e.start ? (e.start + (e.end ? '〜' + e.end : '')) : '終日';
      b += '<div class="li' + (e.done ? ' done' : '') + '"><span class="w">' + day + ' ' + esc(tm) + '</span><span class="n">' + esc(e.title) + (e.google ? ' <span class="caption">G</span>' : '') + '</span></div>';
    });
    var due = c.due || [];
    b += '<div class="sec">⏰ 期限のある課題</div>';
    if (!due.length) b += '<div class="caption">なし</div>';
    due.forEach(function(a){ b += '<div class="li"><span class="w">' + leftLabel(a.left) + '</span><span class="n">' + esc(a.icon || '') + ' ' + esc(a.title) + ' <span class="caption">' + esc(a.progress) + '%</span></span></div>'; });
    b += '<div class="caption" style="margin-top:12px;text-align:center">PC 側の内容（' + esc(c.updated || '不明') + ' 時点）</div>';
    return b;
  }
  function openSheet(kind){
    if (busyN > 0 && kind !== 'plan') return;
    if (fullN > 0) return;
    sheetKind = kind; var b = '';
    if (kind === 'start') {
      var c = choices || {must:[],habits:[],roulette:[]};
      b += '<h3>▶ 何をやる？</h3>';
      var sec = function(label, arr, key){ if (!arr || !arr.length) return; b += '<div class="sec">' + label + '</div>'; arr.forEach(function(x){ var t = key ? x[key] : x; var extra = key ? '<span class="tm">' + esc(x.start) + '〜' + esc(x.end) + '</span>' : ''; b += '<button class="opt" onclick="startTimer(this.dataset.t)" data-t="' + esc(t) + '">' + esc(t) + extra + '</button>'; }); };
      sec('🔴 今日の必須', c.must); sec('🔁 今日の習慣', (c.habits || []).filter(function(x){ return !x.done; }), 'title'); sec('🎲 ルーレット項目', c.roulette);
      b += '<div class="sec">自由入力</div><input id="free" placeholder="例：レポートの下書き"><button class="go" onclick="startFree()">▶ 開始</button>';
    } else if (kind === 'plan') {
      b += planHtml();
    } else if (kind === 'money') {
      b += '<h3>💸 支出を記録</h3><input id="mAmt" type="number" inputmode="numeric" placeholder="金額（円）"><input id="mCat" placeholder="カテゴリ（例：食費）"><input id="mDet" placeholder="何に使った？（空でもOK）"><button class="go" onclick="addMoney()">記録する</button>';
    } else {
      var ds = todayStr();
      b += '<h3>📌 予定を追加</h3><input id="eTitle" placeholder="予定の名前"><div class="row"><input id="eDate" type="date" value="' + ds + '"><input id="eEnd" type="date" value="' + ds + '"></div><div class="row"><input id="eStart" type="time" value="12:00"><input id="eEndT" type="time" value="13:00"></div><button class="go" onclick="addEvent()">追加する</button>';
    }
    $('sheetBody').innerHTML = b;
    $('scrim').classList.add('on'); $('sheet').classList.add('on');
  }
  function openStart(){ openSheet('start'); }
  function startFree(){ startTimer($('free').value); }
  function closeSheet(){ $('scrim').classList.remove('on'); $('sheet').classList.remove('on'); sheetKind = null; }
  /* ---- 動作（書き込みは全画面ロード中にして、結果を読み直すまで操作させない） ---- */
  function startTimer(task){
    task = (task || '').trim(); if (!task) { msg('何をやるか選んでください'); return; }
    if (timer && timer.running) { msg('計測中です。先にストップしてください'); return; }
    closeSheet();
    holdFull('開始しています');
    call({action:'timer_start', task:task}, function(r){
      if (r.ok) { msg('開始しました'); refresh(releaseFull); } else { releaseFull(); msg(r.error); }
    }, releaseFull);
  }
  function stopTimer(){
    if (busyN > 0 || fullN > 0) return;
    if (timer && timer.source === 'pc') {
      if (timer.stop_requested) { msg('送信済みです。PC 側の反映を待っています'); return; }
      holdFull('PC に停止を送っています');
      call({action:'pc_stop'}, function(r){
        msg(r.ok ? 'PC に停止を送りました（30秒以内に記録されます）' : r.error);
        refresh(releaseFull); setTimeout(function(){ refresh(null, true); }, 35000);
      }, releaseFull);
      return;
    }
    holdFull('記録しています');
    call({action:'timer_stop'}, function(r){
      if (r.ok) { msg(r.minutes + ' 分を記録しました'); refresh(releaseFull); } else { releaseFull(); msg(r.error); }
    }, releaseFull);
  }
  function addMoney(){
    var amt = Number($('mAmt').value); if (!(amt > 0)) { msg('金額を入れてください'); return; }
    var body = {action:'add', type:'money', amount:amt, category:$('mCat').value, detail:$('mDet').value};
    closeSheet(); holdFull('送信しています');
    call(body, function(r){ releaseFull(); msg(r.ok ? '支出を送りました' : r.error); }, releaseFull);
  }
  function addEvent(){
    var t = $('eTitle').value.trim(), d = $('eDate').value; if (!t || !d) { msg('名前と日付を入れてください'); return; }
    var body = {action:'add', type:'event', title:t, date:d, endDate:$('eEnd').value || d, start:$('eStart').value, end:$('eEndT').value};
    closeSheet(); holdFull('送信しています');
    call(body, function(r){ releaseFull(); msg(r.ok ? '予定を送りました' : r.error); }, releaseFull);
  }
  boot();
</script></body></html>`;

/* ===== iPhone のタイマー（スタート/ストップを PC 側に即反映する） =====
 * スタート: { action:'timer_start', task }  → 実行中の状態を保存（PC が約30秒ごとに読む）
 * ストップ: { action:'timer_stop' }         → 経過分を受け取り箱に記録して状態を消す
 * 状態:     { action:'timer_state' }
 * PC 用:    { action:'phone_sync' }         → 状態＋受け取り箱の中身をまとめて返す（Gドライブ同期を待たない） */
function timerStart(body) {
  const props = PropertiesService.getScriptProperties();
  props.setProperty('timer', JSON.stringify({
    task: String(body.task || '勉強'), started: Date.now(),
  }));
  return { ok: true, task: String(body.task || '勉強'), started: Date.now() };
}

function timerState() {
  const props = PropertiesService.getScriptProperties();
  const raw = props.getProperty('timer');
  if (raw) {
    try {
      const t = JSON.parse(raw);
      return { ok: true, running: true, source: 'phone', task: t.task, started: t.started,
               elapsed_sec: Math.floor((Date.now() - t.started) / 1000) };
    } catch (err) { /* 壊れていたら PC 側を見る */ }
  }
  // スマホのタイマーが無ければ、PC（小窓/集中モード）の計測状態を返す（PC が約30秒ごとに送ってくる。3分以上古ければ無効）
  const pcRaw = props.getProperty('pc_timer');
  if (pcRaw) {
    try {
      const pc = JSON.parse(pcRaw);
      if (pc.running && Date.now() - (pc.seen || 0) < 3 * 60 * 1000) {
        return { ok: true, running: true, source: 'pc', task: pc.task, started: pc.started,
                 elapsed_sec: Math.floor((Date.now() - pc.started) / 1000),
                 stop_requested: !!props.getProperty('pc_cmd') };
      }
    } catch (err) {}
  }
  return { ok: true, running: false };
}

/** スマホから「PC の計測を止めて記録」。PC が次の phone_sync で受け取って実行する */
function pcStop() {
  const props = PropertiesService.getScriptProperties();
  props.setProperty('pc_cmd', 'pc_stop');
  return { ok: true, queued: true };
}

function timerStop(body) {
  const props = PropertiesService.getScriptProperties();
  const raw = props.getProperty('timer');
  props.deleteProperty('timer');
  if (!raw) return { ok: false, error: 'timer not running' };
  let t;
  try { t = JSON.parse(raw); } catch (err) { return { ok: false, error: 'broken timer state' }; }
  const minutes = Math.max(0, Math.round((Date.now() - t.started) / 60000));
  if (body && body.discard) return { ok: true, task: t.task, minutes: minutes, recorded: false };
  _appendInbox({
    ts: Date.now() / 1000, task: t.task, minutes: minutes,
    date: Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy-MM-dd'),
  });
  return { ok: true, task: t.task, minutes: minutes, recorded: true };
}

function phoneSync(body) {
  const props = PropertiesService.getScriptProperties();
  // PC 側の計測状態を預かる（スマホ用ページの表示用）
  if (body && body.pc_timer) {
    const pc = body.pc_timer;
    if (pc.running) {
      props.setProperty('pc_timer', JSON.stringify({ running: true, task: String(pc.task || ''),
        started: Number(pc.started) || Date.now(), source: String(pc.source || 'pc'), seen: Date.now() }));
    } else {
      props.deleteProperty('pc_timer');
    }
  }
  // スマホ用ページの選択肢・予定・課題（PC が30秒ごとに送る。Gドライブの同期を待たない）
  if (body && body.choices) {
    try {
      props.setProperty('choices', JSON.stringify(body.choices));
    } catch (err) { /* 大きすぎる等で保存できなければ、Drive の choices.json を使う */ }
  }
  // スマホからの停止要求があれば1回だけ PC に渡す
  const cmd = props.getProperty('pc_cmd') || '';
  if (cmd) props.deleteProperty('pc_cmd');
  const file = _inboxFile();
  let arr = [];
  try { arr = JSON.parse(file.getBlob().getDataAsString() || '[]'); } catch (err) { arr = []; }
  return { ok: true, timer: timerState(), inbox: arr, cmd: cmd };
}

/** アプリの「カレンダー」「今日」に表示するために、メインカレンダー（既定のカレンダー）の
 *  予定を読み取り専用で返す。FocusCafe カレンダーは別カレンダーなので含まれない。
 *  { action:'list_events', range_start:'yyyy-MM-dd', range_end:'yyyy-MM-dd' } */
function listEvents(body) {
  const cal = CalendarApp.getDefaultCalendar();
  const start = new Date(body.range_start + 'T00:00:00+09:00');
  const end = new Date(body.range_end + 'T23:59:59+09:00');
  const tz = 'Asia/Tokyo';
  const events = [];
  cal.getEvents(start, end).forEach(function (ev) {
    if ((ev.getDescription() || '').indexOf('fcid:') >= 0) return; // アプリが作ったものは除く
    const allday = ev.isAllDayEvent();
    const s = ev.getStartTime();
    const e = ev.getEndTime();
    let endDate = Utilities.formatDate(e, tz, 'yyyy-MM-dd');
    if (allday) {
      // 終日の終了は翌日0時（排他的）で返ってくるので、1ミリ秒戻して最終日にする
      endDate = Utilities.formatDate(new Date(e.getTime() - 1), tz, 'yyyy-MM-dd');
    }
    events.push({
      id: ev.getId(),
      title: ev.getTitle(),
      allday: allday,
      date: Utilities.formatDate(s, tz, 'yyyy-MM-dd'),
      endDate: endDate,
      start: allday ? '' : Utilities.formatDate(s, tz, 'HH:mm'),
      end: allday ? '' : Utilities.formatDate(e, tz, 'HH:mm'),
      location: ev.getLocation() || '',
      // 作成日時：面接などの予定で制限を外す特例は「開始の24時間以上前に作成」が条件（PC側で判定）
      created: Utilities.formatDate(ev.getDateCreated(), tz, "yyyy-MM-dd'T'HH:mm:ss"),
      // 繰り返しの予定か・自分が作った予定か（招待でないか）。どちらも特例の判定に使う（PC側）
      recurring: ev.isRecurringEvent(),
      ownedByMe: ev.isOwnedByMe(),
    });
  });
  return { ok: true, calendar: cal.getName(), events: events };
}

/** スマホ用ページの選択肢（必須・習慣・ルーレット項目・予定・課題）。PC が phone_sync で30秒ごとに送ったもの */
function readChoices() {
  const raw = PropertiesService.getScriptProperties().getProperty('choices');
  if (!raw) return { ok: false, error: 'PC からまだ届いていません（PC 側の起動後30秒ほどで届きます）' };
  let pc;
  try { pc = JSON.parse(raw); } catch (err) { return { ok: false, error: 'broken choices' }; }
  pc.ok = true;
  pc.source = 'pc';
  pc.names = [].concat(pc.must || [], (pc.habits || []).map(function (h) { return h.title; }), pc.roulette || []);
  return pc;
}

function out(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

function getCal() {
  const cals = CalendarApp.getCalendarsByName(CAL_NAME);
  if (cals.length) return cals[0];
  return CalendarApp.createCalendar(CAL_NAME);
}

function syncEvents(body) {
  const cal = getCal();
  const start = new Date(body.range_start + 'T00:00:00+09:00');
  const end = new Date(body.range_end + 'T23:59:59+09:00');
  // 既存の fcid: 付きイベント（＝このアプリが作ったもの）だけ削除して入れ替える
  cal.getEvents(start, end).forEach(function (ev) {
    if ((ev.getDescription() || '').indexOf('fcid:') >= 0) ev.deleteEvent();
  });
  let n = 0;
  (body.events || []).forEach(function (ev) {
    const desc = (ev.desc || '') + '\nfcid:' + ev.key;
    try {
      if (ev.allday) {
        if (ev.end && ev.end !== ev.start) {
          // 期間もの（例：5日間のインターン）。終了日は翌日0時（排他的）で渡す
          const endEx = new Date(ev.end + 'T00:00:00+09:00');
          endEx.setDate(endEx.getDate() + 1);
          cal.createAllDayEvent(ev.title, new Date(ev.start + 'T00:00:00+09:00'),
            endEx, { description: desc });
        } else {
          cal.createAllDayEvent(ev.title, new Date(ev.start + 'T00:00:00+09:00'),
            { description: desc });
        }
      } else {
        cal.createEvent(ev.title, new Date(ev.start + '+09:00'),
          new Date(ev.end + '+09:00'), { description: desc });
      }
      n++;
    } catch (err) { /* 1件の失敗で全体を止めない */ }
  });
  return { ok: true, created: n };
}

function _inboxFile() {
  const it = DriveApp.getFoldersByName(FOLDER_NAME);
  const folder = it.hasNext() ? it.next() : DriveApp.createFolder(FOLDER_NAME);
  const files = folder.getFilesByName(FILE_NAME);
  return files.hasNext() ? files.next() : folder.createFile(FILE_NAME, '[]');
}

/** iPhoneショートカットからの「支出」「単発予定」「課題メモ」「習慣の完了」を受け取り箱に追記する。
 *  習慣完了: { action:'add', type:'habit_done', title(習慣名), level('full' か 'min'。空=full) }
 *  支出:     { action:'add', type:'money', amount, category, detail }
 *  予定:     { action:'add', type:'event', title, date(yyyy-MM-dd), start(HH:mm), end(HH:mm) }
 *            複数日にまたがる予定は endDate(yyyy-MM-dd) も送る（date〜endDate の毎日に登録される）
 *  課題メモ: { action:'add', type:'asg_note', title(課題名の一部でOK), note, progress(0-100・空OK) }
 *            一致する課題があればメモ追記＋進捗更新、無ければ新しい課題として作成される
 *  デスクトップ側のアプリが5分おきに読み取って、手入力と同じ形で登録する。 */
function appendItem(body) {
  const count = _appendInbox({
    ts: Date.now() / 1000,
    type: String(body.type || ''),
    amount: body.amount,
    category: String(body.category || ''),
    detail: String(body.detail || ''),
    title: String(body.title || ''),
    date: String(body.date || ''),
    endDate: String(body.endDate || ''),
    start: String(body.start || ''),
    end: String(body.end || ''),
    note: String(body.note || ''),
    progress: String(body.progress || ''),
    level: String(body.level || ''),
  });
  return { ok: true, count: count };
}

const INBOX_KEEP_DAYS = 30;  // 受け取り箱に残す日数（PC は ts で取り込み済みを見分けるので、古い分は消してよい）

/** 受け取り箱に1件足す。スマホから続けて送られても片方が上書きで消えないよう、
 *  スクリプトのロック（LockService 公式）で1件ずつ書く。ついでに古い記録を消して箱が増え続けないようにする。
 *  戻り値は追記後の件数 */
function _appendInbox(item) {
  const lock = LockService.getScriptLock();
  lock.waitLock(10000);  // 10秒待っても取れなければ例外（記録は失敗として返る）
  try {
    const file = _inboxFile();
    let arr = [];
    try { arr = JSON.parse(file.getBlob().getDataAsString() || '[]'); } catch (err) { arr = []; }
    const cutoff = Date.now() / 1000 - INBOX_KEEP_DAYS * 24 * 3600;
    arr = arr.filter(function (x) { return Number(x && x.ts) >= cutoff; });
    arr.push(item);
    file.setContent(JSON.stringify(arr));
    return arr.length;
  } finally {
    lock.releaseLock();
  }
}

