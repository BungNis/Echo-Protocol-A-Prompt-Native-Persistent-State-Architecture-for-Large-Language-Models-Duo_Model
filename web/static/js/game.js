// Game page logic
const chat    = document.getElementById('chat');
const input   = document.getElementById('input');
const btnSend = document.getElementById('btn-send');
const btnUndo = document.getElementById('btn-undo');
let busy = false;
let undoLeft = 0;

function setUndoBtn() {
  if (btnUndo) btnUndo.disabled = busy || undoLeft <= 0;
}

// ─── Stats ───────────────────────────────────────────────────────────────────
function renderPips(containerId, value) {
  const el = document.getElementById(containerId);
  if (!el) return;
  const pips = Math.round(value / 10);
  el.innerHTML = Array.from({length:10}, (_,i) =>
    `<div class="stat-pip${i < pips ? ' filled' : ''}"></div>`
  ).join('');
}

function updateStats(s) {
  if (!s) return;
  const set = (id, val) => { const el=document.getElementById(id); if(el) el.textContent=val; };
  set('s-turn',     s.turn);
  set('s-hp',       s.hp);
  set('s-st',       s.stamina);
  set('s-mn',       s.mental);
  set('s-loc',      s.location || '—');
  set('s-laws',     s.laws);
  set('s-gdate',    s.gdate || '—');
  set('s-gtime',    s.gtime || '');
  set('s-items',    s.items);
  set('s-currency', s.currency);
  renderPips('s-hp-bar', s.hp);
  renderPips('s-st-bar', s.stamina);
  renderPips('s-mn-bar', s.mental);
  // PC name (hide chip + separator when empty)
  const pcEl = document.getElementById('s-pc');
  if (pcEl) {
    const has = !!s.pc;
    pcEl.textContent = s.pc || '';
    const w = document.getElementById('s-pc-wrap'), sep = document.getElementById('s-pc-sep');
    if (w)   w.style.display   = has ? '' : 'none';
    if (sep) sep.style.display = has ? '' : 'none';
  }
  // Status effects (hide when none)
  const fxEl = document.getElementById('s-fx'), fxWrap = document.getElementById('s-fx-wrap');
  if (fxEl) {
    const fx = (s.fx && s.fx !== 'none') ? s.fx : '';
    fxEl.textContent = fx.replace(/\|/g, ', ');
    if (fxWrap) fxWrap.style.display = fx ? '' : 'none';
  }
  if (typeof s.undo === 'number') { undoLeft = s.undo; setUndoBtn(); }
}

// ─── Tracker drawer ───────────────────────────────────────────────────────────
function trackerOpen() {
  const p = document.getElementById('tracker-panel');
  return p && p.classList.contains('open');
}

function toggleTracker() {
  const p = document.getElementById('tracker-panel'), o = document.getElementById('tracker-overlay');
  if (!p) return;
  const open = p.classList.toggle('open');
  if (o) o.classList.toggle('open', open);
  if (open) loadTracker();
}

async function loadTracker() {
  const body = document.getElementById('tracker-body');
  if (!body) return;
  body.innerHTML = '<div class="tk-empty">กำลังโหลด…</div>';
  const row = (k, v) => v ? `<div class="tk-row"><span class="tk-k">${k}</span><span class="tk-v">${escapeHtml(String(v))}</span></div>` : '';
  const list = v => Array.isArray(v) ? v.filter(Boolean).join(' / ') : (v || '');
  const clean = v => (v && v !== 'none') ? v : '';
  try {
    const d = await (await fetch('/api/tracker')).json();
    if (d.empty) { body.innerHTML = '<div class="tk-empty">ยังไม่มีเทิร์น</div>'; return; }
    const x = d.decoded || {}, sm = d.summary || {};
    let h = `<div class="tk-turn">เทิร์น ${d.turn}</div>`;
    h += row('📅 วัน', x.date) + row('🕐 เวลา', x.time) + row('📍 ที่อยู่', x.location);
    h += row('❤ HP', x.hp) + row('⚡ ST', x.stamina) + row('🧠 MN', x.mental);
    h += row('✨ สถานะ', clean(x.fx)) + row('🎒 ของ', clean(x.inventory));
    h += row('👥 NPC', clean(x.npcs)) + row('⚖ กฎ', clean(x.laws));
    h += row('🔒 Chk', x.chk) + row('⚠ E', x.error);
    let s = row('การกระทำ', sm.player_action) + row('บทพูด', list(sm.key_dialogue))
          + row('โลกเปลี่ยน', list(sm.world_changes)) + row('ความรู้ใหม่', list(sm.new_knowledge))
          + row('โน้ต', sm.important_notes);
    if (s) h += `<div class="tk-sec">สรุปเทิร์น</div>${s}`;
    h += `<div class="tk-sec">สตริงดิบ</div><pre class="tk-raw">${escapeHtml(d.raw || '')}</pre>`;
    body.innerHTML = h;
  } catch (e) {
    body.innerHTML = `<div class="tk-empty">โหลดไม่ได้: ${e.message}</div>`;
  }
}

