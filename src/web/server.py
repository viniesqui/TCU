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

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordBearer
import jwt
from datetime import datetime, timedelta

from src.agents.orchestrator import Orchestrator
from src.models.gap import GapAnalysis, SkillGap
from src import database
from src.config import format_api_error_message

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

from pydantic import BaseModel

class ConfigUpdatePayload(BaseModel):
    max_cost_researcher: float
    max_cost_coordinator: float
    max_cost_professor: float
    max_cost_student: float

@app.get("/api/config")
def get_config() -> JSONResponse:
    from src.config import settings
    return JSONResponse({
        "max_cost_researcher": settings.max_cost_researcher,
        "max_cost_coordinator": settings.max_cost_coordinator,
        "max_cost_professor": settings.max_cost_professor,
        "max_cost_student": settings.max_cost_student,
    })

@app.post("/api/config")
def update_config(payload: ConfigUpdatePayload) -> JSONResponse:
    from src.config import settings
    settings.max_cost_researcher = payload.max_cost_researcher
    settings.max_cost_coordinator = payload.max_cost_coordinator
    settings.max_cost_professor = payload.max_cost_professor
    settings.max_cost_student = payload.max_cost_student
    logger.info(f"Updated global budgets: {payload.model_dump()}")
    return JSONResponse({"status": "ok"})
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.on_event("startup")
def startup_event():
    database.init_db()


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


# ──────────────────────────────────────────────────────────────────────────
# Multi-Persona REST API Endpoints
# ──────────────────────────────────────────────────────────────────────────

SECRET_KEY = "super-secret-tcu-key"  # Change this in production
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/login")

def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("username")
        role = payload.get("role")
        if username is None or role is None:
            raise HTTPException(status_code=401, detail="Invalid token payload")
        return {"username": username, "role": role}
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

class LoginRequest(BaseModel):
    username: str
    password: str

@app.post("/api/login")
async def login(payload: LoginRequest):
    logger.info(f"[API LOGIN] Received login request for username='{payload.username}'")
    user = database.verify_user(payload.username, payload.password)
    if not user:
        logger.warning(f"[API LOGIN] Authentication failed for username='{payload.username}'")
        raise HTTPException(status_code=401, detail=f"Credenciales inválidas para el usuario '{payload.username}'. Verifica tu contraseña.")
    
    import datetime
    access_token_expires = datetime.datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode = {"username": user["username"], "role": user["role"], "exp": access_token_expires}
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    logger.info(f"[API LOGIN] Login successful! Token issued for username='{user['username']}' role='{user['role']}'")
    
    return {"access_token": encoded_jwt, "token_type": "bearer", "user": user}

@app.get("/api/current_user")
async def get_current_user_endpoint(user: dict = Depends(get_current_user)):
    """Get the currently authenticated user."""
    return user

@app.get("/api/users")
async def get_users_endpoint(user: dict = Depends(get_current_user)):
    """Get all database users."""
    conn = database.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT username, role FROM users")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]



@app.get("/api/student/vark-questions")
async def get_vark_questions(user: dict = Depends(get_current_user)):
    with open("src/vark_questions.json", "r") as f:
        questions = json.load(f)
    return questions

@app.get("/api/student/profile")
async def get_student_profile(user: dict = Depends(get_current_user)):
    profile = database.get_learning_profile(user["username"])
    return profile

class VarkTestPayload(BaseModel):
    answers: dict  # e.g. {"1": "visual", "2": "aural", ...}

@app.post("/api/student/vark-test")
async def submit_vark_test(payload: VarkTestPayload, user: dict = Depends(get_current_user)):
    scores = {"visual": 0, "aural": 0, "reading": 0, "kinesthetic": 0}
    for q_id, ans in payload.answers.items():
        if ans in scores:
            scores[ans] += 1
            
    total = sum(scores.values())
    if total == 0:
        raise HTTPException(status_code=400, detail="Invalid answers")
        
    # Find dominant (highest score). If tie, just pick one of the highest or mark as multimodal.
    max_score = max(scores.values())
    dominant_styles = [k for k, v in scores.items() if v == max_score]
    dominant_style = dominant_styles[0] if len(dominant_styles) == 1 else "multimodal"

    database.save_learning_profile(
        user["username"], 
        scores["visual"], 
        scores["aural"], 
        scores["reading"], 
        scores["kinesthetic"], 
        dominant_style
    )
    
    return {"status": "success", "profile": {
        "visual_score": scores["visual"],
        "aural_score": scores["aural"],
        "reading_score": scores["reading"],
        "kinesthetic_score": scores["kinesthetic"],
        "dominant_style": dominant_style
    }}

@app.get("/api/curriculum/fwd")
async def get_fwd_curriculum_endpoint(user: dict = Depends(get_current_user)):
    """Return the official FWD Costa Rica Front End + IA Applied curriculum data."""
    from src.fwd_loader import get_fwd_raw_data
    data = get_fwd_raw_data()
    return data

@app.post("/api/curriculum/upload")
async def upload_custom_curriculum_endpoint(payload: dict, user: dict = Depends(get_current_user)):
    """Process uploaded curriculum text or JSON to extract topics and skills."""
    text = payload.get("text", "")
    program_title = payload.get("title", "Programa Personalizado")
    institution = payload.get("institution", "Institución Externa")
    
    if not text:
        return JSONResponse({"error": "No curriculum content provided"}, status_code=400)
        
    lines = [line.strip("-•* \t") for line in text.split("\n") if len(line.strip("-•* \t")) > 2]
    skills = lines[:30] if lines else ["programación", "análisis de datos", "desarrollo web"]
    
    return {
        "status": "success",
        "program_title": program_title,
        "institution": institution,
        "skills_extracted": skills,
        "total_skills": len(skills)
    }

@app.post("/api/research")
async def run_research_endpoint(payload: dict, user: dict = Depends(get_current_user)):
    """Run Stage 1-3 (Market & Academic research + Gap Analysis)."""
    sector = payload.get("sector", "Desarrollo de Software")
    force_rebuild = payload.get("force_rebuild", False)
    curriculum_source = payload.get("curriculum_source", "universities")
    custom_curriculum = payload.get("custom_curriculum")
    learning_profile = payload.get("learning_profile")
    
    custom_academic = None
    if curriculum_source == "fwd":
        from src.fwd_loader import get_fwd_academic_landscape
        custom_academic = get_fwd_academic_landscape()
        sector_lookup = f"{sector} (FWD Costa Rica)"
    elif curriculum_source == "custom" and custom_curriculum:
        from src.fwd_loader import create_custom_academic_landscape
        custom_academic = create_custom_academic_landscape(
            program_title=custom_curriculum.get("title", "Programa Personalizado"),
            institution=custom_curriculum.get("institution", "Institución Externa"),
            skills=custom_curriculum.get("skills", []),
            summary=custom_curriculum.get("summary", "")
        )
        sector_lookup = f"{sector} ({custom_curriculum.get('institution', 'Custom')})"
    else:
        sector_lookup = sector

    # A. Check database first if not forcing rebuild
    if not force_rebuild:
        report = database.get_gap_report(sector_lookup) or (database.get_gap_report(sector) if curriculum_source == "universities" else None)
        if report:
            logger.info(f"Reusing existing database gap report for sector: {sector_lookup}")
            return report
            
        # B. Check if saved run JSON file exists
        sector_key = _get_sector_key(sector_lookup)
        filename = f"{sector_key}.json"
        if (_SAVED_RUNS_DIR / filename).exists():
            logger.info(f"Restoring saved run {filename} from disk for sector: {sector_lookup}")
            try:
                _load_run_internal(filename)
                report = database.get_gap_report(sector_lookup) or database.get_gap_report(sector)
                if report:
                    return report
            except Exception as e:
                logger.exception(f"Failed to auto-restore saved run {filename}: {e}")
                
    # C. Perform live run if not found or forcing rebuild
    from src.agents.orchestrator import Orchestrator
    orchestrator = Orchestrator()
    try:
        demand, academic, gap = await asyncio.to_thread(
            orchestrator.run_research,
            sector,
            custom_academic
        )
        
        effective_sector = sector_lookup if custom_academic else sector
        report_id = database.save_gap_report(
            sector=effective_sector,
            industry_demand=demand.model_dump(),
            academic_landscape=academic.model_dump(),
            gap_analysis=gap.model_dump(),
            approved_by=None,
            approved_at=None
        )
        
        # Auto-save immediately to JSON
        _save_run_internal(effective_sector)
        
        return {
            "id": report_id,
            "sector": effective_sector,
            "industry_demand": demand.model_dump(),
            "academic_landscape": academic.model_dump(),
            "gap_analysis": gap.model_dump(),
            "is_new_run": True
        }
    except Exception as e:
        logger.exception("Research stage failed")
        return JSONResponse({"error": format_api_error_message(e)}, status_code=500)


