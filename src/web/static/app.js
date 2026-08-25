// TCU Multi-Persona Web UI Client Logic
// Coordinates Researcher, Approver, Professor, and Student dashboards.

let currentUser = null;
let currentRole = null;
let studentLearningProfile = null;
let authToken = localStorage.getItem("tcu_token");

// Auth Interceptor
const originalFetch = window.fetch;
window.fetch = async function() {
  let [resource, config] = arguments;
  if (!config) config = {};
  if (!config.headers) config.headers = {};
  if (authToken) {
    config.headers['Authorization'] = `Bearer ${authToken}`;
  }
  const response = await originalFetch(resource, config);
  if (response.status === 401 && resource !== "/api/login") {
    logout();
  }
  return response;
};

// Floating Toast Notification System
function showToast(message, type = 'info', duration = 4000) {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const icons = {
    success: '✅',
    error: '❌',
    warning: '⚠️',
    info: 'ℹ️'
  };

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `
    <span class="toast-icon">${icons[type] || 'ℹ️'}</span>
    <span class="toast-message">${message}</span>
    <button class="toast-close" aria-label="Cerrar">&times;</button>
  `;

  container.appendChild(toast);

  requestAnimationFrame(() => {
    toast.classList.add('show');
  });

  const closeToast = () => {
    toast.classList.remove('show');
    toast.addEventListener('transitionend', () => toast.remove(), { once: true });
  };

  toast.querySelector('.toast-close').addEventListener('click', closeToast);

  if (duration > 0) {
    setTimeout(closeToast, duration);
  }
}

function logout() {
  localStorage.removeItem("tcu_token");
  localStorage.removeItem("tcu_user");
  authToken = null;
  currentUser = null;
  currentRole = null;
  document.getElementById("login-container").style.display = "block";
  document.getElementById("app-nav").style.display = "none";
  document.getElementById("app-main").style.display = "none";
  showToast("Sesión cerrada", "info");
}

// Initialize Page
document.addEventListener("DOMContentLoaded", () => {
  // Theme Switcher Logic
  const themeToggleBtn = document.getElementById("btn-theme-toggle");
  const storedTheme = localStorage.getItem("tcu_theme") || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  
  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("tcu_theme", theme);
    if (themeToggleBtn) {
      themeToggleBtn.textContent = theme === "dark" ? "☀️ Claro" : "🌙 Oscuro";
    }
  }

  applyTheme(storedTheme);

  if (themeToggleBtn) {
    themeToggleBtn.addEventListener("click", () => {
      const currentTheme = document.documentElement.getAttribute("data-theme") || "light";
      const newTheme = currentTheme === "dark" ? "light" : "dark";
      applyTheme(newTheme);
      showToast(`Modo ${newTheme === "dark" ? "Oscuro" : "Claro"} activado`, "info");
    });
  }

  // Login form handler
  const formLogin = document.getElementById("form-login");
  if (formLogin) {
    formLogin.addEventListener("submit", async (e) => {
      e.preventDefault();
      const user = document.getElementById("login-username").value.trim();
      const pass = document.getElementById("login-password").value;
      const errDiv = document.getElementById("login-error");
      errDiv.style.display = "none";
      try {
        const res = await originalFetch("/api/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username: user, password: pass })
        });
        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.detail || "Credenciales inválidas");
        }
        authToken = data.access_token;
        localStorage.setItem("tcu_token", authToken);
        localStorage.setItem("tcu_user", JSON.stringify(data.user));
        showToast(`¡Bienvenido, ${data.user.username}!`, "success");
        initApp(data.user);
      } catch (e) {
        errDiv.textContent = e.message;
        errDiv.style.display = "block";
      }
    });
  }

  // Check auth state with live token validation
  if (authToken) {
    originalFetch("/api/current_user")
      .then(res => {
        if (res.ok) return res.json();
        throw new Error("Token expirado o inválido");
      })
      .then(user => {
        localStorage.setItem("tcu_user", JSON.stringify(user));
        initApp(user);
      })
      .catch(err => {
        console.warn("Auto-login token invalid, logging out:", err);
        logout();
      });
  } else {
    logout();
  }
  

  const formTest = document.getElementById("form-learning-test");
  if (formTest) {
    formTest.addEventListener("submit", async (e) => {
      e.preventDefault();
      const q1 = document.querySelector('input[name="q1"]:checked')?.value;
      const q2 = document.querySelector('input[name="q2"]:checked')?.value;
      const q3 = document.querySelector('input[name="q3"]:checked')?.value;
      
      const counts = {texto: 0, visual: 0, auditivo: 0};
      if(q1) counts[q1]++;
      if(q2) counts[q2]++;
      if(q3) counts[q3]++;
      
      // Get max
      let maxStyle = "texto";
      let maxCount = -1;
      for (const [style, count] of Object.entries(counts)) {
        if (count > maxCount) {
          maxCount = count;
          maxStyle = style;
        }
      }
      
      try {
        const res = await fetch("/api/student/preference", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ learning_preference: maxStyle })
        });
        if (res.ok) {
          window.learningPreference = maxStyle;
          document.getElementById("modal-learning-test").style.display = "none";
          // reload student view
          initStudent();
        }
      } catch (err) {
        alert("Error al guardar preferencia");
      }
    });
  }

  const logoutBtn = document.getElementById("btn-logout");
  if (logoutBtn) {
    logoutBtn.addEventListener("click", logout);
  }
});

async function initApp(user) {
  currentUser = user.username;
  currentRole = user.role;
  
  document.getElementById("login-container").style.display = "none";
  document.getElementById("app-nav").style.display = "flex";
  document.getElementById("app-main").style.display = "block";
  

  if (currentRole === "student") {
    try {
      const res = await fetch("/api/student/profile");
      if (res.ok) {
        const prefData = await res.json();
        if (!prefData || !prefData.dominant_style) {
          showStudentProfile();
        } else {
          studentLearningProfile = prefData;
          window.learningPreference = prefData.dominant_style;
        }
      } else {
          showStudentProfile();
      }
    } catch (e) { console.error(e); }
  }
  
  updateUserBadge();
  initNavigation();
  initResearcher();
  initApprover();
  initProfessor();
  initStudent();
  initConfig();
  initGuide();
  
  // Click the tab matching the user's role
  const tab = document.querySelector(`.nav-tab[data-role="${currentRole}"]`);
  if (tab) tab.click();
}

// ────────────────────────────────────────────────────────────────────────
// 0. User & Role Management
// ────────────────────────────────────────────────────────────────────────

function updateUserBadge() {
  const badge = document.getElementById("active-user-badge");
  if (badge) {
    badge.textContent = `Rol: ${getRoleLabel(currentRole)} (${currentUser})`;
  }
}

function getRoleLabel(role) {
  switch (role) {
    case "researcher": return "Investigador";
    case "approver": return "Coordinador";
    case "professor": return "Profesor";
    case "student": return "Estudiante";
    default: return role;
  }
}

function initNavigation() {
  const tabs = document.querySelectorAll(".nav-tab");
  tabs.forEach(tab => {
    tab.addEventListener("click", async () => {
      tabs.forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      
      const role = tab.dataset.role;
      currentRole = role;
      
      // (Simulated select_user removed since we use real login now)

      switchPanel(role);
    });
  });

  // Navigate to Approver from Researcher screen-done
  document.querySelectorAll(".btn-go-approver").forEach(btn => {
    btn.addEventListener("click", () => {
      const tab = document.querySelector('.nav-tab[data-role="approver"]');
      if (tab) tab.click();
    });
  });
}

function switchPanel(role) {
  // Hide all panels
  document.querySelectorAll(".role-panel").forEach(panel => {
    panel.classList.remove("active");
  });
  
  // Show active role panel
  const activePanel = document.getElementById(`panel-${role}`);
  if (activePanel) {
    activePanel.classList.add("active");
  }

  // Refresh tab data
  if (role === "approver") {
    refreshApproverGaps();
  } else if (role === "professor") {
    refreshProfessorSyllabi();
  } else if (role === "student") {
    refreshStudentCourses();
  }
}

// ────────────────────────────────────────────────────────────────────────
// 1. Researcher Dashboard (Investigador)
// ────────────────────────────────────────────────────────────────────────

