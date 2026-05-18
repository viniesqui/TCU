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
let stageState = {};       // { [stage_id]: { status, startedAt, endedAt, attempt, maxAttempts, retryReason } }
let elapsedTicker = null;  // setInterval handle that drives elapsed-time updates

// ── Review state ─────────────────────────────────────────────────────────
// Each entry: { id, source: 'critical'|'moderate'|'manual', name, demand, coverage, depth, severity, notes, accepted }
// Manual cards have a remove button instead of a checkbox and are always "accepted" while present.
let reviewSkills = [];
let filterMode = 'all';   // 'all' | 'critical' | 'moderate' | 'manual'
let sortMode = 'gap';     // 'gap' | 'demand' | 'name'
let manualSeq = 0;

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
// Review screen (PR3) — card grid, filter/sort, sticky course panel
// ════════════════════════════════════════════════════════════════════════
function onReviewRequest(gap) {
  currentGap = gap;
  reviewSkills = [];
  manualSeq = 0;
  filterMode = 'all';
  sortMode = 'gap';

  (gap.critical_gaps || []).forEach((s, i) => reviewSkills.push({
    id: `c${i}`, source: 'critical', name: s.skill_name,
    demand: s.market_demand_score || 0,
    coverage: s.academic_coverage_score || 0,
    depth: s.market_depth_required || 'intermedio',
    severity: 'critical', notes: s.notes || '', accepted: true,
  }));
  (gap.moderate_gaps || []).forEach((s, i) => reviewSkills.push({
    id: `m${i}`, source: 'moderate', name: s.skill_name,
    demand: s.market_demand_score || 0,
    coverage: s.academic_coverage_score || 0,
    depth: s.market_depth_required || 'intermedio',
    severity: 'moderate', notes: s.notes || '', accepted: true,
  }));

  // Update the pipeline timeline (the review stage is now active).
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

  hydrateReview(gap);
  show('review');
}

function hydrateReview(gap) {
  document.getElementById('review-sector').textContent = gap.sector || 'Sector';
  document.getElementById('review-opportunity').textContent = gap.opportunity_statement || '';
  renderKPIs(gap);

  const titleEl = document.getElementById('course-title');
  const ratEl = document.getElementById('course-rationale');
  titleEl.value = gap.proposed_course_title || '';
  ratEl.value = gap.proposed_course_rationale || '';
  updateCharCount(titleEl, 'course-title-count', 120);
  updateCharCount(ratEl, 'course-rationale-count', 800);
  updateTitlePreview();

  // Reset filter UI
  document.querySelectorAll('.filter-btn').forEach(b => {
    b.setAttribute('aria-pressed', String(b.dataset.filter === 'all'));
  });
  document.getElementById('sort-select').value = sortMode;

  renderSkills();
  updateSelectionCounter();
}

function renderKPIs(gap) {
  const critical = (gap.critical_gaps || []).length;
  const moderate = (gap.moderate_gaps || []).length;
  const covered = (gap.well_covered || []).length;
  const depth = gap.proposed_course_depth || 'intermedio';

  const tiles = [
    { label: 'Brechas críticas', value: critical, kind: 'critical' },
    { label: 'Brechas moderadas', value: moderate, kind: 'moderate' },
    { label: 'Ya cubiertas', value: covered, kind: 'success' },
    { label: 'Profundidad propuesta', value: capitalize(depth), kind: 'neutral' },
  ];
  const wrap = document.getElementById('review-kpis');
  wrap.innerHTML = '';
  tiles.forEach(t => {
    const tile = document.createElement('div');
    tile.className = `kpi-tile kpi-${t.kind}`;
    tile.innerHTML = `
      <span class="kpi-value">${escape(String(t.value))}</span>
      <span class="kpi-label">${escape(t.label)}</span>
    `;
    wrap.appendChild(tile);
  });
}

function renderSkills() {
  const grid = document.getElementById('skills-grid');
  const empty = document.getElementById('skills-empty');

  let visible = reviewSkills.filter(s => {
    if (filterMode === 'all') return true;
    if (filterMode === 'manual') return s.source === 'manual';
    return s.source === filterMode;
  });
  visible.sort(sortCompare);

  grid.innerHTML = '';
  empty.hidden = visible.length > 0;
  visible.forEach(s => grid.appendChild(renderSkillCard(s)));
  updateFilterCounts();
}