@app.post("/api/approve-gap")
async def approve_gap_endpoint(payload: dict, user: dict = Depends(get_current_user)):
    """Save the approved gap analysis to database."""
    sector = payload.get("sector")
    approved_by = payload.get("approved_by", user["username"])
    import datetime
    approved_at = datetime.datetime.utcnow().isoformat()
    
    report = database.get_gap_report(sector)
    if not report:
        return JSONResponse({"error": "Report not found"}, status_code=404)
        
    gap_data = payload.get("gap_analysis", report["gap_analysis"])
    
    database.save_gap_report(
        sector=sector,
        industry_demand=report["industry_demand"],
        academic_landscape=report["academic_landscape"],
        gap_analysis=gap_data,
        approved_by=approved_by,
        approved_at=approved_at
    )
    
    # Auto-save immediately to JSON
    _save_run_internal(sector)
    
    return {"status": "success", "approved_by": approved_by, "approved_at": approved_at}


@app.get("/api/gaps")
async def list_gaps_endpoint(user: dict = Depends(get_current_user)):
    """Get all gap reports."""
    reports = database.list_gap_reports()
    result = []
    for r in reports:
        full = database.get_gap_report(r["sector"])
        if full:
            result.append(full)
    return result


@app.post("/api/course-design")
async def run_course_design_endpoint(payload: dict, user: dict = Depends(get_current_user)):
    """Run Stage 4 (Syllabus and Weekly Schedule design)."""
    gap_report_id = payload.get("gap_report_id")
    force_rebuild = payload.get("force_rebuild", False)
    learning_profile = payload.get("learning_profile")
    
    conn = database.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM gap_reports WHERE id = ?", (gap_report_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return JSONResponse({"error": "Gap report not found"}, status_code=404)
        
    sector = row["sector"]
    
    # A. Check if syllabus already exists and we are not forcing rebuild
    if not force_rebuild:
        existing = database.get_syllabus_by_gap(gap_report_id)
        if existing:
            logger.info(f"Reusing existing syllabus from DB for gap_report_id: {gap_report_id}")
            weeks = database.get_weekly_contents(existing["id"])
            return {
                "id": existing["id"],
                "course_title": existing["course_title"],
                "course_code": existing["course_code"],
                "credits": existing["credits"],
                "hours_per_week": existing["hours_per_week"],
                "learning_objectives": existing["learning_objectives"],
                "bibliography": existing["bibliography"],
                "weekly_schedule": weeks
            }
            
    # B. Run live design
    reference_material = payload.get("reference_material")
    gap_analysis_data = json.loads(row["gap_analysis"])
    from src.models.gap import GapAnalysis as GapModel
    gap_model = GapModel.model_validate(gap_analysis_data)
    
    from src.agents.orchestrator import Orchestrator
    orchestrator = Orchestrator()
    if reference_material:
        orchestrator._reference_material = reference_material

    try:
        study_plan = await asyncio.to_thread(orchestrator.run_course_design, gap_model)
        
        # If forcing rebuild, delete old syllabus and weekly contents for this gap_report
        conn = database.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM syllabi WHERE gap_report_id = ?", (gap_report_id,))
        old_syllabus_row = cursor.fetchone()
        if old_syllabus_row:
            old_sys_id = old_syllabus_row["id"]
            cursor.execute("DELETE FROM submissions WHERE weekly_content_id IN (SELECT id FROM weekly_contents WHERE syllabus_id = ?)", (old_sys_id,))
            cursor.execute("DELETE FROM weekly_contents WHERE syllabus_id = ?", (old_sys_id,))
            cursor.execute("DELETE FROM syllabi WHERE id = ?", (old_sys_id,))
        conn.commit()
        conn.close()
        
        # Save syllabus to DB (unapproved)
        syllabus_id = database.save_syllabus(
            gap_report_id=gap_report_id,
            course_title=study_plan.course_title,
            course_code=study_plan.course_code,
            credits=study_plan.credits,
            hours_per_week=study_plan.hours_per_week,
            learning_objectives=[obj.model_dump() for obj in study_plan.learning_objectives],
            bibliography=study_plan.bibliography,
            approved_by=None,
            approved_at=None,
            reference_material=reference_material
        )
        
        # Save the weekly contents structure as draft
        for item in study_plan.weekly_schedule or []:
            database.save_weekly_content(
                syllabus_id=syllabus_id,
                week_number=item.week,
                title=item.title,
                activity_type=item.activity_type,
                reading_material=None,
                assignment_prompt=None
            )
            
        # Auto-save immediately to JSON
        _save_run_internal(sector)
            
        return {
            "id": syllabus_id,
            "course_title": study_plan.course_title,
            "course_code": study_plan.course_code,
            "credits": study_plan.credits,
            "hours_per_week": study_plan.hours_per_week,
            "learning_objectives": [obj.model_dump() for obj in study_plan.learning_objectives],
            "bibliography": study_plan.bibliography,
            "weekly_schedule": [w.model_dump() for w in study_plan.weekly_schedule or []]
        }
    except Exception as e:
        logger.exception("Course design failed")
        return JSONResponse({"error": format_api_error_message(e)}, status_code=500)


@app.post("/api/approve-syllabus")
async def approve_syllabus_endpoint(payload: dict, user: dict = Depends(get_current_user)):
    """Approve course syllabus."""
    syllabus_id = payload.get("syllabus_id")
    approved_by = payload.get("approved_by", user["username"])
    import datetime
    approved_at = datetime.datetime.utcnow().isoformat()
    
    try:
        conn = database.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM syllabi WHERE id = ?", (syllabus_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return JSONResponse({"error": "Syllabus not found"}, status_code=404)
            
        cursor.execute("""
            UPDATE syllabi
            SET course_title = ?,
                course_code = ?,
                credits = ?,
                hours_per_week = ?,
                learning_objectives = ?,
                bibliography = ?,
                approved_by = ?,
                approved_at = ?
            WHERE id = ?
        """, (
            payload.get("course_title", row["course_title"]),
            payload.get("course_code", row["course_code"]),
            payload.get("credits", row["credits"]),
            payload.get("hours_per_week", row["hours_per_week"]),
            json.dumps(payload.get("learning_objectives", json.loads(row["learning_objectives"])), ensure_ascii=False),
            json.dumps(payload.get("bibliography", json.loads(row["bibliography"])), ensure_ascii=False),
            approved_by,
            approved_at,
            syllabus_id
        ))
        conn.commit()
        conn.close()
        
        # Process weekly schedule updates if present
        weekly_schedule = payload.get("weekly_schedule")
        if weekly_schedule:
            for week in weekly_schedule:
                database.save_weekly_content(
                    syllabus_id=syllabus_id,
                    week_number=week.get("week"),
                    title=week.get("title"),
                    activity_type=week.get("activity_type")
                )
        
        # Fetch sector name to auto-save
        conn = database.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT sector FROM gap_reports WHERE id = ?", (row["gap_report_id"],))
        gap_row = cursor.fetchone()
        conn.close()
        if gap_row:
            _save_run_internal(gap_row["sector"])
            
        return {"status": "success", "approved_by": approved_by, "approved_at": approved_at}
    except Exception as e:
        logger.exception("Failed to approve syllabus")
        import sqlite3
        if isinstance(e, sqlite3.OperationalError) and "locked" in str(e).lower():
            error_msg = "La base de datos está ocupada guardando la investigación de otro agente. Por favor, intenta aprobar el curso de nuevo en unos segundos."
        else:
            error_msg = f"Error interno al guardar: {str(e)}"
        return JSONResponse({"error": error_msg}, status_code=500)


