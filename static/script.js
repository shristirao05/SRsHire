// SRsHire — script.js (final fixed version)

let pollInterval = null;
let currentJobId = null;
let lastLogCount = 0;

// ── Show / Hide helpers ───────────────────────────────────────────────────────

function show(id, displayType) {
  document.getElementById(id).style.display = displayType || 'block';
}

function hide(id) {
  document.getElementById(id).style.display = 'none';
}

// ── Folder browser ────────────────────────────────────────────────────────────

async function browseFolder(targetId) {
  try {
    const res = await fetch('/api/browse-folder');
    const data = await res.json();
    if (data.path) {
      document.getElementById(targetId).value = data.path;
      if (targetId === 'input_folder') {
        scanFolder(data.path);
      }
    }
  } catch (e) {
    console.error('Browse error:', e);
  }
}

// ── Scan folder ───────────────────────────────────────────────────────────────

async function scanFolder(folderPath) {
  hide('file-count-badge');
  if (!folderPath) return;
  try {
    const res  = await fetch('/api/scan-folder', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder_path: folderPath }),
    });
    const data = await res.json();
    if (data.count !== undefined) {
      show('file-count-badge', 'flex');
      const text = document.getElementById('file-count-text');
      const badge = document.getElementById('file-count-badge');
      if (data.count === 0) {
        text.textContent = 'No PDF files found in this folder.';
        badge.style.background = '#FEF2F2';
        badge.style.color = '#DC2626';
        badge.style.borderColor = '#FECACA';
      } else {
        text.textContent = `${data.count} PDF file${data.count > 1 ? 's' : ''} found — ready to screen.`;
        badge.style.background = '';
        badge.style.color = '';
        badge.style.borderColor = '';
      }
    }
  } catch (e) {
    console.error('Scan error:', e);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  const f = document.getElementById('input_folder');
  if (!f) return;
  f.addEventListener('change', () => { if (f.value) scanFolder(f.value); });
  f.addEventListener('paste', () => {
    // value isn't updated yet at 'paste' time, so wait a tick
    setTimeout(() => { if (f.value) scanFolder(f.value); }, 0);
  });
});

// ── Job role validation ───────────────────────────────────────────────────────

async function validateRole(roleText) {
  if (!roleText.trim()) { hide('role-feedback'); return { valid: null }; }
  try {
    const res  = await fetch('/api/validate-role', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_role: roleText }),
    });
    const data = await res.json();
    const fb = document.getElementById('role-feedback');
    show('role-feedback');
    if (data.valid) {
      fb.className = 'role-feedback success';
      fb.textContent = `✔ Understood as: "${data.corrected_role}"`;
    } else {
      fb.className = 'role-feedback error';
      fb.textContent = `✘ ${data.message}`;
    }
    return data;
  } catch (e) {
    return { valid: true };
  }
}

document.addEventListener('DOMContentLoaded', () => {
  const r = document.getElementById('job_role');
  if (r) r.addEventListener('blur', () => { if (r.value.trim()) validateRole(r.value); });
});

// ── Popup ─────────────────────────────────────────────────────────────────────

function showPopup(message) {
  document.getElementById('popup-message').textContent = message;
  document.getElementById('popup-input').value = '';
  show('popup-overlay', 'flex');
  setTimeout(() => document.getElementById('popup-input').focus(), 100);
}

function closePopup() {
  hide('popup-overlay');
}

async function retryRole() {
  const newRole = document.getElementById('popup-input').value.trim();
  if (!newRole) {
    document.getElementById('popup-input').style.borderColor = '#DC2626';
    return;
  }
  document.getElementById('popup-input').style.borderColor = '';
  const result = await validateRole(newRole);
  if (result.valid) {
    document.getElementById('job_role').value = newRole;
    closePopup();
    startScreening();
  } else {
    document.getElementById('popup-message').textContent =
      result.message || 'Still not recognised. Please try again.';
  }
}

