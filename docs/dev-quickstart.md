# Dev Quickstart

For developers working **on** TCU — setting up the repo, running the
pipeline, iterating on the agents or frontend, and running tests.

> If you're an *operator* just running an analysis, the Spanish-language
> [`README.md`](../README.md) is what you want. This doc is the developer
> entry point.

---

## Prerequisites

- **Python 3.11** or newer (`python3 --version` to check)
- An **Anthropic API key** (`sk-ant-…`) with credit available
- A POSIX shell — macOS, Linux, or WSL. Native Windows isn't supported by `./run`.
- ~250 MB free for the virtualenv and `~/.cache/uv`-style pip cache

No Node, no npm, no Docker. The frontend is plain HTML/CSS/JS served by
FastAPI. There is no build step.

---

## 1. Clone & bootstrap

```bash
git clone https://github.com/viniesqui/TCU.git
cd TCU
./run
```

`./run` is **idempotent** and does four things in order:

1. Creates `.venv/` if missing.
2. Installs `requirements.txt` if its `sha256` changed since the last run
   (stamp file: `.venv/.requirements.sha256`).
3. Discovers your API key — `$ANTHROPIC_API_KEY` env var → `.env` →
   interactive hidden prompt that writes `.env` for next time.
4. Runs the CLI pipeline with default args.

Running `./run` ten times produces the same state. The only step that
costs real time is the first dependency install.

### What if `./run` doesn't fit your setup?

