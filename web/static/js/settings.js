// ─── Modal (แทน prompt() ที่ browser บล็อก) ──────────────────────────────────
let _modalResolve = null;

function showPrompt(title, placeholder = '') {
  return new Promise(resolve => {
    _modalResolve = resolve;
    const bg  = document.getElementById('modal-bg');
    const inp = document.getElementById('modal-input');
    document.getElementById('modal-title').textContent = title;
    inp.value = '';
    inp.placeholder = placeholder;
    bg.style.display = 'flex';
    setTimeout(() => inp.focus(), 50);
  });
}
function modalOK() {
  const val = document.getElementById('modal-input').value.trim();
  document.getElementById('modal-bg').style.display = 'none';
  if (_modalResolve) { _modalResolve(val || null); _modalResolve = null; }
}
function modalCancel() {
  document.getElementById('modal-bg').style.display = 'none';
  if (_modalResolve) { _modalResolve(null); _modalResolve = null; }
}

const PROVIDERS = {
  deepseek:   { url: 'https://api.deepseek.com/v1/chat/completions',       model: 'deepseek-chat' },
  openai:     { url: 'https://api.openai.com/v1/chat/completions',         model: 'gpt-4o' },
  groq:       { url: 'https://api.groq.com/openai/v1/chat/completions',    model: 'llama3-70b-8192' },
  openrouter: { url: 'https://openrouter.ai/api/v1/chat/completions',      model: 'auto' },
  mistral:    { url: 'https://api.mistral.ai/v1/chat/completions',         model: 'mistral-large-latest' },
  together:   { url: 'https://api.together.xyz/v1/chat/completions',       model: 'meta-llama/Llama-3-70b-chat-hf' },
  ollama:     { url: 'http://localhost:11434/v1/chat/completions',          model: 'llama3:8b' },
};

// Auto-detect provider from API key prefix
function detectFromKey(key) {
  if (key.startsWith('gsk_'))    return 'groq';
  if (key.startsWith('sk-or-'))  return 'openrouter';
  if (key.startsWith('ds-'))     return 'deepseek';
  return null;
}

// ─── Switch mode card ─────────────────────────────────────────────────────────
function setMode(slot, mode) {
  document.getElementById(`${slot}-card-key`).classList.toggle('active', mode === 'key');
  document.getElementById(`${slot}-card-url`).classList.toggle('active', mode === 'url');
  document.getElementById(`${slot}-fields-key`).classList.toggle('show', mode === 'key');
  document.getElementById(`${slot}-fields-url`).classList.toggle('show', mode === 'url');
}

// ─── Key input → auto-select provider ────────────────────────────────────────
function onKey(slot) {
  const key  = document.getElementById(`${slot}-key`).value.trim();
  const prov = detectFromKey(key);
  if (prov) {
    document.getElementById(`${slot}-prov`).value = prov;
    onProv(slot);
  }
}

// ─── Provider changed → fill URL ─────────────────────────────────────────────
function onProv(slot) {
  const prov  = document.getElementById(`${slot}-prov`).value;
  const urlEl = document.getElementById(`${slot}-url-auto`);
  const p     = PROVIDERS[prov];
  if (p) {
    urlEl.value = p.url;
    const mEl = document.getElementById(`${slot}-model-k`);
    if (!mEl.value) mEl.placeholder = `default: ${p.model}`;
  } else {
    urlEl.value = '';
  }
}

// ─── Key Vault (แยก Primary / Secondary) ─────────────────────────────────────
const slotKeys = { pri: [], sec: [] };
const slotName = { pri: 'primary', sec: 'secondary' };

async function loadKeys(slot) {
  const apiSlot = slotName[slot];
  try {
    const res  = await fetch(`/api/keys?slot=${apiSlot}`);
    const data = await res.json();
    slotKeys[slot] = data.keys || [];
    const sel = document.getElementById(`${slot}-vault`);
    if (!sel) return;
    const cur = sel.value;
    sel.innerHTML = '<option value="">📂 Load saved key…</option>';
    slotKeys[slot].forEach(k => {
      const opt = document.createElement('option');
      opt.value = k.name;
      opt.textContent = `${k.name}  (${k.provider || 'custom'})`;
      sel.appendChild(opt);
    });
    if (cur) sel.value = cur;
  } catch(e) { console.warn('loadKeys:', e); }
}

function onVaultSelect(slot, name) {
  const k = slotKeys[slot].find(k => k.name === name);
  const hasSel = !!name;
  document.getElementById(`${slot}-vault-ren`).disabled = !hasSel;
  document.getElementById(`${slot}-vault-del`).disabled = !hasSel;
  if (!k) return;
  const isKey = document.getElementById(`${slot}-fields-key`).classList.contains('show');
  if (isKey) {
    document.getElementById(`${slot}-key`).value = k.api_key || '';
    if (k.provider && PROVIDERS[k.provider]) {
      document.getElementById(`${slot}-prov`).value = k.provider;
      onProv(slot);
    }
    if (k.model) document.getElementById(`${slot}-model-k`).value = k.model;
  } else {
    document.getElementById(`${slot}-url-c`).value = k.url || '';
    document.getElementById(`${slot}-key-c`).value = k.api_key || '';
    if (k.model) document.getElementById(`${slot}-model-u`).value = k.model;
  }
}