function initResearcher() {
  const form = document.getElementById("form-start");
  if (!form) return;

  let selectedCurriculumSource = "fwd"; // default to FWD Costa Rica
  let customCurriculumData = null;

  const btnSrcFwd = document.getElementById("btn-src-fwd");
  const btnSrcUniv = document.getElementById("btn-src-universities");
  const btnSrcCustom = document.getElementById("btn-src-custom");
  const fwdPreview = document.getElementById("fwd-preview-box");
  const customUploadBox = document.getElementById("custom-upload-box");
  const fileInput = document.getElementById("curriculum-file-input");
  const customTextarea = document.getElementById("custom-curriculum-textarea");

  function setCurriculumSource(source) {
    selectedCurriculumSource = source;
    [btnSrcFwd, btnSrcUniv, btnSrcCustom].forEach(btn => {
      if (btn) {
        btn.classList.remove("active");
        btn.style.borderColor = "var(--border)";
        btn.style.background = "var(--card)";
      }
    });

    if (source === "fwd" && btnSrcFwd) {
      btnSrcFwd.classList.add("active");
      btnSrcFwd.style.borderColor = "var(--primary)";
      btnSrcFwd.style.background = "rgba(37, 99, 235, 0.12)";
      if (fwdPreview) fwdPreview.style.display = "block";
      if (customUploadBox) customUploadBox.style.display = "none";
      showToast("Malla oficial FWD Costa Rica seleccionada", "info");
    } else if (source === "universities" && btnSrcUniv) {
      btnSrcUniv.classList.add("active");
      btnSrcUniv.style.borderColor = "var(--primary)";
      btnSrcUniv.style.background = "rgba(37, 99, 235, 0.12)";
      if (fwdPreview) fwdPreview.style.display = "none";
      if (customUploadBox) customUploadBox.style.display = "none";
      showToast("Modo búsqueda general universitaria activado", "info");
    } else if (source === "custom" && btnSrcCustom) {
      btnSrcCustom.classList.add("active");
      btnSrcCustom.style.borderColor = "var(--primary)";
      btnSrcCustom.style.background = "rgba(37, 99, 235, 0.12)";
      if (fwdPreview) fwdPreview.style.display = "none";
      if (customUploadBox) customUploadBox.style.display = "block";
      showToast("Carga de programa personalizado activada", "info");
    }
  }

  if (btnSrcFwd) btnSrcFwd.addEventListener("click", () => setCurriculumSource("fwd"));
  if (btnSrcUniv) btnSrcUniv.addEventListener("click", () => setCurriculumSource("universities"));
  if (btnSrcCustom) btnSrcCustom.addEventListener("click", () => setCurriculumSource("custom"));

  if (fileInput) {
    fileInput.addEventListener("change", async (e) => {
      const file = e.target.files?.[0];
      if (!file) return;

      showToast(`Leyendo archivo: ${file.name}...`, "info");
      const reader = new FileReader();
      reader.onload = async (event) => {
        const text = event.target.result;
        if (customTextarea) customTextarea.value = text.slice(0, 3000);

        try {
          const uploadRes = await fetch("/api/curriculum/upload", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              title: file.name.replace(/\.[^/.]+$/, ""),
              institution: "Archivo Subido",
              text: text
            })
          });
          if (uploadRes.ok) {
            const upData = await uploadRes.json();
            customCurriculumData = {
              title: upData.program_title,
              institution: upData.institution,
              skills: upData.skills_extracted,
              summary: `Programa cargado desde ${file.name} con ${upData.total_skills} habilidades identificadas.`
            };
            showToast(`✓ ${upData.total_skills} habilidades extraídas del programa`, "success");
          }
        } catch (err) {
          console.error("Failed to parse uploaded curriculum", err);
        }
      };
      reader.readAsText(file);
    });
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const sector = document.getElementById("sector").value.trim();
    if (!sector) return;

    // Show progress screen
    document.getElementById("screen-input").classList.remove("active");
    const screenPipeline = document.getElementById("screen-pipeline");
    screenPipeline.classList.add("active");
    resetPipelineUI();

    updatePipelineStage("market", "active", "Investigando mercado laboral...");
    appendLog("Agente Investigador de Mercado buscando ofertas reales en LinkedIn, Computrabajo, CAMTIC...");

    if (selectedCurriculumSource === "fwd") {
      appendLog("Evaluando contra el Programa Oficial FWD Costa Rica (Front End + IA Aplicada, 13 semanas).");
    } else if (selectedCurriculumSource === "custom") {
      appendLog("Evaluando contra programa de estudio personalizado cargado por el usuario.");
    } else {
      appendLog("Buscando programas vigentes en UCR, TEC, UNA y ULACIT...");
    }

    try {
      // Build custom curriculum data if typed in textarea
      if (selectedCurriculumSource === "custom" && !customCurriculumData && customTextarea?.value.trim()) {
        const rawText = customTextarea.value.trim();
        const lines = rawText.split("\n").map(l => l.trim().replace(/^[-•*]\s*/, '')).filter(l => l.length > 2);
        customCurriculumData = {
          title: "Programa Personalizado",
          institution: "Institución Externa",
          skills: lines.slice(0, 30),
          summary: rawText.slice(0, 300)
        };
      }

      // Trigger backend API research (Stage 1-3)
      const forceRebuild = document.getElementById("force-rebuild-research")?.checked || false;
      const payload = {
        sector,
        force_rebuild: forceRebuild,
        curriculum_source: selectedCurriculumSource,
        custom_curriculum: customCurriculumData
      };

      const response = await fetch("/api/research", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });

      if (!response.ok) {
        throw new Error(await response.text());
      }

      const data = await response.json();
      currentGapData = data;

      // Finish progress animation
      updatePipelineStage("market", "done", "Completado");
      updatePipelineStage("academic", "done", "Completado");
      updatePipelineStage("gap", "done", "Completado");
      appendLog("Análisis comparativo de brechas completado con éxito.");

      setTimeout(() => {
        // Load review screen
        screenPipeline.classList.remove("active");
        document.getElementById("screen-review").classList.add("active");
        renderGapReview(data.gap_analysis);
      }, 1000);

    } catch (err) {
      showError(err.message || "Error al ejecutar el análisis de brecha.");
    }
  });

  // Approve Gap analysis
  document.getElementById("btn-approve-gap").addEventListener("click", async () => {
    if (!currentGapData) return;

    // Gather edited values
    const acceptedIds = [];
    document.querySelectorAll('#screen-review input[type="checkbox"]').forEach(cb => {
      if (cb.checked) acceptedIds.push(cb.dataset.id);
    });

    const originalGap = currentGapData.gap_analysis;
    const critical = (originalGap.critical_gaps || []).filter((_, i) => acceptedIds.includes(`c${i}`));
    const moderate = (originalGap.moderate_gaps || []).filter((_, i) => acceptedIds.includes(`m${i}`));

    const editedGap = {
      ...originalGap,
      critical_gaps: critical,
      moderate_gaps: moderate,
      proposed_course_title: document.getElementById("course-title").value.trim(),
      proposed_course_rationale: document.getElementById("course-rationale").value.trim()
    };

    try {
      const res = await fetch("/api/approve-gap", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sector: currentGapData.sector,
          gap_analysis: editedGap,
          approved_by: currentUser
        })
      });

      if (!res.ok) throw new Error("No se pudo aprobar la brecha");

      // Load screen done
      document.getElementById("screen-review").classList.remove("active");
      document.getElementById("screen-done").classList.add("active");
    } catch (err) {
      alert("Error al guardar aprobación: " + err.message);
    }
  });

  // Restart error button
  const restartBtn = document.getElementById("btn-restart-error");
  if (restartBtn) {
    restartBtn.addEventListener("click", () => {
      document.getElementById("screen-error").classList.remove("active");
      document.getElementById("screen-input").classList.add("active");
    });
  }

  // Hook up Save Current Demo button
  const saveDemoBtn = document.getElementById("btn-save-current-demo");
  if (saveDemoBtn) {
    saveDemoBtn.addEventListener("click", () => {
      saveActiveRunAsDemo();
    });
  }

  // Load saved runs list on startup
  refreshSavedRuns();
}

function resetPipelineUI() {
  document.querySelectorAll("#stage-list li").forEach(li => {
    li.className = "pending";
    li.querySelector(".status").textContent = "";
  });
  document.getElementById("log").innerHTML = "";
  document.getElementById("current-status").textContent = "Inicializando agentes…";
}

function updatePipelineStage(stageName, statusClass, statusText) {
  const li = document.querySelector(`#stage-list li[data-stage="${stageName}"]`);
  if (li) {
    li.className = statusClass;
    li.querySelector(".status").textContent = statusText;
  }
}

function appendLog(text) {
  const log = document.getElementById("log");
  if (!log) return;
  const div = document.createElement("div");
  const now = new Date();
  const ts = `${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}:${String(now.getSeconds()).padStart(2,'0')}`;
  div.textContent = `[${ts}] ${text}`;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

function renderGapReview(gap) {
  const critical = gap.critical_gaps || [];
  const moderate = gap.moderate_gaps || [];

  // Summary line
  document.getElementById("review-summary").innerHTML =
    `Sector: <strong>${escapeHTML(gap.sector)}</strong> &middot; ` +
    `<strong>${critical.length}</strong> brechas críticas &middot; ` +
    `<strong>${moderate.length}</strong> brechas moderadas &middot; ` +
    `<strong>${(gap.well_covered || []).length}</strong> cubiertas`;

  renderSkillTable("critical-table", critical, "c");
  renderSkillTable("moderate-table", moderate, "m");

  document.getElementById("course-title").value = gap.proposed_course_title || "";
  document.getElementById("course-rationale").value = gap.proposed_course_rationale || "";
}

function renderSkillTable(tableId, skills, prefix) {
  const tbody = document.querySelector(`#${tableId} tbody`);
  tbody.innerHTML = "";
  if (!skills.length) {
    tbody.innerHTML = `<tr><td colspan="5" class="muted" style="padding:0.8rem; text-align:center;">— sin elementos —</td></tr>`;
    return;
  }
  skills.forEach((s, i) => {
    const id = `${prefix}${i}`;
    const tr = document.createElement("tr");
    tr.dataset.id = id;
    tr.innerHTML = `
      <td><input type="checkbox" data-id="${id}" checked></td>
      <td>${escapeHTML(s.skill_name)}</td>
      <td>${renderProgressBar(s.market_demand_score, "demand")}</td>
      <td>${renderProgressBar(s.academic_coverage_score, "coverage")}</td>
      <td>${escapeHTML(s.market_depth_required || "intermedio")}</td>`;
    tbody.appendChild(tr);
  });
  
  tbody.querySelectorAll('input[type="checkbox"]').forEach(cb => {
    cb.addEventListener("change", () => {
      cb.closest("tr").classList.toggle("rejected", !cb.checked);
    });
  });
}

function renderProgressBar(score, kind) {
  const pct = Math.round((score || 0) * 100);
  return `<div class="bar-cell">
    <div class="bar-track"><div class="bar-fill ${kind}" style="width:${pct}%"></div></div>
    <span class="bar-val">${score.toFixed(2)}</span>
  </div>`;
}

// ────────────────────────────────────────────────────────────────────────
// 2. Coordinador Curricular (Approver)
// ────────────────────────────────────────────────────────────────────────

let selectedGapId = null;

function initApprover() {
  document.getElementById("btn-run-course-design").addEventListener("click", async () => {
    if (!selectedGapId) return;
    
    const progress = document.getElementById("course-design-progress");
    const fields = document.getElementById("syllabus-fields");
    progress.style.display = "block";
    fields.style.display = "none";

    try {
      const forceRebuild = document.getElementById("force-rebuild-syllabus")?.checked || false;
      const refMaterial = document.getElementById("course-reference-material")?.value?.trim() || "";
      const res = await fetch("/api/course-design", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          gap_report_id: selectedGapId,
          force_rebuild: forceRebuild,
          reference_material: refMaterial
        })
      });

      if (!res.ok) throw new Error("Error al generar plan de estudios");
      const syllabus = await res.json();
      
      progress.style.display = "none";
      fields.style.display = "block";
      fields.classList.remove("fade-in-staged");
      void fields.offsetWidth; // trigger reflow
      fields.classList.add("fade-in-staged");
      
      // Load syllabus fields
      document.getElementById("edit-course-title").value = syllabus.course_title;
      document.getElementById("edit-course-code").value = syllabus.course_code;
      document.getElementById("edit-course-credits").value = syllabus.credits;
      document.getElementById("edit-course-hours").value = syllabus.hours_per_week;

      renderEditableList("edit-course-objectives", syllabus.learning_objectives.map(o => o.description));
      renderEditableList("edit-course-bib", syllabus.bibliography);
      renderEditableWeeks(syllabus.weekly_schedule);

      // Save syllabus ID in the workspace data attributes
      document.getElementById("approver-workspace").dataset.syllabusId = syllabus.id;
    } catch (e) {
      alert("Error: " + e.message);
      progress.style.display = "none";
    }
  });

  document.getElementById("btn-save-syllabus").addEventListener("click", async () => {
    const workspace = document.getElementById("approver-workspace");
    const syllabusId = workspace.dataset.syllabusId;
    if (!syllabusId) return;

    // Gather values
    const course_title = document.getElementById("edit-course-title").value.trim();
    const course_code = document.getElementById("edit-course-code").value.trim();
    const credits = parseInt(document.getElementById("edit-course-credits").value, 10);
    const hours_per_week = parseFloat(document.getElementById("edit-course-hours").value);

    // Read list values
    const objectives = [];
    document.querySelectorAll("#edit-course-objectives input").forEach(input => {
      if (input.value.trim()) {
        objectives.push({ bloom_level: "aplicar", description: input.value.trim() });
      }
    });

    const bibliography = [];
    document.querySelectorAll("#edit-course-bib input").forEach(input => {
      if (input.value.trim()) {
        bibliography.push(input.value.trim());
      }
    });

    const weekly_schedule = [];
    document.querySelectorAll("#edit-course-weeks .week-edit-row").forEach(row => {
      const week_number = parseInt(row.querySelector(".week-num").dataset.week, 10);
      const title = row.querySelector("input.week-title").value.trim();
      const activity_type = row.querySelector("input.activity-type").value.trim();
      if (title) {
        weekly_schedule.push({ week: week_number, title, activity_type });
      }
    });

    try {
      const res = await fetch("/api/approve-syllabus", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          syllabus_id: parseInt(syllabusId, 10),
          course_title,
          course_code,
          credits,
          hours_per_week,
          learning_objectives: objectives,
          bibliography,
          weekly_schedule,
          approved_by: currentUser
        })
      });

      if (!res.ok) {
        let errorMsg = "No se pudo guardar la aprobación del curso";
        try {
          const errData = await res.json();
          if (errData.error) errorMsg = errData.error;
        } catch (e) {}
        throw new Error(errorMsg);
      }
      alert("¡Syllabus y Plan de Estudios aprobados y guardados en la base de datos de TCU!");
      
      // Refresh
      refreshApproverGaps();
    } catch (e) {
      alert("Error: " + e.message);
    }
  });
}

