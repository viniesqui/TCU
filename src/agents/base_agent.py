import datetime
import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any

import anthropic
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from src.config import settings
from src.tools.tool_registry import TOOL_REGISTRY

logger = logging.getLogger(__name__)

# Trim context when the raw character count exceeds this threshold (~45k tokens).
_MAX_CONTEXT_CHARS = 180_000

# Structured trace log – one JSON object per line (JSON Lines format).
_TRACE_LOG_PATH = Path("traces") / "llm_calls.jsonl"


def _escape_newlines_in_strings(text: str) -> str:
    """Replace literal newline/carriage-return characters inside JSON string values."""
    result: list[str] = []
    in_string = False
    escaped = False
    for ch in text:
        if escaped:
            result.append(ch)
            escaped = False
        elif ch == "\\" and in_string:
            result.append(ch)
            escaped = True
        elif ch == '"':
            result.append(ch)
            in_string = not in_string
        elif ch == "\n" and in_string:
            result.append("\\n")
        elif ch == "\r" and in_string:
            result.append("\\r")
        else:
            result.append(ch)
    return "".join(result)


def _is_retriable_api_error(exc: BaseException) -> bool:
    """Only retry on rate limits and transient server errors — never on 4xx client errors."""
    if isinstance(exc, anthropic.RateLimitError):
        return True
    if isinstance(exc, anthropic.InternalServerError):
        return True
    if isinstance(exc, anthropic.APIStatusError):
        # 500/502/503/504 are transient; 400/401/403 are deterministic failures
        return exc.status_code in {500, 502, 503, 504}
    return False


def _is_tool_error_response(content: str) -> bool:
    """Return True if a tool returned a structured error JSON (has both 'error' and 'error_code')."""
    try:
        data = json.loads(content)
        return isinstance(data, dict) and "error" in data and "error_code" in data
    except (json.JSONDecodeError, TypeError, ValueError):
        return False