async function saveKey(slot) {
  const isKey = document.getElementById(`${slot}-fields-key`).classList.contains('show');
  let apiKey, url, prov, model;

  if (isKey) {
    prov   = document.getElementById(`${slot}-prov`).value;
    apiKey = document.getElementById(`${slot}-key`).value.trim();
    // ดึงค่าจากช่อง auto แม้จะ disabled
    url    = document.getElementById(`${slot}-url-auto`).value.trim();
    if (!url && prov && PROVIDERS[prov]) url = PROVIDERS[prov].url;
    model  = document.getElementById(`${slot}-model-k`).value.trim();
  } else {
    url    = document.getElementById(`${slot}-url-c`).value.trim();
    apiKey = document.getElementById(`${slot}-key-c`).value.trim();
    prov   = '';
    model  = document.getElementById(`${slot}-model-u`).value.trim();
  }

  if (!url && !apiKey && !prov) {
    alert('Please fill in API Key or URL before saving.');
    return;
  }
  
  const name = await showPrompt('Save key as:', 'My Key Name');
  if (!name) return;
  
  const res  = await fetch('/api/keys/save', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ name: name.trim(), slot: slotName[slot], provider: prov, url, api_key: apiKey, model }),
  });
  const data = await res.json();
  if (data.ok) {
    await loadKeys(slot);
    document.getElementById(`${slot}-vault`).value = name.trim();
    onVaultSelect(slot, name.trim());
  } else { alert(data.error || 'Failed to save'); }
}

async function renameKey(slot) {
  const sel     = document.getElementById(`${slot}-vault`);
  const oldName = sel?.value;
  if (!oldName) return;
  const newName = await showPrompt(`Rename "${oldName}" to:`, oldName);
  if (!newName || newName === oldName) return;
  const res  = await fetch('/api/keys/rename', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ old: oldName, new: newName.trim(), slot: slotName[slot] }),
  });
  const data = await res.json();
  if (data.ok) {
    await loadKeys(slot);
    document.getElementById(`${slot}-vault`).value = newName.trim();
  } else { alert(data.error || 'Failed to rename'); }
}

async function deleteKey(slot) {
  const sel  = document.getElementById(`${slot}-vault`);
  const name = sel?.value;
  if (!name || !confirm(`Delete saved key "${name}"?`)) return;
  const res  = await fetch('/api/keys/delete', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ name, slot: slotName[slot] }),
  });
  if ((await res.json()).ok) {
    await loadKeys(slot);
    document.getElementById(`${slot}-vault-ren`).disabled = true;
    document.getElementById(`${slot}-vault-del`).disabled = true;
  }
}

// ─── Campaigns ────────────────────────────────────────────────────────────────
let selectedCampaign = null;

async function loadCampaigns() {
  try {
    const res  = await fetch('/api/campaigns');
    const data = await res.json();
    renderCampaigns(data);
  } catch (e) {
    document.getElementById('camp-list').innerHTML =
      '<div class="camp-empty">Could not load campaigns.</div>';
  }
}

function renderCampaigns(data) {
  const list = document.getElementById('camp-list');
  const usage = document.getElementById('db-usage');

  if (!data.campaigns || data.campaigns.length === 0) {
    list.innerHTML = '<div class="camp-empty">No campaigns yet. Click "+ Create New" to start.</div>';
  } else {
    list.innerHTML = data.campaigns.map(c => {
      const meta = `${c.turns} turns, ${c.size_mb} MB`;
      const sel  = c.active || selectedCampaign === c.name;
      if (sel && !selectedCampaign) selectedCampaign = c.name;
      return `
        <div class="camp-item ${sel ? 'selected' : ''}" onclick="selectCampaign('${c.name}', this)">
          <input type="radio" name="campaign" value="${c.name}" ${sel ? 'checked' : ''}>
          <span class="camp-name">${c.name}</span>
          <span class="camp-meta">${meta}</span>
        </div>`;
    }).join('');
  }

  usage.innerHTML =
    `<span><b>${data.count}</b> campaigns</span>` +
    `<span>Total: <b>${data.total_mb} MB</b></span>` +
    `<span>Free space: <b>${data.free_gb} GB</b></span>`;

  updateCampButtons();
}

function selectCampaign(name, el) {
  selectedCampaign = name;
  document.querySelectorAll('.camp-item').forEach(i => i.classList.remove('selected'));
  document.querySelectorAll('.camp-item input[type=radio]').forEach(r => r.checked = false);
  el.classList.add('selected');
  el.querySelector('input[type=radio]').checked = true;
  updateCampButtons();
}