function sortCompare(a, b) {
  if (sortMode === 'gap')    return (b.demand - b.coverage) - (a.demand - a.coverage);
  if (sortMode === 'demand') return b.demand - a.demand;
  if (sortMode === 'name')   return a.name.localeCompare(b.name, 'es');
  return 0;
}

function renderSkillCard(s) {
  const card = document.createElement('article');
  card.className = `skill-card severity-${s.severity} source-${s.source}`;
  card.dataset.id = s.id;
  if (s.source !== 'manual' && !s.accepted) card.classList.add('rejected');

  // Header
  const head = document.createElement('header');
  head.className = 'skill-card-head';

  if (s.source === 'manual') {
    head.innerHTML = `
      <div class="skill-title">
        <span class="skill-name">${escape(s.name)}</span>
        <span class="manual-badge" title="Agregado por ti">Manual</span>
      </div>
      <div class="skill-head-right">
        <span class="depth-pill depth-${escape(s.depth)}">${escape(capitalize(s.depth))}</span>
        <button type="button" class="remove-btn" aria-label="Quitar ${escape(s.name)}">×</button>
      </div>
    `;
    head.querySelector('.remove-btn').addEventListener('click', () => {
      reviewSkills = reviewSkills.filter(x => x.id !== s.id);
      renderSkills();
      updateSelectionCounter();
    });
  } else {
    head.innerHTML = `
      <label class="skill-check">
        <input type="checkbox" data-id="${s.id}" ${s.accepted ? 'checked' : ''}>
        <span class="skill-name">${escape(s.name)}</span>
      </label>
      <span class="depth-pill depth-${escape(s.depth)}">${escape(capitalize(s.depth))}</span>
    `;
    head.querySelector('input[type="checkbox"]').addEventListener('change', (e) => {
      const skill = reviewSkills.find(x => x.id === s.id);
      if (skill) skill.accepted = e.target.checked;
      card.classList.toggle('rejected', !e.target.checked);
      updateSelectionCounter();
    });
  }
  card.appendChild(head);

  // Demand/coverage bars
  const meta = document.createElement('div');
  meta.className = 'skill-meta';
  const dPct = Math.round(s.demand * 100);
  const cPct = Math.round(s.coverage * 100);
  meta.innerHTML = `
    <div class="meta-row">
      <span class="meta-label">Demanda</span>
      <div class="bar-track"><div class="bar-fill demand" style="width:${dPct}%"></div></div>
      <span class="meta-val">${dPct}%</span>
    </div>
    <div class="meta-row">
      <span class="meta-label">Cobertura</span>
      <div class="bar-track"><div class="bar-fill coverage" style="width:${cPct}%"></div></div>
      <span class="meta-val">${cPct}%</span>
    </div>
  `;
  card.appendChild(meta);

  // Notes (gap analyst justification or educator note)
  if (s.notes) {
    const det = document.createElement('details');
    det.className = 'skill-notes-wrap';
    det.innerHTML = `
      <summary class="skill-notes-toggle">Ver justificación</summary>
      <p class="skill-notes">${escape(s.notes)}</p>
    `;
    card.appendChild(det);
  }

  return card;
}

function updateFilterCounts() {
  const counts = { all: reviewSkills.length, critical: 0, moderate: 0, manual: 0 };
  reviewSkills.forEach(s => { counts[s.source]++; });
  for (const k of Object.keys(counts)) {
    const el = document.querySelector(`[data-count-for="${k}"]`);
    if (el) el.textContent = counts[k];
  }
}

function updateSelectionCounter() {
  const selected = reviewSkills.filter(s => s.source === 'manual' || s.accepted).length;
  const total = reviewSkills.length;
  document.querySelector('#selection-counter .sel-num').textContent = selected;
  document.querySelector('#selection-counter .sel-label').textContent = ` de ${total} seleccionadas`;
  const label = document.getElementById('accept-label');
  if (label) {
    label.textContent = selected > 0
      ? `Aceptar ${selected} ${selected === 1 ? 'habilidad' : 'habilidades'} y continuar`
      : 'Continuar sin habilidades';
  }
}

function capitalize(s) {
  if (!s) return '';
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// ── Toolbar wiring ─────────────────────────────────────────────────────
document.querySelectorAll('.filter-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    filterMode = btn.dataset.filter;
    document.querySelectorAll('.filter-btn').forEach(b => {
      b.setAttribute('aria-pressed', String(b === btn));
    });
    renderSkills();
  });
});

document.getElementById('sort-select')?.addEventListener('change', (e) => {
  sortMode = e.target.value;
  renderSkills();
});

