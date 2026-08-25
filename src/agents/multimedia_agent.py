import logging
import json
from src.agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

MULTIMEDIA_SYSTEM_PROMPT = """Eres un experto en diseño de material didáctico multimodal.
Tu misión es tomar el texto base de una lección y generar un "Artefacto Multimedia" complementario, basándote en el formato solicitado.

FORMATO DE RESPUESTA:
Debes responder SIEMPRE con un objeto JSON válido con la siguiente estructura exacta:
{
  "media_type": "image" o "interactive",
  "media_content": "CONTENIDO AQUÍ",
  "media_description": "Breve descripción del recurso generado."
}

INSTRUCCIONES POR FORMATO:
- Si se te pide 'visual' (media_type: image): El `media_content` DEBE ser código fuente Mermaid.js puro (ej. graph TD\\n A-->B). Asegúrate de que el diagrama Mermaid resuma visualmente los conceptos más importantes del texto. NO uses bloques Markdown (```mermaid), SOLO EL CÓDIGO PURO.
- Si se te pide 'kinesthetic' (media_type: interactive): El `media_content` DEBE ser un string JSON (escapado como string) que contenga un arreglo de 3 preguntas de flashcards interactivas. Formato esperado dentro del string: [{"question": "...", "answer": "...", "explanation": "..."}]

NO respondas con texto fuera del JSON principal.
"""

class MultimediaAgent(BaseAgent):
    def __init__(self, max_cost: float | None = None) -> None:
        super().__init__(max_cost=max_cost,
            name="MultimediaAgent",
            system_prompt=MULTIMEDIA_SYSTEM_PROMPT,
            tools=[],
        )

    def generate_media(self, title: str, text_content: str, dominant_style: str, week_id: int):
        """
        Generate media structure via Anthropic based on dominant style.
        Returns a tuple: (media_content, media_type)
        """
        logger.info(f"MultimediaAgent generating {dominant_style} artifact for week {week_id}")
        
        if dominant_style == "visual":
            req = "Genera un DIAGRAMA MERMAID (media_type: image) que organice visualmente este contenido."
        elif dominant_style == "kinesthetic":
            req = "Genera 3 FLASHCARDS INTERACTIVAS (media_type: interactive) para practicar este contenido, serializadas como JSON string dentro del media_content."
        else:
            # Fallback for others to keep it visual
            req = "Genera un DIAGRAMA MERMAID (media_type: image) como mapa mental resumen de este contenido."

        user_message = f"""
Tema de la lección: {title}

Texto Base:
{text_content}

Solicitud de Adaptación: {req}
"""
        try:
            response_json_str = self.run(user_message)
            # Safe clean of markdown tags if the LLM leaked them
            if response_json_str.startswith("```json"):
                response_json_str = response_json_str.replace("```json", "").replace("```", "").strip()
                
            data = json.loads(response_json_str)
            content = data.get("media_content")
            
            # If mermaid code has markdown blocks, strip them
            if data.get("media_type") == "image" and content.startswith("```mermaid"):
                content = content.replace("```mermaid", "").replace("```", "").strip()
                
            return content, data.get("media_type")
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse MultimediaAgent JSON response: {e}")
            return None, None
        except Exception as e:
            logger.error(f"MultimediaAgent encountered an error: {e}")
            return None, None
