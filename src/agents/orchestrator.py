"""
TCU Orchestrator – V2 with Quality Gates
=========================================
Python state machine that sequences the six specialist agents.
Between every stage, a quality gate validates the output and — if the result
is insufficient — re-runs the agent with targeted Spanish-language instructions
explaining exactly what to improve.

Pipeline:
    Stage 1: LaborMarketAgent    → IndustryDemand      → MarketResearchGate
    Stage 2: AcademicAgent       → AcademicLandscape   → AcademicResearchGate
    Stage 3: GapAnalystAgent     → GapAnalysis         → GapAnalysisGate
    Stage 4: CurriculumAgent     → partial StudyPlan   → CurriculumGate
    Stage 5: ActivitiesAgent     → weekly_schedule     → ActivitiesGate
    Stage 6: EvaluatorAgent      → Evaluator           → (Pydantic weight-sum already enforces)
    Stage 7: ReportGenerator     → HTML file
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from src.agents.academic_agent import AcademicAgent
from src.agents.activities_agent import ActivitiesAgent
from src.agents.base_agent import BaseAgent
from src.agents.curriculum_agent import CurriculumAgent
from src.agents.evaluator_agent import EvaluatorAgent
from src.agents.gap_analyst_agent import GapAnalystAgent
from src.agents.labor_market_agent import LaborMarketAgent
from src.config import settings
from src.models.academic import AcademicLandscape
from src.models.course_design import Evaluator, LearningActivity, StudyPlan
from src.models.gap import GapAnalysis
from src.models.market import IndustryDemand
from src.quality.downstream_gates import ActivitiesGate, CurriculumGate, GapAnalysisGate
from src.quality.research_gates import AcademicResearchGate, MarketResearchGate

logger = logging.getLogger(__name__)


@dataclass
class OrchestratorResult:
    """All structured outputs produced by the orchestration pipeline."""
    sector: str
    industry_demand: IndustryDemand
    academic_landscape: AcademicLandscape
    gap_analysis: GapAnalysis
    study_plan: StudyPlan
    report_path: str = ""
    quality_scores: dict[str, float] = field(default_factory=dict)


class Orchestrator:
    """
    State machine orchestrator with quality gates between every stage.

    Quality gate behavior:
    - Gate passes  → proceed to next stage
    - Gate fails   → retry the agent with targeted retry_instructions
    - Max retries  → log warning and proceed with best available output
                     (the pipeline never hard-fails due to quality alone)
    """

    def __init__(self, progress: Any = None) -> None:
        self.progress = progress
        self.max_retries: int = settings.max_stage_retries
        self._quality_scores: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run(self, sector: str = "Desarrollo de Software") -> str:
        """Execute the full pipeline. Returns path to generated HTML report."""
        logger.info(f"[Orchestrator] ── V2 Pipeline start ── sector='{sector}'")

        # Stage 1 – Labor Market Research
        self._progress("🔎 Investigando mercado laboral en Costa Rica...")
        industry_demand = self._stage_market_research(sector)

        # Stage 2 – Academic Research
        self._progress("🎓 Investigando oferta académica universitaria...")
        academic_landscape = self._stage_academic_research(sector)

        # Stage 3 – Gap Analysis
        self._progress("📊 Analizando brecha educativa...")
        gap_analysis = self._stage_gap_analysis(industry_demand, academic_landscape)

        # Stage 4 – Curriculum Design
        self._progress("📝 Diseñando plan de estudios...")
        partial_plan = self._stage_curriculum(gap_analysis)

        # Stage 5 – Learning Activities
        self._progress("📅 Creando actividades de aprendizaje...")
        activities = self._stage_activities(partial_plan)

        # Stage 6 – Evaluator
        self._progress("✅ Diseñando sistema de evaluación...")
        evaluator = self._stage_evaluator(partial_plan, activities)

        # Assemble final StudyPlan
        final_plan_dict = partial_plan.model_dump()
        final_plan_dict["weekly_schedule"] = [a.model_dump() for a in activities]
        final_plan_dict["evaluator"] = evaluator.model_dump()
        study_plan = StudyPlan.model_validate(final_plan_dict)

        # Stage 7 – Report
        self._progress("📄 Generando reporte HTML...")
        from src.report_generator import ReportGenerator
        report_path = ReportGenerator().render(
            industry_demand=industry_demand,
            academic_landscape=academic_landscape,
            gap_analysis=gap_analysis,
            study_plan=study_plan,
            quality_scores=self._quality_scores,
        )

        logger.info(f"[Orchestrator] ── Pipeline complete ── report={report_path}")
        return str(report_path)

    # ------------------------------------------------------------------
    # Stage 1: Labor Market Research
    # ------------------------------------------------------------------

    def _stage_market_research(self, sector: str) -> IndustryDemand:
        gate = MarketResearchGate()
        agent = LaborMarketAgent()
        retry_context: str | None = None

        for attempt in range(1, self.max_retries + 2):
            logger.info(f"[Stage 1] Attempt {attempt}/{self.max_retries + 1}")
            try:
                raw = agent.research(sector, retry_context=retry_context)
                result = IndustryDemand.model_validate_json(BaseAgent.clean_json(raw))
            except (ValidationError, ValueError, Exception) as e:
                logger.warning(f"[Stage 1] Parse/validation error: {e}")
                retry_context = (
                    f"Tu respuesta anterior no fue JSON válido. Error: {e}. "
                    f"Responde ÚNICAMENTE con el objeto JSON, sin markdown ni texto adicional."
                )
                if attempt > self.max_retries:
                    raise RuntimeError(f"Stage 1 failed to produce valid JSON after {attempt} attempts") from e
                continue

            gate_result = gate.evaluate(result)
            self._quality_scores["market_research"] = gate_result.score
            self._log_gate(gate_result)

            if gate_result.passed:
                return result

            if attempt > self.max_retries:
                logger.warning(f"[Stage 1] Quality gate failed after all retries. Proceeding with best result.")
                return result

            retry_context = gate_result.retry_instructions

        return result  # unreachable but satisfies type checker

    # ------------------------------------------------------------------
    # Stage 2: Academic Research
    # ------------------------------------------------------------------

    def _stage_academic_research(self, sector: str) -> AcademicLandscape:
        gate = AcademicResearchGate()
        agent = AcademicAgent()
        retry_context: str | None = None
        broaden = False

        for attempt in range(1, self.max_retries + 2):
            logger.info(f"[Stage 2] Attempt {attempt}/{self.max_retries + 1} broaden={broaden}")
            try:
                raw = agent.research(sector, retry_context=retry_context, broaden_to_region=broaden)
                result = AcademicLandscape.model_validate_json(BaseAgent.clean_json(raw))
            except (ValidationError, ValueError, Exception) as e:
                logger.warning(f"[Stage 2] Parse/validation error: {e}")
                retry_context = (
                    f"Tu respuesta anterior no fue JSON válido. Error: {e}. "
                    f"Responde ÚNICAMENTE con el objeto JSON, sin markdown ni texto adicional."
                )
                if attempt > self.max_retries:
                    raise RuntimeError(f"Stage 2 failed to produce valid JSON after {attempt} attempts") from e
                continue

            gate_result = gate.evaluate(result)
            self._quality_scores["academic_research"] = gate_result.score
            self._log_gate(gate_result)

            if gate_result.passed:
                return result

            if attempt > self.max_retries:
                logger.warning(f"[Stage 2] Quality gate failed after all retries. Proceeding with best result.")
                return result

            # On first failure: try geographic broadening if suggested
            if gate_result.suggest_broadening and not broaden:
                logger.info("[Stage 2] Broadening search scope to Central America")
                broaden = True

            retry_context = gate_result.retry_instructions

        return result

    # ------------------------------------------------------------------
    # Stage 3: Gap Analysis
    # ------------------------------------------------------------------

    def _stage_gap_analysis(
        self, industry_demand: IndustryDemand, academic_landscape: AcademicLandscape
    ) -> GapAnalysis:
        gate = GapAnalysisGate()
        agent = GapAnalystAgent()
        demand_json = industry_demand.model_dump_json(indent=2)
        academic_json = academic_landscape.model_dump_json(indent=2)
        retry_context: str | None = None

        for attempt in range(1, self.max_retries + 2):
            logger.info(f"[Stage 3] Attempt {attempt}/{self.max_retries + 1}")
            try:
                raw = agent.analyze(demand_json, academic_json, retry_context=retry_context)
                result = GapAnalysis.model_validate_json(BaseAgent.clean_json(raw))
            except (ValidationError, ValueError, Exception) as e:
                logger.warning(f"[Stage 3] Parse/validation error: {e}")
                retry_context = f"JSON inválido. Error: {e}. Responde solo con JSON."
                if attempt > self.max_retries:
                    raise RuntimeError(f"Stage 3 failed after {attempt} attempts") from e
                continue

            gate_result = gate.evaluate(result)
            self._quality_scores["gap_analysis"] = gate_result.score
            self._log_gate(gate_result)

            if gate_result.passed:
                return result
            if attempt > self.max_retries:
                logger.warning("[Stage 3] Proceeding with best result after gate failures.")
                return result

            retry_context = gate_result.retry_instructions

        return result

    # ------------------------------------------------------------------
    # Stage 4: Curriculum Design
    # ------------------------------------------------------------------

    def _stage_curriculum(self, gap_analysis: GapAnalysis) -> _PartialStudyPlan:
        gate = CurriculumGate()
        agent = CurriculumAgent()
        gap_json = gap_analysis.model_dump_json(indent=2)
        retry_context: str | None = None

        for attempt in range(1, self.max_retries + 2):
            logger.info(f"[Stage 4] Attempt {attempt}/{self.max_retries + 1}")
            try:
                raw = agent.design(gap_json, retry_context=retry_context)
                result = _PartialStudyPlan.model_validate_json(BaseAgent.clean_json(raw))
            except (ValidationError, ValueError, Exception) as e:
                logger.warning(f"[Stage 4] Parse/validation error: {e}")
                retry_context = f"JSON inválido. Error: {e}. Responde solo con JSON."
                if attempt > self.max_retries:
                    raise RuntimeError(f"Stage 4 failed after {attempt} attempts") from e
                continue

            gate_result = gate.evaluate(result.model_dump())
            self._quality_scores["curriculum"] = gate_result.score
            self._log_gate(gate_result)

            if gate_result.passed:
                return result
            if attempt > self.max_retries:
                logger.warning("[Stage 4] Proceeding with best result after gate failures.")
                return result

            retry_context = gate_result.retry_instructions

        return result

    # ------------------------------------------------------------------
    # Stage 5: Learning Activities
    # ------------------------------------------------------------------

    def _stage_activities(self, partial_plan: _PartialStudyPlan) -> list[LearningActivity]:
        gate = ActivitiesGate()
        agent = ActivitiesAgent()
        plan_json = partial_plan.model_dump_json(indent=2)
        num_objectives = len(partial_plan.learning_objectives)
        retry_context: str | None = None

        for attempt in range(1, self.max_retries + 2):
            logger.info(f"[Stage 5] Attempt {attempt}/{self.max_retries + 1}")
            try:
                raw = agent.design(plan_json, retry_context=retry_context)
                wrapper = _ActivitiesWrapper.model_validate_json(BaseAgent.clean_json(raw))
                activities = wrapper.weekly_schedule
            except (ValidationError, ValueError, Exception) as e:
                logger.warning(f"[Stage 5] Parse/validation error: {e}")
                retry_context = f"JSON inválido. Error: {e}. Responde solo con JSON."
                if attempt > self.max_retries:
                    raise RuntimeError(f"Stage 5 failed after {attempt} attempts") from e
                continue

            gate_result = gate.evaluate(
                activities=activities,
                total_weeks=partial_plan.total_weeks,
                num_objectives=num_objectives,
            )
            self._quality_scores["activities"] = gate_result.score
            self._log_gate(gate_result)

            if gate_result.passed:
                return activities
            if attempt > self.max_retries:
                logger.warning("[Stage 5] Proceeding with best result after gate failures.")
                return activities

            retry_context = gate_result.retry_instructions

        return activities

    # ------------------------------------------------------------------
    # Stage 6: Evaluator
    # ------------------------------------------------------------------

    def _stage_evaluator(
        self, partial_plan: _PartialStudyPlan, activities: list[LearningActivity]
    ) -> Evaluator:
        agent = EvaluatorAgent()
        # Build full context including activities for the evaluator
        full_dict = partial_plan.model_dump()
        full_dict["weekly_schedule"] = [a.model_dump() for a in activities]
        full_json = json.dumps(full_dict, ensure_ascii=False, indent=2)
        retry_context: str | None = None

        for attempt in range(1, self.max_retries + 2):
            logger.info(f"[Stage 6] Attempt {attempt}/{self.max_retries + 1}")
            try:
                raw = agent.design(full_json)
                result = Evaluator.model_validate_json(BaseAgent.clean_json(raw))
                # Pydantic already enforces weight sum = 100 — if we get here, it passed
                self._quality_scores["evaluator"] = 1.0
                return result
            except ValidationError as e:
                logger.warning(f"[Stage 6] Validation error (weights?): {e}")
                retry_context = (
                    f"Error de validación: {e}. "
                    f"CRÍTICO: los weight_percent de todos los componentes DEBEN sumar exactamente 100."
                )
                if attempt > self.max_retries:
                    raise RuntimeError(f"Stage 6 failed after {attempt} attempts") from e
            except Exception as e:
                logger.warning(f"[Stage 6] Error: {e}")
                if attempt > self.max_retries:
                    raise RuntimeError(f"Stage 6 failed after {attempt} attempts") from e

        raise RuntimeError("Stage 6: unreachable")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _log_gate(self, result) -> None:
        status = "PASSED ✓" if result.passed else "FAILED ✗"
        logger.info(
            f"[QualityGate] {result.gate_name}: {status} "
            f"score={result.score:.2f} issues={len(result.issues)}"
        )
        for issue in result.issues:
            logger.warning(f"  ↳ {issue}")

    def _progress(self, description: str) -> None:
        if self.progress is not None:
            try:
                self.progress.log(f"[cyan]{description}[/cyan]")
            except Exception:
                pass
        logger.info(f"[Orchestrator] {description}")


# ---------------------------------------------------------------------------
# Internal Pydantic helpers for partial pipeline data
# ---------------------------------------------------------------------------

class _PartialStudyPlan(BaseModel):
    """Partial StudyPlan without weekly_schedule and evaluator (filled in later stages)."""
    course_title: str
    course_code: str
    credits: int
    hours_per_week: float
    total_weeks: int
    target_audience: str
    prerequisites: list[str] = []
    learning_objectives: list[dict] = []
    bibliography: list[str] = []


class _ActivitiesWrapper(BaseModel):
    """Wrapper for activities agent output."""
    weekly_schedule: list[LearningActivity]