async function refreshApproverGaps() {
  const list = document.getElementById("approver-gap-list");
  list.innerHTML = "<li class='muted'>Cargando...</li>";
  
  try {
    const res = await fetch("/api/gaps");
    const gaps = await res.json();
    list.innerHTML = "";
    
    if (!gaps.length) {
      list.innerHTML = "<li class='muted'>No hay brechas analizadas. Corre el panel Investigador primero.</li>";
      return;
    }

    gaps.forEach(g => {
      const li = document.createElement("li");
      const isApproved = g.approved_by ? "✓ Aprobado" : "Pendiente";
      li.innerHTML = `<strong>${escapeHTML(g.sector)}</strong> <span style="font-size:0.75rem; color:var(--muted); float:right;">${isApproved}</span>`;
      li.dataset.gapId = g.id;
      
      li.addEventListener("click", () => {
        document.querySelectorAll("#approver-gap-list li").forEach(el => el.classList.remove("active"));
        li.classList.add("active");
        loadGapForSyllabusDesign(g);
      });
      list.appendChild(li);
    });
  } catch (e) {
    list.innerHTML = `<li class="error">Error: ${e.message}</li>`;
  }
}

async function loadGapForSyllabusDesign(gap) {
  selectedGapId = gap.id;
  
  // Clear layout
  document.querySelector("#approver-workspace .placeholder-msg").style.display = "none";
  const form = document.getElementById("approver-syllabus-form");
  form.style.display = "block";
  
  document.getElementById("workspace-gap-title").textContent = `Diseñar Curso para Sector: ${gap.sector}`;
  document.getElementById("syllabus-fields").style.display = "none";
  document.getElementById("course-design-progress").style.display = "none";

  // Check if syllabus already exists for this gap
  try {
    const res = await fetch("/api/syllabi");
    const syllabi = await res.json();
    const existing = syllabi.find(s => s.gap_report_id === gap.id);
    
    if (existing) {
      // Pre-fill
      document.getElementById("syllabus-fields").style.display = "block";
      document.getElementById("edit-course-title").value = existing.course_title;
      document.getElementById("edit-course-code").value = existing.course_code;
      document.getElementById("edit-course-credits").value = existing.credits;
      document.getElementById("edit-course-hours").value = existing.hours_per_week;

      renderEditableList("edit-course-objectives", existing.learning_objectives.map(o => o.description));
      renderEditableList("edit-course-bib", existing.bibliography);
      document.getElementById("approver-workspace").dataset.syllabusId = existing.id;
      
      try {
        const wcRes = await fetch(`/api/weekly-contents/${existing.id}`);
        const contents = await wcRes.json();
        const mappedWeeks = contents.map(w => ({ week: w.week_number, title: w.title, activity_type: w.activity_type }));
        renderEditableWeeks(mappedWeeks);
      } catch (e) {
        console.error("Failed to fetch weeks", e);
      }
    }
  } catch (e) {
    console.error("Failed to check existing syllabus:", e);
  }
}

function renderEditableList(elementId, items) {
  const container = document.getElementById(elementId);
  container.innerHTML = "";
  
  items.forEach(item => {
    const row = document.createElement("div");
    row.className = "bullet-item-row";
    row.innerHTML = `
      <input type="text" value="${escapeHTML(item)}">
      <button type="button" class="ghost" style="padding:0.25rem 0.5rem;" onclick="this.parentElement.remove()">×</button>
    `;
    container.appendChild(row);
  });

  // Add "+" row at bottom
  const addBtn = document.createElement("button");
  addBtn.type = "button";
  addBtn.className = "ghost";
  addBtn.style.padding = "0.3rem 0.8rem";
  addBtn.textContent = "+ Agregar Elemento";
  addBtn.addEventListener("click", () => {
    const row = document.createElement("div");
    row.className = "bullet-item-row";
    row.innerHTML = `
      <input type="text" placeholder="Escribe aquí...">
      <button type="button" class="ghost" style="padding:0.25rem 0.5rem;" onclick="this.parentElement.remove()">×</button>
    `;
    container.insertBefore(row, addBtn);
  });
  container.appendChild(addBtn);
}

function renderEditableWeeks(weeks) {
  const container = document.getElementById("edit-course-weeks");
  container.innerHTML = "";
  if (!weeks || !weeks.length) return;
  
  weeks.forEach(w => {
    const row = document.createElement("div");
    row.className = "week-edit-row";
    row.innerHTML = `
      <span class="week-num" data-week="${w.week}">Semana ${w.week}</span>
      <input type="text" class="week-title" value="${escapeHTML(w.title)}" placeholder="Título de la semana">
      <input type="text" class="activity-type" value="${escapeHTML(w.activity_type)}" placeholder="Tipo de actividad">
    `;
    container.appendChild(row);
  });
}

// ────────────────────────────────────────────────────────────────────────
// 3. Profesor Dashboard (Professor)
// ────────────────────────────────────────────────────────────────────────

function initProfessor() {
  document.getElementById("btn-generate-reading").addEventListener("click", async () => {
    if (!activeSyllabusId) return;
    
    // Find active week index
    const activeWeekLi = document.querySelector("#professor-weeks-list li.active");
    if (!activeWeekLi) return;
    
    const weekNumber = parseInt(activeWeekLi.dataset.weekNum, 10);
    const progress = document.getElementById("reading-generation-progress");
    const preview = document.getElementById("reading-preview-section");
    const btn = document.getElementById("btn-generate-reading");
    
    progress.style.display = "block";
    preview.style.display = "none";
    btn.style.disabled = true;

    try {
      const forceRebuild = document.getElementById("force-rebuild-reading")?.checked || false;
      const res = await fetch("/api/generate-reading", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          syllabus_id: activeSyllabusId,
          week_number: weekNumber,
          force_rebuild: forceRebuild
        })
      });

      if (!res.ok) throw new Error("Error generating weekly reading material");
      const content = await res.json();

      progress.style.display = "none";
      preview.style.display = "block";
      btn.style.disabled = false;

      document.getElementById("reading-preview-content").innerHTML = content.reading_material;
      document.getElementById("assignment-preview-prompt").textContent = content.assignment_prompt;

      // Update indicators
      activeWeekLi.classList.add("has-content");
    } catch (e) {
      alert("Error: " + e.message);
      progress.style.display = "none";
      btn.style.disabled = false;
    }
  });

  document.getElementById("btn-edit-reading").addEventListener("click", () => {
    const viewMode = document.getElementById("reading-view-mode");
    const editMode = document.getElementById("reading-edit-mode");
    
    if (viewMode.style.display !== "none") {
      // Switch to edit mode
      document.getElementById("edit-reading-content").value = document.getElementById("reading-preview-content").innerHTML;
      document.getElementById("edit-assignment-prompt").value = document.getElementById("assignment-preview-prompt").textContent;
      
      viewMode.style.display = "none";
      editMode.style.display = "block";
      document.getElementById("btn-edit-reading").textContent = "Cancelar Edición";
    } else {
      // Cancel edit mode
      viewMode.style.display = "block";
      editMode.style.display = "none";
      document.getElementById("btn-edit-reading").textContent = "Editar Contenido";
    }
  });

  document.getElementById("btn-save-reading").addEventListener("click", async () => {
    if (!activeSyllabusId) return;
    
    const activeWeekLi = document.querySelector("#professor-weeks-list li.active");
    if (!activeWeekLi) return;
    
    const weekNumber = parseInt(activeWeekLi.dataset.weekNum, 10);
    const newHtml = document.getElementById("edit-reading-content").value;
    const newPrompt = document.getElementById("edit-assignment-prompt").value;
    
    try {
      const res = await fetch("/api/publish-reading", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          syllabus_id: activeSyllabusId,
          week_number: weekNumber,
          reading_material: newHtml,
          assignment_prompt: newPrompt
        })
      });

      if (!res.ok) throw new Error("Error guardando los cambios");
      
      // Update DOM
      document.getElementById("reading-preview-content").innerHTML = newHtml;
      document.getElementById("assignment-preview-prompt").textContent = newPrompt;
      
      // Close edit mode
      document.getElementById("reading-view-mode").style.display = "block";
      document.getElementById("reading-edit-mode").style.display = "none";
      document.getElementById("btn-edit-reading").textContent = "Editar Contenido";
      
      alert("¡Contenido guardado y publicado correctamente!");
    } catch (e) {
      alert("Error: " + e.message);
    }
  });
}

async function refreshProfessorSyllabi() {
  const list = document.getElementById("professor-syllabus-list");
  list.innerHTML = "<li class='muted'>Cargando...</li>";
  
  try {
    const res = await fetch("/api/syllabi");
    const syllabi = await res.json();
    list.innerHTML = "";
    
    // Filter only approved ones (having approved_by not null)
    const approvedSyllabi = syllabi.filter(s => s.approved_by);

    if (!approvedSyllabi.length) {
      list.innerHTML = "<li class='muted'>No hay planes de estudio aprobados. Ve al panel Coordinador primero.</li>";
      return;
    }

    approvedSyllabi.forEach(s => {
      const li = document.createElement("li");
      li.innerHTML = `<strong>${escapeHTML(s.course_title)}</strong> <span style="font-size:0.75rem; color:var(--muted); float:right;">${s.course_code}</span>`;
      li.dataset.syllabusId = s.id;
      
      li.addEventListener("click", () => {
        document.querySelectorAll("#professor-syllabus-list li").forEach(el => el.classList.remove("active"));
        li.classList.add("active");
        loadProfessorCourseWeeks(s);
      });
      list.appendChild(li);
    });
  } catch (e) {
    list.innerHTML = `<li class="error">Error: ${e.message}</li>`;
  }
}

async function loadProfessorCourseWeeks(syllabus) {
  activeSyllabusId = syllabus.id;
  
  document.querySelector("#professor-workspace .placeholder-msg").style.display = "none";
  document.getElementById("professor-weekly-manager").style.display = "block";
  document.getElementById("professor-course-header").textContent = `Curso: ${syllabus.course_title} (${syllabus.course_code})`;

  // Fetch weekly contents details
  const weeksList = document.getElementById("professor-weeks-list");
  weeksList.innerHTML = "<li class='muted'>Cargando cronograma...</li>";
  
  try {
    const res = await fetch(`/api/weekly-contents/${syllabus.id}`);
    const contents = await res.json();
    weeksList.innerHTML = "";
    activeSyllabusWeeks = contents;

    contents.forEach(week => {
      const li = document.createElement("li");
      li.textContent = `Semana ${week.week_number}: ${week.title}`;
      li.dataset.weekNum = week.week_number;
      if (week.reading_material) {
        li.classList.add("has-content");
      }

      li.addEventListener("click", () => {
        document.querySelectorAll("#professor-weeks-list li").forEach(el => el.classList.remove("active"));
        li.classList.add("active");
        loadProfessorSelectedWeek(week);
      });
      weeksList.appendChild(li);
    });

    // Automatically click first week
    if (weeksList.firstChild) weeksList.firstChild.click();
  } catch (e) {
    weeksList.innerHTML = `<li class="error">Error: ${e.message}</li>`;
  }
}

