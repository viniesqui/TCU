import json
import logging
import re
from typing import Any

import anthropic
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.config import settings
from src.tools.tool_registry import TOOL_REGISTRY

logger = logging.getLogger(__name__)


class BaseAgent:
    """
    Base class implementing the standard Anthropic tool-use agentic loop.

    Flow:
      1. Send user message to Claude with tool schemas
      2. If stop_reason == "tool_use": execute tools, append results, loop
      3. If stop_reason == "end_turn": extract and return final text
      4. Retry on rate limit / server errors via tenacity
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
            response = self._call_claude(messages)

            if response.stop_reason == "end_turn":
                text = self._extract_text(response)
                logger.info(f"[{self.name}] Completed after {iteration + 1} iterations")
                return text

            if response.stop_reason == "tool_use":
                # Append assistant turn
                messages.append({"role": "assistant", "content": response.content})
                # Execute tools and build result blocks
                tool_result_blocks = self._execute_tool_calls(response)
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
        retry=retry_if_exception_type((
            anthropic.RateLimitError,
            anthropic.APIStatusError,
            anthropic.InternalServerError,
        )),
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
                    is_error = False
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
        """Extract concatenated text from all TextBlock items in response."""
        parts = []
        for block in response.content:
            if hasattr(block, "text"):
                parts.append(block.text)
        return "\n".join(parts).strip()

    @staticmethod
    def clean_json(raw: str) -> str:
        """Strip markdown code fences from agent output before JSON parsing."""
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned.strip())
        return cleaned.strip()
