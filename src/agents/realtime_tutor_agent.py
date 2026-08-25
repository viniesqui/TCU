import logging
from typing import List, Dict, Any, Optional
from src.agents.base_agent import BaseAgent
from src.agents.rag_retriever import CurriculumRAG
from src.database import get_exam_diagnostic

logger = logging.getLogger(__name__)

TUTOR_BASE_SYSTEM_PROMPT = """Eres un Tutor Universitario Socrático e Interactivo altamente empático, paciente y experto.
Tu objetivo es dar una sesión de tutoría en tiempo real ("Duplex Live Session") para repasar la lección con el estudiante.

REGLAS DE ACTUACIÓN:
1. Basa tus conocimientos ÚNICAMENTE en el material del currículum provisto (RAG). Si el alumno pregunta algo fuera del curso, guíalo amablemente de vuelta a los temas de la lección.
2. Saluda al estudiante reconociendo sus fortalezas en el examen de práctica y haciendo énfasis directo en repasar los conceptos donde tuvo dudas o brechas (knowledge gaps).
3. Utiliza el método socrático: no le des las respuestas directamente; hazle preguntas cortas, analogías sencillas y guía su razonamiento paso a paso.
4. Mantén las respuestas EXTREMADAMENTE CONCISAS (máximo 1 a 2 oraciones cortas). Esto es vital para latencia ultrarrápida de audio y una conversación fluida en tiempo real. NO uses listas ni viñetas.
5. EVALUACIÓN DE DOMINIO: Si en esta respuesta el estudiante demuestra haber comprendido correctamente uno de los temas/brechas pendientes, añade al final de tu mensaje la etiqueta exacta: [RESUELTO: Nombre de la Brecha].
"""

class RealtimeTutorAgent(BaseAgent):
    """
    Agent for live duplex teaching sessions, grounded in RAG curriculum & student exam diagnostic.
    """
    def __init__(self, max_cost: float | None = None) -> None:
        super().__init__(
            max_cost=max_cost,
            name="RealtimeTutorAgent",
            system_prompt=TUTOR_BASE_SYSTEM_PROMPT,
            tools=[],
        )

    @classmethod
    def get_tutor_context(cls, weekly_content_id: int, student_id: str) -> Dict[str, Any]:
        """
        Builds complete context: Curriculum RAG + Exam Diagnostics.
        """
        curriculum_ctx = CurriculumRAG.get_weekly_context(weekly_content_id)
        diagnostic = get_exam_diagnostic(student_id, weekly_content_id)
        
        mastered = diagnostic.get("mastered_topics", []) if diagnostic else []
        gaps = diagnostic.get("knowledge_gaps", []) if diagnostic else []
        score = diagnostic.get("score", None) if diagnostic else None

        return {
            "curriculum": curriculum_ctx,
            "diagnostic": {
                "has_taken_exam": diagnostic is not None,
                "score": score,
                "mastered_topics": mastered,
                "knowledge_gaps": gaps
            }
        }

    def build_initial_greeting(self, weekly_content_id: int, student_id: str) -> str:
        ctx = self.get_tutor_context(weekly_content_id, student_id)
        curr = ctx["curriculum"]
        diag = ctx["diagnostic"]

        prompt = (
            f"{CurriculumRAG.format_prompt_context(weekly_content_id)}\n\n"
            f"DIAGNÓSTICO DEL EXAMEN DEL ESTUDIANTE ({student_id}):\n"
            f"- Ha realizado el examen: {'Sí' if diag['has_taken_exam'] else 'No'}\n"
            f"- Calificación obtenida: {diag['score'] if diag['score'] is not None else 'N/A'} / 100\n"
            f"- Temas Dominados: {', '.join(diag['mastered_topics']) if diag['mastered_topics'] else 'Ninguno registrado'}\n"
            f"- Brechas/Dudas Detectadas: {', '.join(diag['knowledge_gaps']) if diag['knowledge_gaps'] else 'Revisión general de la semana'}\n\n"
            f"INSTRUCCIÓN: Genera el saludo inicial en primera persona (como profesor tutor en voz alta). "
            f"Menciona que viste sus resultados del examen y proponle repasar específicamente las brechas detectadas. Haz una pregunta inicial para empezar."
        )

        greeting = self.run(prompt)
        import re
        return re.sub(r'\[RESUELTO:.*?\]', '', greeting).strip()

    def chat_step(self, weekly_content_id: int, student_id: str, user_message: str, history: List[Dict[str, str]]) -> Dict[str, Any]:
        import re
        ctx = self.get_tutor_context(weekly_content_id, student_id)
        diag = ctx["diagnostic"]

        recent_history = history[-4:] if history else []

        prompt = (
            f"{CurriculumRAG.format_prompt_context(weekly_content_id, max_chars=1200)}\n\n"
            f"BRECHAS A REPASAR DEL ALUMNO: {', '.join(diag['knowledge_gaps']) if diag['knowledge_gaps'] else 'General'}\n\n"
            f"HISTORIAL RECIENTE DE LA TUTORÍA:\n"
        )
        for h in recent_history:
            role = "TUTOR" if h["role"] == "assistant" or h["role"] == "tutor" else "ESTUDIANTE"
            prompt += f"[{role}]: {h['content']}\n"

        prompt += f"\n[ESTUDIANTE]: {user_message}\n\n[TUTOR]: Responde socráticamente en 1-2 oraciones conversacionales. Si el estudiante respondió bien sobre una brecha, incluye [RESUELTO: Nombre de la brecha] al final."
        
        raw_response = self.run(prompt)
        
        # Parse [RESUELTO: ...] tags
        resolved_gaps = re.findall(r'\[RESUELTO:\s*(.*?)\]', raw_response, re.IGNORECASE)
        clean_response = re.sub(r'\[RESUELTO:.*?\]', '', raw_response).strip()

        return {
            "response_text": clean_response,
            "resolved_gaps": resolved_gaps
        }
