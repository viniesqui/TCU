import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class CourseMaterialRAG:
    """
    RAG component for course creation grounded in professor reference materials / textbooks / syllabi notes.
    """
    _in_memory_store: Dict[str, str] = {}

    @classmethod
    def index_material(cls, course_key: str, material_text: str) -> None:
        """
        Indexes reference material for a course topic/key.
        """
        if not material_text:
            return
        cls._in_memory_store[course_key.lower().strip()] = material_text.strip()
        logger.info(f"Indexed reference material for course '{course_key}' ({len(material_text)} chars)")

    @classmethod
    def get_reference_context(cls, course_key: str, syllabus_id: Optional[int] = None, max_chars: int = 2500) -> str:
        """
        Retrieves grounded reference text for course generation from memory or SQLite.
        """
        text = cls._in_memory_store.get(course_key.lower().strip(), "")
        
        # If not in memory and syllabus_id is provided, query SQLite
        if not text and syllabus_id:
            try:
                from src.database import get_db_connection
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT reference_material FROM syllabi WHERE id = ?", (syllabus_id,))
                row = cursor.fetchone()
                conn.close()
                if row and row["reference_material"]:
                    text = row["reference_material"].strip()
                    cls._in_memory_store[course_key.lower().strip()] = text
            except Exception as e:
                logger.warning(f"Could not load reference material from DB: {e}")

        if not text:
            return ""
        
        if len(text) > max_chars:
            text = text[:max_chars] + "... [Material de referencia acotado]"
        
        return f"\n=== MATERIAL Y FUENTE DE REFERENCIA OFICIAL BASE ===\n{text}\n======================================================\n"