Manual equivalent:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
$EDITOR .env                        # paste your ANTHROPIC_API_KEY
python main.py --sector "Ciberseguridad"
```

---

## 2. The `.env` file

Generated automatically by `./run`. The one **required** variable is
`ANTHROPIC_API_KEY`. Everything else has a sensible default — see
`src/config.py` for the canonical schema.

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | — *(required)* | Your `sk-ant-…` key. |
| `MODEL` | `claude-sonnet-4-6` | Claude model id. Use `claude-haiku-4-5-20251001` for cheaper dev runs. |
| `MAX_AGENT_ITERATIONS` | `12` | Per-agent tool-use loop cap. |
| `MAX_STAGE_RETRIES` | `2` | Per-stage retries when a quality gate fails. Total attempts = retries + 1. |
| `SEARCH_MAX_RESULTS` | `5` | Results per DuckDuckGo query. |
| `OUTPUT_DIR` | `output` | Where the generated HTML report lands. |
| `LOG_LEVEL` | `INFO` | Set `DEBUG` to see every agent tool call. |
| `QUALITY_MIN_SKILLS` | `8` | Stage 1 — min distinct skills in `IndustryDemand`. |
| `QUALITY_MIN_JOB_POSTINGS` | `5` | Stage 1 — min job postings sampled. |
| `QUALITY_MIN_SOURCES` | `2` | Stage 1 — min sources consulted. |
| `QUALITY_MIN_UNIVERSITIES` | `5` | Stage 2 — min university programs found. |
| `QUALITY_MIN_COURSES_PER_PROGRAM` | `3` | Stage 2 — min courses per program. |
| `QUALITY_MIN_SKILLS_COVERED` | `10` | Stage 2 — min skills in `all_skills_covered`. |

### Dev-friendly `.env` for fast iteration

A full pipeline run takes 3–5 minutes and costs API credits per run.
For tight iteration, lower the gate thresholds so the orchestrator
accepts smaller agent outputs:

```dotenv
ANTHROPIC_API_KEY=sk-ant-…
MODEL=claude-haiku-4-5-20251001
MAX_STAGE_RETRIES=0
QUALITY_MIN_SKILLS=3
QUALITY_MIN_JOB_POSTINGS=1
QUALITY_MIN_SOURCES=1
QUALITY_MIN_UNIVERSITIES=2
QUALITY_MIN_COURSES_PER_PROGRAM=1
QUALITY_MIN_SKILLS_COVERED=3
LOG_LEVEL=DEBUG
```

This trades report quality for run-time. Don't ship reports generated
with these settings; use them to verify a code change end-to-end.

---

## 3. Running the pipeline

```bash
./run                                          # default sector
./run --sector "Ciberseguridad"
./run --sector "Inteligencia Artificial" --verbose
./run --review                                 # pause for the human checkpoint
./run --review --reviewer "Tu Nombre"
./run --help
```

### Web UI (with the inline review)

```bash
./run web                  # opens http://127.0.0.1:8765
./run web --port 9000
./run web --no-browser     # don't auto-open
```

The web UI runs one execution at a time, drives the orchestrator over a
WebSocket, and exposes the gap-analysis review checkpoint inline.

### Stage cache (the dev superpower)

Each stage's structured output is checkpointed to
`stage_cache/<sector_slug>_<stage>.json`. On the next run for the same
sector, completed stages are loaded from disk — only stages that
changed or were never run actually call the API.

```bash
ls stage_cache/                                # see what's cached
rm stage_cache/desarrollo_de_software_*.json   # force a re-run of one sector
rm -rf stage_cache                             # nuke the cache entirely
```

If you change a prompt in `src/prompts.py` or a Pydantic model in
`src/models/`, **clear the relevant cache** — the cached JSON is
re-validated against the model on load and will reject incompatible
shapes, but mid-pipeline mismatches are easier to debug starting fresh.

---

## 4. Running the tests

```bash
./run test                                     # full suite (≈ 2 s)
./run test tests/test_quality_gates.py -v      # one module
./run test tests/test_web_ui_smoke.py          # the web-UI smoke test
./run test -k "review"                         # by name pattern
```

The suite is fast (~2 s) because every agent and HTTP call is mocked —
no API key required at test time. You can run it without a network or
without `ANTHROPIC_API_KEY` set.

The web-UI smoke test (`tests/test_web_ui_smoke.py`) uses FastAPI's
`TestClient` to assert that every DOM id `app.js` depends on still
exists in `index.html`. Changing the static frontend without updating
the test (or vice-versa) will fail CI.

---

## 5. Project layout (where things live)

```
TCU/
├── main.py                    # CLI entrypoint
├── main_web.py                # uvicorn launcher for the web UI
├── run                        # bash bootstrap
├── requirements.txt
├── .env                       # your secrets (gitignored)
├── src/
│   ├── agents/                # one file per pipeline stage agent
│   │   ├── orchestrator.py    # state machine that sequences stages 1-6
│   │   └── …
│   ├── quality/               # gates that validate each stage's output
│   ├── models/                # Pydantic schemas (the contracts)
│   ├── prompts.py             # all agent system prompts
│   ├── tools/                 # web_search, web_fetch
│   ├── report_generator.py    # Jinja → HTML render
│   ├── config.py              # Settings schema (env-driven)
│   └── web/
│       ├── server.py          # FastAPI app
│       └── static/            # index.html, style.css, app.js
├── templates/
│   ├── report.html.jinja2     # the generated report
│   └── _design_tokens.css.jinja  # shared color tokens
├── tests/                     # pytest, fully mocked
├── docs/
│   ├── dev-quickstart.md      # ← you are here
│   └── frontend-audit-and-plan.md
└── output/                    # generated reports (gitignored)
```

Runtime-only directories, all gitignored:

| Dir | Created by | Safe to delete? |
|---|---|---|
| `.venv/` | `./run` first run | Yes — rebuilt automatically |
| `output/` | every successful run | Yes — but you lose the reports |
| `stage_cache/` | every successful stage | Yes — forces a full re-run |
| `search_cache/` | web search tool | Yes |
| `traces/`, `logs/` | debug runs | Yes |

---

## 6. Working on the frontend

The web UI is in `src/web/static/{index.html, style.css, app.js}`.
There is no build step.

```bash
./run web --no-browser         # start the FastAPI server
# edit src/web/static/*.{html,css,js} in your editor
# hard-refresh (⌘/Ctrl + Shift + R) — uvicorn serves the files directly
```

`uvicorn` doesn't auto-reload the *static* directory by default.
For a true file-watching reload while iterating on frontend assets:

```bash
.venv/bin/uvicorn src.web.server:app --reload --reload-dir src/web/static
```

### Design system

Color and spacing tokens are defined twice:

- `templates/_design_tokens.css.jinja` — canonical, included by the
  Jinja report
- `src/web/static/style.css` — duplicate `:root` block at the top, must
  stay in sync (there's a sync-required comment in the file)

If you add a color, add it to both. See
[`frontend-audit-and-plan.md`](./frontend-audit-and-plan.md) §7 for the
deferred "token-sync CI check" follow-up.

### Frontend testing

After any change to `app.js` or `index.html`, run:

```bash
./run test tests/test_web_ui_smoke.py -v
```

This will fail if a DOM id `app.js` references stops existing in
`index.html` — a common foot-gun when refactoring screens.

---

## 7. Common dev tasks

**Add a new pipeline stage**: extend `src/models/` with the Pydantic
schema, add a gate in `src/quality/`, add an agent in `src/agents/`,
wire it into `src/agents/orchestrator.py`, and add a stage id to
`STAGES` in `src/web/static/app.js`. The web UI's stage timeline
renders from that catalog.

**Change an agent prompt**: edit `src/prompts.py`, clear the relevant
`stage_cache/` entries, re-run. The agent will hit the API on next
invocation since the cache is bypassed.

**Tweak a quality gate**: edit `src/quality/*.py` and corresponding
threshold in `src/config.py`. The orchestrator already surfaces retry
events to the web UI (`stage_retry` over the WebSocket) — your gate's
first issue message shows up as a chip on the active stage card.

**Add a sector chip suggestion**: edit `SECTOR_SUGGESTIONS` and the
`RELATED_SECTORS` adjacency map at the top of `src/web/static/app.js`.

**Debug a flaky agent**: set `LOG_LEVEL=DEBUG` in `.env` and run with
`--verbose` to see every tool call, every Claude response, and every
gate evaluation.

---

## 8. Troubleshooting

**`✗ Error de configuración: …anthropic_api_key`** — `.env` is missing
or the key isn't exported. Either run `./run` again (it'll prompt) or
`export ANTHROPIC_API_KEY=sk-ant-…` in your shell.

**`Stage N failed to produce valid JSON after K attempts`** — an agent
couldn't produce valid JSON within `MAX_STAGE_RETRIES + 1` tries.
Usually transient; re-run with the stage cache intact (only the failed
stage is retried). Persistent failures suggest a model regression or a
prompt issue.

**`ModuleNotFoundError: No module named 'fastapi'`** — you're running
Python directly without activating the venv. Use `./run web` or
`. .venv/bin/activate` first.

**Web UI shows "Ya hay una ejecución en curso"** — a previous run is
still alive. Either wait for it to finish, or restart the uvicorn
process (Ctrl-C then `./run web`).

**Cached stage data conflicts with a new Pydantic model** — clear
`stage_cache/`. The cache stores serialized JSON keyed by sector
slug; schema changes invalidate older files.

**Tests pass locally but the web UI looks wrong** — `tests/test_web_ui_smoke.py`
only checks structure (DOM ids and the WebSocket contract), not visual
correctness. Open the browser and hard-refresh after CSS changes.