@app.get("/api/syllabi")
async def list_syllabi_endpoint(user: dict = Depends(get_current_user)):
    """List all syllabi."""
    rows = database.list_syllabi()
    result = []
    for r in rows:
        conn = database.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM syllabi WHERE id = ?", (r["id"],))
        row = cursor.fetchone()
        conn.close()
        if row:
            result.append({
                "id": row["id"],
                "gap_report_id": row["gap_report_id"],
                "course_title": row["course_title"],
                "course_code": row["course_code"],
                "credits": row["credits"],
                "hours_per_week": row["hours_per_week"],
                "learning_objectives": json.loads(row["learning_objectives"]),
                "bibliography": json.loads(row["bibliography"]),
                "approved_by": row["approved_by"],
                "approved_at": row["approved_at"]
            })
    return result


def get_fallback_content(week_number: int, week_title: str) -> dict[str, str]:
    fallbacks = {
        1: {
            "reading_material": """
                <h3>Semana 1: Introducción a la Nube y DevOps</h3>
                <p>La computación en la nube ha transformado radicalmente la forma en que las empresas de tecnología en Costa Rica diseñan, despliegan y operan sus sistemas. Tradicionalmente, las organizaciones dependían de infraestructura física local (on-premise), lo cual requería altos costos de adquisición y mantenimiento. Hoy en día, nubes públicas como Amazon Web Services (AWS) proveen recursos bajo demanda con elasticidad y pago por uso.</p>
                <p>DevOps surge como respuesta a la brecha histórica entre los equipos de desarrollo (Dev) y operaciones (Ops). A través de la automatización de la integración y el despliegue de software, DevOps promueve entregas rápidas y seguras con alta calidad de software, eliminando los silos organizacionales.</p>
                <p>En este módulo inicial, exploraremos el modelo de responsabilidad compartida de la nube, las diferencias entre IaaS, PaaS y SaaS, y cómo los pilares de DevOps (Cultura, Automatización, Medición e Intercambio) habilitan la agilidad técnica que buscan las multinacionales en el país.</p>
            """,
            "assignment_prompt": "Redacte un ensayo corto (mínimo 250 palabras) comparando los beneficios de la arquitectura Cloud-Native frente a la tradicional on-premise en el contexto de una PYME costarricense."
        },
        2: {
            "reading_material": """
                <h3>Semana 2: Contenedores y Docker Básico</h3>
                <p>Los contenedores resuelven el clásico problema de "funciona en mi máquina, pero no en producción". A diferencia de las máquinas virtuales tradicionales que empaquetan un sistema operativo completo, un contenedor Docker comparte el núcleo del sistema operativo anfitrión, siendo mucho más ligero y rápido de iniciar.</p>
                <p>El archivo fundamental de configuración es el <code>Dockerfile</code>, que define las instrucciones paso a paso para construir la imagen del contenedor. Aprenderemos a utilizar comandos esenciales como <code>FROM</code>, <code>WORKDIR</code>, <code>COPY</code>, <code>RUN</code>, <code>EXPOSE</code> y <code>CMD</code>.</p>
                <p>Una buena práctica clave en la industria es mantener las imágenes lo más pequeñas posible utilizando compilaciones multi-etapa (multi-stage builds) y evitando incluir archivos innecesarios en la imagen final.</p>
            """,
            "assignment_prompt": "Escriba un Dockerfile optimizado para una aplicación web sencilla en Python/Node.js, detallando el propósito de cada instrucción utilizada y cómo aplicaría multi-stage builds."
        },
        3: {
            "reading_material": """
                <h3>Semana 3: Almacenamiento y Redes en Docker</h3>
                <p>Por defecto, los datos dentro de un contenedor son efímeros; si el contenedor se destruye, los datos se pierden. Para solucionar esto, Docker provee volúmenes (Volumes) y montajes de unión (Bind Mounts), permitiendo persistir datos fuera del ciclo de vida del contenedor.</p>
                <p>En cuanto a las redes, Docker cuenta con controladores (Bridge, Host, Overlay, None) para permitir la intercomunicación aislada entre contenedores o con la red del host. Utilizaremos Docker Compose para orquestar entornos multi-contenedor de manera local.</p>
            """,
            "assignment_prompt": "Describa la configuración de un archivo docker-compose.yml que conecte un servicio de backend (Web API) con una base de datos PostgreSQL persistente compartiendo una red virtual privada."
        },
        4: {
            "reading_material": """
                <h3>Semana 4: Introducción a Kubernetes</h3>
                <p>A medida que la cantidad de contenedores en producción crece, se vuelve inviable gestionarlos manualmente. Aquí es donde entra Kubernetes (K8s), un orquestador de contenedores de código abierto que automatiza el despliegue, la escala y la operación de aplicaciones en contenedores.</p>
                <p>Las unidades básicas en Kubernetes son los <b>Pods</b> (que agrupan uno o más contenedores), los <b>Deployments</b> (que gestionan la replicación y las actualizaciones de Pods) y los <b>Services</b> (que exponen los Pods a la red externa).</p>
            """,
            "assignment_prompt": "Explique la diferencia entre un Pod, un Deployment y un Service en Kubernetes, y cómo trabajan juntos para mantener una aplicación disponible y escalable."
        },
        5: {
            "reading_material": """
                <h3>Semana 5: Despliegue Local con Minikube</h3>
                <p>Minikube es una herramienta que facilita la ejecución local de Kubernetes, levantando un clúster de un solo nodo en nuestra computadora. Esto permite a los desarrolladores experimentar con manifiestos YAML y validar sus despliegues de K8s antes de subirlos a nubes como AWS EKS.</p>
                <p>Aprenderemos a usar la herramienta CLI <code>kubectl</code> para interactuar con el clúster, crear recursos y depurar contenedores en ejecución a través de comandos como <code>logs</code> y <code>describe</code>.</p>
            """,
            "assignment_prompt": "Escriba los manifiestos YAML mínimos para desplegar una aplicación web (un Deployment con 2 réplicas y un Service tipo ClusterIP) y verifique el estado de los Pods."
        },
        6: {
            "reading_material": """
                <h3>Semana 6: Configuración en Kubernetes (ConfigMaps y Secrets)</h3>
                <p>Para lograr la portabilidad de las aplicaciones en contenedores, es crucial desacoplar el código de su configuración. En Kubernetes, esto se logra utilizando <b>ConfigMaps</b> para datos de configuración no confidenciales y <b>Secrets</b> para información sensible (como contraseñas, claves API y certificados).</p>
                <p>Estos recursos pueden inyectarse a los contenedores como variables de entorno o montarse como volúmenes de archivos, permitiendo actualizar la configuración sin necesidad de reconstruir la imagen del contenedor.</p>
            """,
            "assignment_prompt": "Elabore un ejemplo YAML de un ConfigMap y un Secret y muestre cómo referenciarlos dentro de la sección env de un manifiesto de Deployment."
        },
        7: {
            "reading_material": """
                <h3>Semana 7: Trabajo Ágil y GitFlow</h3>
                <p>El desarrollo moderno de software en las multinacionales en Costa Rica no solo requiere competencias técnicas, sino también metodologías ágiles de trabajo en equipo. El uso de Scrum permite organizar tareas en ciclos cortos llamados sprints, asegurando entregas continuas y feedback del cliente.</p>
                <p>Complementariamente, GitFlow provee un modelo robusto de ramificación para Git, estructurando el trabajo colaborativo en ramas de características (feature), desarrollo (develop), lanzamiento (release) y producción (main/master).</p>
            """,
            "assignment_prompt": "Describa detalladamente el flujo de trabajo de GitFlow desde que se inicia el desarrollo de una nueva característica hasta que se publica en producción."
        },
        8: {
            "reading_material": """
                <h3>Semana 8: Integración Continua (CI) con GitHub Actions</h3>
                <p>La Integración Continua (CI) es la práctica de automatizar la compilación y pruebas del código cada vez que un miembro del equipo sube cambios al repositorio. Esto previene conflictos de integración ("infierno de integración") y detecta errores tempranamente.</p>
                <p>GitHub Actions nos permite definir flujos de trabajo (workflows) en archivos YAML ubicados en <code>.github/workflows/</code>, los cuales reaccionan a eventos del repositorio como <code>push</code> o <code>pull_request</code>.</p>
            """,
            "assignment_prompt": "Escriba un archivo de flujo de trabajo de GitHub Actions (.yml) que se deba disparar en pull requests a main, instale dependencias y compile el proyecto."
        },
        9: {
            "reading_material": """
                <h3>Semana 9: Calidad del Código y Testing Automatizado</h3>
                <p>Las pruebas unitarias automatizadas garantizan que bloques individuales de código (funciones, clases) se comporten de la manera esperada. Mediante frameworks como PyTest (Python) o Jest (JavaScript), podemos ejecutar cientos de pruebas en segundos.</p>
                <p>La cobertura de código (code coverage) mide qué porcentaje de nuestro código fuente está siendo ejercitado por las pruebas, sirviendo como indicador clave en el pipeline de Integración Continua para rechazar cambios deficientes.</p>
            """,
            "assignment_prompt": "Escriba 3 casos de prueba unitarios utilizando PyTest o Jest para probar el comportamiento de un validador de correos electrónicos y simule su ejecución en un pipeline."
        },
        10: {
            "reading_material": """
                <h3>Semana 10: Análisis de Código Estático y Linter</h3>
                <p>El análisis de código estático examina el código fuente sin ejecutarlo. Los linters (como Flake8 o ESLint) aseguran la consistencia de estilo de codificación, mientras que herramientas de seguridad (como Bandit o SonarQube) buscan vulnerabilidades conocidas en las dependencias o patrones peligrosos.</p>
                <p>Integrar estas herramientas en nuestro pipeline de CI asegura que ningún código que no cumpla con los estándares mínimos de la organización pueda integrarse a las ramas principales.</p>
            """,
            "assignment_prompt": "Explique el propósito del análisis estático de código y configure un paso de linter (por ejemplo, Flake8) en su flujo de trabajo de GitHub Actions."
        },
        11: {
            "reading_material": """
                <h3>Semana 11: Despliegue Continuo (CD) y Nubes Públicas</h3>
                <p>El Despliegue Continuo (CD) toma el artefacto construido y probado en la fase de CI y lo publica automáticamente en los servidores de producción o staging. Analizaremos las estrategias de despliegue como Blue-Green (minimiza el tiempo de inactividad) y Canary (despliega gradualmente para un grupo pequeño de usuarios).</p>
            """,
            "assignment_prompt": "Compare las estrategias de despliegue Blue-Green y Canary, listando las ventajas y riesgos de cada una para aplicaciones empresariales."
        },
        12: {
            "reading_material": """
                <h3>Semana 12: Despliegue Automatizado en AWS</h3>
                <p>AWS ECS (Elastic Container Service) es un servicio de orquestación de contenedores altamente escalable y de alto rendimiento que permite ejecutar contenedores Docker en AWS. Configuraremos GitHub Actions para autenticarse de manera segura con AWS e instruir el despliegue automático de una nueva imagen de contenedor.</p>
            """,
            "assignment_prompt": "Explique los pasos necesarios para configurar credenciales seguras (OIDC o AWS Access Keys) y automatizar el despliegue en Amazon ECS desde GitHub Actions."
        },
        13: {
            "reading_material": """
                <h3>Semana 13: Monitoreo y Observabilidad</h3>
                <p>Una vez desplegada en la nube, es vital saber cómo se comporta nuestra aplicación en tiempo real. El monitoreo recopila métricas cuantitativas (CPU, memoria, latencia de solicitudes), mientras que la observabilidad nos permite entender los estados internos del sistema a través de logs centralizados y trazas distribuidas.</p>
            """,
            "assignment_prompt": "Proponga una arquitectura básica de monitoreo para una aplicación microservicios en Kubernetes utilizando Prometheus y Grafana."
        },
        14: {
            "reading_material": """
                <h3>Semana 14: Proyecto Integrador - Fase Desarrollo</h3>
                <p>En esta penúltima fase del proyecto de TCU, el estudiante consolida los conocimientos de desarrollo y empaquetamiento. Trabajando colaborativamente en equipos, estructurarán el backend en contenedores Docker y configurarán el repositorio de código fuente listo para el despliegue.</p>
            """,
            "assignment_prompt": "Presente un diagrama de arquitectura y el estado del repositorio de código de su proyecto integrador con los Dockerfiles correspondientes."
        },
        15: {
            "reading_material": """
                <h3>Semana 15: Proyecto Integrador - Fase Despliegue</h3>
                <p>Esta fase finaliza la puesta en marcha de la aplicación en la nube. Se configuran los pipelines de GitHub Actions para compilar, probar e inyectar la imagen optimizada en la infraestructura cloud de producción, asegurando que cada commit a main se refleje de inmediato en vivo.</p>
            """,
            "assignment_prompt": "Envíe el enlace del repositorio activo y una captura de pantalla del pipeline de GitHub Actions completando exitosamente el despliegue en la nube."
        },
        16: {
            "reading_material": """
                <h3>Semana 16: Defensa Final y Evaluación de Competencias</h3>
                <p>El cierre del curso comprende la evaluación final de las competencias adquiridas. Cada grupo presenta y defiende su solución Cloud-Native ante el comité evaluador, demostrando el flujo completo de entrega de valor automatizada y discutiendo las lecciones aprendidas durante el Trabajo Comunal Universitario (TCU).</p>
            """,
            "assignment_prompt": "Suba la presentación final de su proyecto de TCU y el documento resumen con la justificación técnica de la infraestructura implementada."
        }
    }
    return fallbacks.get(week_number, {
        "reading_material": f"<h3>Lectura Semanal: {week_title}</h3><p>Contenido educativo detallado sobre {week_title}.</p>",
        "assignment_prompt": f"Responda a las preguntas conceptuales sobre {week_title}."
    })


