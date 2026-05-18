"""
FastAPI web UI for the TCU pipeline.

Single-session design: one pipeline run at a time. The orchestrator is sync and
multi-minute, so it executes in a background thread; messages are marshalled to
the browser through asyncio queues. The gap-analysis review checkpoint is a
``WebReviewHook`` that blocks the orchestrator thread on a ``threading.Event``
until the browser POSTs back the edited gap analysis.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.agents.orchestrator import Orchestrator
from src.models.gap import GapAnalysis, SkillGap

logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent / "static"
_OUTPUT_DIR = Path("output")
_REPORT_PREFIX = "reporte_"


# ──────────────────────────────────────────────────────────────────────────
# Session state
# ──────────────────────────────────────────────────────────────────────────

@dataclass
class Session:
    """All state for a single pipeline run. One session at a time."""
    loop: asyncio.AbstractEventLoop
    outbound: asyncio.Queue  # messages to send to the browser
    review_event: threading.Event = field(default_factory=threading.Event)
    review_payload: dict | None = None  # browser's response to the review
    cancelled: threading.Event = field(default_factory=threading.Event)
    report_path: str | None = None
    error: str | None = None
    thread: threading.Thread | None = None

    def push(self, message: dict[str, Any]) -> None:
        """Thread-safe push of a message to the outbound queue."""
        try:
            asyncio.run_coroutine_threadsafe(self.outbound.put(message), self.loop)
        except RuntimeError:
            # Loop closed (client disconnected) – drop the message.
            pass


_current_session: Session | None = None
_session_lock = threading.Lock()


# ──────────────────────────────────────────────────────────────────────────
# Bridge adapters: orchestrator (sync thread) ↔ websocket (async event loop)
# ──────────────────────────────────────────────────────────────────────────

class _WebProgressAdapter:
    """Receives stage descriptions from the orchestrator and forwards them."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def log(self, message: str) -> None:
        self._session.push({"type": "stage_progress", "description": message})


def _make_web_review_hook(session: Session):
    """Hook that pauses the orchestrator thread until the browser responds."""

    def hook(gap: GapAnalysis) -> tuple[GapAnalysis, dict | None]:
        session.push({
            "type": "review_request",
            "gap_analysis": json.loads(gap.model_dump_json()),
        })

        # Block until the browser responds (or the run is cancelled).
        while not session.review_event.wait(timeout=0.5):
            if session.cancelled.is_set():
                raise RuntimeError("Run cancelled by client during review")

        payload = session.review_payload or {}
        edited_gap = _apply_review(gap, payload)
        audit = payload.get("audit") or {}
        return edited_gap, audit

    return hook


def _apply_review(original: GapAnalysis, payload: dict) -> GapAnalysis:
    """Reconstruct GapAnalysis from the browser's edited payload.

    The payload mirrors the schema in static/app.js:
      - ``accepted_ids``: list of skill ids from the original gap (format 'c<i>' or 'm<i>')
      - ``manual_additions``: list of {name, depth}
      - ``proposed_course_title``: string (possibly edited)
      - ``proposed_course_rationale``: string (possibly edited)
    """
    if payload.get("skipped"):
        return original

    accepted: set[str] = set(payload.get("accepted_ids", []))
    critical: list[SkillGap] = [s for i, s in enumerate(original.critical_gaps) if f"c{i}" in accepted]
    moderate: list[SkillGap] = [s for i, s in enumerate(original.moderate_gaps) if f"m{i}" in accepted]

    for addition in payload.get("manual_additions", []):
        name = (addition.get("name") or "").strip()
        depth = (addition.get("depth") or "intermedio").lower()
        if not name or depth not in ("basico", "intermedio", "avanzado"):
            continue
        critical.append(SkillGap(
            skill_name=name,
            market_demand_score=0.7,
            academic_coverage_score=0.1,
            gap_severity="critical",
            notes="Agregado manualmente por el educador durante revisión.",
            market_depth_required=depth,  # type: ignore[arg-type]
        ))

    return original.model_copy(update={
        "critical_gaps": critical,
        "moderate_gaps": moderate,
        "proposed_course_title": payload.get("proposed_course_title") or original.proposed_course_title,
        "proposed_course_rationale": payload.get("proposed_course_rationale") or original.proposed_course_rationale,
    })


