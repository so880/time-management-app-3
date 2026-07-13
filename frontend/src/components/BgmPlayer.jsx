// 環境音プレイヤー（YouTube）。既存 components/bgm_player.py のHTMLを
// iframe(srcDoc) としてそのまま移植（YouTube IFrame API を内部で使用）。
const PLAYER_HTML = `<!DOCTYPE html><html><head><meta charset="utf-8"><style>
    body { margin:0; font-family:'Segoe UI',sans-serif; }
    .snd-wrap { background: rgba(0,0,0,0.4); padding: 14px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.1); color: white; box-sizing:border-box; }
    .snd-grid { display:flex; flex-direction:column; gap:8px; }
    .snd-btn { display:block; width:100%; box-sizing:border-box; text-align:center; padding:10px 12px; border-radius:6px; cursor:pointer; color:#fff; font-size:1em; transition: all .15s; }
    .snd-cafe { background:rgba(139,69,19,0.35); border:1px solid #8B4513; }
    .snd-chat { background:rgba(210,105,30,0.35); border:1px solid #D2691E; }
    .snd-relax { background:rgba(70,130,180,0.35); border:1px solid #4682B4; }
    .snd-silent { background:rgba(255,75,75,0.2); border:1px solid #ff4b4b; }
    .snd-custom { background:rgba(76,175,80,0.3); border:1px solid #4CAF50; margin-top:6px; }
    .snd-btn:hover { filter: brightness(1.35); }
    .snd-btn.active { filter: brightness(1.8); border-color:#ffffff !important; font-weight:bold; box-shadow: 0 0 14px rgba(255,255,255,0.85); }
    .snd-url-box { border:1px solid #4CAF50; border-radius:6px; padding:8px; margin-top:10px; background:rgba(76,175,80,0.08); box-sizing:border-box; }
    .snd-url-box input { width:100%; box-sizing:border-box; padding:7px; border-radius:4px; border:1px solid #555; background:#222; color:#fff; margin-bottom:6px; }
    .snd-label { font-size:0.82em; color:#cfcfcf; margin-bottom:4px; }
    #snd-status { text-align:center; font-size:0.8em; color:#9e9e9e; margin-top:8px; min-height:1em; }
</style></head><body>
<div class="snd-wrap">
    <div class="snd-grid">
        <button class="snd-btn snd-cafe" data-snd="cafe" onclick="playVid('cafe', this)">☕ カフェ</button>
        <button class="snd-btn snd-chat" data-snd="chat" onclick="playVid('chat', this)">🗣️ 雑踏</button>
        <button class="snd-btn snd-relax" data-snd="relax" onclick="playVid('relax', this)">🐋 波と鯨</button>
        <button class="snd-btn snd-silent active" data-snd="silent" onclick="stopVid(this)">🔇 無音</button>
    </div>
    <div class="snd-url-box">
        <div class="snd-label">🔗 自分のURL（YouTube）を貼り付け</div>
        <input id="customUrl" type="text" placeholder="https://www.youtube.com/watch?v=...">
        <button class="snd-btn snd-custom" data-snd="custom" onclick="playCustom(this)">▶ このURLを再生</button>
    </div>
    <div id="snd-status">読み込み中…</div>
    <div id="ytplayer" style="display:none;"></div>
    <script>
        var tag = document.createElement('script'); tag.src = "https://www.youtube.com/iframe_api";
        var firstScriptTag = document.getElementsByTagName('script')[0]; firstScriptTag.parentNode.insertBefore(tag, firstScriptTag);
        var player = null, ytReady = false, pendingAction = null;
        const vids = { 'cafe': '__CAFE_ID__', 'chat': '__CHAT_ID__', 'relax': '__RELAX_ID__' };
        function setStatus(msg) { var el = document.getElementById('snd-status'); if (el) el.textContent = msg; }
        function onYouTubeIframeAPIReady() {
            player = new YT.Player('ytplayer', {
                height: '0', width: '0',
                playerVars: { 'autoplay': 0, 'controls': 0, 'playsinline': 1 },
                events: {
                    'onReady': function() {
                        ytReady = true;
                        setStatus('準備OK（ボタンで再生）');
                        if (pendingAction) { pendingAction(); pendingAction = null; }
                    },
                    'onStateChange': function(e) {
                        if (e.data === YT.PlayerState.ENDED) { player.seekTo(0); player.playVideo(); }
                    },
                    'onError': function() { setStatus('⚠️ この動画は再生できません（別のURLを試してください）'); }
                }
            });
        }
        function run(fn) { if (ytReady && player) { fn(); } else { pendingAction = fn; setStatus('プレイヤー準備中…もう一度押してください'); } }
        function setActive(btn) {
            document.querySelectorAll('.snd-btn').forEach(function(b){ b.classList.remove('active'); });
            if (btn) btn.classList.add('active');
        }
        function playVid(t, btn) {
            setActive(btn);
            var vid = extractId(vids[t]) || vids[t];
            run(function(){ player.loadVideoById(vid); player.playVideo(); setStatus('▶ 再生中'); });
        }
        function stopVid(btn) {
            setActive(btn);
            run(function(){ player.stopVideo(); setStatus('🔇 停止中'); });
        }
        function extractId(u) {
            u = (u || '').trim();
            if (u.indexOf('youtu.be/') !== -1) return u.split('youtu.be/')[1].slice(0,11);
            if (u.indexOf('v=') !== -1) return u.split('v=')[1].slice(0,11);
            if (u.indexOf('embed/') !== -1) return u.split('embed/')[1].slice(0,11);
            if (u.length === 11) return u;
            return null;
        }
        function playCustom(btn) {
            var id = extractId(document.getElementById('customUrl').value);
            if (!id) { setStatus('⚠️ URLが正しくありません'); alert('YouTubeのURLが正しくないようです'); return; }
            setActive(btn);
            run(function(){ player.loadVideoById(id); player.playVideo(); setStatus('▶ 再生中（自分のURL）'); });
        }
    </script>
</div></body></html>`

function BgmPlayer({ cafeId, chatId, relaxId }) {
  const html = PLAYER_HTML
    .replaceAll('__CAFE_ID__', (cafeId || '').replaceAll("'", ''))
    .replaceAll('__CHAT_ID__', (chatId || '').replaceAll("'", ''))
    .replaceAll('__RELAX_ID__', (relaxId || '').replaceAll("'", ''))
  return (
    <iframe
      title="bgm-player"
      srcDoc={html}
      style={{ width: '100%', height: '400px', border: 'none' }}
      allow="autoplay; encrypted-media"
    />
  )
}

export default BgmPlayer