function loadProfessorSelectedWeek(week) {
  document.getElementById("professor-selected-week-title").textContent = `Semana ${week.week_number}: ${week.title}`;
  document.getElementById("professor-selected-week-desc").textContent = `Tipo: ${week.activity_type.toUpperCase()} · Puntos: ${week.points}`;
  
  const genSection = document.getElementById("reading-generation-section");
  const previewSection = document.getElementById("reading-preview-section");
  
  genSection.style.display = "block";
  document.getElementById("reading-generation-progress").style.display = "none";
  
  if (week.reading_material) {
    previewSection.style.display = "block";
    document.getElementById("reading-preview-content").innerHTML = week.reading_material;
    document.getElementById("assignment-preview-prompt").textContent = week.assignment_prompt;
  } else {
    previewSection.style.display = "none";
  }
}

// ────────────────────────────────────────────────────────────────────────
// 4. Student Portal (Estudiante)
// ────────────────────────────────────────────────────────────────────────


async function initStudent() {
  document.getElementById("nav-student-profile")?.addEventListener("click", (e) => {
    e.preventDefault();
    showStudentProfile();
  });

  document.getElementById("nav-student-analytics")?.addEventListener("click", (e) => {
    e.preventDefault();
    showStudentAnalytics();
  });

  document.getElementById("btn-refresh-analytics")?.addEventListener("click", () => {
    loadStudentAnalyticsPortal();
  });

  document.getElementById("btn-retake-vark")?.addEventListener("click", () => {
    document.getElementById("vark-results-section").style.display = "none";
    document.getElementById("vark-test-section").style.display = "block";
    loadVarkTest();
  });

  try {
    const res = await fetch("/api/student/profile");
    if (res.ok) {
      studentLearningProfile = await res.json();
    }
  } catch(e) {}

  const form = document.getElementById("form-submission");
  if (!form) return;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    
    const weeklyContentId = document.getElementById("submission-weekly-content-id").value;
    const submittedText = document.getElementById("submission-text").value.trim();
    if (!submittedText) {
      showToast("Por favor escribe tu respuesta antes de entregar", "warning");
      return;
    }

    try {
      const parsedId = parseInt(weeklyContentId, 10);
      const res = await fetch("/api/submissions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          weekly_content_id: isNaN(parsedId) ? 1 : parsedId,
          submitted_text: submittedText,
          student_id: currentUser
        })
      });

      if (!res.ok) {
        let errText = "Error submitting assignment response";
        try {
          const errJson = await res.json();
          if (errJson.error || errJson.detail) errText = errJson.error || errJson.detail;
        } catch (e) {}
        throw new Error(errText);
      }
      
      const submitData = await res.json();
      const submissionId = submitData.submission_id;

      document.getElementById("submission-success-msg").style.display = "block";
      
      // Auto-trigger grading
      const gradeSection = document.getElementById("student-grade-section");
      const gradingSpinner = document.getElementById("grading-spinner");
      const gradingResults = document.getElementById("grading-results");
      
      gradeSection.style.display = "block";
      gradingSpinner.style.display = "flex";
      gradingResults.style.display = "none";
      
      try {
        const gradeRes = await fetch("/api/grade-submission", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ submission_id: submissionId })
        });
        
        if (!gradeRes.ok) {
          let errorMsg = "Error en la calificación por IA";
          try {
            const errData = await gradeRes.json();
            if (errData.error) errorMsg = errData.error;
          } catch (e) {}
          throw new Error(errorMsg);
        }
        
        const gradeData = await gradeRes.json();
        
        gradingSpinner.style.display = "none";
        gradingResults.style.display = "block";
        
        document.getElementById("grade-score").textContent = gradeData.grade;
        document.getElementById("grade-feedback").textContent = gradeData.feedback;
        
      } catch (err) {
        gradingSpinner.style.display = "none";
        gradingResults.style.display = "block";
        document.getElementById("grade-score").textContent = "N/A";
        document.getElementById("grade-feedback").textContent = "Error al calificar: " + err.message;
      }

    } catch (e) {
      alert("Error al entregar tarea: " + e.message);
    }
  });
}


function showStudentProfile() {
  document.getElementById("student-placeholder-msg").style.display = "none";
  document.getElementById("student-analytics-portal").style.display = "none";
  const mainPortal = document.getElementById("student-course-portal");
  if (mainPortal) mainPortal.style.display = "none";
  document.getElementById("student-profile-portal").style.display = "block";
  
  if (studentLearningProfile) {
    document.getElementById("vark-test-section").style.display = "none";
    document.getElementById("vark-results-section").style.display = "block";
    renderVarkResults(studentLearningProfile);
  } else {
    document.getElementById("vark-results-section").style.display = "none";
    document.getElementById("vark-test-section").style.display = "block";
    loadVarkTest();
  }
}

function showStudentAnalytics() {
  document.getElementById("student-placeholder-msg").style.display = "none";
  document.getElementById("student-profile-portal").style.display = "none";
  const mainPortal = document.getElementById("student-course-portal");
  if (mainPortal) mainPortal.style.display = "none";
  document.getElementById("student-analytics-portal").style.display = "block";

  loadStudentAnalyticsPortal();
}

async function loadStudentAnalyticsPortal() {
  const studentId = currentUser ? currentUser.username : "VinicioPrueba";
  try {
    const res = await fetch(`/api/student/analytics/${studentId}`);
    if (!res.ok) return;
    const data = await res.json();

    // 1. KPIs
    document.getElementById("kpi-avg-score").textContent = `${data.avg_score}/100`;
    document.getElementById("kpi-exams-count").textContent = data.exams_completed;
    document.getElementById("kpi-mastered-count").textContent = data.mastered_topics_count;
    document.getElementById("kpi-gaps-count").textContent = data.active_gaps_count;

    // 2. Weekly Progress Bars
    const weeklyBarsContainer = document.getElementById("analytics-weekly-bars");
    if (data.exam_history && data.exam_history.length > 0) {
      weeklyBarsContainer.innerHTML = data.exam_history.map(ex => {
        const scoreColor = ex.score >= 80 ? '#16a34a' : (ex.score >= 60 ? '#d97706' : '#dc2626');
        return `
          <div>
            <div style="display: flex; justify-content: space-between; font-size: 0.85rem; margin-bottom: 0.2rem;">
              <strong>Semana ${ex.week_number}: ${escapeHTML(ex.week_title)}</strong>
              <span style="color: ${scoreColor}; font-weight: 700;">${ex.score}/100</span>
            </div>
            <div style="background: var(--border); height: 8px; border-radius: 4px; overflow: hidden;">
              <div style="background: ${scoreColor}; width: ${ex.score}%; height: 100%; border-radius: 4px; transition: width 0.5s;"></div>
            </div>
          </div>
        `;
      }).join("");
    } else {
      weeklyBarsContainer.innerHTML = `<div class="muted" style="font-size: 0.9rem;">Aún no has realizado ningún examen de práctica adaptativo. Realízalo en la pestaña Examen para ver tus analíticas aquí.</div>`;
    }

    // 3. VARK Profile Distribution
    const varkContainer = document.getElementById("analytics-vark-bars");
    const prof = data.vark_profile;
    if (prof && prof.dominant_style) {
      const tot = (prof.visual_score || 0) + (prof.aural_score || 0) + (prof.reading_score || 0) + (prof.kinesthetic_score || 0);
      const getPct = s => tot > 0 ? Math.round(((s || 0) / tot) * 100) : 0;
      
      varkContainer.innerHTML = `
        <div style="margin-bottom: 0.5rem; font-weight: 600; color: var(--primary);">Estilo Dominante: <span style="text-transform: capitalize; color: #2563eb;">${prof.dominant_style}</span></div>
        <div style="font-size: 0.8rem; display: flex; flex-direction: column; gap: 0.4rem;">
          <div>👁️ Visual: <strong>${getPct(prof.visual_score)}%</strong></div>
          <div>🎧 Auditivo: <strong>${getPct(prof.aural_score)}%</strong></div>
          <div>📖 Lectura: <strong>${getPct(prof.reading_score)}%</strong></div>
          <div>🖐️ Kinestésico: <strong>${getPct(prof.kinesthetic_score)}%</strong></div>
        </div>
      `;
    } else {
      varkContainer.innerHTML = `<div class="muted" style="font-size: 0.9rem;">Completa el Test VARK en tu perfil para conocer tus porcentajes de afinidad.</div>`;
    }

    // 4. Mastered vs Knowledge Gaps
    const masteredUl = document.getElementById("analytics-mastered-ul");
    const gapsUl = document.getElementById("analytics-gaps-ul");

    if (data.mastered_topics && data.mastered_topics.length > 0) {
      masteredUl.innerHTML = data.mastered_topics.map(t => `<li style="color: #16a34a; margin-bottom: 0.3rem;">${escapeHTML(t)}</li>`).join("");
    } else {
      masteredUl.innerHTML = `<li class="muted">No hay temas dominados aún.</li>`;
    }

    if (data.knowledge_gaps && data.knowledge_gaps.length > 0) {
      gapsUl.innerHTML = data.knowledge_gaps.map(g => `<li style="color: #dc2626; margin-bottom: 0.3rem;">${escapeHTML(g)}</li>`).join("");
    } else {
      gapsUl.innerHTML = `<li class="muted">¡Felicidades! No tienes brechas de conocimiento registradas.</li>`;
    }

  } catch (e) {
    console.error("Error loading analytics:", e);
  }
}

async function loadVarkTest() {
  const form = document.getElementById("form-vark-test");
  if (!form) return;
  form.innerHTML = '<span class="spinner"></span> Cargando inventario...';
  try {
    const res = await fetch("/api/student/vark-questions");
    const questions = await res.json();
    
    let html = "";
    questions.forEach((q, i) => {
      html += `<div style="margin-bottom: 2rem; background: var(--card-bg); border: 1px solid var(--border); padding: 1.5rem; border-radius: 8px;">`;
      html += `<h4 style="margin-top:0;">${i+1}. ${q.text}</h4>`;
      q.options.forEach(opt => {
        html += `
          <label style="display: block; margin-bottom: 0.5rem; padding: 0.5rem; border: 1px solid transparent; border-radius: 4px; cursor: pointer; transition: background 0.2s;" onmouseover="this.style.background='var(--bg)'" onmouseout="this.style.background='transparent'">
            <input type="radio" name="q_${q.id}" value="${opt.type}" required>
            ${opt.text}
          </label>
        `;
      });
      html += `</div>`;
    });
    
    html += `<button type="submit" class="primary" style="font-size: 1.1rem; padding: 0.8rem 2rem;">Enviar y Analizar mi Perfil</button>`;
    form.innerHTML = html;
    
    form.onsubmit = async (e) => {
      e.preventDefault();
      document.getElementById("vark-test-progress").style.display = "flex";
      
      const formData = new FormData(form);
      const answers = {};
      for (let [key, value] of formData.entries()) {
        answers[key.replace('q_', '')] = value;
      }
      
      try {
        const pRes = await fetch("/api/student/vark-test", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({ answers })
        });
        if (pRes.ok) {
          const data = await pRes.json();
          studentLearningProfile = data.profile;
          document.getElementById("vark-test-progress").style.display = "none";
          showStudentProfile(); // Show results
        }
      } catch (err) { console.error(err); }
    };
    
  } catch(e) {
    form.innerHTML = `<p class="error">Error cargando el test.</p>`;
  }
}