@app.post("/api/generate-reading")
async def generate_reading_endpoint(payload: dict, user: dict = Depends(get_current_user)):
    """Run ReadingAgent to generate reading material and assignments for a week."""
    syllabus_id = payload.get("syllabus_id")
    week_number = payload.get("week_number")
    force_rebuild = payload.get("force_rebuild", False)
    learning_profile = payload.get("learning_profile")
    
    conn = database.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM syllabi WHERE id = ?", (syllabus_id,))
    syllabus_row = cursor.fetchone()
    cursor.execute("SELECT * FROM weekly_contents WHERE syllabus_id = ? AND week_number = ?", (syllabus_id, week_number))
    week_row = cursor.fetchone()
    conn.close()
    
    if not syllabus_row or not week_row:
        return JSONResponse({"error": "Syllabus or week content not found"}, status_code=404)
        
    # A. Check if reading content already exists and we are not forcing rebuild
    if not force_rebuild:
        if week_row["reading_material"] and week_row["assignment_prompt"]:
            logger.info(f"Reusing existing week {week_number} content from DB")
            return {
                "week_number": week_number,
                "reading_material": week_row["reading_material"],
                "assignment_prompt": week_row["assignment_prompt"]
            }
            
    # B. Run live generation
    from src.agents.reading_agent import NotebookLMAgent, ReadingAgent
    from src.config import settings
    if learning_profile and learning_profile.get("dominant_style") == "aural":
        agent = NotebookLMAgent(max_cost=settings.max_cost_professor)
    else:
        agent = ReadingAgent(max_cost=settings.max_cost_professor)
    try:
        raw = await asyncio.to_thread(
            agent.generate_reading,
            course_title=syllabus_row["course_title"],
            week_number=week_number,
            week_title=week_row["title"],
            activity_type=week_row["activity_type"],
            week_description=week_row["title"],
            objectives=syllabus_row["learning_objectives"],
            learning_profile=learning_profile
        )
        
        import src.agents.base_agent
        clean_raw = src.agents.base_agent.BaseAgent.clean_json(raw)
        data = json.loads(clean_raw)
        reading_material = data.get("reading_material")
        assignment_prompt = data.get("assignment_prompt")
    except Exception as e:
        logger.exception("Reading generation failed, using high-fidelity fallback")
        fallback = get_fallback_content(week_number, week_row["title"])
        reading_material = fallback["reading_material"]
        assignment_prompt = fallback["assignment_prompt"]
        
    database.save_weekly_content(
        syllabus_id=syllabus_id,
        week_number=week_number,
        title=week_row["title"],
        activity_type=week_row["activity_type"],
        reading_material=reading_material,
        assignment_prompt=assignment_prompt
    )
    
    # Multimedia Integration
    audio_url = None
    video_url = None
    heygen_video_id = None
    anki_url = None
    
    if learning_profile:
        dom_style = learning_profile.get("dominant_style")
        
        # We process multimedia asynchronously so it doesn't block entirely, 
        # but for this script we do it synchronously as a proof of concept.
        from src.multimedia import generate_elevenlabs_audio, generate_heygen_video, generate_anki_deck
        
        if dom_style == "aural":
            import uuid
            audio_filename = f"podcast_{uuid.uuid4().hex[:8]}.mp3"
            audio_path = str(_STATIC_DIR / "audio" / audio_filename)
            # Remove HTML tags for TTS
            import re
            clean_text = re.sub(r'<[^>]+>', ' ', reading_material)
            success = generate_elevenlabs_audio(clean_text, audio_path)
            if success:
                audio_url = f"/static/audio/{audio_filename}"
                
        elif dom_style == "visual":
            # Just send a chunk of the material to avoid massive HeyGen costs
            import re
            clean_text = re.sub(r'<[^>]+>', ' ', reading_material)
            video_id = generate_heygen_video(clean_text[:500])
            if video_id:
                # Retornamos el ID para que el frontend inicie el polling
                heygen_video_id = video_id
                
        elif dom_style == "kinesthetic":
            import uuid
            deck_filename = f"flashcards_{uuid.uuid4().hex[:8]}.apkg"
            deck_path = str(_STATIC_DIR / "decks" / deck_filename)
            success = generate_anki_deck(reading_material, week_row["title"], deck_path)
            if success:
                anki_url = f"/static/decks/{deck_filename}"
    