// ─── Render restored turns into the chat ─────────────────────────────────────
function renderTurns(turns) {
  turns.forEach(t => {
    if (t.player)   addMsg('user', t.player);
    if (t.narrator) addMsg('ai', t.narrator);
  });
}

// ─── Markdown (small built-in renderer, offline, no deps) ─────────────────────
function escapeHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function mdInline(s) {                 // s is already HTML-escaped
  return s
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/__([^_]+)__/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>')
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
}

function mdToHtml(text) {
  const lines = escapeHtml(text).split('\n');
  let html = '', listType = null, inQuote = false;
  const closeList  = () => { if (listType) { html += `</${listType}>`; listType = null; } };
  const closeQuote = () => { if (inQuote) { html += '</blockquote>'; inQuote = false; } };
  for (const line of lines) {
    if (/^\s*([-*_])\1{2,}\s*$/.test(line)) { closeList(); closeQuote(); html += '<hr>'; continue; }
    const h = line.match(/^\s*(#{1,6})\s+(.*)$/);
    if (h) { closeList(); closeQuote(); const lv = h[1].length; html += `<h${lv}>${mdInline(h[2])}</h${lv}>`; continue; }
    const q = line.match(/^\s*&gt;\s?(.*)$/);   // '>' was HTML-escaped to '&gt;' above
    if (q) { closeList(); if (!inQuote) { html += '<blockquote>'; inQuote = true; } html += mdInline(q[1]) + '<br>'; continue; }
    closeQuote();
    const ul = line.match(/^\s*[-*+]\s+(.*)$/);
    if (ul) { if (listType !== 'ul') { closeList(); html += '<ul>'; listType = 'ul'; } html += `<li>${mdInline(ul[1])}</li>`; continue; }
    const ol = line.match(/^\s*\d+\.\s+(.*)$/);
    if (ol) { if (listType !== 'ol') { closeList(); html += '<ol>'; listType = 'ol'; } html += `<li>${mdInline(ol[1])}</li>`; continue; }
    closeList();
    if (/^\s*$/.test(line)) { html += '<br>'; continue; }
    html += mdInline(line) + '<br>';
  }
  closeList(); closeQuote();
  return html.replace(/(<br>)+$/, '');
}

// ─── Message Rendering ────────────────────────────────────────────────────────
function addMsg(role, text) {
  const wrap  = document.createElement('div');
  wrap.className = `msg ${role}`;
  const label  = document.createElement('div');
  label.className = 'msg-label';
  label.textContent = role === 'ai' ? 'Narrator' : 'You';
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  if (role === 'ai') { bubble._raw = text || ''; bubble.innerHTML = mdToHtml(bubble._raw); }
  else               { bubble.textContent = text; }   // user input stays plain (safe)
  wrap.appendChild(label);
  wrap.appendChild(bubble);
  chat.appendChild(wrap);
  scrollBottom();
  return bubble;
}

function addSystem(text, cls = '') {
  const el = document.createElement('div');
  el.className = `system-msg ${cls}`;
  el.textContent = text;
  chat.appendChild(el);
  scrollBottom();
  return el;
}

function addTyping() {
  const el = document.createElement('div');
  el.className = 'typing';
  el.id = 'typing-indicator';
  el.innerHTML = '<div class="typing-dots"><span></span><span></span><span></span></div><span>Narrator is writing…</span>';
  chat.appendChild(el);
  scrollBottom();
  return el;
}

function removeTyping() {
  const el = document.getElementById('typing-indicator');
  if (el) el.remove();
}

function scrollBottom() {
  chat.scrollTop = chat.scrollHeight;
}

// ─── Send Message ─────────────────────────────────────────────────────────────
async function sendMessage() {
  const text = input.value.trim();
  if (!text || busy) return;

  busy = true;
  input.disabled = true;
  btnSend.disabled = true;
  setUndoBtn();
  input.value = '';
  input.style.height = '42px';

  addMsg('user', text);

  let aiBubble = null;
  let typing   = null;

  const src = new EventSource('/api/send');
  // Use POST with fetch for body, but SSE needs GET…
  // We use a workaround: POST first, then connect SSE
  // Simpler: use fetch with ReadableStream

  src.close(); // Not using EventSource for POST — use fetch stream instead

  try {
    const res = await fetch('/api/send', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({input: text}),
    });

    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, {stream: true});

      const lines = buffer.split('\n');
      buffer = lines.pop();

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        let data;
        try { data = JSON.parse(line.slice(6)); } catch { continue; }

        if (data.type === 'auditor_start') {
          const el = addSystem(`⚙ Turn ${data.turn} — Auditor processing…`);
          el.id = 'auditor-status';
        }
        else if (data.type === 'auditor_ok') {
          const s = document.getElementById('auditor-status');
          if (s) s.remove();
          if (data.new_law) {
            addSystem(`⚖ New law: ${data.new_law.law_name || data.new_law.law_id}`, 'law');
          }
          typing = addTyping();
        }
        else if (data.type === 'auditor_fail') {
          const s = document.getElementById('auditor-status');
          if (s) s.remove();
          addSystem('⚠ Auditor offline — fallback mode', 'fail');
          typing = addTyping();
        }
        else if (data.type === 'narrator_chunk') {
          if (typing) { removeTyping(); typing = null; }
          if (!aiBubble) aiBubble = addMsg('ai', '');
          aiBubble._raw = (aiBubble._raw || '') + data.text;
          aiBubble.innerHTML = mdToHtml(aiBubble._raw);
          scrollBottom();
        }
        else if (data.type === 'done') {
          removeTyping();
          updateStats(data.stats);
          if (trackerOpen()) loadTracker();
        }
      }
    }
  } catch(e) {
    removeTyping();
    addSystem(`✗ Error: ${e.message}`, 'fail');
  }

  busy = false;
  input.disabled = false;
  btnSend.disabled = false;
  setUndoBtn();
  input.focus();
}