function renderVarkResults(profile) {
  const total = profile.visual_score + profile.aural_score + profile.reading_score + profile.kinesthetic_score;
  const getPct = (score) => total > 0 ? Math.round((score / total) * 100) : 0;
  
  const vPct = getPct(profile.visual_score);
  const aPct = getPct(profile.aural_score);
  const rPct = getPct(profile.reading_score);
  const kPct = getPct(profile.kinesthetic_score);
  
  document.getElementById("bar-visual").style.width = `${vPct}%`;
  document.getElementById("pct-visual").textContent = `${vPct}%`;
  
  document.getElementById("bar-aural").style.width = `${aPct}%`;
  document.getElementById("pct-aural").textContent = `${aPct}%`;
  
  document.getElementById("bar-reading").style.width = `${rPct}%`;
  document.getElementById("pct-reading").textContent = `${rPct}%`;
  
  document.getElementById("bar-kinesthetic").style.width = `${kPct}%`;
  document.getElementById("pct-kinesthetic").textContent = `${kPct}%`;
  
  document.getElementById("vark-dominant-label").innerHTML = `Tienes una alta preferencia <strong style="text-transform: capitalize;">${profile.dominant_style}</strong>`;
  
  let desc = "";
  if (profile.dominant_style === "visual") desc = "<strong>Estrategia recomendada:</strong> Dibuja mapas mentales de las lecturas, usa resaltadores de colores para agrupar conceptos, e intenta esquematizar la información antes de estudiarla.";
  else if (profile.dominant_style === "aural") desc = "<strong>Estrategia recomendada:</strong> Graba audios cortos resumiendo lo que acabas de leer, estudia en grupo discutiendo los temas o escucha podcasts relacionados al material.";
  else if (profile.dominant_style === "reading") desc = "<strong>Estrategia recomendada:</strong> Toma notas detalladas, reescribe los conceptos con tus propias palabras y elabora listas estructuradas para organizar tus ideas.";
  else if (profile.dominant_style === "kinesthetic") desc = "<strong>Estrategia recomendada:</strong> Aplica lo que lees en un mini-proyecto físico, usa simuladores, o intenta levantarte y caminar mientras repasas la información en tu mente.";
  else desc = "<strong>Estrategia recomendada:</strong> Eres sumamente adaptable. Mezcla lectura, videos y proyectos prácticos para retener mejor la información.";
  
  desc += "<br><br><small class='muted'><strong>💡 Dato clave:</strong> La Inteligencia Artificial adaptará tu contenido para integrar tus preferencias, pero el cerebro retiene mejor la información cuando la exponemos a <em>múltiples formatos a la vez</em>. Aprovecha toda la diversidad del material.</small>";
  
  document.getElementById("vark-dominant-desc").innerHTML = desc;
}


async function refreshStudentCourses() {
  const list = document.getElementById("student-course-list");
  list.innerHTML = "<li class='muted'>Cargando cursos...</li>";
  
  try {
    const res = await fetch("/api/syllabi");
    const syllabi = await res.json();
    list.innerHTML = "";
    
    const approvedSyllabi = syllabi.filter(s => s.approved_by);

    if (!approvedSyllabi.length) {
      list.innerHTML = "<li class='muted'>No hay cursos publicados para matricular en Costa Rica.</li>";
      return;
    }

    approvedSyllabi.forEach(s => {
      const li = document.createElement("li");
      li.innerHTML = `<strong>${escapeHTML(s.course_title)}</strong> <span style="font-size:0.75rem; color:var(--muted); float:right;">Matricular</span>`;
      li.dataset.syllabusId = s.id;
      
      li.addEventListener("click", () => {
        document.querySelectorAll("#student-course-list li").forEach(el => el.classList.remove("active"));
        li.classList.add("active");
        loadStudentCoursePortal(s);
      });
      list.appendChild(li);
    });
  } catch (e) {
    list.innerHTML = `<li class="error">Error: ${e.message}</li>`;
  }
}

async function loadStudentCoursePortal(syllabus) {
  activeStudentSyllabusId = syllabus.id;
  
  document.querySelector("#student-workspace .placeholder-msg").style.display = "none";
  document.getElementById("student-course-portal").style.display = "block";
  
  if (!studentLearningProfile) {
    document.getElementById("student-placeholder-msg").style.display = "block";
    document.getElementById("student-placeholder-msg").innerHTML = `
      <div style="text-align:center; padding: 2rem;">
        <h3 style="margin-bottom: 1rem;">🔒 Perfil Requerido</h3>
        <p style="margin-bottom: 1.5rem;">Para poder adaptar tu material de estudio automáticamente usando Inteligencia Artificial, necesitamos que completes tu Perfil de Aprendizaje VARK.</p>
        <button class="primary" onclick="showStudentProfile()">Completar Mi Perfil Ahora</button>
      </div>
    `;
    document.getElementById("student-course-portal").style.display = "none";
    document.getElementById("student-profile-portal").style.display = "none";
    return;
  }
  document.getElementById("student-placeholder-msg").style.display = "none";
  document.getElementById("student-profile-portal").style.display = "none";

  document.getElementById("student-course-title").textContent = `Aula Virtual: ${syllabus.course_title}`;

  // Fetch syllabus weekly contents
  const studentWeeksList = document.getElementById("student-weeks-list");
  studentWeeksList.innerHTML = "<li class='muted'>Cargando clases...</li>";

  try {
    const res = await fetch(`/api/weekly-contents/${syllabus.id}`);
    const contents = await res.json();
    studentWeeksList.innerHTML = "";
    activeStudentWeeks = contents;

    contents.forEach(week => {
      const li = document.createElement("li");
      li.textContent = `Semana ${week.week_number}: ${week.title}`;
      li.dataset.weekNum = week.week_number;
      
      if (week.reading_material) {
        li.classList.add("has-content");
      }

      li.addEventListener("click", () => {
        document.querySelectorAll("#student-weeks-list li").forEach(el => el.classList.remove("active"));
        li.classList.add("active");
        loadStudentSelectedWeek(week);
      });
      studentWeeksList.appendChild(li);
    });

    if (studentWeeksList.firstChild) studentWeeksList.firstChild.click();
  } catch (e) {
    studentWeeksList.innerHTML = `<li class="error">Error: ${e.message}</li>`;
  }
}

async function loadStudentSelectedWeek(week) {
  document.getElementById("student-selected-week-title").textContent = `Semana ${week.week_number}: ${week.title}`;
  document.getElementById("submission-weekly-content-id").value = week.id;

  const noMaterial = document.getElementById("student-no-material-msg");
  const materialSection = document.getElementById("student-material-section");
  document.getElementById("student-media-container").style.display = "none";

  if (!week.reading_material) {
    noMaterial.style.display = "block";
    materialSection.style.display = "none";
  } else {
    noMaterial.style.display = "none";
    materialSection.style.display = "block";
    
    document.getElementById("reading-style-badge").innerHTML = "Contenido Base 📄";
            document.getElementById("student-reading-material").innerHTML = week.reading_material;

    const adaptBtn = document.getElementById("btn-adapt-reading");
    if (adaptBtn) {
      // clear previous listeners
      const newBtn = adaptBtn.cloneNode(true);
      adaptBtn.parentNode.replaceChild(newBtn, adaptBtn);
      
      newBtn.addEventListener("click", async () => {
        document.getElementById("adapt-progress").style.display = "block";
        newBtn.disabled = true;
        const styleSelect = document.getElementById("select-adapt-style").value;
        let profileToUse = studentLearningProfile;
        if (styleSelect !== "auto") {
            profileToUse = { dominant_style: styleSelect };
        }
        
        try {
          const res = await fetch("/api/generate-reading", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              syllabus_id: activeStudentSyllabusId,
              week_number: week.week_number,
              force_rebuild: true,
              learning_profile: profileToUse
            })
          });
          if (res.ok) {
            const data = await res.json();
            
            let htmlContent = "";
            if (data.audio_url) {
                htmlContent += `<div style="margin-bottom: 20px;"><audio controls style="width: 100%; border-radius: 8px;"><source src="${data.audio_url}" type="audio/mpeg"></audio></div>`;
            }
            if (data.video_url) {
                htmlContent += `<div style="margin-bottom: 20px;"><a href="${data.video_url}" target="_blank" style="display:inline-block; padding: 10px 15px; background: #2563eb; color: white; text-decoration: none; border-radius: 6px;">🎥 Ver Clase Magistral en Video (HeyGen)</a></div>`;
            }
            if (data.heygen_video_id) {
                htmlContent += `
                <div id="heygen-video-container-${data.heygen_video_id}" style="margin-bottom: 20px; padding: 20px; border: 1px solid var(--border); border-radius: 8px; text-align: center; background: var(--card-bg);">
                    <div class="pipeline-progress-mini" style="display: flex; justify-content: center; align-items: center; gap: 10px;">
                        <span class="spinner"></span> 
                        <strong>⏳ Renderizando tu Avatar 3D...</strong> Esto tomará entre 1 y 3 minutos.
                    </div>
                </div>`;
            }
            if (data.anki_url) {
                htmlContent += `<div style="margin-bottom: 20px;"><a href="${data.anki_url}" download style="display:inline-block; padding: 10px 15px; background: #16a34a; color: white; text-decoration: none; border-radius: 6px;">🧠 Descargar Mazo de Anki (.apkg)</a></div>`;
            }
            
            document.getElementById("student-reading-material").innerHTML = htmlContent + data.reading_material;
            
            if (data.flashcards && data.flashcards.length > 0) {
              initFlashcardsInteractive(data.flashcards);
            }
            
            // Render Mermaid diagrams if any were generated
            setTimeout(() => {
              if (window.mermaid) {
                try {
                  window.mermaid.run({ querySelector: '.mermaid' });
                } catch(e) { console.error('Mermaid render error', e); }
              }
            }, 100);

            // update badge
            const badge = document.getElementById("reading-style-badge");
            badge.innerHTML = "Contenido Adaptado ✨ (" + (profileToUse?.dominant_style || "Base") + ")";

            if (data.heygen_video_id) {
                const pollInterval = setInterval(async () => {
                    try {
                        const statusRes = await fetch(`/api/video-status/${data.heygen_video_id}`);
                        if (statusRes.ok) {
                            const statusData = await statusRes.json();
                            if (statusData.status === "completed" && statusData.video_url) {
                                clearInterval(pollInterval);
                                const container = document.getElementById(`heygen-video-container-${data.heygen_video_id}`);
                                if (container) {
                                    container.innerHTML = `<video controls style="width: 100%; border-radius: 8px;"><source src="${statusData.video_url}" type="video/mp4"></video>`;
                                }
                            } else if (statusData.status === "failed") {
                                clearInterval(pollInterval);
                                const container = document.getElementById(`heygen-video-container-${data.heygen_video_id}`);
                                if (container) {
                                    container.innerHTML = `<div style="color: red;">❌ Error renderizando el avatar 3D.</div>`;
                                }
                            }
                        }
                    } catch(e) {
                        console.error("Error polling video status", e);
                    }
                }, 10000); // poll every 10 seconds
            }
          }
        } catch (e) {
          alert("Error adaptando el contenido.");
        } finally {
          document.getElementById("adapt-progress").style.display = "none";
          newBtn.disabled = false;
        }
      });
    }

    document.getElementById("student-assignment-prompt").textContent = week.assignment_prompt || "Responda a las preguntas correspondientes.";
    
    // Reset submission textbox
    document.getElementById("submission-text").value = "";
    
    // Check if student has already submitted for this week
    try {
      const res = await fetch(`/api/submissions/${currentUser}`);
      const submissions = await res.json();
      const existing = submissions.find(s => s.weekly_content_id === week.id);
      
      const gradeSection = document.getElementById("student-grade-section");
      const gradingSpinner = document.getElementById("grading-spinner");
      const gradingResults = document.getElementById("grading-results");
      
      if (existing) {
        document.getElementById("submission-text").value = existing.submitted_text;
        appendLog(`Cargada respuesta ya entregada para Semana ${week.week_number}.`);
        
        if (existing.grade !== null && existing.grade !== undefined) {
          gradeSection.style.display = "block";
          gradingSpinner.style.display = "none";
          gradingResults.style.display = "block";
          document.getElementById("grade-score").textContent = existing.grade;
          document.getElementById("grade-feedback").textContent = existing.feedback;
        } else {
          gradeSection.style.display = "none";
        }
      } else {
        gradeSection.style.display = "none";
      }
    } catch (e) {
      console.error("Failed to fetch existing student submission:", e);
    }

    // Auto-extract flashcards from week content if present
    if (week.reading_material) {
      const parsedCards = extractFlashcardsFromHTML(week.reading_material);
      if (parsedCards.length > 0) {
        initFlashcardsInteractive(parsedCards);
      } else {
        const container = document.getElementById("flashcard-interactive-section");
        if (container) container.style.display = "none";
      }
    }

    // Initialize 3-step navigation & handlers
    setupStepTabs(week);
  }
}

