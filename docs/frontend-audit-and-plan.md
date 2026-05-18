# Frontend Audit & Redesign Plan

Audit of the TCU web UI (`src/web/static/{index,style,app}.*` + `src/web/server.py`)
and a concrete plan to make it **easier to use** and **more aesthetically
pleasing** — without rewriting the backend contract.

> Scope: the operator-facing web UI (`./run web`). The Jinja2 *report*
> (`templates/report.html.jinja2`) shares a visual language with the UI and is
> addressed at the end as a secondary target.

---

## 1. What exists today

| File | Lines | Role |
|---|---|---|
| `src/web/static/index.html` | 140 | 6 stacked `<section>` "screens" toggled by `.active` |
| `src/web/static/style.css`  | 288 | Vanilla CSS, CSS variables, single stylesheet |
| `src/web/static/app.js`     | 366 | Vanilla JS, WebSocket-driven state machine |
| `src/web/server.py`         | 270 | FastAPI: `/`, `/ws/run`, `/api/reports`, `/reports/{name}` |
| `templates/report.html.jinja2` | 578 | Final report (separate from web UI, similar palette) |

**Flow:** `input → pipeline → review → done` (with `error` and `archive` side branches).
**State model:** browser drives a `WebSocket /ws/run`. Server runs the orchestrator
on a worker thread; review checkpoint blocks until the browser POSTs back edits.

---

## 2. Audit findings

### 2.1 Usability (what makes it harder than it needs to be)

**U1. No example sectors / no autocomplete.**
The input is a single freeform text field defaulted to "Desarrollo de Software".
A first-time operator has to *know* what sectors are sensible (Ciberseguridad,
Inteligencia Artificial, Datos, …). There are no chips, no suggestions, no
recently-used list.

**U2. The pipeline screen is opaque while it runs.**
A run takes minutes. The UI shows a stage list and a dark log box, but:
- No elapsed time, no per-stage duration, no ETA.
- The log is the only feedback once a stage starts; messages are short and
  identical-looking; you can't tell if the system is stuck.
- Stage matching is keyword-based (`STAGE_KEYWORDS` in `app.js:12`). If the
  backend phrasing changes, the stepper silently stops updating.
- No retry/quality-gate visibility — when an agent re-runs after a gate
  failure, the UI shows nothing about it.

**U3. The review screen is dense and easy to misread.**
- All critical and moderate gaps are in two long tables with bare-number score
  bars; there is no sort, no filter, no "select all / none", no count of
  currently-accepted skills updating live.
- "Manual addition" is a flat list of pills with no depth color-coding and no
  edit-after-add.
- The two big actions ("Aceptar y continuar" / "Saltar") sit on the same row
  with the same width — easy to misclick "Saltar".
- No "back to pipeline" / no review-summary preview before submitting.
- The course title + rationale are buried *below* the tables; an operator who
  scrolls to the bottom and clicks Accept may not realize they were editable.

**U4. The "done" screen iframes the report.**
Embedding a 30+ KB report inside the operator UI doubles the rendering work and
makes the report's own table-of-contents links scroll the *iframe*, not the
page. The "Abrir en pestaña nueva" link is the actually-useful affordance.

**U5. Error state is a dead end.**
`screen-error` renders the raw exception text and a single "Volver a empezar"
that does a `location.reload()`. There is no retry-with-same-sector, no link
to the partial cache, and no copy-to-clipboard for the traceback.

**U6. Restart = full page reload.**
"Nuevo análisis" and "Volver a empezar" both call `location.reload()`
(`app.js:38-39`). Easy to implement, but it discards the WebSocket and any
unrelated browser state, and feels less responsive than a soft reset.

**U7. Archive is a separate screen, not a drawer.**
"Ver reportes anteriores" hides the input form. A drawer/sidebar would let
the operator browse old reports while keeping the start form visible.

**U8. No keyboard affordances.**
Enter submits the form (browser default), but there is no `⌘/Ctrl+Enter` to
accept the review, no `Esc` to close the archive, no focus management when
transitioning screens (focus stays where it last was).