def validate_and_sanitize_flashcards(raw_cards: list[dict[str, str]]) -> list[dict[str, str]]:
    import re
    valid_cards = []
    
    JUNK_TITLE_PATTERNS = [
        r"^módulo\b",
        r"^semana\s+\d+",
        r"\bclick para revelar\b",
        r"\bhaz clic\b",
        r"^\d+[\.\)]\s*introducción\b",
        r"^\d+[\.\)]\s*conclusión\b",
        r"^\d+[\.\)]\s*resumen\b",
        r"^introducción\b",
        r"^conclusión\b",
        r"^resumen\b",
        r"^objetivos?\b",
        r"^bibliografía\b",
        r"^tabla de contenidos?\b",
        r"^ejercicios?\b",
        r"^tarea\b",
        r"^práctica\b",
    ]
    
    for card in raw_cards:
        front = card.get("front", "").strip()
        back = card.get("back", "").strip()
        
        front = re.sub(r'\(click para revelar\)', '', front, flags=re.IGNORECASE).strip()
        front = re.sub(r'\(haz clic para revelar\)', '', front, flags=re.IGNORECASE).strip()
        front = re.sub(r'^\s*📌\s*', '', front).strip()
        
        if not front or len(front) < 5 or not back or len(back) < 10:
            continue
            
        is_junk = False
        for pattern in JUNK_TITLE_PATTERNS:
            if re.search(pattern, front, re.IGNORECASE):
                is_junk = True
                break
        if is_junk:
            continue
            
        if len(front) > 110:
            continue
            
        if front.lower() in back.lower() and len(back) < len(front) + 15:
            continue
            
        clean_q = front.strip(" .:")
        if not (clean_q.endswith("?") or clean_q.startswith("¿") or clean_q.lower().startswith("concepto") or clean_q.lower().startswith("qué") or clean_q.lower().startswith("cómo") or clean_q.lower().startswith("cuál") or clean_q.lower().startswith("diferencia")):
            if len(clean_q.split()) <= 6:
                front = f"📌 ¿En qué consiste '{clean_q}' y cuál es su función?"
            else:
                front = f"📌 ¿Qué representa o cómo se aplica '{clean_q}'?"
        else:
            front = f"📌 {clean_q}"

        valid_cards.append({"front": front, "back": back})
        
    return valid_cards

def extract_flashcards_from_html(html_text: str) -> list[dict[str, str]]:
    import re
    raw_flashcards = []
    pattern = r'<details[^>]*class=["\']flashcard["\'][^>]*>\s*<summary>(.*?)</summary>\s*<div[^>]*class=["\']flashcard-body["\'][^>]*>(.*?)</div>\s*</details>'
    matches = re.findall(pattern, html_text, re.DOTALL | re.IGNORECASE)
    for summary, body in matches:
        clean_front = re.sub(r'<[^>]+>', ' ', summary).strip()
        clean_back = re.sub(r'\s+', ' ', re.sub(r'<br\s*/?>', '\n', body)).strip()
        clean_back = re.sub(r'<[^>]+>', ' ', clean_back).strip()
        if clean_front and clean_back:
            raw_flashcards.append({"front": clean_front, "back": clean_back})

    if not raw_flashcards:
        headers = re.findall(r'<h[234][^>]*>(.*?)</h[234]>', html_text, re.IGNORECASE)
        paragraphs = re.findall(r'<p[^>]*>(.*?)</p>', html_text, re.IGNORECASE)
        lists = re.findall(r'<li[^>]*>(.*?)</li[^>]*>', html_text, re.IGNORECASE)
        
        if lists and len(lists) >= 4:
            for i, li in enumerate(lists[:8]):
                li_clean = re.sub(r'<[^>]+>', ' ', li).strip()
                if len(li_clean) > 15:
                    parts = li_clean.split(":", 1)
                    if len(parts) == 2:
                        raw_flashcards.append({"front": parts[0].strip(), "back": parts[1].strip()})
                    else:
                        raw_flashcards.append({"front": f"Concepto Clave #{i+1}", "back": li_clean})
        else:
            for i in range(min(len(headers), len(paragraphs))):
                h_clean = re.sub(r'<[^>]+>', ' ', headers[i]).strip()
                p_clean = re.sub(r'<[^>]+>', ' ', paragraphs[i]).strip()
                if h_clean and p_clean and len(p_clean) > 20:
                    raw_flashcards.append({"front": h_clean, "back": p_clean})

    return validate_and_sanitize_flashcards(raw_flashcards)


    # Auto-save immediately to JSON
    _save_run_internal(syllabus_row["course_title"])
    
    flashcards_list = extract_flashcards_from_html(reading_material)
    
    return {
        "week_number": week_number,
        "reading_material": reading_material,
        "assignment_prompt": assignment_prompt,
        "audio_url": audio_url,
        "video_url": video_url,
        "heygen_video_id": heygen_video_id,
        "anki_url": anki_url,
        "flashcards": flashcards_list
    }


