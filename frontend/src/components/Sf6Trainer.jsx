// スト6 コンボ練習（既存 components/sf6_trainer.py のHTMLを iframe で移植）
const SF6_HTML = `<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<style>
  body { background-color: rgba(18,18,18,0.9); color: #fff; font-family: 'Segoe UI', sans-serif; padding: 10px; display: flex; flex-direction: column; height: 100vh; box-sizing: border-box; margin: 0; border-radius: 10px;}
  #status { color: #ffeb3b; margin-bottom: 10px; font-size: 1.2em; font-family: monospace; }
  .combo-panel { background-color: rgba(30,30,30,0.8); border: 2px solid #4caf50; border-radius: 8px; padding: 15px; margin-bottom: 15px; display: flex; flex-direction: column; gap: 10px; }
  .combo-header { display: flex; justify-content: space-between; align-items: center; }
  .combo-header select { background: #333; color: white; border: 1px solid #555; padding: 5px 10px; border-radius: 4px; font-size: 1em; }
  .combo-progress { font-size: 1.4em; font-weight: bold; text-align: center; padding: 10px; background: #111; border-radius: 6px; }
  .step { color: #555; transition: all 0.2s; }
  .step.completed { color: #4caf50; }
  .step.current { color: #ffeb3b; text-shadow: 0 0 8px rgba(255,235,59,0.5); }
  .step-arrow { color: #444; font-size: 0.8em; margin: 0 10px; }
  .container { display: flex; flex: 1; gap: 20px; overflow: hidden; }
  .icon-svg { width: 22px; height: 22px; display: inline-block; vertical-align: middle; filter: drop-shadow(0 2px 2px rgba(0,0,0,0.5)); }
  .icon-arrow { fill: #eee; }
  .icon-neutral { fill: #555; }
  .btn-icon { width: 22px; height: 22px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; font-weight: bold; font-size: 14px; }
  .btn-p { background: linear-gradient(135deg, #f44336, #b71c1c); color: white; border: 2px solid #ffcdd2;}
  .btn-k { background: linear-gradient(135deg, #2196f3, #0d47a1); color: white; border: 2px solid #bbdefb;}
  .history-panel { width: 220px; background-color: rgba(30,30,30,0.8); border: 2px solid #333; border-radius: 8px; padding: 10px; overflow-y: hidden; display: flex; flex-direction: column; }
  .history-panel h3 { margin: 0 0 10px 0; font-size: 0.9em; color: #888; text-align: center; border-bottom: 1px solid #333; padding-bottom: 5px; }
  #history-list { display: flex; flex-direction: column; gap: 4px; }
  .history-item { display: flex; align-items: center; justify-content: space-between; background-color: #2a2a2a; padding: 6px 12px; border-radius: 6px; border-left: 4px solid #444; }
  .history-item.neutral-item { background-color: #1a1a1a; border-left-color: #222; }
  .history-item.punch-item { border-left-color: #f44336; }
  .history-item.kick-item { border-left-color: #2196f3; }
  .icon-container { display: flex; align-items: center; justify-content: center; width: 30px; }
  .frame-text { font-family: monospace; font-size: 1.1em; color: #bbb; width: 50px; text-align: right; }
  .log-panel { flex: 1; background-color: rgba(30,30,30,0.8); border: 2px solid #333; border-radius: 8px; padding: 15px; overflow-y: auto; }
  .log-panel h3 { margin: 0 0 15px 0; font-size: 1em; color: #888; border-bottom: 1px solid #333; padding-bottom: 5px;}
  .success { margin-bottom: 12px; padding: 12px; border-left: 6px solid #4caf50; background: linear-gradient(90deg, rgba(76, 175, 80, 0.15) 0%, rgba(30, 30, 30, 0) 100%); animation: fadein 0.3s; border-radius: 4px;}
  .sa-success { border-left-color: #ff9800; background: linear-gradient(90deg, rgba(255, 152, 0, 0.15) 0%, rgba(30, 30, 30, 0) 100%); }
  .special-success { border-left-color: #2196f3; background: linear-gradient(90deg, rgba(33, 150, 243, 0.15) 0%, rgba(30, 30, 30, 0) 100%); }
  .combo-success-log { border-left: 6px solid #e91e63; background: linear-gradient(90deg, rgba(233, 30, 99, 0.2) 0%, rgba(30, 30, 30, 0) 100%); }
  .eval-excellent { color: #ffeb3b; font-weight: bold; }
  .eval-good { color: #4caf50; font-weight: bold; }
  .eval-slow { color: #9e9e9e; font-weight: bold; }
  .details-box { font-size: 1em; margin-top: 10px; background: rgba(0,0,0,0.3); padding: 10px; border-radius: 6px; display: flex; flex-wrap: wrap; align-items: center; gap: 4px;}
  .warning-text { color: #ff9800; font-size: 0.9em; margin-top: 6px; display: block; border-left: 3px solid #ff9800; padding-left: 8px;}
  .danger-text { color: #f44336; font-size: 0.9em; margin-top: 6px; display: block; border-left: 3px solid #f44336; padding-left: 8px; font-weight: bold;}
  .frame-badge { background: #333; padding: 2px 6px; border-radius: 4px; font-family: monospace; font-size: 0.9em; margin-left: 2px; margin-right: 6px;}
  .fast-input { color: #4caf50; border: 1px solid #4caf50; }
  .slow-input { color: #ff5252; border: 1px solid #ff5252; background: rgba(244, 67, 54, 0.1); }
  .combo-streak { display: inline-block; background-color: #ff5722; color: white; padding: 2px 8px; border-radius: 12px; font-size: 0.85em; margin-left: 10px; font-weight: bold;}
  @keyframes fadein { from { opacity: 0; transform: translateX(-10px); } to { opacity: 1; transform: translateX(0); } }
</style>
</head>
<body>
  <div id="status">キーボード受付中 / コントローラー未接続</div>
  <div class="combo-panel">
    <div class="combo-header">
      <span style="font-weight: bold; color: #4caf50;">🎯 コンボ練習モード</span>
      <select id="combo-selector">
        <option value="combo1">基本キャンセル: しゃがみK → 波動拳</option>
        <option value="combo2">昇竜キャンセル: 立ちP → 昇竜拳 → 真空波動拳</option>
        <option value="combo3">竜巻コンボ: しゃがみP → 竜巻旋風脚</option>
      </select>
    </div>
    <div id="combo-progress" class="combo-progress"></div>
  </div>
  <div class="container">
    <div class="history-panel"><h3>INPUT</h3><div id="history-list"></div></div>
    <div class="log-panel"><h3>COMMAND ANALYZER</h3><div id="log"></div></div>
  </div>
<script>
  const statusElement = document.getElementById('status');
  const logElement = document.getElementById('log');
  const historyListElement = document.getElementById('history-list');
  const comboSelector = document.getElementById('combo-selector');
  const comboProgressElement = document.getElementById('combo-progress');

  let inputBuffer = [];
  const BUFFER_TIME_LIMIT = 1500;
  const FRAME_MS = 1000 / 60;
  const MAX_VISUAL_HISTORY = 20;
  let prevDir = 5; let prevPunch = false; let prevKick = false; let currentVisualDir = null;
  let streakCount = 0; let lastSuccessfulCommand = "";
  const COMBO_RECIPES = {
    "combo1": { name: "しゃがみKキャンセル波動", sequence: ["しゃがみK", "波動拳"] },
    "combo2": { name: "昇竜SA3キャンセル", sequence: ["立ちP", "昇竜拳", "真空波動拳"] },
    "combo3": { name: "小足竜巻", sequence: ["しゃがみP", "竜巻旋風脚"] }
  };
  let activeComboId = comboSelector.value; let comboStep = 0; let lastMoveTime = 0;
  comboSelector.addEventListener('change', (e) => { activeComboId = e.target.value; comboStep = 0; renderComboUI(); });
  const baseArrowSVG = \`<svg class="icon-svg icon-arrow" viewBox="0 0 24 24"><path d="M12 2L19 10H14V22H10V10H5L12 2Z"/></svg>\`;
  const neutralSVG = \`<svg class="icon-svg icon-neutral" viewBox="0 0 24 24"><circle cx="12" cy="12" r="6"/></svg>\`;
  const dirData = {
    1: { type: 'arrow', rot: 225 }, 2: { type: 'arrow', rot: 180 }, 3: { type: 'arrow', rot: 135 },
    4: { type: 'arrow', rot: 270 }, 5: { type: 'neutral', rot: 0 }, 6: { type: 'arrow', rot: 90 },
    7: { type: 'arrow', rot: 315 }, 8: { type: 'arrow', rot: 0 }, 9: { type: 'arrow', rot: 45 }
  };
  function getIconHtml(val) {
    if (val === 'P') return \`<div class="btn-icon btn-p">P</div>\`;
    if (val === 'K') return \`<div class="btn-icon btn-k">K</div>\`;
    const d = dirData[val];
    if (!d) return '';
    if (d.type === 'neutral') return neutralSVG;
    return \`<div style="transform: rotate(\${d.rot}deg); display: inline-flex;">\${baseArrowSVG}</div>\`;
  }
  const keys = { ArrowUp: false, ArrowDown: false, ArrowLeft: false, ArrowRight: false, z: false, x: false };
  window.addEventListener('keydown', e => { if (keys.hasOwnProperty(e.key)) { keys[e.key] = true; e.preventDefault(); } });
  window.addEventListener('keyup', e => { if (keys.hasOwnProperty(e.key)) { keys[e.key] = false; e.preventDefault(); } });
  function gameLoop() { pollInput(); requestAnimationFrame(gameLoop); }
  function pollInput() {
    let x = 0, y = 0; let isPunch = keys.z; let isKick = keys.x;
    if (keys.ArrowRight) x = 1; else if (keys.ArrowLeft) x = -1;
    if (keys.ArrowDown) y = 1; else if (keys.ArrowUp) y = -1;
    const gamepads = navigator.getGamepads(); const pad = gamepads[0];
    if (pad) {
      statusElement.textContent = \`🎮 接続中: \${pad.id}\`; statusElement.style.color = '#4caf50';
      if (pad.axes[0] > 0.5) x = 1; else if (pad.axes[0] < -0.5) x = -1;
      if (pad.axes[1] > 0.5) y = 1; else if (pad.axes[1] < -0.5) y = -1;
      if (pad.buttons[15]?.pressed) x = 1; else if (pad.buttons[14]?.pressed) x = -1;
      if (pad.buttons[13]?.pressed) y = 1; else if (pad.buttons[12]?.pressed) y = -1;
      if (pad.axes.length > 9) {
        const pov = pad.axes[9];
        if (pov > -1.1 && pov < 1.1) {
          const angle = Math.round((pov + 1) * 3.5);
          if (angle === 0 || angle === 1 || angle === 7) y = -1;
          if (angle === 3 || angle === 4 || angle === 5) y = 1;
          if (angle === 1 || angle === 2 || angle === 3) x = 1;
          if (angle === 5 || angle === 6 || angle === 7) x = -1;
        }
      }
      if (pad.buttons[0]?.pressed || pad.buttons[2]?.pressed || pad.buttons[3]?.pressed) isPunch = true;
      if (pad.buttons[1]?.pressed || pad.buttons[4]?.pressed || pad.buttons[5]?.pressed) isKick = true;
    }
    let currentDir = 5;
    if (y === -1) { if (x === -1) currentDir = 7; else if (x === 0) currentDir = 8; else if (x === 1) currentDir = 9; }
    else if (y === 1) { if (x === -1) currentDir = 1; else if (x === 0) currentDir = 2; else if (x === 1) currentDir = 3; }
    else { if (x === -1) currentDir = 4; else if (x === 0) currentDir = 5; else if (x === 1) currentDir = 6; }
    const now = performance.now();
    if (currentDir !== prevDir) {
      if (currentVisualDir) currentVisualDir.frameElement.textContent = \`\${Math.max(1, Math.round((now - currentVisualDir.startTime) / FRAME_MS))}F\`;
      inputBuffer.push({ type: 'dir', val: currentDir, time: now });
      currentVisualDir = addVisualHistory(getIconHtml(currentDir), currentDir === 5 ? 'neutral-item' : '');
    } else if (currentVisualDir) {
      currentVisualDir.frameElement.textContent = \`\${Math.max(1, Math.round((now - currentVisualDir.startTime) / FRAME_MS))}F\`;
    }

    if (isPunch && !prevPunch) { inputBuffer.push({ type: 'atk', val: 'P', time: now }); addVisualHistory(getIconHtml('P'), 'punch-item'); checkAllCommands('P', currentDir); }
    if (isKick && !prevKick) { inputBuffer.push({ type: 'atk', val: 'K', time: now }); addVisualHistory(getIconHtml('K'), 'kick-item'); checkAllCommands('K', currentDir); }
    inputBuffer = inputBuffer.filter(input => (now - input.time) < BUFFER_TIME_LIMIT);
    prevDir = currentDir; prevPunch = isPunch; prevKick = isKick;
  }
  function addVisualHistory(iconHtml, className) {
    const div = document.createElement('div'); div.className = \`history-item \${className}\`;
    div.innerHTML = \`<div class="icon-container">\${iconHtml}</div><span class="frame-text">1F</span>\`;
    historyListElement.prepend(div);
    if (historyListElement.children.length > MAX_VISUAL_HISTORY) historyListElement.removeChild(historyListElement.lastChild);
    return { frameElement: div.querySelector('.frame-text'), startTime: performance.now() };
  }
  function checkAllCommands(atk, currentDir) {
    const b = [...inputBuffer].reverse(); if (b.length === 0) return;
    let match; let detectedMove = null;
    if ((match = matchSequence(b, [atk, 6, 3, 2, 6, 3, 2]))) { detectedMove = "真空波動拳"; showResult(\`真空波動拳\`, \`(236x2+\${atk})\`, 'sa-success', b, match); }
    else if ((match = matchSequence(b, [atk, 4, 1, 2, 4, 1, 2]))) { detectedMove = "真空竜巻旋風脚"; showResult(\`真空竜巻旋風脚\`, \`(214x2+\${atk})\`, 'sa-success', b, match); }
    else if ((match = matchSequence(b, [atk, 3, 2, 6]))) { detectedMove = "昇竜拳"; showResult(\`昇竜拳\`, \`(623+\${atk})\`, 'success', b, match); }
    else if ((match = matchSequence(b, [atk, 6, 3, 2]))) { detectedMove = "波動拳"; showResult(\`波動拳\`, \`(236+\${atk})\`, 'special-success', b, match); }
    else if ((match = matchSequence(b, [atk, 4, 1, 2]))) { detectedMove = "竜巻旋風脚"; showResult(\`竜巻旋風脚\`, \`(214+\${atk})\`, 'special-success', b, match); }
    if (!detectedMove) detectedMove = (currentDir === 1 || currentDir === 2 || currentDir === 3) ? \`しゃがみ\${atk}\` : \`立ち\${atk}\`;
    processComboTracking(detectedMove, performance.now());
  }
  function processComboTracking(moveName, time) {
    const targetSeq = COMBO_RECIPES[activeComboId].sequence;
    if (comboStep > 0 && (time - lastMoveTime) > 800) comboStep = 0;
    if (moveName === targetSeq[comboStep]) {
      comboStep++; lastMoveTime = time;
      if (comboStep === targetSeq.length) { showComboSuccessLog(); comboStep = 0; }
    } else { comboStep = (moveName === targetSeq[0]) ? 1 : 0; lastMoveTime = time; }
    renderComboUI();
  }
  function renderComboUI() {
    const seq = COMBO_RECIPES[activeComboId].sequence;
    comboProgressElement.innerHTML = seq.map((s, i) => \`<span class="step \${i < comboStep ? 'completed' : i === comboStep ? 'current' : ''}">\${s}</span>\`).join('<span class="step-arrow">➔</span>');
  }
  function showComboSuccessLog() {
    const div = document.createElement('div'); div.className = \`success combo-success-log\`;
    div.innerHTML = \`<div style="font-weight: bold; font-size: 1.4em; color: #e91e63;">✨ COMBO SUCCESS !!</div><div>【\${COMBO_RECIPES[activeComboId].name}】が完璧に繋がりました！</div>\`;
    logElement.prepend(div);
  }
  function matchSequence(buffer, sequence) {
    let seqIdx = 0; let matchIndices = [];
    for (let i = 0; i < buffer.length; i++) {
      const input = buffer[i]; const target = sequence[seqIdx];
      if ((typeof target === 'string' && input.val === target) || (typeof target === 'number' && input.val === target)) { matchIndices.push(i); seqIdx++; }
      if (seqIdx === sequence.length) return matchIndices;
    }
    return false;
  }
  function showResult(cmdName, cmdInput, className, buffer, matchIndices) {
    const seq = [...matchIndices].reverse();
    const startTime = buffer[seq[0]].time; const endTime = buffer[seq[seq.length - 1]].time;
    const totalFrames = Math.max(1, Math.round((endTime - startTime) / FRAME_MS));
    const dirCount = seq.length - 1;
    let evaluation = totalFrames <= dirCount * 3 ? "⚡ EXCELLENT" : totalFrames <= dirCount * 5 ? "👍 GOOD" : "🐢 SLOW (遅すぎます)";
    let evalClass = totalFrames <= dirCount * 3 ? "eval-excellent" : totalFrames <= dirCount * 5 ? "eval-good" : "eval-slow";

    if (totalFrames <= dirCount * 5) { streakCount = (lastSuccessfulCommand === cmdName + cmdInput) ? streakCount + 1 : 1; lastSuccessfulCommand = cmdName + cmdInput; }
    else { streakCount = 0; lastSuccessfulCommand = ""; }
    let streakHtml = streakCount >= 2 ? \`<span class="combo-streak">🔥 連続成功: \${streakCount}回</span>\` : "";
    let wrongDirs = new Set(); let hasNeutralNoise = false;

    for (let i = seq[0]; i >= seq[seq.length - 1]; i--) {
      if (!seq.includes(i)) { if (buffer[i].val === 5) hasNeutralNoise = true; else if (typeof buffer[i].val === 'number') wrongDirs.add(buffer[i].val); }
    }
    let noiseHtml = hasNeutralNoise ? \`<span class="warning-text">⚠️ 間に [N] が挟まりました (入力がフワついています)</span>\` : "";
    if (wrongDirs.size > 0) noiseHtml += \`<span class="danger-text">❌ 不要な方向 \${Array.from(wrongDirs).map(v => getIconHtml(v)).join(' ')} が混ざっています</span>\`;
    let detailsHtml = '<div class="details-box">';
    for (let i = 0; i < dirCount; i++) {
      const frames = Math.max(1, Math.round((buffer[seq[i+1]].time - buffer[seq[i]].time) / FRAME_MS));
      detailsHtml += \`\${getIconHtml(buffer[seq[i]].val)}<span class="frame-badge \${frames >= 5 ? 'slow-input' : frames <= 2 ? 'fast-input' : ''}">\${frames}F</span>\`;
    }
    detailsHtml += \`\${getIconHtml(buffer[seq[seq.length-1]].val)}</div>\`;
    const div = document.createElement('div'); div.className = \`success \${className}\`;
    div.innerHTML = \`<div style="font-weight: bold; font-size: 1.2em;">\${cmdName} <span style="font-weight:normal; font-size:0.8em; color:#888;">\${cmdInput}</span></div><div class="\${evalClass}" style="font-size: 1.1em; margin: 6px 0;">\${evaluation} : 合計 \${totalFrames}F \${streakHtml}</div>\${detailsHtml}\${noiseHtml}\`;
    logElement.prepend(div); inputBuffer = [];
  }
  renderComboUI(); gameLoop();
</script>
</body>
</html>`

function Sf6Trainer() {
  return (
    <iframe
      title="sf6-trainer"
      srcDoc={SF6_HTML}
      style={{ width: '100%', height: '650px', border: 'none' }}
      allow="gamepad"
    />
  )
}

export default Sf6Trainer