# ──────────────────────────────────────────────────────────────────────────
# Pipeline runner (thread target)
# ──────────────────────────────────────────────────────────────────────────

def _run_pipeline(session: Session, sector: str, reviewer: str | None) -> None:
    try:
        orchestrator = Orchestrator(
            progress=_WebProgressAdapter(session),
            review_hook=_make_web_review_hook(session),
        )
        report_path = orchestrator.run(sector=sector)
        session.report_path = report_path
        session.push({
            "type": "complete",
            "report_path": Path(report_path).name,
            "quality_scores": orchestrator._quality_scores,
        })
    except Exception as exc:
        logger.exception("Pipeline failed")
        session.error = str(exc)
        session.push({"type": "error", "message": str(exc)})


# ──────────────────────────────────────────────────────────────────────────
# FastAPI app
# ──────────────────────────────────────────────────────────────────────────

app = FastAPI(title="TCU – Análisis de Brecha Educativa")
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    html_path = _STATIC_DIR / "index.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.get("/reports/{filename}")
async def get_report(filename: str):
    """Serve a generated HTML report. Filename is validated to live in output/."""
    if not filename.startswith(_REPORT_PREFIX) or not filename.endswith(".html"):
        return JSONResponse({"error": "invalid filename"}, status_code=400)
    path = _OUTPUT_DIR / filename
    if not path.exists() or not path.resolve().is_relative_to(_OUTPUT_DIR.resolve()):
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(path, media_type="text/html")


@app.get("/api/reports")
async def list_reports():
    """List all generated reports for the archive sidebar."""
    if not _OUTPUT_DIR.exists():
        return {"reports": []}
    files = sorted(
        _OUTPUT_DIR.glob(f"{_REPORT_PREFIX}*.html"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return {"reports": [{"name": f.name, "mtime": f.stat().st_mtime} for f in files]}


@app.websocket("/ws/run")
async def ws_run(ws: WebSocket) -> None:
    global _current_session
    await ws.accept()

    with _session_lock:
        if _current_session is not None and _current_session.thread and _current_session.thread.is_alive():
            await ws.send_json({"type": "error", "message": "Ya hay una ejecución en curso."})
            await ws.close()
            return
        _current_session = Session(loop=asyncio.get_running_loop(), outbound=asyncio.Queue())
        session = _current_session

    try:
        # Wait for the start message from the client.
        start = await ws.receive_json()
        if start.get("type") != "start":
            await ws.send_json({"type": "error", "message": "Expected start message"})
            return

        sector = (start.get("sector") or "").strip() or "Desarrollo de Software"
        reviewer = start.get("reviewer")

        # Launch the orchestrator in a worker thread.
        session.thread = threading.Thread(
            target=_run_pipeline,
            args=(session, sector, reviewer),
            daemon=True,
        )
        session.thread.start()

        # Concurrent tasks: relay outbound messages, and read inbound (review responses, cancel).
        relay_task = asyncio.create_task(_relay_outbound(session, ws))
        inbound_task = asyncio.create_task(_handle_inbound(session, ws))

        done, pending = await asyncio.wait(
            {relay_task, inbound_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()

    except WebSocketDisconnect:
        session.cancelled.set()
        session.review_event.set()  # unblock the review hook so it can raise
    finally:
        try:
            await ws.close()
        except Exception:
            pass


async def _relay_outbound(session: Session, ws: WebSocket) -> None:
    """Drain the session outbound queue and send each message to the browser."""
    while True:
        message = await session.outbound.get()
        await ws.send_json(message)
        if message.get("type") in ("complete", "error"):
            return


async def _handle_inbound(session: Session, ws: WebSocket) -> None:
    """Receive messages from the browser (review responses, cancel)."""
    while True:
        msg = await ws.receive_json()
        kind = msg.get("type")
        if kind == "review_response":
            session.review_payload = msg.get("payload") or {}
            session.review_event.set()
        elif kind == "cancel":
            session.cancelled.set()
            session.review_event.set()
            return
