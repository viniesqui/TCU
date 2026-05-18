// TCU web UI — single-session, WebSocket-driven.
// State machine: input → pipeline → review → done | error
// Archive screen is reachable from input/done.

const screens = ['input', 'pipeline', 'review', 'done', 'error', 'archive'];

// Which sidebar nav item should highlight for each screen.
const SCREEN_TO_NAV = {
  input:    'input',
  pipeline: 'input',
  review:   'input',
  done:     'input',
  error:    'input',
  archive:  'archive',
};

function show(name) {
  for (const s of screens) {
    document.getElementById(`screen-${s}`).classList.toggle('active', s === name);
  }
  const navKey = SCREEN_TO_NAV[name];
  document.querySelectorAll('.nav-item[data-nav]').forEach(btn => {
    if (btn.dataset.nav === navKey) {
      btn.setAttribute('aria-current', 'page');
    } else {
      btn.removeAttribute('aria-current');
    }
  });
  // Move focus to main on screen change for keyboard / screen-reader users.
  const main = document.getElementById('main');
  if (main && document.activeElement && document.activeElement.tagName !== 'INPUT' && document.activeElement.tagName !== 'TEXTAREA') {
    main.focus({ preventScroll: true });
  }
}

// ────────────────────────────────────────────────────────────────────────
// Theme toggle (light / dark) persisted to localStorage
// ────────────────────────────────────────────────────────────────────────
const THEME_KEY = 'tcu-theme';

function currentTheme() {
  const explicit = document.documentElement.getAttribute('data-theme');
  if (explicit) return explicit;
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function setTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  try { localStorage.setItem(THEME_KEY, theme); } catch (e) { /* ignore */ }
}

document.getElementById('theme-toggle')?.addEventListener('click', () => {
  setTheme(currentTheme() === 'dark' ? 'light' : 'dark');
});

// ────────────────────────────────────────────────────────────────────────
// Sidebar nav
// ────────────────────────────────────────────────────────────────────────
document.querySelectorAll('.nav-item[data-nav]').forEach(btn => {
  btn.addEventListener('click', () => {
    const target = btn.dataset.nav;
    if (target === 'input') {
      show('input');
    } else if (target === 'archive') {
      openArchive();
    }
  });
});

const STAGE_KEYWORDS = {
  market:   ['mercado laboral'],
  academic: ['académica', 'universitaria'],
  gap:      ['brecha educativa', 'brecha'],
  course:   ['plan de estudios', 'cronograma'],
  eval:     ['evaluación', 'evaluacion'],
  report:   ['reporte html', 'reporte'],
};

let ws = null;
let currentGap = null;
let manualAdditions = [];

// ────────────────────────────────────────────────────────────────────────
// Start
// ────────────────────────────────────────────────────────────────────────
document.getElementById('form-start').addEventListener('submit', (e) => {
  e.preventDefault();
  const sector = document.getElementById('sector').value.trim();
  const reviewer = document.getElementById('reviewer').value.trim() || null;
  if (!sector) return;
  resetPipelineUI();
  show('pipeline');
  connectAndStart(sector, reviewer);
});

document.getElementById('btn-restart').addEventListener('click', () => location.reload());
document.getElementById('btn-restart-error').addEventListener('click', () => location.reload());

document.getElementById('open-archive').addEventListener('click', openArchive);
document.getElementById('btn-archive-back').addEventListener('click', () => show('input'));

function connectAndStart(sector, reviewer) {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(`${proto}//${location.host}/ws/run`);
  ws.addEventListener('open', () => {
    ws.send(JSON.stringify({ type: 'start', sector, reviewer }));
  });
  ws.addEventListener('message', (ev) => {
    const msg = JSON.parse(ev.data);
    handleMessage(msg);
  });
  ws.addEventListener('close', () => {
    appendLog('⊗ Conexión cerrada');
  });
  ws.addEventListener('error', (e) => {
    showError('Error de conexión WebSocket.');
  });
}

// ────────────────────────────────────────────────────────────────────────
// Message dispatch
// ────────────────────────────────────────────────────────────────────────
function handleMessage(msg) {
  switch (msg.type) {
    case 'stage_progress':
      updateStageFromMessage(msg.description);
      appendLog(msg.description);
      break;
    case 'review_request':
      onReviewRequest(msg.gap_analysis);
      break;
    case 'complete':
      onComplete(msg);
      break;
    case 'error':
      showError(msg.message);
      break;
  }
}

// ────────────────────────────────────────────────────────────────────────
// Pipeline UI
// ────────────────────────────────────────────────────────────────────────
function resetPipelineUI() {
  for (const li of document.querySelectorAll('#stage-list li')) {
    li.classList.remove('active', 'done');
    li.classList.add('pending');
    li.querySelector('.status').textContent = '';
  }
  document.getElementById('log').innerHTML = '';
  document.getElementById('current-status').textContent = 'Inicializando agentes…';
}