**U9. Single-session lock is invisible.**
`server.py:204` rejects a second `/ws/run` with `"Ya hay una ejecución en
curso."`. The frontend treats that as a fatal error. A second operator opening
the page sees the error screen with no information about *whose* run is in
progress or when it started.

**U10. No accessibility scaffolding.**
- No `aria-live` on the log / current-status / progress list — screen
  readers don't announce stage changes.
- The progress dots convey state by color only.
- Form labels are wrapped `<label>`s (good) but the manual-add row is a bare
  `<input>` + `<select>` with no associated `<label>`.
- Color contrast is fine on the hero but the muted text (`#7f8c8d` on `#f4f6f9`)
  is ~3.3:1 — below WCAG AA for body text.

### 2.2 Aesthetics

**A1. Generic "corporate dashboard" feel.**
Navy + gold + Segoe UI is functional but undifferentiated. Nothing signals
"AI / multi-agent / Costa Rica / education". The hero is a flat gradient strip;
the cards are flat white rectangles with thin shadows.

**A2. Inconsistent spacing rhythm.**
Mixing `1.2rem`, `1.5rem`, `1.6rem`, `1.8rem`, `2rem`, `2.5rem` across cards,
sections, and forms with no 4/8-px grid. Vertical rhythm jitters.

**A3. Typography is undifferentiated.**
Single font (`'Segoe UI', Arial, sans-serif`), three font sizes used inconsistently
(`0.78rem`, `0.82rem`, `0.85rem`, `0.88rem`, `0.92rem`, `0.95rem`, `1rem`,
`1.25rem`, `1.7rem`). No display font for the hero / report title.

**A4. The log box (`#1e2735`) collides with the otherwise-light palette.**
It's the only dark surface on the page. It reads as a "developer artifact"
embedded in a UX surface.

**A5. Pipeline dots are tiny.**
12-px circles with a 4-px pulse halo. On a 27" monitor they're hard to read at
a glance; on mobile they're easy to miss. No iconography per stage.

**A6. Tables in the review screen look like a database admin tool.**
Hard column borders, hover row swap, primary-color header bar. There's no
visual hierarchy that says "this is the most important decision in the whole
flow".

**A7. No empty / loading / skeleton states.**
The "Cargando…" muted text in the archive list is the only loading indicator
in the entire UI.

**A8. No dark mode** (and no light/dark toggle).

**A9. Mobile breakpoint missing.**
No `@media` queries. The hero, cards, and tables scale by their `max-width:
960px` but the manual-add row, the two-button rows, and the review tables all
overflow horizontally on phones.

### 2.3 Code quality (small but real)

**C1. Stage detection by substring match (`app.js:12-19`).**
Brittle. The backend's `progress.log(...)` strings are the contract. Solution:
have the orchestrator emit a `stage_id` field on each `stage_progress` message.

**C2. `currentGap`, `manualAdditions` are module-level mutable globals.**
Fine for a 366-line file; will hurt the moment a second feature touches them.

**C3. `escape()` is reinvented (`app.js:359-366`).**
It's correct but using `textContent` for plain strings would be cheaper and
less error-prone. Most current usages are fine; a few `innerHTML = …${escape}…`
patterns mix concerns.

