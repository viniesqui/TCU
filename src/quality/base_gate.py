"""
Quality gate infrastructure for the TCU pipeline.

Each gate evaluates the output of a pipeline stage and returns a QualityResult.
Gates use Python rules (free, fast) to generate targeted retry instructions.
The orchestrator uses these to re-run agents with specific guidance on what to fix.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class QualityResult(BaseModel):
    """Structured result from a quality gate evaluation."""
    gate_name: str
    passed: bool
    score: float  # 0.0 – 1.0
    issues: list[str]  # Human-readable list of problems found
    retry_instructions: str  # Injected into the agent prompt on retry (Spanish)
    suggest_broadening: bool = False  # True when geographic scope should widen


class QualityGate(ABC):
    """
    Abstract base class for all quality gates.

    Subclasses implement `evaluate()` with domain-specific rules.
    When a gate fails, `retry_instructions` are injected into the
    agent's next attempt so it knows exactly what to improve.
    """

    @property
    @abstractmethod
    def gate_name(self) -> str:
        ...

    @abstractmethod
    def evaluate(self, data: Any) -> QualityResult:
        ...

    def _result(
        self,
        issues: list[str],
        score: float,
        suggest_broadening: bool = False,
    ) -> QualityResult:
        passed = len(issues) == 0
        retry_instructions = self._build_retry_instructions(issues) if not passed else ""
        return QualityResult(
            gate_name=self.gate_name,
            passed=passed,
            score=round(score, 2),
            issues=issues,
            retry_instructions=retry_instructions,
            suggest_broadening=suggest_broadening,
        )

    @abstractmethod
    def _build_retry_instructions(self, issues: list[str]) -> str:
        """Build a Spanish-language instruction string for the retrying agent."""
        ...