document.addEventListener('DOMContentLoaded', () => {
  const pi = document.getElementById('popup-input');
  if (pi) pi.addEventListener('keydown', (e) => { if (e.key === 'Enter') retryRole(); });
});

// ── Form submission ───────────────────────────────────────────────────────────

async function startScreening() {
  closePopup();

  const inputFolder      = document.getElementById('input_folder').value.trim();
  const jobRole          = document.getElementById('job_role').value.trim();
  const compulsorySkills = document.getElementById('compulsory_skills').value.trim();
  const outputFolder     = document.getElementById('output_folder').value.trim();
  const errorEl          = document.getElementById('error-msg');
  const submitBtn        = document.getElementById('submit-btn');

  errorEl.textContent = '';

  // Check all required fields FIRST — no API calls until all filled
  if (!inputFolder) {
    errorEl.textContent = '⚠ Please select the Resume Folder.';
    return;
  }
  if (!jobRole) {
    errorEl.textContent = '⚠ Please enter the Job Role.';
    return;
  }
  if (!outputFolder) {
    errorEl.textContent = '⚠ Please select the Output Folder.';
    return;
  }

  // All fields filled — now validate job role
  submitBtn.disabled = true;
  submitBtn.textContent = 'Validating job role…';

  let validation;
  try {
    const res = await fetch('/api/validate-role', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_role: jobRole }),
    });
    validation = await res.json();
  } catch (e) {
    validation = { valid: true };
  }

  if (validation.valid === false) {
    submitBtn.disabled = false;
    submitBtn.innerHTML = '<span class="btn-icon">🔍</span> Start Screening';
    showPopup(validation.message || 'Job role not recognised. Please rewrite it clearly.');
    return;
  }

  // Submit to backend
  submitBtn.textContent = 'Starting…';
  try {
    const res  = await fetch('/api/process', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        input_folder:      inputFolder,
        output_folder:     outputFolder,
        job_role:          jobRole,
        compulsory_skills: compulsorySkills,
      }),
    });
    const data = await res.json();
    if (!res.ok || data.error) {
      errorEl.textContent = data.error || 'Something went wrong.';
      submitBtn.disabled = false;
      submitBtn.innerHTML = '<span class="btn-icon">🔍</span> Start Screening';
      return;
    }
    currentJobId = data.job_id;
    lastLogCount = 0;
    showProgress();
    startPolling();
  } catch (e) {
    errorEl.textContent = 'Could not connect to server.';
    submitBtn.disabled = false;
    submitBtn.innerHTML = '<span class="btn-icon">🔍</span> Start Screening';
  }
}

// ── Progress ──────────────────────────────────────────────────────────────────

function showProgress() {
  hide('form-card');
  show('progress-card');
  hide('done-card');
}

function startPolling() {
  if (pollInterval) clearInterval(pollInterval);
  pollInterval = setInterval(pollStatus, 2000);
}