**C4. No build step → no minification, no source maps, no TypeScript.**
For a 366-line app this is fine, but the lack of types means the
WebSocket message contract is implicit (e.g. `msg.gap_analysis` shape lives
only in `_apply_review`'s docstring).

**C5. No tests for the frontend.**
The Python suite is thorough (93 tests) but the WebSocket message contract is
covered only on the server side. A change to `app.js` cannot fail CI.

**C6. The "screen" CSS toggles `display: block` but each section is also a
`.card`** — so when none is `.active`, the page is empty. There's no skeleton
shell to anchor branding/nav.

---

## 3. Design goals

In priority order:

1. **Every screen tells you what's happening and what's next.** No ambiguity
   about whether the system is working, stuck, or done.
2. **The review screen makes the right action obvious.** Accept-and-continue
   is the primary; skip is a secondary surface, not a peer.
3. **Aesthetics signal "thoughtful, modern, education-domain tool"** —
   not "internal admin panel".
4. **Accessible by default.** WCAG AA contrast, keyboard navigation,
   `aria-live` regions for async updates.
5. **Mobile-tolerant.** Phone-friendly review at a minimum; full
   responsive on the input + done screens.
6. **No new build toolchain.** Stay on vanilla HTML/CSS/JS; avoid Node, npm,
   bundlers. The whole repo is a Python tool — keep the frontend tractable.

Explicit non-goals:

- No SPA framework (React/Vue/Svelte). Adds a build step for a 4-screen UI.
- No CSS framework (Tailwind/Bootstrap). The existing CSS-variable system is
  already serviceable; we extend it, not replace it.
- No new server endpoints unless the redesign demands them. List below
  identifies the *one* place the contract should grow (stage IDs).

---

## 4. Plan

### Phase 1 — Foundations (no behavior change, sets up everything else)

**1.1 Design tokens.** Replace the current `:root` block with a richer token
set:

- Spacing scale: `--space-1 … --space-8` on a 4-px grid.
- Type scale: `--text-xs … --text-3xl` (clamp-based for fluid scaling).
- Radius scale: `--radius-sm/md/lg/full`.
- Elevation: `--shadow-sm/md/lg`.
- Semantic colors: `--surface`, `--surface-raised`, `--border-subtle`,
  `--text-primary`, `--text-muted`, `--accent-bg`, `--accent-fg`.
- Status colors with both `bg` and `fg` variants (so a "critical" pill and
  a "critical" bar fill come from the same source).
- Add a `[data-theme="dark"]` overlay that re-points the same tokens.

**1.2 Typography.** Adopt **two** webfonts via `<link>` (no build step):
- `Inter` (variable) for UI + body — proven legibility at small sizes.
- `Fraunces` or `Source Serif` for hero headlines + report titles — gives the
  product a recognizable voice.

Fall back to system fonts during font load (`font-display: swap`).

**1.3 Layout shell.** Promote the page into a persistent shell:

```
┌─────────────────────────────────────┐
│  Sidebar nav (collapsible on mobile)│  ← logo, "Nuevo análisis", "Reportes",
│                                     │     "Acerca de", theme toggle
│   ┌─────────────────────────────┐   │
│   │  Active screen content      │   │
│   └─────────────────────────────┘   │
└─────────────────────────────────────┘
```

This is what fixes **U7** (archive becomes a sidebar item, not a screen
takeover) and **C6** (the shell stays even when no screen is active —
useful for the in-between moment between submit and pipeline start).

**1.4 Stage contract change** (the one backend touch):
Add a `stage_id` field to `stage_progress` messages emitted from the
orchestrator. The frontend stops doing substring matching (**C1**).
The orchestrator already knows which stage it's in — surface it.

Touchpoints: `_WebProgressAdapter.log` in `src/web/server.py:73` and every
`self.progress.log(...)` call site in `src/agents/orchestrator.py`.
Add the field; keep the existing `description` string for the human log.

### Phase 2 — Input screen

**2.1 Sector picker** that combines:
- 4–6 prominent suggestion chips (the sectors that actually appear in
  examples: Desarrollo de Software, Ciberseguridad, IA, Datos, DevOps,
  Cloud).
- A freeform text input below, for anything else.
- A "recently analyzed" list (read from `/api/reports`, derive sectors
  from filenames) — gives one-click re-run.

**2.2 Reviewer field** becomes optional inline ("Tu nombre" inside an
expandable "Opciones avanzadas" disclosure). Reduces visual noise on the
default path.

**2.3 Inline tagline copy** explaining what *will* happen — 1 sentence per
pipeline stage as a 7-step preview with icons. Sets expectations about
duration ("≈ 3–5 minutos"). Fixes **U2** before it starts.

**2.4 Primary CTA = "Iniciar análisis"** as a single full-width button.
"Ver reportes anteriores" moves to the sidebar nav.

### Phase 3 — Pipeline screen (where ≥ 80 % of the operator's time is spent)

**3.1 Vertical timeline component** replacing the flat `<ol>`:
- Each stage is a row with: icon, label, status pill (Pendiente / En curso /
  Listo / Reintento), elapsed time, expandable "ver detalles".
- The active row visibly distinct: card with shadow, animated indeterminate
  progress bar inside it.
- Completed rows collapse to one-line summaries.

**3.2 Surface quality-gate retries.**
The orchestrator already retries on gate failure (`MAX_STAGE_RETRIES`). Emit
a `stage_retry` event from the backend (small contract addition) and render
"Reintento 1/2 — razón: muestra insuficiente de habilidades" as a chip
inside the stage row. Fixes **U2**.

**3.3 Replace the dark `.log` box** with a light, collapsible "Detalles
técnicos" panel:
- Default collapsed; click to expand.
- Same monospace font but on a `--surface-raised` background, not a black box.
- The casual operator never sees it; the curious one can.

**3.4 `aria-live="polite"`** on the current-status line and on each stage's
status pill. Screen readers announce progress without flooding (**U10**).

**3.5 Cancel button.** The server already accepts `{type: "cancel"}`
(`server.py:267`). The frontend never sends it. Wire a "Cancelar ejecución"
button with a confirmation dialog. Fixes a real footgun: a wrong-sector
run forces a full reload today.

### Phase 4 — Review screen (highest-value redesign)

This is the only screen with real decision-making. Optimize hard.

**4.1 Hero summary at the top, not just a one-liner:**
- Sector name + analyzed-at timestamp.
- 4 KPI tiles: critical count, moderate count, already-covered count,
  estimated course credits.
- A live "X de Y habilidades seleccionadas" counter that updates as the
  operator toggles checkboxes.

**4.2 Skill cards, not tables.**
Each skill becomes a card with:
- Checkbox + skill name as the title.
- Two horizontal bars side-by-side: market demand vs. academic coverage,
  with labels and percentages (not just bare 0–1 decimals).
- Depth required as a pill (basico/intermedio/avanzado), color-coded.
- Optional "notas" expansion for the gap analyst's justification text
  (currently shown only in the final report).
- A red/yellow left border per severity, matching the report's badges.

Cards stack into a CSS grid (`auto-fill, minmax(320px, 1fr)`) — phones
get one column, desktops 2–3. Fixes **U3** and **A6**.

**4.3 Filter + sort toolbar** above the cards:
- Filter: "Mostrar solo críticas / moderadas / todas".
- Sort: "Por demanda ↓ / Por gap (demanda − cobertura) ↓ / A-Z".
- "Seleccionar todas / ninguna" buttons.

**4.4 Manual-add UX:**
- An "Agregar habilidad" card with the same shape as skill cards, with the
  name + depth + optional note inputs inline.
- Added skills appear as a new card in the grid, visibly distinct (dashed
  border, "manual" badge). Editable until submission.

**4.5 Course title & rationale** moved to a **sticky bottom panel**
("Curso propuesto") that the operator can always see while scrolling
the skills. Two text fields with character counts; preview of how it
will appear in the report.

**4.6 Primary CTA hierarchy:**
- `Aceptar y continuar` — large, full-width on mobile, with the live
  selection count baked in: "Aceptar 12 habilidades y continuar".
- `Saltar (modo automático)` — smaller, secondary, with a tooltip
  explaining what "skipped" means.

### Phase 5 — Done screen

**5.1 Drop the iframe.**
Replace with a "Vista previa" — first paragraph of the executive summary,
hero numbers (credits, weeks, # of activities), then a single big
"Abrir reporte completo" CTA that opens in a new tab. Add a "Descargar
HTML" link. Fixes **U4**.

**5.2 Quality-score visualization.**
Replace the pills row with a horizontal stacked bar per stage (good/warn/
poor zones), or a small radar chart (SVG, no library). Same data, better
shape.

**5.3 "Hacer otro análisis con un sector relacionado"** — single-click
buttons for sectors that share the same skill family. Use the existing
sectors-from-archive logic.

### Phase 6 — Error screen

**6.1 Layout:** title, plain-language summary ("La etapa de mercado laboral
falló después de 2 reintentos"), expandable traceback, primary
"Reintentar con el mismo sector", secondary "Empezar de nuevo",
tertiary "Copiar detalles". Fixes **U5**.

**6.2 Map common backend errors to friendly messages:**
- `RuntimeError("Run cancelled by client")` → "Cancelaste la ejecución."
- API-key errors → "Falta `ANTHROPIC_API_KEY`. Revisa tu .env."
- Quality-gate-after-retries → "El sector no produjo resultados suficientes
  después de 2 reintentos. Probá un sector más específico."

### Phase 7 — Cross-cutting

**7.1 Keyboard map** (**U8**):
- `Enter` on the input — start (already works).
- `Ctrl/⌘ + Enter` on the review — submit "Aceptar".
- `Esc` — close sidebar, close manual-add inline form.
- `/` — focus the sector input on the home screen.
- `?` — show a small "atajos de teclado" overlay.

**7.2 Focus management.** On screen transition, move focus to the new
screen's heading (`tabindex="-1"; element.focus()`). Critical for screen
readers (**U10**).

**7.3 Responsive breakpoints.** Three: 480 px, 768 px, 1024 px. The
sidebar collapses to a top bar on < 768 px; review cards go single-column
on < 480 px; the form is already tolerant.

**7.4 Dark mode.** `prefers-color-scheme: dark` by default; manual toggle
in the sidebar persisted to `localStorage`. With the token system from
Phase 1.1 this is ~30 lines of CSS.

**7.5 Soft restart.** Replace `location.reload()` with: close WebSocket,
reset state objects, transition to input screen, focus the sector input.
Fixes **U6**.

**7.6 Toast notifications** for non-blocking feedback (connection lost,
reconnected, link copied, run cancelled). A 30-line vanilla toast util,
no library.

### Phase 8 — Tightening the code

- **C1** is closed by Phase 1.4 (stage IDs in messages).
- **C2:** wrap UI state in a single `state` object with a `setState()`
  that re-renders the active screen. Tiny step toward a reactive model
  without a framework.
- **C3:** introduce a `t(node, text)` helper that uses `textContent` for
  plain strings; reserve `escape()`+`innerHTML` for fragments.
- **C4:** add JSDoc typedefs for the four WebSocket message shapes; that's
  enough type safety for a 366-line file without a TS build.
- **C5:** add a Playwright-based smoke test that boots the FastAPI app with
  a stubbed orchestrator, walks input → fake-pipeline → fake-review → done,
  and asserts the DOM at each transition. One test, one file, runs in CI.

### Phase 9 — Report template alignment (secondary)

The Jinja2 report (`templates/report.html.jinja2`) duplicates the palette
inline (lines 8–21). After Phase 1.1, lift the token block into a tiny
shared partial (`templates/_design_tokens.html`) and `{% include %}` it
in both the report and a future server-rendered fallback. Keeps the UI
and the deliverable visually unified.

---

## 5. Suggested sequencing

A sensible 4-PR breakdown:

1. **PR 1 — Tokens, type, shell** (Phase 1 + 7.3 + 7.4).
   No screen logic changes; pure visual refresh. Safe to ship alone.
2. **PR 2 — Pipeline & input redesign** (Phase 2 + 3, including the
   `stage_id` backend contract change and `stage_retry` event).
3. **PR 3 — Review redesign** (Phase 4). Highest impact, biggest diff;
   isolate it.
4. **PR 4 — Done, error, polish, smoke test** (Phases 5, 6, 7.1–7.2,
   7.5–7.6, 8, 9).

Each PR is shippable on its own and improves the UI without depending on
the next.

---

## 6. What success looks like

- A first-time operator lands on the page, picks a chip, hits Enter, and
  is on the pipeline screen in < 3 seconds with no documentation read.
- During the pipeline run, the operator can tell at a glance which stage
  is active, how long it's taken, and whether a retry happened.
- At the review checkpoint, the operator can scan all gaps as cards,
  toggle them, and submit with a single keyboard shortcut. The course
  title is always visible.
- The UI works on a phone screen.
- It looks like something built for educators, not for engineers.