// ────────────────────────────────────────────────────────────────────────
// 3D Interactive Flashcards Controller
// ────────────────────────────────────────────────────────────────────────

let currentFlashcardDeck = [];
let currentFlashcardIndex = 0;

function extractFlashcardsFromHTML(htmlText) {
  const cards = [];
  const div = document.createElement("div");
  div.innerHTML = htmlText;

  const detailsList = div.querySelectorAll("details.flashcard");
  detailsList.forEach(d => {
    const summary = d.querySelector("summary")?.textContent?.trim();
    const body = d.querySelector(".flashcard-body")?.textContent?.trim();
    if (summary && body) {
      cards.push({ front: summary, back: body });
    }
  });

  if (cards.length === 0) {
    const headers = div.querySelectorAll("h3, h4");
    const paragraphs = div.querySelectorAll("p");
    for (let i = 0; i < Math.min(headers.length, paragraphs.length); i++) {
      const h = headers[i].textContent.trim();
      const p = paragraphs[i].textContent.trim();
      if (h && p) {
        cards.push({ front: h, back: p.substring(0, 180) + (p.length > 180 ? "..." : "") });
      }
    }
  }

  return cards;
}

function initFlashcardsInteractive(flashcards) {
  const container = document.getElementById("flashcard-interactive-section");
  
  // Client-side defensive filter against junk titles or empty cards
  const cleanedDeck = (flashcards || []).filter(c => {
    if (!c || !c.front || !c.back) return false;
    const f = c.front.toLowerCase();
    if (f.includes("módulo de la semana") || f.includes("click para revelar") || f.includes("1. introducción") || f.includes("tabla de contenido")) return false;
    return c.front.trim().length >= 4 && c.back.trim().length >= 8;
  });

  if (cleanedDeck.length === 0) {
    if (container) container.style.display = "none";
    return;
  }

  currentFlashcardDeck = [...cleanedDeck];
  currentFlashcardIndex = 0;

  if (container) container.style.display = "block";
  renderCurrentFlashcard();

  const stage = document.getElementById("flashcard-stage");
  const btnFlip = document.getElementById("btn-flashcard-flip");
  const btnMastered = document.getElementById("btn-flashcard-mastered");
  const btnRepeat = document.getElementById("btn-flashcard-repeat");

  function toggleFlip(e) {
    if (e && e.target && (e.target.tagName === "BUTTON" || e.target.closest("button"))) return;
    if (window.getSelection && window.getSelection().toString().length > 0) return;
    if (stage) stage.classList.toggle("flipped");
  }

  if (stage) stage.onclick = toggleFlip;
  if (btnFlip) btnFlip.onclick = toggleFlip;

  if (btnMastered) {
    btnMastered.onclick = () => {
      if (stage) stage.classList.remove("flipped");
      currentFlashcardIndex++;
      setTimeout(renderCurrentFlashcard, 200);
    };
  }

  if (btnRepeat) {
    btnRepeat.onclick = () => {
      const card = currentFlashcardDeck[currentFlashcardIndex];
      if (card) currentFlashcardDeck.push(card);
      if (stage) stage.classList.remove("flipped");
      currentFlashcardIndex++;
      setTimeout(renderCurrentFlashcard, 200);
    };
  }
}

function renderCurrentFlashcard() {
  const container = document.getElementById("flashcard-interactive-section");

  if (currentFlashcardIndex >= currentFlashcardDeck.length) {
    if (container) {
      container.innerHTML = `
        <div style="text-align: center; padding: 2rem;">
          <h3 style="color: #16a34a; margin-top: 0;">🎉 ¡Excelente! Has completado las flashcards</h3>
          <p style="color: var(--text-muted);">Has repasado todos los conceptos clave de esta lección.</p>
          <button type="button" class="primary" onclick="initFlashcardsInteractive(currentFlashcardDeck)">🔄 Volver a Repasar el Mazo</button>
        </div>
      `;
    }
    return;
  }

  const card = currentFlashcardDeck[currentFlashcardIndex];
  const counter = document.getElementById("flashcard-counter");
  const front = document.getElementById("flashcard-front-text");
  const back = document.getElementById("flashcard-back-text");

  if (counter) counter.textContent = `Tarjeta ${currentFlashcardIndex + 1} de ${currentFlashcardDeck.length}`;
  if (front) front.innerHTML = escapeHTML(card.front);
  if (back) {
    const lines = (card.back || "").split("\n").map(l => l.trim()).filter(l => l.length > 0);
    if (lines.length > 1) {
      back.innerHTML = lines.map(l => `<p style="margin: 0 0 0.5rem 0; line-height: 1.55;">${escapeHTML(l)}</p>`).join("");
    } else {
      back.textContent = card.back;
    }
  }
}

// ────────────────────────────────────────────────────────────────────────
// 3-Step Modality Workflow: Lecture -> Exam Mode -> Live AI Tutor
// ────────────────────────────────────────────────────────────────────────

let currentExamIteration = 1;
let examHistory = [];
let activeWeeklyContentId = null;
let tutorHistory = [];

function setupStepTabs(week) {
  activeWeeklyContentId = week.id;
  
  const tab1 = document.getElementById("tab-step-1");
  const tab2 = document.getElementById("tab-step-2");
  const tab3 = document.getElementById("tab-step-3");
  
  const panel1 = document.getElementById("step-1-container");
  const panel2 = document.getElementById("step-2-container");
  const panel3 = document.getElementById("step-3-container");

  function switchStep(stepNum) {
    [tab1, tab2, tab3].forEach((t, idx) => {
      if (idx + 1 === stepNum) {
        t.classList.remove("ghost");
        t.classList.add("primary");
      } else {
        t.classList.remove("primary");
        t.classList.add("ghost");
      }
    });

    panel1.style.display = stepNum === 1 ? "block" : "none";
    panel2.style.display = stepNum === 2 ? "block" : "none";
    panel3.style.display = stepNum === 3 ? "block" : "none";

    if (stepNum === 2 && (!examHistory || examHistory.length === 0)) {
      startExam(week.id);
    }
    if (stepNum === 3) {
      initLiveTutor(week.id);
    }
  }

  tab1.onclick = () => switchStep(1);
  tab2.onclick = () => switchStep(2);
  tab3.onclick = () => switchStep(3);

  const goTutorBtn = document.getElementById("btn-go-to-tutor");
  if (goTutorBtn) {
    goTutorBtn.onclick = () => switchStep(3);
  }

  // Setup Exam Submit Button
  const btnExam = document.getElementById("btn-submit-exam-answer");
  if (btnExam) {
    btnExam.onclick = () => submitExamAnswer();
  }

  // Setup Tutor Send Button & Text Input
  const btnTutorSend = document.getElementById("btn-send-tutor-text");
  const tutorInput = document.getElementById("tutor-user-text");
  if (btnTutorSend && tutorInput) {
    tutorInput.addEventListener("input", () => stopActiveTutorAudio());
    btnTutorSend.onclick = () => {
      const val = tutorInput.value.trim();
      if (val) {
        sendTutorMessage(val);
        tutorInput.value = "";
      }
    };
    tutorInput.onkeydown = (e) => {
      if (e.key === "Enter") {
        btnTutorSend.click();
      }
    };
  }

  // Setup Mic toggle with Web Speech API
  const btnMic = document.getElementById("btn-tutor-mic");
  if (btnMic) {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SpeechRecognition) {
      const recognition = new SpeechRecognition();
      recognition.lang = "es-ES";
      recognition.continuous = false;

      recognition.onstart = () => {
        stopActiveTutorAudio();
        btnMic.textContent = "🎙️ Escuchando...";
        btnMic.style.background = "#dc2626";
      };
      recognition.onresult = (event) => {
        const transcript = event.results[0][0].transcript;
        if (tutorInput) tutorInput.value = transcript;
        sendTutorMessage(transcript);
      };
      recognition.onend = () => {
        btnMic.textContent = "🎙️ Iniciar / Hablar con Tutor AI";
        btnMic.style.background = "";
      };

      btnMic.onclick = () => {
        stopActiveTutorAudio();
        try { recognition.start(); } catch(e) { recognition.stop(); }
      };
    } else {
      btnMic.onclick = () => {
        alert("Tu navegador no soporta reconocimiento de voz por micrófono directo. Puedes escribir tus preguntas en el campo de texto.");
      };
    }
  }

  switchStep(1);
}

async function startExam(weeklyContentId) {
  currentExamIteration = 1;
  examHistory = [];
  document.getElementById("exam-box").style.display = "block";
  document.getElementById("exam-result-summary").style.display = "none";
  document.getElementById("exam-feedback-box").style.display = "none";
  document.getElementById("exam-progress-badge").textContent = `Iteración 1 de 3`;
  document.getElementById("exam-question-text").textContent = "Cargando primera pregunta adaptativa...";
  
  try {
    const res = await fetch("/api/exam/step", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        weekly_content_id: weeklyContentId,
        student_id: currentUser || "VinicioPrueba",
        history: [],
        iteration: 1
      })
    });
    if (res.ok) {
      const data = await res.json();
      document.getElementById("exam-question-text").textContent = data.next_question || data.feedback;
      examHistory.push({ role: "examiner", content: data.next_question || data.feedback });
    }
  } catch (e) {
    console.error("Exam start error:", e);
  }
}