async function pollStatus() {
  if (!currentJobId) return;
  try {
    const res  = await fetch(`/api/status/${currentJobId}`);
    const data = await res.json();

    if (data.corrected_role) {
      document.getElementById('role-pill').textContent = `Screening for: ${data.corrected_role}`;
    }

    const total   = data.total   || 0;
    const current = data.current || 0;
    const pct     = total > 0 ? Math.round((current / total) * 100) : 0;
    document.getElementById('progress-fill').style.width = pct + '%';
    document.getElementById('progress-label').textContent =
      total > 0 ? `Processing ${current} of ${total}: ${data.current_file || ''}` : 'Starting…';

    const consoleEl = document.getElementById('console');
    const logs = data.log || [];
    for (let i = lastLogCount; i < logs.length; i++) {
      const line = logs[i];
      const div  = document.createElement('div');
      if (line.includes('✔') || line.includes('Shortlisted')) div.className = 'log-success';
      else if (line.includes('✘') || line.includes('ERROR'))   div.className = 'log-error';
      else if (line.includes('Found') || line.includes('confirmed')) div.className = 'log-info';
      div.textContent = line;
      consoleEl.appendChild(div);
    }
    lastLogCount = logs.length;
    consoleEl.scrollTop = consoleEl.scrollHeight;

    if (data.status === 'invalid_role') {
      clearInterval(pollInterval);
      show('form-card');
      hide('progress-card');
      const btn = document.getElementById('submit-btn');
      btn.disabled = false;
      btn.innerHTML = '<span class="btn-icon">🔍</span> Start Screening';
      showPopup(data.error || 'Job role not recognised.');
      return;
    }

    if (data.status === 'error') {
      clearInterval(pollInterval);
      show('form-card');
      hide('progress-card');
      document.getElementById('error-msg').textContent = data.error || 'An error occurred.';
      const btn = document.getElementById('submit-btn');
      btn.disabled = false;
      btn.innerHTML = '<span class="btn-icon">🔍</span> Start Screening';
      return;
    }

    if (data.status === 'done') {
      clearInterval(pollInterval);
      document.getElementById('progress-fill').style.width = '100%';
      setTimeout(() => showResults(data), 600);
    }
  } catch (e) {
    console.error('Poll error:', e);
  }
}

// ── Results ───────────────────────────────────────────────────────────────────

function showResults(data) {
  hide('progress-card');
  show('done-card');

  const shortlisted = data.shortlisted || [];
  const rejected    = data.rejected    || [];
  const total       = data.total || (shortlisted.length + rejected.length);

  document.getElementById('done-summary').textContent =
    `Screened ${total} resume${total !== 1 ? 's' : ''}. Shortlisted: ${shortlisted.length} | Not selected: ${rejected.length}`;

  const sBody = document.getElementById('shortlisted-body');
  sBody.innerHTML = '';
  if (shortlisted.length > 0) {
    show('shortlisted-section');
    shortlisted.forEach((c, i) => {
      const cls  = c.percentage >= 70 ? 'pct-high' : c.percentage >= 40 ? 'pct-mid' : 'pct-low';
      const safe = c.name.replace(/[<>:"/\\|?*]/g, '').trim();
      const tr   = document.createElement('tr');
      tr.innerHTML = `
        <td>${i + 1}</td>
        <td>${c.name}</td>
        <td><span class="pct-badge ${cls}">${c.percentage}%</span></td>
        <td style="font-size:0.8rem;color:#6B7A99">${safe}_${c.percentage}%.pdf</td>`;
      sBody.appendChild(tr);
    });
  } else {
    hide('shortlisted-section');
  }

  const rBody = document.getElementById('rejected-body');
  rBody.innerHTML = '';
  if (rejected.length > 0) {
    show('rejected-section');
    rejected.forEach((c, i) => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${i + 1}</td>
        <td>${c.name}</td>
        <td style="color:#6B7A99;font-size:0.82rem">${c.reason}</td>`;
      rBody.appendChild(tr);
    });
  } else {
    hide('rejected-section');
  }
}

// ── Reset ─────────────────────────────────────────────────────────────────────

function resetForm() {
  currentJobId = null;
  lastLogCount = 0;
  if (pollInterval) clearInterval(pollInterval);

  document.getElementById('input_folder').value      = '';
  document.getElementById('job_role').value           = '';
  document.getElementById('compulsory_skills').value  = '';
  document.getElementById('output_folder').value      = '';
  document.getElementById('error-msg').textContent    = '';
  document.getElementById('console').innerHTML        = '';
  document.getElementById('progress-fill').style.width = '0%';

  hide('file-count-badge');
  hide('role-feedback');

  const btn = document.getElementById('submit-btn');
  btn.disabled = false;
  btn.innerHTML = '<span class="btn-icon">🔍</span> Start Screening';

  show('form-card');
  hide('progress-card');
  hide('done-card');
}
