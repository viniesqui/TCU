import logging
import json
from src.agents.base_agent import BaseAgent
from src.agents.rag_retriever import CurriculumRAG

logger = logging.getLogger(__name__)

EXAM_SYSTEM_PROMPT = """Eres un examinador universitario experto en Evaluación Dinámica y Testing Adaptativo Computarizado (CAT).
Tu objetivo es evaluar al estudiante mediante preguntas iterativas basadas ÚNICAMENTE en el material del currículum provisto (RAG).

FORMATO DE RESPUESTA OBLIGATORIO: JSON válido únicamente.

Si es la PRIMERA pregunta (sin historial previo de respuestas), devuelve:
{
  "feedback": "¡Bienvenido al Examen de Práctica! Empecemos con esta pregunta para evaluar lo aprendido esta semana.",
  "is_correct": true,
  "next_question": "PREGUNTA DE NIVEL MEDIO BASADA EN LA LECCIÓN",
  "is_finished": false,
  "final_grade": 0,
  "mastered_topics": [],
  "knowledge_gaps": []
}

Si el estudiante envía una respuesta, analiza su texto contra la lección y devuelve:
{
  "is_correct": true/false,
  "feedback": "Retroalimentación pedagógica detallada y PISTAS si falló.",
  "next_question": "Siguiente pregunta adaptativa (o null si finalizó el examen).",
  "is_finished": true/false (finaliza en la iteración 3 o al completar la evaluación),
  "final_grade": Número de 0 a 100 (si is_finished es true),
  "mastered_topics": ["Lista de conceptos o preguntas que el estudiante demostró dominar"],
  "knowledge_gaps": ["Lista de temas, errores o conceptos específicos donde tuvo fallas o dudas"]
}

REGLAS CRÍTICAS:
- Las preguntas deben basarse 100% en el texto de la lección provisto.
- En la iteración final (is_finished = true), asegúrate de listar en 'knowledge_gaps' los temas exactos que el estudiante falló o no explicó adecuadamente para que el Tutor en Vivo los repase con él.
- NO incluyas bloques de código Markdown alrededor del JSON.
"""

class ExamAgent(BaseAgent):
    def __init__(self, max_cost: float | None = None) -> None:
        super().__init__(
            max_cost=max_cost,
            name="ExamAgent",
            system_prompt=EXAM_SYSTEM_PROMPT,
            tools=[],
        )

    def evaluate_step(self, text_content: str, history: list, iteration: int, weekly_content_id: int | None = None):
        """
        history: list of dicts {"role": "student"/"examiner", "content": "..."}
        """
        logger.info(f"ExamAgent step iteration {iteration}")
        
        # Use RAG if weekly_content_id is provided
        if weekly_content_id:
            context_str = CurriculumRAG.format_prompt_context(weekly_content_id, max_chars=1200) + "\n\n"
        else:
            context_str = f"TEXTO DE LA LECCIÓN (Base RAG para evaluar):\n{text_content[:1200]}\n\n"
            
        context_str += f"ITERACIÓN ACTUAL: {iteration} de 3.\n\n"
        
        recent_history = history[-4:] if history else []

        if not recent_history:
            context_str += "No hay historial. Genera la PRIMERA pregunta base de nivel medio."
        else:
            context_str += "HISTORIAL RECIENTE DEL EXAMEN:\n"
            for msg in recent_history:
                context_str += f"[{msg['role'].upper()}]: {msg['content']}\n"
            context_str += "\nEvalúa la última respuesta del ESTUDIANTE. Genera la siguiente pregunta adaptativa (o finaliza con el diagnóstico de brechas si es la iteración 3)."
            
        try:
            response_json_str = self.run(context_str)
            clean_str = self.clean_json(response_json_str)
            data = json.loads(clean_str)
            
            # Ensure keys exist
            data.setdefault("mastered_topics", [])
            data.setdefault("knowledge_gaps", [])
            data.setdefault("final_grade", 0)
            data.setdefault("is_finished", False)
            
            return data
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse ExamAgent JSON response: {e}")
            return {
                "is_correct": False,
                "feedback": "Hubo un error evaluando tu respuesta. Por favor intenta responder nuevamente.",
                "next_question": None,
                "is_finished": False,
                "final_grade": 0,
                "mastered_topics": [],
                "knowledge_gaps": ["Error de procesamiento en la pregunta"]
            }
        except Exception as e:
            logger.error(f"ExamAgent encountered an error: {e}")
            raise