function updateStageFromMessage(desc) {
  document.getElementById('current-status').textContent = desc;
  const lower = desc.toLowerCase();
  let matched = null;
  for (const [stage, keywords] of Object.entries(STAGE_KEYWORDS)) {
    if (keywords.some(k => lower.includes(k))) {
      matched = stage;
      break;
    }
  }
  if (!matched) return;
  // Mark previous active stages as done.
  let beforeMatch = true;
  for (const li of document.querySelectorAll('#stage-list li')) {
    const stage = li.dataset.stage;
    if (stage === matched) {
      li.classList.remove('pending', 'done');
      li.classList.add('active');
      beforeMatch = false;
    } else if (beforeMatch) {
      li.classList.remove('pending', 'active');
      li.classList.add('done');
    }
  }
}

function appendLog(text) {
  const log = document.getElementById('log');
  const div = document.createElement('div');
  const now = new Date();
  const ts = `${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}:${String(now.getSeconds()).padStart(2,'0')}`;
  div.textContent = `[${ts}] ${text}`;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

// ────────────────────────────────────────────────────────────────────────
// Review screen
// ────────────────────────────────────────────────────────────────────────
function onReviewRequest(gap) {
  currentGap = gap;
  manualAdditions = [];

  // Mark gap stage done, mark review active
  const stages = document.querySelectorAll('#stage-list li');
  for (const li of stages) {
    if (li.dataset.stage === 'gap') { li.classList.remove('active','pending'); li.classList.add('done'); }
    if (li.dataset.stage === 'review') { li.classList.remove('pending','done'); li.classList.add('active'); }
  }

  renderReview(gap);
  show('review');
}

function renderReview(gap) {
  const critical = gap.critical_gaps || [];
  const moderate = gap.moderate_gaps || [];

  // Summary line
  document.getElementById('review-summary').innerHTML =
    `Sector: <strong>${escape(gap.sector)}</strong> &middot; ` +
    `<strong>${critical.length}</strong> brechas críticas &middot; ` +
    `<strong>${moderate.length}</strong> moderadas &middot; ` +
    `<strong>${(gap.well_covered || []).length}</strong> ya cubiertas`;

  renderSkillTable('critical-table', critical, 'c');
  renderSkillTable('moderate-table', moderate, 'm');

  document.getElementById('course-title').value = gap.proposed_course_title || '';
  document.getElementById('course-rationale').value = gap.proposed_course_rationale || '';
  document.getElementById('manual-list').innerHTML = '';
}

function renderSkillTable(tableId, skills, prefix) {
  const tbody = document.querySelector(`#${tableId} tbody`);
  tbody.innerHTML = '';
  if (!skills.length) {
    tbody.innerHTML = `<tr><td colspan="5" class="muted" style="padding:0.8rem; text-align:center;">— sin elementos —</td></tr>`;
    return;
  }
  skills.forEach((s, i) => {
    const id = `${prefix}${i}`;
    const tr = document.createElement('tr');
    tr.dataset.id = id;
    tr.innerHTML = `
      <td><input type="checkbox" data-id="${id}" checked></td>
      <td>${escape(s.skill_name)}</td>
      <td>${bar(s.market_demand_score, 'demand')}</td>
      <td>${bar(s.academic_coverage_score, 'coverage')}</td>
      <td>${escape(s.market_depth_required || 'intermedio')}</td>`;
    tbody.appendChild(tr);
  });
  tbody.querySelectorAll('input[type="checkbox"]').forEach(cb => {
    cb.addEventListener('change', () => {
      cb.closest('tr').classList.toggle('rejected', !cb.checked);
    });
  });
}

function bar(score, kind) {
  const pct = Math.round((score || 0) * 100);
  return `<div class="bar-cell">
    <div class="bar-track"><div class="bar-fill ${kind}" style="width:${pct}%"></div></div>
    <span class="bar-val">${score.toFixed(2)}</span>
  </div>`;
}

document.getElementById('btn-manual-add').addEventListener('click', () => {
  const name = document.getElementById('manual-name').value.trim();
  const depth = document.getElementById('manual-depth').value;
  if (!name) return;
  manualAdditions.push({ name, depth });
  renderManualList();
  document.getElementById('manual-name').value = '';
  document.getElementById('manual-name').focus();
});

function renderManualList() {
  const ul = document.getElementById('manual-list');
  ul.innerHTML = '';
  manualAdditions.forEach((m, idx) => {
    const li = document.createElement('li');
    li.innerHTML = `${escape(m.name)} <em style="opacity:0.85;">${escape(m.depth)}</em>
      <button type="button" data-idx="${idx}" aria-label="quitar">×</button>`;
    li.querySelector('button').addEventListener('click', () => {
      manualAdditions.splice(idx, 1);
      renderManualList();
    });
    ul.appendChild(li);
  });
}

document.getElementById('btn-accept').addEventListener('click', () => sendReviewResponse(false));
document.getElementById('btn-skip').addEventListener('click', () => sendReviewResponse(true));

function sendReviewResponse(skipped) {
  const acceptedIds = [];
  document.querySelectorAll('#screen-review input[type="checkbox"]').forEach(cb => {
    if (cb.checked) acceptedIds.push(cb.dataset.id);
  });
  const accepted = (currentGap.critical_gaps || []).filter((_, i) => acceptedIds.includes(`c${i}`)).length
    + (currentGap.moderate_gaps || []).filter((_, i) => acceptedIds.includes(`m${i}`)).length;
  const payload = skipped
    ? { skipped: true, audit: buildAudit({ skipped: true, accepted, manualCount: 0 }) }
    : {
        skipped: false,
        accepted_ids: acceptedIds,
        manual_additions: manualAdditions,
        proposed_course_title: document.getElementById('course-title').value.trim(),
        proposed_course_rationale: document.getElementById('course-rationale').value.trim(),
        audit: buildAudit({ skipped: false, accepted, manualCount: manualAdditions.length }),
      };
  ws.send(JSON.stringify({ type: 'review_response', payload }));

  // Mark review done, advance UI
  const stages = document.querySelectorAll('#stage-list li');
  for (const li of stages) {
    if (li.dataset.stage === 'review') { li.classList.remove('active'); li.classList.add('done'); }
  }
  show('pipeline');
}

function buildAudit({ skipped, accepted, manualCount }) {
  const reviewer = (document.getElementById('reviewer').value.trim()) || 'web-user';
  const acceptedNames = [];
  if (!skipped) {
    document.querySelectorAll('#screen-review input[type="checkbox"]:checked').forEach(cb => {
      const id = cb.dataset.id;
      const idx = parseInt(id.slice(1), 10);
      const bucket = id[0] === 'c' ? currentGap.critical_gaps : currentGap.moderate_gaps;
      if (bucket && bucket[idx]) acceptedNames.push(bucket[idx].skill_name);
    });
    manualAdditions.forEach(m => acceptedNames.push(m.name));
  } else {
    (currentGap.critical_gaps || []).forEach(s => acceptedNames.push(s.skill_name));
    (currentGap.moderate_gaps || []).forEach(s => acceptedNames.push(s.skill_name));
  }
  return {
    reviewer,
    reviewed_at: new Date().toISOString(),
    skipped,
    accepted_skills: acceptedNames,
    manual_additions: skipped ? [] : manualAdditions.map(m => ({ name: m.name, depth: m.depth })),
    proposed_course_title: skipped ? currentGap.proposed_course_title : document.getElementById('course-title').value.trim(),
  };
}

// ────────────────────────────────────────────────────────────────────────
// Completion
// ────────────────────────────────────────────────────────────────────────
function onComplete(msg) {
  // mark all stages done
  for (const li of document.querySelectorAll('#stage-list li')) {
    li.classList.remove('active', 'pending');
    li.classList.add('done');
  }
  const url = `/reports/${encodeURIComponent(msg.report_path)}`;
  document.getElementById('report-link').href = url;
  document.getElementById('report-frame').src = url;
  renderQualitySummary(msg.quality_scores || {});
  show('done');
}

const STAGE_LABELS = {
  market_research: 'Mercado laboral',
  academic_research: 'Oferta académica',
  gap_analysis: 'Análisis de brecha',
  curriculum: 'Plan de estudios',
  activities: 'Actividades',
  evaluator: 'Evaluación',
};

function renderQualitySummary(scores) {
  const container = document.getElementById('quality-summary');
  container.innerHTML = '';
  for (const [k, v] of Object.entries(scores)) {
    const pct = Math.round(v * 100);
    const cls = pct >= 75 ? 'good' : (pct >= 50 ? 'warn' : 'poor');
    const pill = document.createElement('span');
    pill.className = `quality-pill ${cls}`;
    pill.innerHTML = `${escape(STAGE_LABELS[k] || k)} <span class="pct">${pct}%</span>`;
    container.appendChild(pill);
  }
}

// ────────────────────────────────────────────────────────────────────────
// Errors
// ────────────────────────────────────────────────────────────────────────
function showError(text) {
  document.getElementById('error-message').textContent = text;
  show('error');
}

// ────────────────────────────────────────────────────────────────────────
// Archive
// ────────────────────────────────────────────────────────────────────────
async function openArchive() {
  show('archive');
  const ul = document.getElementById('archive-list');
  ul.innerHTML = '<li class="muted">Cargando…</li>';
  try {
    const res = await fetch('/api/reports');
    const data = await res.json();
    if (!data.reports.length) {
      ul.innerHTML = '<li class="muted">No hay reportes anteriores.</li>';
      return;
    }
    ul.innerHTML = '';
    data.reports.forEach(r => {
      const li = document.createElement('li');
      const dt = new Date(r.mtime * 1000);
      const tsLabel = dt.toLocaleString('es-CR');
      li.innerHTML = `<a href="/reports/${encodeURIComponent(r.name)}" target="_blank">${escape(r.name)}</a><time>${tsLabel}</time>`;
      ul.appendChild(li);
    });
  } catch (e) {
    ul.innerHTML = `<li class="muted">Error: ${escape(String(e))}</li>`;
  }
}

// ────────────────────────────────────────────────────────────────────────
// Util
// ────────────────────────────────────────────────────────────────────────
function escape(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
