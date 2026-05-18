// TCU web UI — single-session, WebSocket-driven.
// State machine: input → pipeline → review → done | error
// Archive is reachable from the sidebar.

// ════════════════════════════════════════════════════════════════════════
// Stage catalog — single source of truth.
// Order matches the orchestrator's pipeline; ids match `stage_id` from the
// server and the data-stage attribute on each rendered timeline row.
// ════════════════════════════════════════════════════════════════════════
const STAGES = [
  { id: 'market',   label: 'Mercado laboral',          desc: 'Buscar ofertas y extraer habilidades demandadas',     eta: 90, icon: 'search' },
  { id: 'academic', label: 'Oferta académica',         desc: 'Mapear currículos de universidades costarricenses',   eta: 90, icon: 'graduation' },
  { id: 'gap',      label: 'Análisis de brecha',       desc: 'Cruzar demanda vs. cobertura',                        eta: 45, icon: 'chart' },
  { id: 'review',   label: 'Revisión humana',          desc: 'Validar habilidades antes del diseño del curso',      eta: 0,  icon: 'user' },
  { id: 'course',   label: 'Diseño curricular',        desc: 'Plan de estudios y cronograma de 16 semanas',         eta: 75, icon: 'clipboard' },
  { id: 'eval',     label: 'Sistema de evaluación',    desc: 'Componentes, rúbricas y matriz de competencias',      eta: 45, icon: 'check' },
  { id: 'report',   label: 'Generación del reporte',   desc: 'Renderizar HTML final',                               eta: 10, icon: 'file' },
];
const STAGE_INDEX = Object.fromEntries(STAGES.map((s, i) => [s.id, i]));

const SECTOR_SUGGESTIONS = [
  'Desarrollo de Software',
  'Ciberseguridad',
  'Inteligencia Artificial',
  'Análisis de Datos',
  'DevOps y Cloud',
  'Diseño UX/UI',
];

const ICONS = {
  search: '<path d="M11 4a7 7 0 014.95 11.95l4.55 4.55-1.41 1.41-4.55-4.55A7 7 0 1111 4zm0 2a5 5 0 100 10 5 5 0 000-10z"/>',
  graduation: '<path d="M12 2L1 8l11 6 9-4.91V17h2V8L12 2zm0 13.18L4 11v3.18l8 4.36 8-4.36V11l-8 4.18z"/>',
  chart: '<path d="M5 21V9h3v12H5zm5 0V3h3v18h-3zm5 0v-7h3v7h-3z"/>',
  user: '<path d="M12 12a5 5 0 100-10 5 5 0 000 10zm0 2c-4.42 0-8 2.24-8 5v3h16v-3c0-2.76-3.58-5-8-5z"/>',
  clipboard: '<path d="M16 2H8a2 2 0 00-2 2v16a2 2 0 002 2h8a2 2 0 002-2V4a2 2 0 00-2-2zm-4 0a2 2 0 110 4 2 2 0 010-4zM8 8h8v2H8V8zm0 4h8v2H8v-2zm0 4h5v2H8v-2z"/>',
  check: '<path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41L9 16.17z"/>',
  file: '<path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6zm4 18H6V4h7v5h5v11z"/>',
};

const screens = ['input', 'pipeline', 'review', 'done', 'error', 'archive'];

const SCREEN_TO_NAV = {
  input: 'input', pipeline: 'input', review: 'input', done: 'input', error: 'input',
  archive: 'archive',
};

function show(name) {
  for (const s of screens) {
    document.getElementById(`screen-${s}`).classList.toggle('active', s === name);
  }
  const navKey = SCREEN_TO_NAV[name];
  document.querySelectorAll('.nav-item[data-nav]').forEach(btn => {
    if (btn.dataset.nav === navKey) btn.setAttribute('aria-current', 'page');
    else btn.removeAttribute('aria-current');
  });
  const main = document.getElementById('main');
  if (main && document.activeElement && document.activeElement.tagName !== 'INPUT' && document.activeElement.tagName !== 'TEXTAREA') {
    main.focus({ preventScroll: true });
  }
}

// ════════════════════════════════════════════════════════════════════════
// Theme toggle
// ════════════════════════════════════════════════════════════════════════
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

// ════════════════════════════════════════════════════════════════════════
// Sidebar nav
// ════════════════════════════════════════════════════════════════════════
document.querySelectorAll('.nav-item[data-nav]').forEach(btn => {
  btn.addEventListener('click', () => {
    const target = btn.dataset.nav;
    if (target === 'input') show('input');
    else if (target === 'archive') openArchive();
  });
});

