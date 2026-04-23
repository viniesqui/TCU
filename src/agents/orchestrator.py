"""
TCU Orchestrator – simplified pipeline with quality gates
=========================================================
Python state machine that sequences the specialist agents.
Between every stage, a quality gate validates the output and — if the result
is insufficient — re-runs the agent with targeted Spanish-language instructions
explaining exactly what to improve.

Pipeline:
    Stage 1: LaborMarketAgent    → IndustryDemand      → MarketResearchGate
    Stage 2: AcademicAgent       → AcademicLandscape   → AcademicResearchGate
    Stage 3: GapAnalystAgent     → GapAnalysis         → GapAnalysisGate
    Stage 4: CourseDesignerAgent → StudyPlan (partial) → CurriculumGate + ActivitiesGate
    Stage 5: EvaluatorAgent      → Evaluator           → EvaluatorGate
    Stage 6: ReportGenerator     → HTML file
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from src.agents.academic_agent import AcademicAgent
from src.agents.base_agent import BaseAgent
from src.agents.course_designer_agent import CourseDesignerAgent
from src.agents.evaluator_agent import EvaluatorAgent
from src.agents.gap_analyst_agent import GapAnalystAgent
from src.agents.labor_market_agent import LaborMarketAgent
from src.config import settings
from src.models.academic import AcademicLandscape
from src.models.course_design import Evaluator, StudyPlan
from src.models.gap import GapAnalysis
from src.models.market import IndustryDemand
from src.quality.downstream_gates import ActivitiesGate, CurriculumGate, EvaluatorGate, GapAnalysisGate
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
        logger.info(f"[Orchestrator] ── Pipeline start ── sector='{sector}'")

        # Stage 1 – Labor Market Research
        self._progress("🔎 Investigando mercado laboral en Costa Rica...")
        industry_demand = self._stage_market_research(sector)

        # Stage 2 – Academic Research
        self._progress("🎓 Investigando oferta académica universitaria...")
        academic_landscape = self._stage_academic_research(sector)

        # Stage 3 – Gap Analysis
        self._progress("📊 Analizando brecha educativa...")
        gap_analysis = self._stage_gap_analysis(industry_demand, academic_landscape)

        # Stage 4 – Course Design (curriculum + activities in one call)
        self._progress("📝 Diseñando plan de estudios y cronograma de actividades...")
        study_plan = self._stage_course_design(gap_analysis)

        # Stage 5 – Evaluator
        self._progress("✅ Diseñando sistema de evaluación...")
        evaluator = self._stage_evaluator(study_plan)
        study_plan.evaluator = evaluator

        # Stage 6 – Report
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
            except (ValidationError, ValueError, json.JSONDecodeError) as e:
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
            except (ValidationError, ValueError, json.JSONDecodeError) as e:
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

            # On first failure: try geographic broadening if suggested.
            # Use broadening-specific instructions instead of the gate's CR-focused ones
            # to avoid sending contradictory guidance (search CA + focus on UCR/TEC).
            if gate_result.suggest_broadening and not broaden:
                logger.info("[Stage 2] Broadening search scope to Central America")
                broaden = True
                retry_context = (
                    "La búsqueda en Costa Rica no encontró suficientes programas. "
                    "Amplía la búsqueda a toda Centroamérica: incluye USAC (Guatemala), "
                    "UES (El Salvador), UNAH (Honduras), UNAN (Nicaragua), UP (Panamá) "
                    "además de las universidades costarricenses ya encontradas."
                )
            else:
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
            except (ValidationError, ValueError, json.JSONDecodeError) as e:
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
    # Stage 4: Course Design (curriculum + activities)
    # ------------------------------------------------------------------

    def _stage_course_design(self, gap_analysis: GapAnalysis) -> StudyPlan:
        curriculum_gate = CurriculumGate()
        activities_gate = ActivitiesGate()
        agent = CourseDesignerAgent()
        gap_json = gap_analysis.model_dump_json(indent=2)
        retry_context: str | None = None

        for attempt in range(1, self.max_retries + 2):
            logger.info(f"[Stage 4] Attempt {attempt}/{self.max_retries + 1}")
            try:
                raw = agent.design(gap_json, retry_context=retry_context)
                result = StudyPlan.model_validate_json(BaseAgent.clean_json(raw))
            except (ValidationError, ValueError, json.JSONDecodeError) as e:
                logger.warning(f"[Stage 4] Parse/validation error: {e}")
                retry_context = f"JSON inválido o índices de objetivos fuera de rango. Error: {e}. Responde solo con JSON."
                if attempt > self.max_retries:
                    raise RuntimeError(f"Stage 4 failed after {attempt} attempts") from e
                continue

            curriculum_result = curriculum_gate.evaluate(result)
            activities_result = activities_gate.evaluate(
                activities=result.weekly_schedule or [],
                total_weeks=result.total_weeks,
                num_objectives=len(result.learning_objectives),
            )
            self._quality_scores["curriculum"] = curriculum_result.score
            self._quality_scores["activities"] = activities_result.score
            self._log_gate(curriculum_result)
            self._log_gate(activities_result)

            if curriculum_result.passed and activities_result.passed:
                return result
            if attempt > self.max_retries:
                logger.warning("[Stage 4] Quality gate(s) failed after all retries. Proceeding with best result.")
                return result

            parts = [
                curriculum_result.retry_instructions if not curriculum_result.passed else "",
                activities_result.retry_instructions if not activities_result.passed else "",
            ]
            retry_context = "\n\n".join(p for p in parts if p)

        return result  # unreachable but satisfies type checker

    # ------------------------------------------------------------------
    # Stage 5: Evaluator
    # ------------------------------------------------------------------

    def _stage_evaluator(self, study_plan: StudyPlan) -> Evaluator:
        gate = EvaluatorGate()
        agent = EvaluatorAgent()
        full_json = study_plan.model_dump_json(indent=2, exclude={"evaluator"})
        retry_context: str | None = None

        for attempt in range(1, self.max_retries + 2):
            logger.info(f"[Stage 5] Attempt {attempt}/{self.max_retries + 1}")
            try:
                raw = agent.design(full_json, retry_context=retry_context)
                result = Evaluator.model_validate_json(BaseAgent.clean_json(raw))
            except ValidationError as e:
                logger.warning(f"[Stage 5] Validation error (weights?): {e}")
                retry_context = (
                    f"Error de validación Pydantic: {e}. "
                    f"CRÍTICO: los weight_percent de todos los componentes DEBEN sumar exactamente 100."
                )
                if attempt > self.max_retries:
                    raise RuntimeError(f"Stage 5 failed after {attempt} attempts") from e
                continue
            except Exception as e:
                logger.warning(f"[Stage 5] Error: {e}")
                retry_context = f"Tu respuesta anterior no fue JSON válido. Error: {e}. Responde solo con JSON."
                if attempt > self.max_retries:
                    raise RuntimeError(f"Stage 5 failed after {attempt} attempts") from e
                continue

            gate_result = gate.evaluate(result)
            self._quality_scores["evaluator"] = gate_result.score
            self._log_gate(gate_result)

            if gate_result.passed:
                return result

            if attempt > self.max_retries:
                logger.warning("[Stage 5] Quality gate failed after all retries. Proceeding with best result.")
                return result

            retry_context = gate_result.retry_instructions

        raise RuntimeError("Stage 5: unreachable")

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