@app.post("/api/publish-reading")
async def publish_reading_endpoint(payload: dict):
    """Save professor's manual edits to the generated reading."""
    syllabus_id = payload.get("syllabus_id")
    week_number = payload.get("week_number")
    reading_material = payload.get("reading_material")
    assignment_prompt = payload.get("assignment_prompt")
    
    if not all([syllabus_id, week_number, reading_material, assignment_prompt]):
        return JSONResponse({"error": "Missing required fields"}, status_code=400)
        
    conn = database.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT title, activity_type FROM weekly_contents WHERE syllabus_id = ? AND week_number = ?", (syllabus_id, week_number))
    week_row = cursor.fetchone()
    conn.close()
    
    if not week_row:
        return JSONResponse({"error": "Week content not found"}, status_code=404)
        
    database.save_weekly_content(
        syllabus_id=syllabus_id,
        week_number=week_number,
        title=week_row["title"],
        activity_type=week_row["activity_type"],
        reading_material=reading_material,
        assignment_prompt=assignment_prompt
    )
    
    # Auto-save
    conn = database.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT course_title FROM syllabi WHERE id = ?", (syllabus_id,))
    s_row = cursor.fetchone()
    conn.close()
    if s_row:
        _save_run_internal(s_row["course_title"])
        
    return {"status": "success"}


@app.get("/api/weekly-contents/{syllabus_id}")
async def get_weekly_contents_endpoint(syllabus_id: int):
    """Get all weekly contents for a syllabus."""
    return database.get_weekly_contents(syllabus_id)


@app.post("/api/submissions")
async def submit_answer_endpoint(payload: dict, user: dict = Depends(get_current_user)):
    """Submit text response for weekly assignment (Student persona)."""
    weekly_content_id = payload.get("weekly_content_id")
    student_id = payload.get("student_id") or user.get("username") or "estudiante1"
    submitted_text = payload.get("submitted_text")
    import datetime
    submitted_at = datetime.datetime.utcnow().isoformat()
    
    if not submitted_text:
        return JSONResponse({"error": "Por favor escribe tu respuesta antes de entregar."}, status_code=400)
    
    try:
        wc_id = int(weekly_content_id) if weekly_content_id is not None else 1
    except (ValueError, TypeError):
        wc_id = 1

    try:
        submission_id = database.save_submission(
            weekly_content_id=wc_id,
            student_id=student_id,
            submitted_text=submitted_text,
            submitted_at=submitted_at
        )
        
        # Auto-save immediately to JSON
        try:
            conn = database.get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT s.course_title FROM syllabi s
                JOIN weekly_contents wc ON wc.syllabus_id = s.id
                WHERE wc.id = ?
            """, (wc_id,))
            row = cursor.fetchone()
            conn.close()
            if row:
                _save_run_internal(row["course_title"])
        except Exception as e:
            logger.warning(f"Auto-save after submission warning: {e}")
            
        return {"status": "success", "submitted_at": submitted_at, "submission_id": submission_id}
    except Exception as e:
        logger.exception("Error saving submission")
        return JSONResponse({"error": f"Error al guardar la entrega: {str(e)}"}, status_code=500)


@app.get("/api/submissions/{student_id}")
async def get_submissions_endpoint(student_id: str):
    """Get all submissions for a student."""
    return database.get_submissions(student_id)


@app.post("/api/grade-submission")
async def grade_submission_endpoint(payload: dict, user: dict = Depends(get_current_user)):
    """Run GradingAgent to evaluate a specific submission."""
    submission_id = payload.get("submission_id")
    
    if not submission_id:
        return JSONResponse({"error": "Missing submission_id"}, status_code=400)
        
    conn = database.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT s.id, s.submitted_text, wc.assignment_prompt, wc.syllabus_id
        FROM submissions s
        JOIN weekly_contents wc ON s.weekly_content_id = wc.id
        WHERE s.id = ?
    """, (submission_id,))
    sub_row = cursor.fetchone()
    conn.close()
    
    if not sub_row:
        return JSONResponse({"error": "Submission not found"}, status_code=404)
        
    from src.agents.grading_agent import GradingAgent
    from src.config import settings
    import json
    import src.agents.base_agent
    
    agent = GradingAgent(max_cost=settings.max_cost_student)
    try:
        raw = await asyncio.to_thread(
            agent.grade_submission,
            assignment_prompt=sub_row["assignment_prompt"],
            submitted_text=sub_row["submitted_text"]
        )
        
        clean_raw = src.agents.base_agent.BaseAgent.clean_json(raw)
        data = json.loads(clean_raw)
        grade = float(data.get("grade", 0))
        feedback = data.get("feedback", "Sin retroalimentación.")
    except Exception as e:
        logger.exception("Grading generation failed")
        error_msg = f"No se pudo calificar el documento. Hubo un error en la validación por IA: {str(e)}. Intenta de nuevo más tarde."
        return JSONResponse({"error": error_msg}, status_code=500)
        
    database.grade_submission(
        submission_id=submission_id,
        grade=grade,
        feedback=feedback
    )
    
    return {
        "submission_id": submission_id,
        "grade": grade,
        "feedback": feedback
    }


# ──────────────────────────────────────────────────────────────────────────
# Practice Exam & Live AI Tutor Endpoints (3-Step Modality Workflow)
# ──────────────────────────────────────────────────────────────────────────

@app.api_route("/api/tutor/stream-audio", methods=["GET", "POST"])
async def tutor_stream_audio_endpoint(text: str = "", voice: str = "alloy", payload: dict = None):
    """
    Realtime audio streaming endpoint that pipes OpenAI TTS MP3 byte chunks in real-time.
    """
    from src.multimedia import stream_openai_audio
    
    if payload:
        text = payload.get("text", text)
        voice = payload.get("voice", voice)
        
    if not text:
        return JSONResponse({"error": "Missing text"}, status_code=400)
        
    return StreamingResponse(
        stream_openai_audio(text=text, voice=voice),
        media_type="audio/mpeg",
        headers={
            "Cache-Control": "no-cache",
            "X-Content-Type-Options": "nosniff"
        }
    )