// ════════════════════════════════════════════════════════════════════════
// Session state
// ════════════════════════════════════════════════════════════════════════
let ws = null;
let currentGap = null;
let manualAdditions = [];
let stageState = {};       // { [stage_id]: { status, startedAt, endedAt, attempt, maxAttempts, retryReason } }
let elapsedTicker = null;  // setInterval handle that drives elapsed-time updates

function resetStageState() {
  stageState = {};
  STAGES.forEach(s => {
    stageState[s.id] = {
      status: 'pending',
      startedAt: null,
      endedAt: null,
      attempt: 1,
      maxAttempts: 1,
      retryReason: null,
    };
  });
}

// ════════════════════════════════════════════════════════════════════════
// Boot: input screen sub-views
// ════════════════════════════════════════════════════════════════════════
function renderSectorChips() {
  const wrap = document.getElementById('sector-chips');
  if (!wrap) return;
  wrap.innerHTML = '';
  SECTOR_SUGGESTIONS.forEach(name => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'chip';
    btn.textContent = name;
    btn.addEventListener('click', () => {
      const input = document.getElementById('sector');
      input.value = name;
      input.focus();
      syncChipSelection();
    });
    wrap.appendChild(btn);
  });
  syncChipSelection();
}

function syncChipSelection() {
  const val = (document.getElementById('sector')?.value || '').trim().toLowerCase();
  document.querySelectorAll('#sector-chips .chip').forEach(c => {
    c.classList.toggle('chip-active', c.textContent.toLowerCase() === val);
  });
}

function renderStagePreview() {
  const list = document.getElementById('stage-preview');
  if (!list) return;
  list.innerHTML = '';
  STAGES.forEach((s, i) => {
    const li = document.createElement('li');
    li.className = 'preview-item';
    li.innerHTML = `
      <span class="preview-num">${i + 1}</span>
      <span class="preview-icon">${stageIconSVG(s.icon)}</span>
      <span class="preview-text">
        <strong>${escape(s.label)}</strong>
        <span class="muted">${escape(s.desc)}</span>
      </span>
    `;
    list.appendChild(li);
  });
  const totalSec = STAGES.reduce((a, s) => a + s.eta, 0);
  const totalEl = document.getElementById('eta-total');
  if (totalEl) totalEl.textContent = `≈ ${Math.ceil(totalSec / 60)} min`;
}

async function renderRecentReports() {
  const wrap = document.getElementById('recent-reports');
  if (!wrap) return;
  wrap.innerHTML = '<li class="muted">Cargando…</li>';
  try {
    const res = await fetch('/api/reports');
    const data = await res.json();
    if (!data.reports || !data.reports.length) {
      wrap.innerHTML = '<li class="muted">Aún no hay reportes. ¡Genera el primero!</li>';
      return;
    }
    wrap.innerHTML = '';
    data.reports.slice(0, 4).forEach(r => {
      const sector = filenameToSector(r.name);
      const dt = new Date(r.mtime * 1000);
      const li = document.createElement('li');
      li.innerHTML = `
        <a href="/reports/${encodeURIComponent(r.name)}" target="_blank">
          <strong>${escape(sector)}</strong>
          <time>${escape(dt.toLocaleString('es-CR'))}</time>
        </a>
      `;
      wrap.appendChild(li);
    });
  } catch (e) {
    wrap.innerHTML = `<li class="muted">No se pudo cargar el archivo.</li>`;
  }
}

function filenameToSector(name) {
  // reporte_<sector_slug>_<timestamp>.html → "Sector slug"
  const m = name.match(/^reporte_(.+)_\d{4,}.*\.html$/i);
  if (!m) return name;
  return m[1].replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

// Sync chip selection as the user types
document.getElementById('sector')?.addEventListener('input', syncChipSelection);

// Advanced options disclosure uses the native <details>/<summary>.</details>
// No JS handler needed — keep aria-expanded in sync for screen readers.
document.querySelector('details.disclosure')?.addEventListener('toggle', (e) => {
  const det = e.currentTarget;
  det.querySelector('summary')?.setAttribute('aria-expanded', String(det.open));
});

// ════════════════════════════════════════════════════════════════════════
// Start a run
// ════════════════════════════════════════════════════════════════════════
document.getElementById('form-start').addEventListener('submit', (e) => {
  e.preventDefault();
  const sector = document.getElementById('sector').value.trim();
  const reviewer = document.getElementById('reviewer').value.trim() || null;
  if (!sector) return;
  resetStageState();
  renderPipelineTimeline();
  document.getElementById('log').innerHTML = '';
  document.getElementById('current-status').textContent = 'Inicializando agentes…';
  show('pipeline');
  startElapsedTicker();
  connectAndStart(sector, reviewer);
});

document.getElementById('btn-restart').addEventListener('click', () => location.reload());
document.getElementById('btn-restart-error').addEventListener('click', () => location.reload());
document.getElementById('open-archive')?.addEventListener('click', openArchive);
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
    stopElapsedTicker();
  });
  ws.addEventListener('error', () => showError('Error de conexión WebSocket.'));
}

