// Loading page — SSE progress
const icons = { pending:'○', loading:'<span class="spinner"></span>', ok:'✓', fail:'✗' };

function setStep(id, state, label) {
  const el = document.getElementById(`step-${id}`);
  if (!el) return;
  const icon = el.querySelector('.icon');
  icon.innerHTML = icons[state] || icons.pending;
  if (label) el.childNodes[1].textContent = ' ' + label;
  el.className = state === 'ok' ? 'done' : state === 'fail' ? 'fail' : '';
}

function setProgress(pct) {
  document.getElementById('pbar').style.width = pct + '%';
}

window.addEventListener('DOMContentLoaded', () => {
  // Set all steps to pending
  ['config','providers','prompts','auditor','narrator','database'].forEach(s => setStep(s, 'pending'));

  const src = new EventSource('/api/check');
  let currentStep = null;

  src.onmessage = e => {
    const data = JSON.parse(e.data);

    if (currentStep) setStep(currentStep, 'pending');

    if (data.step === 'done') {
      src.close();
      // Show provider info
      const infoRow = document.getElementById('info-row');
      infoRow.style.visibility = 'visible';
      document.getElementById('info-pri').textContent = `Narrator: ${data.pri.name} · ${data.pri.model}`;
      document.getElementById('info-sec').textContent = `Auditor: ${data.sec.name} · ${data.sec.model}`;
      // Show ready
      const ready = document.getElementById('ready-msg');
      ready.style.display = 'block';
      setTimeout(() => location.href = `/game`, 1200);
      return;
    }

    setStep(data.step, data.ok ? 'ok' : 'fail', data.label);
    setProgress(data.pct);

    // Show spinner on next step
    const order = ['config','providers','prompts','auditor','narrator','database'];
    const idx   = order.indexOf(data.step);
    if (idx + 1 < order.length) {
      currentStep = order[idx + 1];
      setStep(currentStep, 'loading');
    }
  };

  src.onerror = () => {
    src.close();
    document.getElementById('ready-msg').textContent = '✗ Connection error. Check server.';
    document.getElementById('ready-msg').style.display = 'block';
    document.getElementById('ready-msg').style.color = '#f87171';
    document.getElementById('ready-msg').style.animation = 'none';
  };
});