@app.post("/api/exam/step")
async def exam_step_endpoint(payload: dict):
    """
    Evaluates an interactive step of the adaptive practice exam using RAG over weekly content.
    """
    from src.agents.exam_agent import ExamAgent
    from src.config import settings
    
    weekly_content_id = payload.get("weekly_content_id")
    student_id = payload.get("student_id", "VinicioPrueba")
    history = payload.get("history", [])
    iteration = int(payload.get("iteration", 1))
    
    if not weekly_content_id:
        return JSONResponse({"error": "Missing weekly_content_id"}, status_code=400)
        
    agent = ExamAgent(max_cost=settings.max_cost_student)
    try:
        data = await asyncio.to_thread(
            agent.evaluate_step,
            text_content="",
            history=history,
            iteration=iteration,
            weekly_content_id=weekly_content_id
        )
        
        # If exam finished, save diagnostic record
        if data.get("is_finished"):
            score = float(data.get("final_grade", 0))
            mastered = data.get("mastered_topics", [])
            gaps = data.get("knowledge_gaps", [])
            database.save_exam_diagnostic(student_id, weekly_content_id, score, mastered, gaps)
            
        return data
    except Exception as e:
        logger.exception("Exam step evaluation failed")
        return JSONResponse({"error": f"Error evaluando el examen: {str(e)}"}, status_code=500)


@app.get("/api/exam/diagnostic/{weekly_content_id}")
async def get_exam_diagnostic_endpoint(weekly_content_id: int, student_id: str = "VinicioPrueba"):
    """
    Get saved exam diagnostic (mastered topics and knowledge gaps) for a student and week.
    """
    diag = database.get_exam_diagnostic(student_id, weekly_content_id)
    return diag or {"has_taken_exam": False}


@app.get("/api/student/analytics/{student_id}")
async def get_student_analytics_endpoint(student_id: str):
    """
    Get aggregated learning progress, VARK profile, exam score history & knowledge gaps analytics.
    """
    return database.get_student_analytics_data(student_id)


@app.post("/api/tutor/init")
async def tutor_init_endpoint(payload: dict):
    """
    Initialize Live AI Tutor session with initial socratic greeting based on student exam diagnostic.
    """
    from src.agents.realtime_tutor_agent import RealtimeTutorAgent
    from src.config import settings
    from urllib.parse import quote
    
    weekly_content_id = payload.get("weekly_content_id")
    student_id = payload.get("student_id", "VinicioPrueba")
    voice_name = payload.get("voice", "alloy")
    
    if not weekly_content_id:
        return JSONResponse({"error": "Missing weekly_content_id"}, status_code=400)
        
    agent = RealtimeTutorAgent(max_cost=settings.max_cost_student)
    try:
        greeting = await asyncio.to_thread(
            agent.build_initial_greeting,
            weekly_content_id=weekly_content_id,
            student_id=student_id
        )
        
        ctx = RealtimeTutorAgent.get_tutor_context(weekly_content_id, student_id)
        
        # Realtime audio streaming URL
        stream_url = f"/api/tutor/stream-audio?text={quote(greeting[:1000])}&voice={voice_name}"

        return {
            "greeting": greeting,
            "audio_url": stream_url,
            "stream_url": stream_url,
            "context": ctx
        }
    except Exception as e:
        logger.exception("Tutor initialization failed")
        return JSONResponse({"error": f"Error iniciando tutoría: {str(e)}"}, status_code=500)


@app.post("/api/tutor/chat")
async def tutor_chat_endpoint(payload: dict):
    """
    Process interactive duplex turn in Live AI Tutor session.
    """
    from src.agents.realtime_tutor_agent import RealtimeTutorAgent
    from src.config import settings
    from urllib.parse import quote
    
    weekly_content_id = payload.get("weekly_content_id")
    student_id = payload.get("student_id", "VinicioPrueba")
    user_message = payload.get("user_message", "")
    history = payload.get("history", [])
    voice_name = payload.get("voice", "alloy")
    
    if not weekly_content_id or not user_message:
        return JSONResponse({"error": "Missing weekly_content_id or user_message"}, status_code=400)
        
    agent = RealtimeTutorAgent(max_cost=settings.max_cost_student)
    try:
        tutor_data = await asyncio.to_thread(
            agent.chat_step,
            weekly_content_id=weekly_content_id,
            student_id=student_id,
            user_message=user_message,
            history=history
        )
        
        response_text = tutor_data.get("response_text", "")
        resolved_gaps = tutor_data.get("resolved_gaps", [])

        # Auto-sync resolved gaps directly to SQLite database
        if resolved_gaps:
            for gap in resolved_gaps:
                database.resolve_student_knowledge_gap(student_id, int(weekly_content_id), gap)
        
        # Realtime audio streaming URL
        stream_url = f"/api/tutor/stream-audio?text={quote(response_text[:1000])}&voice={voice_name}"

        return {
            "response_text": response_text,
            "resolved_gaps": resolved_gaps,
            "audio_url": stream_url,
            "stream_url": stream_url
        }
    except Exception as e:
        logger.exception("Tutor chat turn failed")
        return JSONResponse({"error": f"Error en tutoría: {str(e)}"}, status_code=500)




# ──────────────────────────────────────────────────────────────────────────
# Saved Runs / Demo Packages Management
# ──────────────────────────────────────────────────────────────────────────

import re
import datetime

_SAVED_RUNS_DIR = Path("saved_runs")
_SAVED_RUNS_DIR.mkdir(exist_ok=True)


def _get_sector_key(sector: str) -> str:
    return re.sub(r"[^\w]", "_", sector).lower()


def _save_run_internal(sector: str, custom_name: str | None = None) -> str:
    sector_key = _get_sector_key(sector)
    filename_base = _get_sector_key(custom_name) if custom_name else sector_key
    filename = f"{filename_base}.json"
    
    # 1. Load stage cache files
    stage_cache = {}
    stages = ["market_research", "academic_research", "gap_analysis", "course_design", "evaluator"]
    stage_cache_dir = Path("stage_cache")
    for stage in stages:
        cache_file = stage_cache_dir / f"{sector_key}_{stage}.json"
        if cache_file.exists():
            try:
                stage_cache[stage] = json.loads(cache_file.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"Failed to load cache file {cache_file}: {e}")
                
    # 2. Query Database rows
    db_data = {
        "gap_report": None,
        "syllabus": None,
        "weekly_contents": [],
        "submissions": []
    }
    
    conn = database.get_db_connection()
    cursor = conn.cursor()
    try:
        # Get gap report
        cursor.execute("SELECT * FROM gap_reports WHERE sector = ?", (sector,))
        gap_row = cursor.fetchone()
        if gap_row:
            db_data["gap_report"] = dict(gap_row)
            gap_report_id = gap_row["id"]
            
            # Get syllabus
            cursor.execute("SELECT * FROM syllabi WHERE gap_report_id = ?", (gap_report_id,))
            syllabus_row = cursor.fetchone()
            if syllabus_row:
                db_data["syllabus"] = dict(syllabus_row)
                syllabus_id = syllabus_row["id"]
                
                # Get weekly contents
                cursor.execute("SELECT * FROM weekly_contents WHERE syllabus_id = ?", (syllabus_id,))
                wc_rows = cursor.fetchall()
                db_data["weekly_contents"] = [dict(r) for r in wc_rows]
                
                # Get submissions
                if wc_rows:
                    wc_ids = [r["id"] for r in wc_rows]
                    placeholders = ",".join("?" for _ in wc_ids)
                    cursor.execute(f"SELECT * FROM submissions WHERE weekly_content_id IN ({placeholders})", wc_ids)
                    sub_rows = cursor.fetchall()
                    db_data["submissions"] = [dict(r) for r in sub_rows]
    except Exception as e:
        logger.exception(f"Failed to query DB during run save for sector {sector}: {e}")
    finally:
        conn.close()
        
    # Write to saved_runs
    out_path = _SAVED_RUNS_DIR / filename
    saved_data = {
        "sector": sector,
        "sector_key": sector_key,
        "saved_at": datetime.datetime.utcnow().isoformat(),
        "stage_cache": stage_cache,
        "database": db_data
    }
    
    out_path.write_text(json.dumps(saved_data, ensure_ascii=False, indent=2), encoding="utf-8")
    return filename