async function submitExamAnswer() {
  const answerInput = document.getElementById("exam-user-answer");
  const answerText = answerInput ? answerInput.value.trim() : "";
  if (!answerText) return;

  const btn = document.getElementById("btn-submit-exam-answer");
  if (btn) btn.disabled = true;
  
  examHistory.push({ role: "student", content: answerText });
  if (answerInput) answerInput.value = "";

  currentExamIteration++;

  try {
    const res = await fetch("/api/exam/step", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        weekly_content_id: activeWeeklyContentId,
        student_id: currentUser || "VinicioPrueba",
        history: examHistory,
        iteration: currentExamIteration
      })
    });

    if (res.ok) {
      const data = await res.json();

      // Show feedback
      const feedbackBox = document.getElementById("exam-feedback-box");
      feedbackBox.style.display = "block";
      feedbackBox.className = data.is_correct ? "alert alert-success" : "alert alert-warning";
      feedbackBox.innerHTML = `<strong>${data.is_correct ? "¡Correcto! 🎉" : "Pista / Retroalimentación 💡"}</strong>: ${escapeHTML(data.feedback)}`;

      if (data.is_finished) {
        document.getElementById("exam-box").style.display = "none";
        document.getElementById("exam-result-summary").style.display = "block";
        document.getElementById("exam-final-score").textContent = data.final_grade;

        const masteredUl = document.getElementById("exam-mastered-list");
        masteredUl.innerHTML = (data.mastered_topics && data.mastered_topics.length > 0)
          ? data.mastered_topics.map(t => `<li>${escapeHTML(t)}</li>`).join("")
          : "<li>Evaluación general completada</li>";

        const gapsUl = document.getElementById("exam-gaps-list");
        gapsUl.innerHTML = (data.knowledge_gaps && data.knowledge_gaps.length > 0)
          ? data.knowledge_gaps.map(g => `<li>${escapeHTML(g)}</li>`).join("")
          : "<li>¡Excelente! No se detectaron brechas graves.</li>";

      } else {
        document.getElementById("exam-progress-badge").textContent = `Iteración ${currentExamIteration} de 3`;
        document.getElementById("exam-question-text").textContent = data.next_question || "Siguiente pregunta...";
        if (data.next_question) {
          examHistory.push({ role: "examiner", content: data.next_question });
        }
      }
    }
  } catch (e) {
    console.error("Error submitting exam answer:", e);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function initLiveTutor(weeklyContentId) {
  const chatHistory = document.getElementById("tutor-chat-history");
  chatHistory.innerHTML = "<div class='pipeline-progress-mini'><span class='spinner'></span> Conectando con el Tutor AI y sintetizando audio inicial...</div>";

  const voiceSelect = document.getElementById("select-tutor-voice");
  const selectedVoice = voiceSelect ? voiceSelect.value : "alloy";

  try {
    const res = await fetch("/api/tutor/init", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        weekly_content_id: weeklyContentId,
        student_id: currentUser || "VinicioPrueba",
        voice: selectedVoice
      })
    });

    if (res.ok) {
      const data = await res.json();
      const diag = data.context?.diagnostic;
      const gapsSummary = document.getElementById("tutor-gaps-summary");
      if (diag && diag.knowledge_gaps && diag.knowledge_gaps.length > 0) {
        gapsSummary.innerHTML = `Temas a repasar en esta sesión: <strong>${diag.knowledge_gaps.join(", ")}</strong>`;
      } else {
        gapsSummary.innerHTML = "Revisión socrática general sobre la lección de la semana.";
      }

      tutorHistory = [{ role: "tutor", content: data.greeting }];
      renderTutorChatHistory();

      if (data.audio_url) {
        playTutorAudio(data.audio_url);
      }
    }
  } catch (e) {
    console.error("Error initializing tutor:", e);
  }
}

function renderTutorChatHistory() {
  const chatHistory = document.getElementById("tutor-chat-history");
  chatHistory.innerHTML = tutorHistory.map(h => {
    if (h.isAchievement) {
      return `
        <div style="padding: 0.8rem; background: #f0fdf4; border-radius: 8px; margin-bottom: 0.8rem; border: 1px solid #bbf7d0; border-left: 4px solid #16a34a; color: #15803d; font-size: 0.9rem;">
          <strong>🎯 Logro de Dominio:</strong> ${escapeHTML(h.content)}
        </div>
      `;
    }
    const isTutor = h.role === "tutor" || h.role === "assistant";
    const isPlaceholder = h.isPlaceholder;
    return `
      <div style="padding: 0.8rem; background: ${isTutor ? 'var(--card-bg)' : 'var(--bg)'}; border-radius: 8px; margin-bottom: 0.8rem; border-left: 3px solid ${isTutor ? '#2563eb' : '#16a34a'};">
        <strong>${isTutor ? '👨‍🏫 Tutor AI' : '👤 Tú'}:</strong> ${isPlaceholder ? '<span class="spinner" style="display:inline-block; vertical-align:middle; margin-right:6px;"></span> <em>' + escapeHTML(h.content) + '</em>' : escapeHTML(h.content)}
      </div>
    `;
  }).join("");
  chatHistory.scrollTop = chatHistory.scrollHeight;
}

function stopActiveTutorAudio() {
  const audioPlayer = document.getElementById("tutor-audio-player");
  const badge = document.getElementById("tutor-audio-bargein-badge");

  if (audioPlayer && !audioPlayer.paused) {
    audioPlayer.pause();
    audioPlayer.currentTime = 0;
    console.log("⚡ Barge-in: Voz del Tutor AI interrumpida inmediatamente por interacción del usuario.");
    
    if (badge) {
      badge.style.display = "inline-block";
      badge.style.background = "#dc2626";
      badge.innerHTML = "⚡ <strong>Interrumpiste al Tutor. Escuchándote...</strong>";
      setTimeout(() => {
        if (audioPlayer.paused) badge.style.display = "none";
      }, 3000);
    }
  }
}

let isVisualizerRunning = false;

function initTutorAudioVisualizer() {
  const canvas = document.getElementById("tutor-voice-canvas");
  const audioPlayer = document.getElementById("tutor-audio-player");
  if (!canvas || !audioPlayer || isVisualizerRunning) return;

  const ctx = canvas.getContext("2d");
  isVisualizerRunning = true;

  function renderWaveform() {
    requestAnimationFrame(renderWaveform);

    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const numBars = 22;
    const barWidth = (canvas.width / numBars) - 3;
    const isPlaying = audioPlayer && !audioPlayer.paused;

    for (let i = 0; i < numBars; i++) {
      let barHeight = 4;
      if (isPlaying) {
        const time = Date.now() * 0.009;
        const wave = Math.sin(time + i * 0.45) * 0.5 + 0.5;
        barHeight = Math.max(6, wave * (canvas.height - 8));
      } else {
        barHeight = 4 + Math.sin(Date.now() * 0.002 + i * 0.3) * 2;
      }

      const x = i * (barWidth + 3) + 6;
      const y = (canvas.height - barHeight) / 2;

      const gradient = ctx.createLinearGradient(0, y, 0, y + barHeight);
      if (isPlaying) {
        gradient.addColorStop(0, "#2563eb");
        gradient.addColorStop(1, "#3b82f6");
      } else {
        gradient.addColorStop(0, "#94a3b8");
        gradient.addColorStop(1, "#cbd5e1");
      }

      ctx.fillStyle = gradient;
      ctx.beginPath();
      if (ctx.roundRect) {
        ctx.roundRect(x, y, barWidth, barHeight, 3);
      } else {
        ctx.rect(x, y, barWidth, barHeight);
      }
      ctx.fill();
    }
  }

  renderWaveform();
}

function playTutorAudio(url) {
  const audioPlayer = document.getElementById("tutor-audio-player");
  const badge = document.getElementById("tutor-audio-bargein-badge");

  if (audioPlayer) {
    audioPlayer.src = url;
    audioPlayer.style.display = "block";
    
    if (badge) {
      badge.style.display = "inline-block";
      badge.style.background = "#2563eb";
      badge.innerHTML = '🗣️ <strong>Tutor AI Hablando...</strong> <span style="font-size: 0.75rem; opacity: 0.9;">(Escribe o usa el micrófono para interrumpir)</span>';
    }

    initTutorAudioVisualizer();

    audioPlayer.onended = () => {
      if (badge) badge.style.display = "none";
    };

    audioPlayer.play().catch(e => console.log("Audio autoplay prevented", e));
  }
}

async function sendTutorMessage(text) {
  if (!text) return;
  stopActiveTutorAudio();

  const voiceSelect = document.getElementById("select-tutor-voice");
  const selectedVoice = voiceSelect ? voiceSelect.value : "alloy";

  // 1. Instantly append student message
  tutorHistory.push({ role: "student", content: text });
  
  // 2. Instantly append placeholder for AI Tutor so UX feels instant
  tutorHistory.push({ role: "tutor", content: "Generando respuesta y grabando audio...", isPlaceholder: true });
  renderTutorChatHistory();

  try {
    const res = await fetch("/api/tutor/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        weekly_content_id: activeWeeklyContentId,
        student_id: currentUser || "VinicioPrueba",
        user_message: text,
        history: tutorHistory.filter(h => !h.isPlaceholder && !h.isAchievement),
        voice: selectedVoice
      })
    });

    if (res.ok) {
      const data = await res.json();
      // Remove placeholder
      tutorHistory = tutorHistory.filter(h => !h.isPlaceholder);

      // If a gap was resolved during this turn, insert achievement banner
      if (data.resolved_gaps && data.resolved_gaps.length > 0) {
        data.resolved_gaps.forEach(gap => {
          tutorHistory.push({ 
            role: "tutor", 
            content: `🎉 ¡BRECHA RESUELTA! Has demostrado dominio total en: "${gap}". El tema ha sido movido a Temas Dominados.`,
            isAchievement: true 
          });
        });
        loadStudentAnalyticsPortal();
      }

      tutorHistory.push({ role: "tutor", content: data.response_text });
      renderTutorChatHistory();
      if (data.audio_url) {
        playTutorAudio(data.audio_url);
      }
    } else {
      tutorHistory = tutorHistory.filter(h => !h.isPlaceholder);
      tutorHistory.push({ role: "tutor", content: "Hubo un pequeño retraso al conectar. ¿Podrías intentar responder nuevamente?" });
      renderTutorChatHistory();
    }
  } catch (e) {
    console.error("Error in tutor chat:", e);
    tutorHistory = tutorHistory.filter(h => !h.isPlaceholder);
    renderTutorChatHistory();
  }
}


// ────────────────────────────────────────────────────────────────────────
// Errors & Helpers
// ────────────────────────────────────────────────────────────────────────

function showError(text) {
  document.getElementById("error-message").textContent = text;
  document.getElementById("panel-researcher").querySelectorAll(".screen").forEach(s => s.classList.remove("active"));
  document.getElementById("screen-error").classList.add("active");
}