// ════════════════════════════════════════════════════════════════════════
// Message dispatch — stage_id is authoritative (no more keyword matching)
// ════════════════════════════════════════════════════════════════════════
function handleMessage(msg) {
  switch (msg.type) {
    case 'stage_progress':
      onStageProgress(msg);
      break;
    case 'stage_retry':
      onStageRetry(msg);
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

function onStageProgress(msg) {
  document.getElementById('current-status').textContent = msg.description || '';
  appendLog(msg.description || '');

  const stageId = msg.stage_id;
  if (!stageId || !(stageId in stageState)) return;

  const now = Date.now();
  // Mark previous stages as done; mark this stage as active.
  const idx = STAGE_INDEX[stageId];
  STAGES.forEach((s, i) => {
    const st = stageState[s.id];
    if (i < idx && st.status !== 'done') {
      st.status = 'done';
      st.endedAt = st.endedAt || now;
    }
    if (i === idx && st.status !== 'active') {
      st.status = 'active';
      st.startedAt = st.startedAt || now;
      st.endedAt = null;
    }
  });
  renderPipelineTimeline();
}

function onStageRetry(msg) {
  const st = stageState[msg.stage_id];
  if (!st) return;
  st.attempt = msg.attempt;
  st.maxAttempts = msg.max_attempts;
  st.retryReason = msg.reason;
  appendLog(`⟲ Reintento ${msg.attempt}/${msg.max_attempts} (${msg.stage_id}): ${msg.reason}`);
  renderPipelineTimeline();
}

// ════════════════════════════════════════════════════════════════════════
// Pipeline UI — vertical timeline of stage cards
// ════════════════════════════════════════════════════════════════════════
function renderPipelineTimeline() {
  const list = document.getElementById('stage-list');
  if (!list) return;
  list.innerHTML = '';
  STAGES.forEach(s => {
    const st = stageState[s.id] || { status: 'pending' };
    const li = document.createElement('li');
    li.dataset.stage = s.id;
    li.className = `stage stage-${st.status}`;
    li.innerHTML = `
      <span class="stage-icon" aria-hidden="true">${stageIconSVG(s.icon)}</span>
      <span class="stage-body">
        <span class="stage-label">${escape(s.label)}</span>
        <span class="stage-meta">
          ${stageStatusPill(st)}
          ${st.retryReason ? `<span class="chip chip-warn" title="${escape(st.retryReason)}">⟲ Reintento ${st.attempt}/${st.maxAttempts}</span>` : ''}
          ${stageElapsedLabel(st) ? `<span class="stage-elapsed" data-stage-elapsed="${s.id}">${stageElapsedLabel(st)}</span>` : ''}
        </span>
      </span>
    `;
    list.appendChild(li);
  });
}

function stageStatusPill(st) {
  const map = {
    pending: { label: 'Pendiente', cls: 'pill-muted' },
    active:  { label: 'En curso',  cls: 'pill-active' },
    done:    { label: 'Listo',     cls: 'pill-done' },
  };
  const m = map[st.status] || map.pending;
  return `<span class="pill ${m.cls}">${m.label}</span>`;
}

function stageElapsedLabel(st) {
  if (st.status === 'pending') return '';
  if (st.status === 'done' && st.startedAt && st.endedAt) {
    return formatDuration(Math.round((st.endedAt - st.startedAt) / 1000));
  }
  if (st.status === 'active' && st.startedAt) {
    return formatDuration(Math.round((Date.now() - st.startedAt) / 1000));
  }
  return '';
}

function startElapsedTicker() {
  stopElapsedTicker();
  elapsedTicker = setInterval(() => {
    // Only the currently-active stage's label needs to tick.
    for (const s of STAGES) {
      const st = stageState[s.id];
      if (st && st.status === 'active') {
        const el = document.querySelector(`[data-stage-elapsed="${s.id}"]`);
        if (el) el.textContent = stageElapsedLabel(st);
      }
    }
  }, 1000);
}
function stopElapsedTicker() {
  if (elapsedTicker) { clearInterval(elapsedTicker); elapsedTicker = null; }
}

function formatDuration(sec) {
  if (sec < 60) return `${sec}s`;
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return s ? `${m}m ${s}s` : `${m}m`;
}

function stageIconSVG(name) {
  const path = ICONS[name] || ICONS.file;
  return `<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">${path}</svg>`;
}

function appendLog(text) {
  if (!text) return;
  const log = document.getElementById('log');
  const div = document.createElement('div');
  const now = new Date();
  const ts = `${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}:${String(now.getSeconds()).padStart(2,'0')}`;
  div.textContent = `[${ts}] ${text}`;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

// Collapsible details panel
document.getElementById('toggle-details')?.addEventListener('click', (e) => {
  const btn = e.currentTarget;
  const panel = document.getElementById('details-panel');
  const open = panel.classList.toggle('open');
  btn.setAttribute('aria-expanded', String(open));
  btn.querySelector('.toggle-label').textContent = open ? 'Ocultar detalles técnicos' : 'Mostrar detalles técnicos';
});

// Cancel button
document.getElementById('btn-cancel')?.addEventListener('click', () => {
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    location.reload();
    return;
  }
  if (!confirm('¿Cancelar la ejecución actual? Se perderá el progreso no guardado.')) return;
  try { ws.send(JSON.stringify({ type: 'cancel' })); } catch (e) { /* ignore */ }
  stopElapsedTicker();
  appendLog('⊗ Cancelando…');
});

// ════════════════════════════════════════════════════════════════════════
// Review screen (unchanged from PR1 — redesigned in PR3)
// ════════════════════════════════════════════════════════════════════════
function onReviewRequest(gap) {
  currentGap = gap;
  manualAdditions = [];

  // Force the stages around the review checkpoint to the right state.
  const now = Date.now();
  for (const id of ['market', 'academic', 'gap']) {
    const st = stageState[id];
    if (st && st.status !== 'done') { st.status = 'done'; st.endedAt = st.endedAt || now; }
  }
  if (stageState.review) {
    stageState.review.status = 'active';
    stageState.review.startedAt = stageState.review.startedAt || now;
  }
  renderPipelineTimeline();

  renderReview(gap);
  show('review');
}

function renderReview(gap) {
  const critical = gap.critical_gaps || [];
  const moderate = gap.moderate_gaps || [];

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

  // Mark the review stage done and return to the pipeline.
  const now = Date.now();
  if (stageState.review) {
    stageState.review.status = 'done';
    stageState.review.endedAt = stageState.review.endedAt || now;
  }
  renderPipelineTimeline();
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

// ════════════════════════════════════════════════════════════════════════
// Completion
// ════════════════════════════════════════════════════════════════════════
function onComplete(msg) {
  const now = Date.now();
  STAGES.forEach(s => {
    const st = stageState[s.id];
    if (st.status !== 'done') {
      st.status = 'done';
      st.endedAt = st.endedAt || now;
    }
  });
  renderPipelineTimeline();
  stopElapsedTicker();

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

// ════════════════════════════════════════════════════════════════════════
// Errors
// ════════════════════════════════════════════════════════════════════════
function showError(text) {
  stopElapsedTicker();
  document.getElementById('error-message').textContent = text;
  show('error');
}

// ════════════════════════════════════════════════════════════════════════
// Archive
// ════════════════════════════════════════════════════════════════════════
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
      const sector = filenameToSector(r.name);
      li.innerHTML = `<a href="/reports/${encodeURIComponent(r.name)}" target="_blank">${escape(sector)}</a><time>${escape(tsLabel)}</time>`;
      ul.appendChild(li);
    });
  } catch (e) {
    ul.innerHTML = `<li class="muted">Error: ${escape(String(e))}</li>`;
  }
}

// ════════════════════════════════════════════════════════════════════════
// Util
// ════════════════════════════════════════════════════════════════════════
function escape(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// ════════════════════════════════════════════════════════════════════════
// Boot
// ════════════════════════════════════════════════════════════════════════
renderSectorChips();
renderStagePreview();
renderRecentReports();
resetStageState();
renderPipelineTimeline();