def _load_run_internal(filename: str) -> str:
    p = _SAVED_RUNS_DIR / filename
    if not p.exists() or not p.resolve().is_relative_to(_SAVED_RUNS_DIR.resolve()):
        raise FileNotFoundError(f"Archivo no encontrado: {filename}")
        
    data = json.loads(p.read_text(encoding="utf-8"))
    sector = data.get("sector")
    sector_key = data.get("sector_key") or _get_sector_key(sector)
    stage_cache = data.get("stage_cache") or {}
    db_data = data.get("database") or {}
    
    # 1. Restore Stage Cache files
    stage_cache_dir = Path("stage_cache")
    stage_cache_dir.mkdir(exist_ok=True)
    
    # Clear old cache files for this sector key first
    for f in stage_cache_dir.glob(f"{sector_key}_*.json"):
        try:
            f.unlink()
        except Exception:
            pass
            
    # Write new cache files
    for stage, cache_content in stage_cache.items():
        cache_file = stage_cache_dir / f"{sector_key}_{stage}.json"
        try:
            cache_file.write_text(json.dumps(cache_content, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to write stage cache file {cache_file}: {e}")
            
    # 2. Restore DB tables
    conn = database.get_db_connection()
    cursor = conn.cursor()
    try:
        # Step A: Perform manual cascading deletion to clear previous records for this sector
        cursor.execute("SELECT id FROM gap_reports WHERE sector = ?", (sector,))
        gap_row = cursor.fetchone()
        if gap_row:
            old_gap_id = gap_row["id"]
            cursor.execute("SELECT id FROM syllabi WHERE gap_report_id = ?", (old_gap_id,))
            syllabi_rows = cursor.fetchall()
            for s_row in syllabi_rows:
                s_id = s_row["id"]
                cursor.execute("SELECT id FROM weekly_contents WHERE syllabus_id = ?", (s_id,))
                wc_rows = cursor.fetchall()
                for wc_row in wc_rows:
                    cursor.execute("DELETE FROM submissions WHERE weekly_content_id = ?", (wc_row["id"],))
                cursor.execute("DELETE FROM weekly_contents WHERE syllabus_id = ?", (s_id,))
            cursor.execute("DELETE FROM syllabi WHERE gap_report_id = ?", (old_gap_id,))
            cursor.execute("DELETE FROM gap_reports WHERE id = ?", (old_gap_id,))
            
        # Step B: Insert new records (re-mapping IDs)
        gap_report = db_data.get("gap_report")
        if gap_report:
            cursor.execute("""
                INSERT INTO gap_reports (sector, industry_demand, academic_landscape, gap_analysis, approved_by, approved_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                sector,
                gap_report["industry_demand"],
                gap_report["academic_landscape"],
                gap_report["gap_analysis"],
                gap_report.get("approved_by"),
                gap_report.get("approved_at")
            ))
            new_gap_id = cursor.lastrowid
            
            syllabus = db_data.get("syllabus")
            if syllabus:
                cursor.execute("""
                    INSERT INTO syllabi (gap_report_id, course_title, course_code, credits, hours_per_week, learning_objectives, bibliography, approved_by, approved_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    new_gap_id,
                    syllabus["course_title"],
                    syllabus["course_code"],
                    syllabus["credits"],
                    syllabus["hours_per_week"],
                    syllabus["learning_objectives"],
                    syllabus["bibliography"],
                    syllabus.get("approved_by"),
                    syllabus.get("approved_at")
                ))
                new_syllabus_id = cursor.lastrowid
                
                weekly_contents = db_data.get("weekly_contents") or []
                old_to_new_wc_id = {}
                for wc in weekly_contents:
                    cursor.execute("""
                        INSERT INTO weekly_contents (syllabus_id, week_number, title, activity_type, reading_material, assignment_prompt, points)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        new_syllabus_id,
                        wc["week_number"],
                        wc["title"],
                        wc["activity_type"],
                        wc.get("reading_material"),
                        wc.get("assignment_prompt"),
                        wc.get("points", 10)
                    ))
                    new_wc_id = cursor.lastrowid
                    old_to_new_wc_id[wc["id"]] = new_wc_id
                    
                submissions = db_data.get("submissions") or []
                for sub in submissions:
                    new_wc_id = old_to_new_wc_id.get(sub["weekly_content_id"])
                    if new_wc_id:
                        cursor.execute("""
                            INSERT INTO submissions (weekly_content_id, student_id, submitted_text, submitted_at, grade, feedback)
                            VALUES (?, ?, ?, ?, ?, ?)
                        """, (
                            new_wc_id,
                            sub["student_id"],
                            sub["submitted_text"],
                            sub["submitted_at"],
                            sub.get("grade"),
                            sub.get("feedback")
                        ))
        conn.commit()
        return sector
    except Exception as e:
        conn.rollback()
        logger.exception("Failed to restore DB records")
        raise e
    finally:
        conn.close()


@app.get("/api/saved-runs")
async def list_saved_runs_endpoint():
    """List all saved demo runs."""
    if not _SAVED_RUNS_DIR.exists():
        return {"runs": []}
    
    runs = []
    for p in sorted(_SAVED_RUNS_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            runs.append({
                "filename": p.name,
                "sector": data.get("sector"),
                "saved_at": data.get("saved_at"),
                "has_syllabus": data.get("database", {}).get("syllabus") is not None,
                "has_readings": len(data.get("database", {}).get("weekly_contents") or []) > 0
            })
        except Exception as e:
            logger.warning(f"Failed to read saved run {p}: {e}")
    return {"runs": runs}


@app.post("/api/saved-runs/save")
async def save_run_endpoint(payload: dict):
    """Save active run (cache and DB records) for a sector."""
    sector = payload.get("sector")
    custom_name = payload.get("name")
    if not sector:
        return JSONResponse({"error": "Missing sector"}, status_code=400)
        
    try:
        filename = _save_run_internal(sector, custom_name)
        return {"status": "success", "filename": filename, "sector": sector}
    except Exception as e:
        logger.exception("Failed to save run")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/saved-runs/load")
async def load_run_endpoint(payload: dict):
    """Load and restore a saved demo run."""
    filename = payload.get("filename")
    if not filename:
        return JSONResponse({"error": "Missing filename"}, status_code=400)
        
    try:
        sector = _load_run_internal(filename)
        return {"status": "success", "sector": sector}
    except Exception as e:
        logger.exception("Failed to load run")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/saved-runs/delete")
async def delete_run_endpoint(payload: dict):
    """Delete a saved run file."""
    filename = payload.get("filename")
    if not filename:
        return JSONResponse({"error": "Missing filename"}, status_code=400)
        
    p = _SAVED_RUNS_DIR / filename
    if not p.exists() or not p.resolve().is_relative_to(_SAVED_RUNS_DIR.resolve()):
        return JSONResponse({"error": "File not found"}, status_code=404)
        
    try:
        p.unlink()
        return {"status": "success"}
    except Exception as e:
        return JSONResponse({"error": f"Failed to delete file: {str(e)}"}, status_code=500)

@app.get("/api/video-status/{video_id}")
async def get_video_status(video_id: str, user: dict = Depends(get_current_user)):
    """Check HeyGen video status"""
    from src.multimedia import check_heygen_video_status
    status_data = await asyncio.to_thread(check_heygen_video_status, video_id)
    if status_data:
        return status_data
    return JSONResponse({"error": "Failed to check status"}, status_code=500)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.web.server:app", host="127.0.0.1", port=8765, reload=False)