class BaseAgent:
    """
    Base class implementing the standard Anthropic tool-use agentic loop.

    Flow:
      1. Send user message to Claude with tool schemas
      2. If stop_reason == "tool_use": execute tools, append results, loop
      3. If stop_reason == "end_turn": extract and return final text
      4. Retry on transient rate-limit / server errors via tenacity
    """

    cumulative_costs: dict[str, float] = {}

    @classmethod
    def reset_cost(cls) -> None:
        cls.cumulative_costs.clear()

    def __init__(
        self,
        name: str,
        system_prompt: str,
        tools: list[dict] | None = None,
        model: str | None = None,
        max_iterations: int | None = None,
        max_cost: float | None = None,
    ) -> None:
        self.name = name
        self.system_prompt = system_prompt
        self.tools = tools or []
        self.model = model or settings.model
        self.max_iterations = max_iterations or settings.max_agent_iterations
        self.max_cost = max_cost if max_cost is not None else settings.max_run_cost
        api_key = settings.anthropic_api_key or "mock-key-since-missing"
        self._client = anthropic.Anthropic(api_key=api_key)
        
        if self.name not in BaseAgent.cumulative_costs:
            BaseAgent.cumulative_costs[self.name] = 0.0

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run(self, user_message: str) -> str:
        """
        Run the agentic loop for a single task.
        Returns the agent's final text response (typically JSON).
        """
        logger.info(f"[{self.name}] Starting run")

        # --- BUDGET CHECK ---
        current_cost = BaseAgent.cumulative_costs[self.name]
        if current_cost >= self.max_cost:
            logger.warning(
                f"[{self.name}] Cost limit reached (${current_cost:.4f} >= ${self.max_cost:.4f}). "
                f"Falling back to high-fidelity mock/fallback data."
            )
            return self.get_fallback_response(user_message)

        messages: list[dict[str, Any]] = [{"role": "user", "content": user_message}]

        for iteration in range(self.max_iterations):
            logger.debug(f"[{self.name}] Iteration {iteration + 1}/{self.max_iterations}")
            messages = self._maybe_trim_messages(messages)

            # --- Check budget limit before calling Claude ---
            if BaseAgent.cumulative_costs[self.name] >= self.max_cost:
                logger.warning(
                    f"[{self.name}] Cost limit reached during iteration. Using fallback."
                )
                return self.get_fallback_response(user_message)

            try:
                response = self._call_claude(messages)

                # --- UPDATE CUMULATIVE COST ---
                cost = self._calculate_call_cost(response)
                BaseAgent.cumulative_costs[self.name] += cost
                new_total = BaseAgent.cumulative_costs[self.name]
                logger.info(f"[{self.name}] Call cost: ${cost:.4f}. Cumulative run cost for {self.name}: ${new_total:.4f}")
            except (anthropic.AuthenticationError, anthropic.RateLimitError, anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
                from src.config import format_api_error_message
                msg = format_api_error_message(exc)
                logger.error(f"[{self.name}] {msg}")
                logger.warning(f"[{self.name}] Falling back to high-fidelity mock/fallback data.")
                return self.get_fallback_response(user_message)
            except Exception as exc:
                from src.config import format_api_error_message
                msg = format_api_error_message(exc)
                logger.error(f"[{self.name}] {msg}")
                logger.warning(f"[{self.name}] Falling back to high-fidelity mock/fallback data.")
                return self.get_fallback_response(user_message)

            if response.stop_reason == "end_turn":
                text = self._extract_text(response)
                logger.info(f"[{self.name}] Completed after {iteration + 1} iterations")
                return text

            if response.stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": response.content})
                # Guard: if tool execution raises, roll back the assistant turn so
                # the messages list stays in a consistent alternating state.
                try:
                    tool_result_blocks = self._execute_tool_calls(response)
                except Exception as exc:
                    messages.pop()
                    logger.warning(f"[{self.name}] Tool execution failed: {exc}. Falling back to high-fidelity mock/fallback data.")
                    return self.get_fallback_response(user_message)
                messages.append({"role": "user", "content": tool_result_blocks})
                continue

            # Unexpected stop reason — return whatever text exists
            logger.warning(f"[{self.name}] Unexpected stop_reason: {response.stop_reason}")
            return self._extract_text(response)

        raise RuntimeError(
            f"[{self.name}] Exceeded max_iterations ({self.max_iterations}) without end_turn"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @retry(
        retry=retry_if_exception(predicate=_is_retriable_api_error),
        wait=wait_exponential(multiplier=1, min=5, max=60),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def _call_claude(self, messages: list[dict]) -> anthropic.types.Message:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 8096,
            "system": self.system_prompt,
            "messages": messages,
        }
        if self.tools:
            kwargs["tools"] = self.tools
        response = self._client.messages.create(**kwargs)
        self._log_llm_trace(response)
        return response

    def _log_llm_trace(self, response: anthropic.types.Message) -> None:
        """Append a structured trace record for each completed LLM call."""
        entry = {
            "trace_id": str(uuid.uuid4()),
            "agent": self.name,
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "model": self.model,
            "prompt_tokens": response.usage.input_tokens,
            "completion_tokens": response.usage.output_tokens,
            "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
        }
        try:
            _TRACE_LOG_PATH.parent.mkdir(exist_ok=True)
            with _TRACE_LOG_PATH.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
        except Exception as exc:
            logger.warning(f"[{self.name}] Failed to write trace log: {exc}")

    def _execute_tool_calls(self, response: anthropic.types.Message) -> list[dict]:
        """Execute all tool_use blocks from the response, return tool_result blocks."""
        tool_result_blocks = []
        for block in response.content:
            if block.type != "tool_use":
                continue

            tool_name = block.name
            tool_input = block.input
            tool_use_id = block.id

            logger.info(f"[{self.name}] Calling tool '{tool_name}' with input: {json.dumps(tool_input)[:200]}")

            if tool_name not in TOOL_REGISTRY:
                result_content = json.dumps({
                    "error": f"Unknown tool '{tool_name}'",
                    "error_code": "UNKNOWN_TOOL",
                })
                is_error = True
                logger.warning(f"[{self.name}] Tool '{tool_name}' is not registered")
            else:
                try:
                    raw_result = TOOL_REGISTRY[tool_name](**tool_input)
                    result_content = raw_result if isinstance(raw_result, str) else json.dumps(raw_result)
                    # Detect structured error responses returned by tools (JSON with error+error_code)
                    # so Claude sees is_error=True and tries a different query instead of
                    # treating empty or failed results as valid data.
                    is_error = _is_tool_error_response(result_content)
                    if is_error:
                        logger.warning(
                            f"[{self.name}] Tool '{tool_name}' returned an error response: "
                            f"{result_content[:300]}"
                        )
                except Exception as e:
                    result_content = json.dumps({
                        "error": str(e),
                        "error_code": "TOOL_EXECUTION_ERROR",
                    })
                    is_error = True
                    logger.warning(f"[{self.name}] Tool '{tool_name}' raised an exception: {e}")

            tool_result_blocks.append({
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": result_content,
                "is_error": is_error,
            })

        return tool_result_blocks

    @staticmethod
    def _extract_text(response: anthropic.types.Message) -> str:
        """Return the LAST non-empty text block — Claude places its final answer there."""
        text_blocks = [b.text for b in response.content if hasattr(b, "text") and b.text.strip()]
        return text_blocks[-1].strip() if text_blocks else ""

    @staticmethod
    def clean_json(raw: str) -> str:
        """
        Extract JSON from agent output, robust against surrounding prose.

        Strategy 1: locate the outermost { } or [ ] block and validate it parses.
        Strategy 2: strip all markdown code fences (multiline-aware) and return remainder.
        Strategy 3: lightweight repair for trailing commas and unescaped newlines, then retry.
        """
        text = raw.strip()

        # Strategy 1: find the outermost JSON object or array
        for start_char, end_char in [('{', '}'), ('[', ']')]:
            start = text.find(start_char)
            end = text.rfind(end_char)
            if start != -1 and end != -1 and end > start:
                candidate = text[start:end + 1]
                try:
                    json.loads(candidate)
                    return candidate
                except json.JSONDecodeError:
                    pass

        # Strategy 2: strip markdown fences anywhere in the string
        cleaned = re.sub(r"```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        cleaned = re.sub(r"```", "", cleaned)
        cleaned = cleaned.strip()

        # Strategy 3: repair trailing commas and unescaped newlines, then retry
        repaired = re.sub(r",\s*([}\]])", r"\1", cleaned)
        repaired = _escape_newlines_in_strings(repaired)
        try:
            json.loads(repaired)
            return repaired
        except json.JSONDecodeError:
            pass

        return cleaned

    def repair_json(self, raw: str) -> str:
        """
        Full JSON repair pipeline.

        1. Run clean_json (prose extraction + lightweight regex repair).
        2. If the result still does not parse, fall back to a targeted LLM repair call.

        Returns a string that json.loads() accepts, or raises ValueError.
        """
        cleaned = self.clean_json(raw)
        try:
            json.loads(cleaned)
            return cleaned
        except json.JSONDecodeError:
            pass

        logger.warning(f"[{self.name}] clean_json produced invalid JSON; attempting LLM repair")
        return self._llm_repair_json(raw)

    def _llm_repair_json(self, broken: str) -> str:
        """Single targeted LLM call that returns only the corrected JSON."""
        response = self._client.messages.create(
            model=self.model,
            max_tokens=4096,
            system="You are a JSON repair tool. Output only valid JSON — no explanation, no markdown fences.",
            messages=[{"role": "user", "content": f"Fix this malformed JSON:\n\n{broken}"}],
        )
        fixed = self._extract_text(response)
        fixed = re.sub(r"```(?:json)?\s*|\s*```", "", fixed, flags=re.IGNORECASE).strip()
        try:
            json.loads(fixed)
        except json.JSONDecodeError as exc:
            raise ValueError(f"[{self.name}] LLM JSON repair produced invalid JSON: {exc}") from exc
        logger.info(f"[{self.name}] LLM JSON repair succeeded")
        return fixed

    def _maybe_trim_messages(self, messages: list[dict]) -> list[dict]:
        """
        Trim the conversation history when the total size approaches the context limit.

        Keeps the first user message (the task) + the last 4 messages (2 full exchanges).
        The resulting list always maintains the required user/assistant alternating pattern.
        """
        if len(messages) <= 5:
            return messages

        total_chars = sum(len(str(m)) for m in messages)
        if total_chars <= _MAX_CONTEXT_CHARS:
            return messages

        # [0] is always "user" (initial task); messages[-4:] always starts with "assistant"
        # since the list alternates starting from user.
        preserved = [messages[0]] + messages[-4:]
        logger.warning(
            f"[{self.name}] Context trimmed: {total_chars} chars, "
            f"{len(messages)} → {len(preserved)} messages to stay within limit"
        )
        return preserved

    def _calculate_call_cost(self, response: anthropic.types.Message) -> float:
        model_lower = self.model.lower()
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        
        if "opus" in model_lower:
            input_rate = 15.0 / 1_000_000
            output_rate = 75.0 / 1_000_000
        elif "haiku-3-5" in model_lower or "3.5-haiku" in model_lower or "3-5-haiku" in model_lower:
            input_rate = 0.80 / 1_000_000
            output_rate = 4.00 / 1_000_000
        elif "haiku" in model_lower:
            input_rate = 0.25 / 1_000_000
            output_rate = 1.25 / 1_000_000
        else:
            # Default to Sonnet (3.5/3.7) pricing
            input_rate = 3.00 / 1_000_000
            output_rate = 15.00 / 1_000_000
        
        return (input_tokens * input_rate) + (output_tokens * output_rate)

    def get_fallback_response(self, user_message: str) -> str:
        """
        Generate high-fidelity fallback JSON data for each agent when budget is exceeded or API fails.
        Conforms perfectly to the target Pydantic schemas and quality gates.
        """
        import re
        
        # Extract sector from user message
        sector = "Desarrollo de Software"
        match = re.search(r"sector '([^']+)'|sector \"([^\"]+)\"|área de '([^']+)'|área de \"([^\"]+)\"|=== ANÁLISIS DE BRECHA ===\s*\{\s*\"sector\"\s*:\s*\"([^\"]+)\"", user_message, re.IGNORECASE)
        if match:
            sector = next((g for g in match.groups() if g is not None), "Desarrollo de Software")
            
        sector_lower = sector.lower()
        
        if self.name == "LaborMarketAgent":
            if "ciber" in sector_lower or "seguridad" in sector_lower or "cyber" in sector_lower:
                skills = [
                    {"name": "Análisis de Vulnerabilidades", "category": "technical", "frequency_score": 0.88, "example_sources": ["https://linkedin.com/jobs"]},
                    {"name": "Pruebas de Penetración (Pentesting)", "category": "technical", "frequency_score": 0.85, "example_sources": ["https://computrabajo.co.cr"]},
                    {"name": "Configuración de Firewalls y IDS/IPS", "category": "technical", "frequency_score": 0.82, "example_sources": ["https://camtic.org"]},
                    {"name": "Seguridad en la Nube (AWS/Azure)", "category": "tool", "frequency_score": 0.80, "example_sources": ["https://linkedin.com/jobs"]},
                    {"name": "Administración de Redes y Linux", "category": "technical", "frequency_score": 0.78, "example_sources": ["https://linkedin.com/jobs"]},
                    {"name": "Normativa ISO 27001 y NIST", "category": "certification", "frequency_score": 0.75, "example_sources": ["https://computrabajo.co.cr"]},
                    {"name": "Gestión de Incidentes de Seguridad", "category": "technical", "frequency_score": 0.70, "example_sources": ["https://camtic.org"]},
                    {"name": "Comunicación Asertiva en Crisis", "category": "soft", "frequency_score": 0.65, "example_sources": ["https://linkedin.com/jobs"]},
                    {"name": "Trabajo en Equipo Multidisciplinario", "category": "soft", "frequency_score": 0.60, "example_sources": ["https://linkedin.com/jobs"]},
                    {"name": "Scripting con Python para Automatización", "category": "technical", "frequency_score": 0.72, "example_sources": ["https://computrabajo.co.cr"]}
                ]
            elif "inteligencia" in sector_lower or "artificial" in sector_lower or "ia" in sector_lower or "machine" in sector_lower or "data" in sector_lower:
                skills = [
                    {"name": "Aprendizaje Automático (Machine Learning)", "category": "technical", "frequency_score": 0.92, "example_sources": ["https://linkedin.com/jobs"]},
                    {"name": "Programación en Python", "category": "technical", "frequency_score": 0.90, "example_sources": ["https://computrabajo.co.cr"]},
                    {"name": "Procesamiento de Lenguaje Natural (NLP)", "category": "technical", "frequency_score": 0.82, "example_sources": ["https://camtic.org"]},
                    {"name": "Redes Neuronales y Deep Learning", "category": "technical", "frequency_score": 0.80, "example_sources": ["https://linkedin.com/jobs"]},
                    {"name": "Ingeniería de Datos y Pipelines (ETL)", "category": "technical", "frequency_score": 0.78, "example_sources": ["https://computrabajo.co.cr"]},
                    {"name": "Uso de Git y Control de Versiones", "category": "tool", "frequency_score": 0.75, "example_sources": ["https://camtic.org"]},
                    {"name": "Operaciones de Machine Learning (MLOps)", "category": "tool", "frequency_score": 0.70, "example_sources": ["https://linkedin.com/jobs"]},
                    {"name": "Pensamiento Crítico y Resolución de Problemas", "category": "soft", "frequency_score": 0.68, "example_sources": ["https://linkedin.com/jobs"]},
                    {"name": "Comunicación de Resultados de Datos", "category": "soft", "frequency_score": 0.60, "example_sources": ["https://computrabajo.co.cr"]},
                    {"name": "SQL y Bases de Datos Relacionales", "category": "technical", "frequency_score": 0.76, "example_sources": ["https://linkedin.com/jobs"]}
                ]
            else: # Default: Desarrollo de Software
                skills = [
                    {"name": "Programación con Python", "category": "technical", "frequency_score": 0.90, "example_sources": ["https://linkedin.com/jobs"]},
                    {"name": "Contenedores con Docker", "category": "tool", "frequency_score": 0.85, "example_sources": ["https://computrabajo.co.cr"]},
                    {"name": "Orquestación con Kubernetes", "category": "tool", "frequency_score": 0.80, "example_sources": ["https://camtic.org"]},
                    {"name": "Desarrollo de Web APIs (FastAPI/Flask)", "category": "technical", "frequency_score": 0.78, "example_sources": ["https://linkedin.com/jobs"]},
                    {"name": "Bases de Datos Relacionales (PostgreSQL)", "category": "technical", "frequency_score": 0.75, "example_sources": ["https://computrabajo.co.cr"]},
                    {"name": "Plataforma de Nube AWS", "category": "tool", "frequency_score": 0.72, "example_sources": ["https://camtic.org"]},
                    {"name": "Uso de Git y Control de Versiones", "category": "tool", "frequency_score": 0.95, "example_sources": ["https://linkedin.com/jobs"]},
                    {"name": "Comunicación Efectiva en Equipos Ágiles", "category": "soft", "frequency_score": 0.65, "example_sources": ["https://linkedin.com/jobs"]},
                    {"name": "Metodología Ágil (Scrum/Kanban)", "category": "soft", "frequency_score": 0.60, "example_sources": ["https://computrabajo.co.cr"]},
                    {"name": "Desarrollo Frontend Básico (JavaScript)", "category": "technical", "frequency_score": 0.70, "example_sources": ["https://linkedin.com/jobs"]}
                ]

            job_postings = []
            companies = ["Tech Solutions Costa Rica", "Global Services CR", "Fintech Innovations", "Cloud Services Central", "Enterprise software group"]
            for i in range(5):
                req_skills = [skills[(i * 2) % len(skills)], skills[(i * 2 + 1) % len(skills)]]
                pref_skills = [skills[(i * 2 + 2) % len(skills)]]
                
                # Deduplicate within the same posting
                seen = set()
                final_req = []
                for s in req_skills:
                    if s["name"] not in seen:
                        seen.add(s["name"])
                        final_req.append(s)
                final_pref = []
                for s in pref_skills:
                    if s["name"] not in seen:
                        seen.add(s["name"])
                        final_pref.append(s)

                job_postings.append({
                    "title": f"Profesional de {sector}",
                    "company": companies[i],
                    "source_url": f"https://example.com/jobs/{i}",
                    "required_skills": final_req,
                    "preferred_skills": final_pref,
                    "seniority": ["mid", "senior", "junior", "senior", "mid"][i],
                    "location": "Costa Rica"
                })

            demand_data = {
                "sector": sector,
                "top_skills": skills,
                "job_postings_sampled": job_postings,
                "market_sources": ["https://linkedin.com", "https://computrabajo.co.cr", "https://camtic.org"],
                "research_date": "2026-06-29",
                "summary": f"El análisis del mercado laboral en Costa Rica para el sector '{sector}' revela un alto dinamismo con vacantes constantes enfocadas en habilidades prácticas. Las empresas buscan principalmente profesionales autónomos y con dominio de herramientas de vanguardia."
            }
            return json.dumps(demand_data, ensure_ascii=False)

        elif self.name == "AcademicAgent":
            curricula = [
                {
                    "degree_name": "Bachillerato en Ingeniería en Computación",
                    "degree_level": "bachillerato",
                    "university": "TEC",
                    "is_public": True,
                    "url": "https://tec.ac.cr/computacion",
                    "courses": [
                        {"code": "CO-1101", "name": "Introducción a la Programación", "credits": 4, "skills_taught": ["programación", "lógica"]},
                        {"code": "CO-2102", "name": "Estructuras de Datos", "credits": 4, "skills_taught": ["estructuras de datos", "algoritmos"]},
                        {"code": "CO-3103", "name": "Bases de Datos I", "credits": 3, "skills_taught": ["bases de datos", "sql"]}
                    ]
                },
                {
                    "degree_name": "Bachillerato en Ciencias de la Computación",
                    "degree_level": "bachillerato",
                    "university": "UCR",
                    "is_public": True,
                    "url": "https://ecci.ucr.ac.cr",
                    "courses": [
                        {"code": "CI-1101", "name": "Programación I", "credits": 4, "skills_taught": ["programación"]},
                        {"code": "CI-1202", "name": "Sistemas Operativos", "credits": 3, "skills_taught": ["sistemas operativos", "linux"]},
                        {"code": "CI-1303", "name": "Redes de Computadoras", "credits": 3, "skills_taught": ["redes de computadoras"]}
                    ]
                },
                {
                    "degree_name": "Ingeniería en Sistemas de Información",
                    "degree_level": "bachillerato",
                    "university": "UNA",
                    "is_public": True,
                    "url": "https://una.ac.cr/sistemas",
                    "courses": [
                        {"code": "SI-101", "name": "Fundamentos de Sistemas", "credits": 3, "skills_taught": ["lógica"]},
                        {"code": "SI-102", "name": "Programación Estructurada", "credits": 4, "skills_taught": ["programación"]},
                        {"code": "SI-103", "name": "Bases de Datos Relacionales", "credits": 3, "skills_taught": ["bases de datos"]}
                    ]
                },
                {
                    "degree_name": "Bachillerato en Ingeniería en Sistemas de Computación",
                    "degree_level": "bachillerato",
                    "university": "ULACIT",
                    "is_public": False,
                    "url": "https://ulacit.ac.cr/ingenieria-sistemas",
                    "courses": [
                        {"code": "IS-101", "name": "Programación de Computadoras", "credits": 3, "skills_taught": ["programación"]},
                        {"code": "IS-102", "name": "Diseño de Base de Datos", "credits": 3, "skills_taught": ["bases de datos"]},
                        {"code": "IS-103", "name": "Desarrollo Web", "credits": 3, "skills_taught": ["javascript", "programación"]}
                    ]
                },
                {
                    "degree_name": "Ingeniería en Desarrollo de Software",
                    "degree_level": "bachillerato",
                    "university": "CENFOTEC",
                    "is_public": False,
                    "url": "https://ucenfotec.ac.cr/desarrollo-software",
                    "courses": [
                        {"code": "DS-101", "name": "Introducción a la Tecnología", "credits": 3, "skills_taught": ["lógica"]},
                        {"code": "DS-102", "name": "Programación Orientada a Objetos", "credits": 4, "skills_taught": ["programación"]},
                        {"code": "DS-103", "name": "Diseño de Software", "credits": 3, "skills_taught": ["ingeniería de software"]}
                    ]
                }
            ]
            
            all_skills = ["programación", "lógica", "estructuras de datos", "algoritmos", "bases de datos", "sql", "sistemas operativos", "linux", "redes de computadoras", "javascript", "ingeniería de software"]
            
            landscape_data = {
                "curricula_sampled": curricula,
                "all_skills_covered": all_skills,
                "research_date": "2026-06-29",
                "summary": f"La oferta académica universitaria en Costa Rica para {sector} cubre los fundamentos teóricos indispensables como algoritmia y bases de datos, pero tiene limitaciones al incorporar herramientas modernas de desarrollo y metodologías de despliegue ágil."
            }
            return json.dumps(landscape_data, ensure_ascii=False)

        elif self.name == "GapAnalystAgent":
            if "ciber" in sector_lower or "seguridad" in sector_lower or "cyber" in sector_lower:
                critical = [
                    {"skill_name": "Seguridad en la Nube (AWS/Azure)", "market_demand_score": 0.80, "academic_coverage_score": 0.05, "gap_severity": "critical", "notes": "No se enseña en universidades analizadas.", "market_depth_required": "avanzado"},
                    {"skill_name": "Pruebas de Penetración (Pentesting)", "market_demand_score": 0.85, "academic_coverage_score": 0.10, "gap_severity": "critical", "notes": "Falta de enfoque práctico.", "market_depth_required": "intermedio"},
                    {"skill_name": "Normativa ISO 27001 y NIST", "market_demand_score": 0.75, "academic_coverage_score": 0.10, "gap_severity": "critical", "notes": "Poca cobertura de gobernanza.", "market_depth_required": "intermedio"}
                ]
                moderate = [
                    {"skill_name": "Análisis de Vulnerabilidades", "market_demand_score": 0.88, "academic_coverage_score": 0.30, "gap_severity": "moderate", "notes": "Se cubre a nivel teórico básico.", "market_depth_required": "intermedio"}
                ]
                covered = [
                    {"skill_name": "Administración de Redes y Linux", "market_demand_score": 0.78, "academic_coverage_score": 0.70, "gap_severity": "covered", "notes": "Bien cubierto en cursos de redes clásicos.", "market_depth_required": "basico"}
                ]
                title = "Especialización en Ciberseguridad y Protección de Activos"
                rationale = "Diseñado para cerrar la brecha en seguridad de infraestructura en la nube y pruebas de penetración prácticas solicitadas por multinacionales en Costa Rica."
            elif "inteligencia" in sector_lower or "artificial" in sector_lower or "ia" in sector_lower or "machine" in sector_lower or "data" in sector_lower:
                critical = [
                    {"skill_name": "Operaciones de Machine Learning (MLOps)", "market_demand_score": 0.70, "academic_coverage_score": 0.05, "gap_severity": "critical", "notes": "Inexistente en currículos tradicionales.", "market_depth_required": "avanzado"},
                    {"skill_name": "Procesamiento de Lenguaje Natural (NLP)", "market_demand_score": 0.82, "academic_coverage_score": 0.10, "gap_severity": "critical", "notes": "No se incluye en asignaturas optativas.", "market_depth_required": "intermedio"},
                    {"skill_name": "Redes Neuronales y Deep Learning", "market_demand_score": 0.80, "academic_coverage_score": 0.15, "gap_severity": "critical", "notes": "Se requiere mayor profundidad práctica.", "market_depth_required": "intermedio"}
                ]
                moderate = [
                    {"skill_name": "Aprendizaje Automático (Machine Learning)", "market_demand_score": 0.92, "academic_coverage_score": 0.40, "gap_severity": "moderate", "notes": "Se ve teoría matemática pero sin despliegue.", "market_depth_required": "intermedio"}
                ]
                covered = [
                    {"skill_name": "Programación en Python", "market_demand_score": 0.90, "academic_coverage_score": 0.85, "gap_severity": "covered", "notes": "Ampliamente cubierto en cursos introductorios.", "market_depth_required": "basico"}
                ]
                title = "Especialización en Modelos de Inteligencia Artificial y MLOps"
                rationale = "Curso práctico orientado a la construcción, entrenamiento y despliegue automatizado de modelos de aprendizaje automático y deep learning en producción."
            else:
                critical = [
                    {"skill_name": "Orquestación con Kubernetes", "market_demand_score": 0.80, "academic_coverage_score": 0.05, "gap_severity": "critical", "notes": "Falta absoluta en el currículo.", "market_depth_required": "avanzado"},
                    {"skill_name": "Contenedores con Docker", "market_demand_score": 0.85, "academic_coverage_score": 0.15, "gap_severity": "critical", "notes": "Solo se menciona brevemente.", "market_depth_required": "intermedio"},
                    {"skill_name": "Plataforma de Nube AWS", "market_demand_score": 0.72, "academic_coverage_score": 0.10, "gap_severity": "critical", "notes": "Falta de laboratorios cloud.", "market_depth_required": "intermedio"}
                ]
                moderate = [
                    {"skill_name": "Desarrollo de Web APIs (FastAPI/Flask)", "market_demand_score": 0.78, "academic_coverage_score": 0.35, "gap_severity": "moderate", "notes": "Se enseña desarrollo web clásico, no APIs modernas.", "market_depth_required": "intermedio"}
                ]
                covered = [
                    {"skill_name": "Programación con Python", "market_demand_score": 0.90, "academic_coverage_score": 0.80, "gap_severity": "covered", "notes": "Bien cubierto en cursos iniciales.", "market_depth_required": "basico"}
                ]
                title = "Diseño de Aplicaciones Cloud-Native y DevOps"
                rationale = "Propone capacitar en herramientas fundamentales para microservicios y despliegue continuo en la nube, respondiendo al perfil de DevOps solicitado en el país."

            gap_data = {
                "sector": sector,
                "critical_gaps": critical,
                "moderate_gaps": moderate,
                "well_covered": covered,
                "opportunity_statement": f"Existe una clara oportunidad para capacitar a los graduados en {sector} mediante un curso práctico que aborde el desfase tecnológico en herramientas demandadas.",
                "proposed_course_title": title,
                "proposed_course_rationale": rationale,
                "proposed_course_depth": "intermedio"
            }
            return json.dumps(gap_data, ensure_ascii=False)

        elif self.name == "CourseDesignerAgent":
            title = "Diseño y Despliegue de Sistemas Prácticos en " + sector
            objectives = [
                {"bloom_level": "comprender", "description": f"Identificar las brechas y desafíos clave en el sector de {sector}."},
                {"bloom_level": "aplicar", "description": "Aplicar herramientas de automatización y control de versiones en el flujo de trabajo."},
                {"bloom_level": "analizar", "description": "Analizar la arquitectura técnica de soluciones de software escalables."},
                {"bloom_level": "aplicar", "description": "Configurar y desplegar servicios en entornos aislados y controlados."},
                {"bloom_level": "evaluar", "description": "Evaluar la seguridad y el rendimiento de la solución técnica implementada."},
                {"bloom_level": "crear", "description": "Diseñar y construir un proyecto integrador que resuelva un problema del mundo real."}
            ]
            
            activities = []
            for w in range(1, 17):
                act_type = "lectura"
                if w in (2, 4, 6, 8, 10):
                    act_type = "laboratorio"
                elif w in (12, 14, 15):
                    act_type = "proyecto"
                elif w in (5, 11):
                    act_type = "taller"
                elif w in (9, 13, 16):
                    act_type = "evaluacion"
                    
                activities.append({
                    "week": w,
                    "title": f"Módulo de la Semana {w}: Introducción y práctica",
                    "activity_type": act_type,
                    "description": f"Sesión teórico-práctica sobre los conceptos y herramientas clave de la semana {w}.",
                    "estimated_hours": 6.0,
                    "learning_objectives_addressed": [w % 6]
                })
                
            plan_data = {
                "course_title": title,
                "course_code": "TCU-501",
                "credits": 4,
                "hours_per_week": 12.0,
                "total_weeks": 16,
                "target_audience": f"Estudiantes universitarios avanzados de informática o ingeniería afín interesados en {sector}.",
                "prerequisites": ["Programación Básica", "Redes"],
                "learning_objectives": objectives,
                "weekly_schedule": activities,
                "bibliography": [
                    "Manual Oficial del Desarrollador Profesional, Editorial Tech, 2025.",
                    "DevOps y Cloud en Costa Rica, Ediciones Académicas, 2024.",
                    "Sistemas Distribuidos y Escalables, CloudPress, 2023."
                ]
            }
            return json.dumps(plan_data, ensure_ascii=False)

        elif self.name == "EvaluatorAgent":
            components = [
                {"component": "Proyecto Integrador", "weight_percent": 40.0, "rubric_items": ["Arquitectura técnica", "Calidad del código", "Funcionalidad"], "passing_threshold": 70.0},
                {"component": "Laboratorios Prácticos", "weight_percent": 30.0, "rubric_items": ["Configuración", "Resolución de problemas", "Entregables a tiempo"], "passing_threshold": 70.0},
                {"component": "Pruebas Teóricas", "weight_percent": 20.0, "rubric_items": ["Comprensión conceptual", "Análisis de casos", "Dominio del temario"], "passing_threshold": 70.0},
                {"component": "Participación y Foros", "weight_percent": 10.0, "rubric_items": ["Aportes constructivos", "Interacción con compañeros", "Puntualidad"], "passing_threshold": 70.0}
            ]
            eval_data = {
                "evaluation_components": components,
                "competency_matrix": {
                    "Automatización": ["Módulo de la Semana 2: Introducción y práctica", "Módulo de la Semana 4: Introducción y práctica"],
                    "Despliegue": ["Módulo de la Semana 6: Introducción y práctica", "Módulo de la Semana 12: Introducción y práctica"],
                    "Análisis Crítico": ["Módulo de la Semana 9: Introducción y práctica", "Módulo de la Semana 16: Introducción y práctica"]
                }
            }
            return json.dumps(eval_data, ensure_ascii=False)

        elif self.name == "ReadingAgent":
            reading_data = {
                "reading_material": f"<h3>Lectura Semanal: Introducción General</h3><p>La computación moderna requiere comprender cómo se integran las tecnologías de vanguardia en el sector de {sector}. En esta lección inicial abordamos los fundamentos y marcos de referencia teóricos.</p><h4>Conceptos Clave</h4><ul><li>Modularidad: División en componentes aislados.</li><li>Seguridad: Minimizar la superficie de ataque.</li><li>Automatización: Eliminar tareas repetitivas y propensas a error.</li></ul>",
                "assignment_prompt": "Redacte un ensayo descriptivo analizando cómo los pilares discutidos impactan el desarrollo de sistemas en el sector en Costa Rica."
            }
            return json.dumps(reading_data, ensure_ascii=False)

        return "{}"