function escapeHTML(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// ────────────────────────────────────────────────────────────────────────
// Saved Runs / Demo Packages Client Logic
// ────────────────────────────────────────────────────────────────────────

async function refreshSavedRuns() {
  const ul = document.getElementById("saved-runs-ul");
  if (!ul) return;
  ul.innerHTML = "<li class='muted'>Cargando...</li>";
  
  try {
    const res = await fetch("/api/saved-runs");
    const data = await res.json();
    ul.innerHTML = "";
    
    if (!data.runs || !data.runs.length) {
      ul.innerHTML = "<li class='muted'>No hay ejecuciones guardadas. Haz una ejecución real y guárdala abajo.</li>";
      return;
    }
    
    data.runs.forEach(run => {
      const li = document.createElement("li");
      li.style.display = "flex";
      li.style.justifyContent = "space-between";
      li.style.alignItems = "center";
      li.style.padding = "0.6rem 0.8rem";
      
      const infoSpan = document.createElement("span");
      infoSpan.innerHTML = `<strong>${escapeHTML(run.sector)}</strong> <span style="font-size:0.75rem; color:var(--muted); margin-left:0.5rem;">(${run.filename})</span>`;
      
      const metaSpan = document.createElement("span");
      metaSpan.style.fontSize = "0.75rem";
      metaSpan.style.color = "var(--muted)";
      metaSpan.style.marginRight = "1rem";
      let details = [];
      if (run.has_syllabus) details.push("Syllabus");
      if (run.has_readings) details.push("Lecturas");
      metaSpan.textContent = details.length ? `[${details.join(" + ")}]` : "[Solo brecha]";
      
      const btnGroup = document.createElement("div");
      btnGroup.style.display = "flex";
      btnGroup.style.gap = "0.4rem";
      
      const loadBtn = document.createElement("button");
      loadBtn.type = "button";
      loadBtn.className = "ghost";
      loadBtn.style.padding = "0.25rem 0.6rem";
      loadBtn.style.fontSize = "0.8rem";
      loadBtn.textContent = "Cargar";
      loadBtn.addEventListener("click", async (e) => {
        e.stopPropagation();
        await loadSavedRun(run.filename);
      });
      
      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.className = "ghost";
      delBtn.style.padding = "0.25rem 0.6rem";
      delBtn.style.fontSize = "0.8rem";
      delBtn.style.color = "var(--critical)";
      delBtn.textContent = "Eliminar";
      delBtn.addEventListener("click", async (e) => {
        e.stopPropagation();
        if (confirm(`¿Estás seguro de eliminar la ejecución guardada "${run.filename}"?`)) {
          await deleteSavedRun(run.filename);
        }
      });
      
      btnGroup.appendChild(loadBtn);
      btnGroup.appendChild(delBtn);
      
      li.appendChild(infoSpan);
      li.appendChild(metaSpan);
      li.appendChild(btnGroup);
      ul.appendChild(li);
    });
  } catch (e) {
    ul.innerHTML = `<li class="error">Error: ${e.message}</li>`;
  }
}

async function loadSavedRun(filename) {
  showDemoStatus("Restaurando ejecución y base de datos...", "info");
  try {
    const res = await fetch("/api/saved-runs/load", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename })
    });
    
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Error al cargar la ejecución.");
    
    showDemoStatus(`¡Ejecución de "${data.sector}" cargada con éxito! Todos los paneles han sido actualizados.`, "success");
    
    // Set the sector input box to this sector
    const sectorInput = document.getElementById("sector");
    if (sectorInput) sectorInput.value = data.sector;
    
    // Refresh other tabs
    refreshApproverGaps();
    refreshProfessorSyllabi();
    refreshStudentCourses();
    
    // Load this gap report for review right away to show the user it was loaded
    const gapsRes = await fetch("/api/gaps");
    const gaps = await gapsRes.json();
    const loadedGap = gaps.find(g => g.sector === data.sector);
    if (loadedGap) {
      currentGapData = {
        id: loadedGap.id,
        sector: loadedGap.sector,
        gap_analysis: loadedGap.gap_analysis
      };
      
      const hasSyllabus = loadedGap.approved_by !== null;
      
      document.getElementById("screen-input").classList.remove("active");
      document.getElementById("screen-pipeline").classList.remove("active");
      
      if (hasSyllabus) {
        document.getElementById("screen-review").classList.remove("active");
        document.getElementById("screen-done").classList.add("active");
      } else {
        document.getElementById("screen-done").classList.remove("active");
        document.getElementById("screen-review").classList.add("active");
        renderGapReview(loadedGap.gap_analysis);
      }
    }
    
  } catch (e) {
    showDemoStatus(`Error al cargar: ${e.message}`, "error");
  }
}

async function deleteSavedRun(filename) {
  try {
    const res = await fetch("/api/saved-runs/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename })
    });
    if (!res.ok) {
      const data = await res.json();
      throw new Error(data.error || "Error al eliminar.");
    }
    refreshSavedRuns();
  } catch (e) {
    alert("Error al eliminar demo: " + e.message);
  }
}

async function saveActiveRunAsDemo() {
  const sectorInput = document.getElementById("sector");
  const sector = (currentGapData ? currentGapData.sector : (sectorInput ? sectorInput.value.trim() : ""));
  if (!sector) {
    showDemoStatus("Error: No hay ningún sector activo o ingresado para guardar.", "error");
    return;
  }
  
  const nameInput = document.getElementById("save-demo-name");
  const name = nameInput ? nameInput.value.trim() : "";
  
  showDemoStatus("Guardando estado actual de la ejecución...", "info");
  try {
    const res = await fetch("/api/saved-runs/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sector, name })
    });
    
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Error al guardar.");
    
    showDemoStatus(`¡Ejecución guardada correctamente como "${data.filename}"!`, "success");
    if (nameInput) nameInput.value = "";
    refreshSavedRuns();
  } catch (e) {
    showDemoStatus(`Error al guardar: ${e.message}`, "error");
  }
}

function showDemoStatus(msg, type) {
  const alertDiv = document.getElementById("demo-action-status");
  if (!alertDiv) return;
  alertDiv.textContent = msg;
  alertDiv.className = "alert";
  if (type === "success") {
    alertDiv.classList.add("alert-success");
    alertDiv.style.background = "rgba(39, 174, 96, 0.1)";
    alertDiv.style.color = "var(--covered)";
    alertDiv.style.border = "1px solid rgba(39, 174, 96, 0.2)";
  } else if (type === "error") {
    alertDiv.style.background = "rgba(192, 57, 43, 0.1)";
    alertDiv.style.color = "var(--critical)";
    alertDiv.style.border = "1px solid rgba(192, 57, 43, 0.2)";
  } else {
    alertDiv.style.background = "rgba(45, 106, 159, 0.1)";
    alertDiv.style.color = "var(--secondary)";
    alertDiv.style.border = "1px solid rgba(45, 106, 159, 0.2)";
  }
  alertDiv.style.display = "block";
  
  if (type === "success" || type === "error") {
    setTimeout(() => {
      alertDiv.style.display = "none";
    }, 5000);
  }
}



// ────────────────────────────────────────────────────────────────────────
// Configuración Demo e IA
// ────────────────────────────────────────────────────────────────────────
async function initConfig() {
  const btnConfig = document.getElementById("btn-config-demo");
  const modalConfig = document.getElementById("modal-config");
  const btnClose = document.getElementById("btn-close-config");
  const formConfig = document.getElementById("form-config");
  const btnPresetMocks = document.getElementById("btn-preset-mocks");
  const btnPresetLLM = document.getElementById("btn-preset-llm");

  const roles = ["researcher", "coordinator", "professor", "student"];

  function updateSliderUI(role) {
    const slider = document.getElementById(`cfg-${role}`);
    const pill = document.getElementById(`pill-${role}`);
    const badge = document.getElementById(`badge-${role}`);
    if (!slider) return;

    const val = parseFloat(slider.value) || 0;
    if (pill) pill.textContent = `$${val.toFixed(2)}`;

    if (badge) {
      if (val === 0) {
        badge.className = "mode-badge mock";
        badge.textContent = "⚡ Mocks";
      } else {
        badge.className = "mode-badge llm";
        badge.textContent = "🤖 LLM";
      }
    }
    updateTotalMeter();
  }

  function updateTotalMeter() {
    let total = 0;
    roles.forEach(role => {
      const slider = document.getElementById(`cfg-${role}`);
      if (slider) total += parseFloat(slider.value) || 0;
    });

    const totalValSpan = document.getElementById("total-budget-val");
    const totalFill = document.getElementById("total-cost-fill");

    if (totalValSpan) totalValSpan.textContent = `$${total.toFixed(2)} / $20.00 Max`;
    if (totalFill) {
      const pct = Math.min(100, (total / 20) * 100);
      totalFill.style.width = `${pct}%`;
    }
  }

  roles.forEach(role => {
    const slider = document.getElementById(`cfg-${role}`);
    if (slider) {
      slider.addEventListener("input", () => updateSliderUI(role));
    }
  });

  // Load config on startup
  try {
    const res = await fetch("/api/config");
    if (res.ok) {
      const config = await res.json();
      document.getElementById("cfg-researcher").value = config.max_cost_researcher;
      document.getElementById("cfg-coordinator").value = config.max_cost_coordinator;
      document.getElementById("cfg-professor").value = config.max_cost_professor;
      document.getElementById("cfg-student").value = config.max_cost_student;
      roles.forEach(updateSliderUI);
    }
  } catch(e) {
    console.error("Failed to load config", e);
  }

  if (btnPresetMocks) {
    btnPresetMocks.addEventListener("click", () => {
      roles.forEach(role => {
        const slider = document.getElementById(`cfg-${role}`);
        if (slider) slider.value = 0;
        updateSliderUI(role);
      });
      showToast("Configurado en modo Mocks Locales ($0.00)", "info");
    });
  }

  if (btnPresetLLM) {
    btnPresetLLM.addEventListener("click", () => {
      roles.forEach(role => {
        const slider = document.getElementById(`cfg-${role}`);
        if (slider) slider.value = 1.00;
        updateSliderUI(role);
      });
      showToast("Configurado en modo Anthropic Claude ($1.00 c/u)", "info");
    });
  }

  if (btnConfig) {
    btnConfig.addEventListener("click", () => {
      modalConfig.style.display = "flex";
      roles.forEach(updateSliderUI);
    });
  }

  if (btnClose) {
    btnClose.addEventListener("click", () => {
      modalConfig.style.display = "none";
    });
  }

  if (formConfig) {
    formConfig.addEventListener("submit", async (e) => {
      e.preventDefault();
      
      const payload = {
        max_cost_researcher: parseFloat(document.getElementById("cfg-researcher").value),
        max_cost_coordinator: parseFloat(document.getElementById("cfg-coordinator").value),
        max_cost_professor: parseFloat(document.getElementById("cfg-professor").value),
        max_cost_student: parseFloat(document.getElementById("cfg-student").value),
      };

      try {
        const res = await fetch("/api/config", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        if (res.ok) {
          modalConfig.style.display = "none";
          showToast("Presupuestos de agentes actualizados correctamente", "success");
        } else {
          showToast("Error al guardar la configuración", "error");
        }
      } catch (err) {
        showToast("Error de conexión con el servidor", "error");
      }
    });
  }
}

window.fillLoginForm = function(user, pass) {
  const usernameInput = document.getElementById("login-username");
  const passwordInput = document.getElementById("login-password");
  const formLogin = document.getElementById("form-login");
  if (usernameInput && passwordInput && formLogin) {
    usernameInput.value = user;
    passwordInput.value = pass;
    formLogin.dispatchEvent(new Event("submit"));
  }
};

function initGuide() {
  const btnGuide = document.getElementById("btn-guide");
  const modalGuide = document.getElementById("modal-guide");
  const btnClose = document.getElementById("btn-close-guide");
  const btnCloseFooter = document.getElementById("btn-close-guide-footer");

  if (btnGuide && modalGuide) {
    btnGuide.addEventListener("click", () => {
      modalGuide.style.display = "flex";
    });
  }

  const closeGuideModal = () => {
    if (modalGuide) modalGuide.style.display = "none";
  };

  if (btnClose) btnClose.addEventListener("click", closeGuideModal);
  if (btnCloseFooter) btnCloseFooter.addEventListener("click", closeGuideModal);

  // Backdrop click & ESC key handlers for modals
  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closeGuideModal();
      const modalConfig = document.getElementById("modal-config");
      if (modalConfig) modalConfig.style.display = "none";
    }
  });

  if (modalGuide) {
    modalGuide.addEventListener("click", (e) => {
      if (e.target === modalGuide) closeGuideModal();
    });
  }

  const modalConfig = document.getElementById("modal-config");
  if (modalConfig) {
    modalConfig.addEventListener("click", (e) => {
      if (e.target === modalConfig) modalConfig.style.display = "none";
    });
  }
}
