import json
import logging
from pathlib import Path
from datetime import datetime
from src.models.academic import AcademicLandscape, Curriculum, Course

logger = logging.getLogger(__name__)

FWD_JSON_PATH = Path(__file__).resolve().parent / "data" / "fwd_curriculum.json"

def get_fwd_raw_data() -> dict:
    """Load the raw JSON dictionary of FWD Costa Rica curriculum."""
    if not FWD_JSON_PATH.exists():
        logger.error(f"FWD curriculum JSON not found at {FWD_JSON_PATH}")
        return {}
    with open(FWD_JSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def get_fwd_academic_landscape() -> AcademicLandscape:
    """
    Constructs a validated AcademicLandscape model matching the official FWD Costa Rica curriculum.
    """
    data = get_fwd_raw_data()
    courses = []
    
    for axis in data.get("axes", []):
        axis_name = axis.get("name", "")
        for mod in axis.get("modules", []):
            course_obj = Course(
                code=f"FWD-M{mod.get('module_number', 1)}",
                name=f"{axis_name} - {mod.get('name', '')}",
                credits=3,
                skills_taught=mod.get("topics", []),
                description=", ".join(mod.get("topics", []))
            )
            courses.append(course_obj)

    curriculum = Curriculum(
        degree_name=data.get("program_title", "Artificial Intelligence Systems and Solutions Engineering"),
        degree_level="tecnico",
        university=data.get("institution", "FWD Costa Rica · Tech & Freedom"),
        is_public=False,
        url="https://fwdcostarica.com",
        courses=courses,
        last_updated="2026-08-18"
    )

    all_skills = data.get("all_skills_covered", [])
    
    return AcademicLandscape(
        curricula_sampled=[curriculum],
        all_skills_covered=all_skills,
        research_date=datetime.now().strftime("%Y-%m-%d"),
        summary=data.get("summary", "Programa oficial FWD Costa Rica de Front End e Inteligencia Artificial Aplicada.")
    )

def create_custom_academic_landscape(
    program_title: str,
    institution: str,
    skills: list[str],
    summary: str = ""
) -> AcademicLandscape:
    """
    Constructs an AcademicLandscape from user-uploaded curriculum text or PDF content.
    """
    course = Course(
        code="CUSTOM-01",
        name=program_title or "Programa de Estudio Personalizado",
        credits=4,
        skills_taught=skills,
        description=summary or f"Programa proporcionado por {institution}"
    )

    curriculum = Curriculum(
        degree_name=program_title or "Programa Personalizado",
        degree_level="tecnico",
        university=institution or "Institución / ONG Externa",
        is_public=False,
        courses=[course],
        last_updated=datetime.now().strftime("%Y-%m-%d")
    )

    return AcademicLandscape(
        curricula_sampled=[curriculum],
        all_skills_covered=skills,
        research_date=datetime.now().strftime("%Y-%m-%d"),
        summary=summary or f"Programa de estudio personalizado para {program_title} ({institution})."
    )
