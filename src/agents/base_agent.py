import json
import logging
import re
from typing import Any

import anthropic
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from src.config import settings
from src.tools.tool_registry import TOOL_REGISTRY

logger = logging.getLogger(__name__)

# Trim context when the raw character count exceeds this threshold (~45k tokens).
_MAX_CONTEXT_CHARS = 180_000


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

    def __init__(
        self,
        name: str,
        system_prompt: str,
        tools: list[dict] | None = None,
        model: str | None = None,
        max_iterations: int | None = None,
    ) -> None:
        self.name = name
        self.system_prompt = system_prompt
        self.tools = tools or []
        self.model = model or settings.model
        self.max_iterations = max_iterations or settings.max_agent_iterations
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run(self, user_message: str) -> str:
        """
        Run the agentic loop for a single task.
        Returns the agent's final text response (typically JSON).
        """
        logger.info(f"[{self.name}] Starting run")
        messages: list[dict[str, Any]] = [{"role": "user", "content": user_message}]

        for iteration in range(self.max_iterations):
            logger.debug(f"[{self.name}] Iteration {iteration + 1}/{self.max_iterations}")
            messages = self._maybe_trim_messages(messages)
            response = self._call_claude(messages)

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
                    raise RuntimeError(f"[{self.name}] Tool execution failed unexpectedly: {exc}") from exc
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
        return self._client.messages.create(**kwargs)

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
                result_content = f"ERROR: Unknown tool '{tool_name}'"
                is_error = True
            else:
                try:
                    raw_result = TOOL_REGISTRY[tool_name](**tool_input)
                    result_content = raw_result if isinstance(raw_result, str) else json.dumps(raw_result)
                    # Detect structured error responses (tools return JSON with error+error_code)
                    # so Claude sees is_error=True and knows to try a different approach.
                    is_error = _is_tool_error_response(result_content)
                except Exception as e:
                    result_content = f"ERROR executing {tool_name}: {e}"
                    is_error = True
                    logger.warning(f"[{self.name}] Tool '{tool_name}' failed: {e}")

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
        return cleaned.strip()

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