document.getElementById('btn-select-all')?.addEventListener('click', () => {
  reviewSkills.forEach(s => { if (s.source !== 'manual') s.accepted = true; });
  renderSkills();
  updateSelectionCounter();
});

document.getElementById('btn-select-none')?.addEventListener('click', () => {
  reviewSkills.forEach(s => { if (s.source !== 'manual') s.accepted = false; });
  renderSkills();
  updateSelectionCounter();
});

// ── Manual addition ────────────────────────────────────────────────────
document.getElementById('btn-manual-add')?.addEventListener('click', () => {
  const nameEl = document.getElementById('manual-name');
  const depthEl = document.getElementById('manual-depth');
  const noteEl = document.getElementById('manual-note');
  const name = nameEl.value.trim();
  const depth = depthEl.value;
  const notes = noteEl.value.trim();
  if (!name) { nameEl.focus(); return; }
  reviewSkills.push({
    id: `man${manualSeq++}`,
    source: 'manual',
    name,
    demand: 0.7,
    coverage: 0.1,
    depth,
    severity: 'critical',
    notes,
    accepted: true,
  });
  nameEl.value = '';
  noteEl.value = '';
  nameEl.focus();
  // Switch filter to manual so the new card is visible immediately.
  if (filterMode !== 'all' && filterMode !== 'manual') {
    const allBtn = document.querySelector('.filter-btn[data-filter="all"]');
    if (allBtn) allBtn.click();
  } else {
    renderSkills();
    updateSelectionCounter();
  }
});

document.getElementById('manual-name')?.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') { e.preventDefault(); document.getElementById('btn-manual-add').click(); }
});

// ── Course title / rationale char counters and preview ─────────────────
function updateCharCount(el, countId, max) {
  const c = document.getElementById(countId);
  if (c) c.textContent = `${el.value.length}/${max}`;
}
function updateTitlePreview() {
  const title = document.getElementById('course-title').value.trim();
  const preview = document.getElementById('course-title-preview');
  if (preview) preview.textContent = title ? `· ${title}` : '';
}
document.getElementById('course-title')?.addEventListener('input', (e) => {
  updateCharCount(e.target, 'course-title-count', 120);
  updateTitlePreview();
});
document.getElementById('course-rationale')?.addEventListener('input', (e) => {
  updateCharCount(e.target, 'course-rationale-count', 800);
});

// ── Submit ─────────────────────────────────────────────────────────────
document.getElementById('btn-accept')?.addEventListener('click', () => sendReviewResponse(false));
document.getElementById('btn-skip')?.addEventListener('click', () => {
  if (!confirm('¿Saltar la revisión? Se aceptarán todas las habilidades detectadas sin tu intervención.')) return;
  sendReviewResponse(true);
});

function sendReviewResponse(skipped) {
  const acceptedIds = [];
  const manuals = [];
  reviewSkills.forEach(s => {
    if (s.source === 'manual') {
      manuals.push({ name: s.name, depth: s.depth, notes: s.notes });
    } else if (s.accepted) {
      acceptedIds.push(s.id);
    }
  });
  const accepted = acceptedIds.length + manuals.length;

  const payload = skipped
    ? { skipped: true, audit: buildAudit({ skipped: true, accepted, manualCount: 0 }) }
    : {
        skipped: false,
        accepted_ids: acceptedIds,
        manual_additions: manuals,
        proposed_course_title: document.getElementById('course-title').value.trim(),
        proposed_course_rationale: document.getElementById('course-rationale').value.trim(),
        audit: buildAudit({ skipped: false, accepted, manualCount: manuals.length }),
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

function buildAudit({ skipped }) {
  const reviewer = (document.getElementById('reviewer').value.trim()) || 'web-user';
  const acceptedNames = [];
  if (!skipped) {
    reviewSkills.forEach(s => {
      if (s.source === 'manual' || s.accepted) acceptedNames.push(s.name);
    });
  } else {
    reviewSkills.forEach(s => acceptedNames.push(s.name));
  }
  return {
    reviewer,
    reviewed_at: new Date().toISOString(),
    skipped,
    accepted_skills: acceptedNames,
    manual_additions: skipped
      ? []
      : reviewSkills.filter(s => s.source === 'manual').map(s => ({ name: s.name, depth: s.depth, notes: s.notes })),
    proposed_course_title: skipped
      ? (currentGap?.proposed_course_title || '')
      : document.getElementById('course-title').value.trim(),
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
