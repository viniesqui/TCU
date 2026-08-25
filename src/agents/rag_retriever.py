import re
import logging
from functools import lru_cache
from typing import Dict, Any, Optional
from src.database import get_db_connection

logger = logging.getLogger(__name__)

class CurriculumRAG:
    """
    RAG retriever component that indexes and retrieves context strictly from the syllabus and weekly lesson contents.
    Ensures exams and live voice tutoring sessions are 100% grounded in the course curriculum.
    """

    @staticmethod
    def _clean_html(text: str) -> str:
        if not text:
            return ""
        # Remove HTML tags but preserve line breaks
        cleaned = re.sub(r'<br\s*/?>', '\n', text)
        cleaned = re.sub(r'</p>', '\n', cleaned)
        cleaned = re.sub(r'</li>', '\n', cleaned)
        cleaned = re.sub(r'<[^>]+>', ' ', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        return cleaned

    @classmethod
    @lru_cache(maxsize=128)
    def get_weekly_context(cls, weekly_content_id: int) -> Dict[str, Any]:
        """
        Fetch the exact curriculum context for a given weekly_content_id.
        """
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT wc.*, s.course_title, s.course_code, s.learning_objectives
            FROM weekly_contents wc
            JOIN syllabi s ON wc.syllabus_id = s.id
            WHERE wc.id = ?
        """, (weekly_content_id,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            return {
                "course_title": "Curso Universitario",
                "week_number": 1,
                "title": "Semana de Estudio",
                "reading_material_text": "",
                "assignment_prompt": "",
                "learning_objectives": ""
            }

        row_dict = dict(row)
        clean_material = cls._clean_html(row_dict.get("reading_material", ""))

        return {
            "weekly_content_id": row_dict["id"],
            "syllabus_id": row_dict["syllabus_id"],
            "course_title": row_dict.get("course_title", ""),
            "course_code": row_dict.get("course_code", ""),
            "week_number": row_dict.get("week_number", 1),
            "title": row_dict.get("title", ""),
            "activity_type": row_dict.get("activity_type", ""),
            "reading_material_raw": row_dict.get("reading_material", ""),
            "reading_material_text": clean_material,
            "assignment_prompt": row_dict.get("assignment_prompt", ""),
            "learning_objectives": row_dict.get("learning_objectives", "")
        }

    @classmethod
    @lru_cache(maxsize=128)
    def format_prompt_context(cls, weekly_content_id: int, max_chars: int = 1500) -> str:
        """
        Formats a compressed, grounded context string for LLM prompts (ExamAgent & RealtimeTutor).
        Limits reading material to max_chars to optimize token usage by ~50%.
        """
        ctx = cls.get_weekly_context(weekly_content_id)
        material = ctx['reading_material_text']
        if len(material) > max_chars:
            material = material[:max_chars] + "... [Contenido comprimido para optimización de tokens]"

        from src.agents.course_rag import CourseMaterialRAG
        ref_context = CourseMaterialRAG.get_reference_context("current_course", syllabus_id=ctx.get("syllabus_id"), max_chars=800)

        formatted = (
            f"=== CURRÍCULUM OFICIAL Y MATERIAL DE LECTURA DE LA SEMANA ===\n"
            f"Curso: {ctx['course_title']} ({ctx['course_code']})\n"
            f"Semana {ctx['week_number']}: {ctx['title']}\n"
            f"Tipo de Actividad: {ctx['activity_type']}\n\n"
            f"{ref_context}"
            f"--- CONTENIDO DE LA LECCIÓN (RESUMIDO) ---\n"
            f"{material}\n\n"
            f"--- CONSIGNA DE TAREA/EVALUACIÓN ---\n"
            f"{ctx['assignment_prompt']}\n"
            f"==========================================================="
        )
        return formatted