function updateCampButtons() {
  const hasSel = !!selectedCampaign;
  document.getElementById('btn-rename').disabled = !hasSel;
  document.getElementById('btn-reset').disabled  = !hasSel;
  document.getElementById('btn-delete').disabled = !hasSel;
}

async function campReset() {
  if (!selectedCampaign) return;
  if (!confirm(`Reset campaign "${selectedCampaign}"?\n\nAll turns, history, and game data will be cleared.\nThe campaign folder will be kept.`)) return;
  if (!confirm(`⚠️ Final confirmation\n\nAll data in "${selectedCampaign}" will be permanently deleted.\n\nClick OK to reset.`)) return;
  const res  = await fetch('/api/campaigns/reset', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ name: selectedCampaign }),
  });
  if ((await res.json()).ok) {
    await loadCampaigns();
  }
}

async function campCreate() {
  const name = await showPrompt('Campaign name:', 'My Campaign');
  if (!name) return;
  const res  = await fetch('/api/campaigns/create', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ name: name.trim() }),
  });
  const data = await res.json();
  if (data.ok) {
    selectedCampaign = name.trim();
    await loadCampaigns();
  } else {
    alert(data.error || 'Failed to create campaign');
  }
}

async function campRename() {
  if (!selectedCampaign) return;
  const newName = await showPrompt(`Rename "${selectedCampaign}" to:`, selectedCampaign);
  if (!newName || newName === selectedCampaign) return;
  const res  = await fetch('/api/campaigns/rename', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ old: selectedCampaign, new: newName.trim() }),
  });
  const data = await res.json();
  if (data.ok) {
    selectedCampaign = newName.trim();
    await loadCampaigns();
  } else {
    alert(data.error || 'Failed to rename');
  }
}

async function campDelete() {
  if (!selectedCampaign) return;
  if (!confirm(`Delete campaign "${selectedCampaign}"?\nThis cannot be undone.`)) return;
  const res  = await fetch('/api/campaigns/delete', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ name: selectedCampaign }),
  });
  const data = await res.json();
  if (data.ok) {
    selectedCampaign = null;
    await loadCampaigns();
  } else {
    alert(data.error || 'Failed to delete');
  }
}

// ─── Collect slot values ──────────────────────────────────────────────────────
function collect(slot) {
  const isKey = document.getElementById(`${slot}-fields-key`).classList.contains('show');
  if (isKey) {
    const prov = document.getElementById(`${slot}-prov`).value;
    return {
      url:   document.getElementById(`${slot}-url-auto`).value.trim(),
      key:   document.getElementById(`${slot}-key`).value.trim(),
      model: document.getElementById(`${slot}-model-k`).value.trim()
             || (PROVIDERS[prov]?.model ?? ''),
    };
  }
  return {
    url:   document.getElementById(`${slot}-url-c`).value.trim(),
    key:   document.getElementById(`${slot}-key-c`).value.trim(),
    model: document.getElementById(`${slot}-model-u`).value.trim(),
  };
}

// ─── Save + Start ─────────────────────────────────────────────────────────────
async function save() {
  const btn  = document.getElementById('btn-save');
  const stat = document.getElementById('status');
  const pri  = collect('pri');
  const sec  = collect('sec');

  if (!pri.url || !sec.url) {
    stat.textContent = '✗ URL missing — select a provider or switch to Custom URL';
    stat.className = 'status err';
    return;
  }

  btn.disabled = true; btn.textContent = 'Saving…';
  try {
    // 1. Save model + auto-save settings
    const r1 = await fetch('/api/save-settings', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        pri_url: pri.url, pri_key: pri.key, pri_model: pri.model,
        sec_url: sec.url, sec_key: sec.key, sec_model: sec.model,
        history_turns: document.getElementById('hist').value,
        as_enabled: document.getElementById('as-enabled').checked,
        as_turns:   document.getElementById('as-turns').value,
        as_keep:    document.getElementById('as-keep').value,
        ingame_date: document.getElementById('ingame-date').checked,
        web_lookup:  document.getElementById('web-lookup').checked,
      }),
    });
    if (!(await r1.json()).ok) throw new Error('Settings save failed');

    // 2. Set active campaign (if selected)
    if (selectedCampaign) {
      const r2 = await fetch('/api/campaigns/select', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: selectedCampaign }),
      });
      if (!(await r2.json()).ok) throw new Error('Campaign select failed');
    }

    stat.textContent = '✓ Saved!'; stat.className = 'status ok';
    setTimeout(() => location.href = '/loading', 600);
  } catch (e) {
    stat.textContent = `✗ ${e.message}`; stat.className = 'status err';
    btn.disabled = false; btn.textContent = 'Start Game →';
  }
}

// ─── Init ─────────────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
  loadKeys('pri');
  loadKeys('sec');
  loadCampaigns();
});