// ─── Undo / Rewind ────────────────────────────────────────────────────────────
async function undoTurn() {
  if (busy || undoLeft <= 0) return;
  if (!confirm('ย้อนกลับ 1 เทิร์น? เทิร์นล่าสุดจะถูกลบถาวร (กดซ้ำเพื่อย้อนต่อได้)')) return;

  busy = true;
  btnSend.disabled = true;
  setUndoBtn();
  try {
    const res  = await fetch('/api/undo', { method: 'POST' });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || 'undo failed');
    chat.innerHTML = '';
    addSystem(`↩ ย้อนเทิร์น ${data.undone_turn} แล้ว — เหลือย้อนได้ ${data.undo_left} เทิร์น`);
    renderTurns(data.turns || []);
    updateStats(data.stats);
    if (trackerOpen()) loadTracker();
  } catch (e) {
    addSystem(`✗ ย้อนไม่ได้: ${e.message}`, 'fail');
  }
  busy = false;
  input.disabled = false;
  btnSend.disabled = false;
  setUndoBtn();
  input.focus();
}

// ─── Input Handling ───────────────────────────────────────────────────────────
input.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

input.addEventListener('input', () => {
  input.style.height = '42px';
  input.style.height = Math.min(input.scrollHeight, 120) + 'px';
});

document.addEventListener('keydown', e => {           // Esc closes the tracker drawer
  if (e.key === 'Escape' && trackerOpen()) toggleTracker();
});

// ─── Init ─────────────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', async () => {
  updateStats(STATS);

  // Load today's history
  try {
    const res  = await fetch('/api/history');
    const data = await res.json();
    if (data.turns && data.turns.length > 0) {
      addSystem('— Session restored —');
      data.turns.forEach(t => {
        if (t.player)   addMsg('user', t.player);
        if (t.narrator) addMsg('ai', t.narrator);
      });
    } else {
      addSystem('— New session — Type to begin —');
    }
  } catch(e) {
    addSystem('— Ready —');
  }

  input.focus();
});
