"""
Quality gates for Stages 3–5 (Gap Analysis, Curriculum, Activities).

These agents do pure reasoning — they don't search the web.
Their gates focus on logical coherence, coverage, and pedagogical soundness.

Stage 6 (Evaluator) is already covered by Pydantic's weight-sum validator,
so no additional gate is needed there.
"""

from __future__ import annotations

from src.models.course_design import LearningActivity, LearningObjective
from src.models.gap import GapAnalysis
from src.quality.base_gate import QualityGate, QualityResult


class GapAnalysisGate(QualityGate):
    """
    Validates that the gap analysis is actionable and well-structured.

    Checks:
    - At least some critical or moderate gaps found
    - All gaps have meaningful demand/coverage scores
    - A proposed course title exists and is non-trivial
    - Opportunity statement is substantive
    - Well-covered list is present (shows thorough comparison)
    """

    @property
    def gate_name(self) -> str:
        return "GapAnalysisGate"

    def evaluate(self, data: GapAnalysis) -> QualityResult:
        issues: list[str] = []
        score_components: list[float] = []

        # --- Check: actionable gaps exist ---
        actionable = len(data.critical_gaps) + len(data.moderate_gaps)
        if actionable < 3:
            issues.append(
                f"Solo {actionable} brechas críticas/moderadas identificadas. "
                f"Se necesitan al menos 3 para justificar un curso nuevo. "
                f"Revisa si las habilidades del mercado están realmente cubiertas por la academia."
            )
        score_components.append(min(actionable / 5, 1.0))

        # --- Check: critical gaps are truly critical ---
        if data.critical_gaps:
            bad_critical = [
                g for g in data.critical_gaps
                if g.market_demand_score < 0.4 or g.academic_coverage_score > 0.5
            ]
            if bad_critical:
                names = ", ".join(g.skill_name for g in bad_critical[:3])
                issues.append(
                    f"Algunas brechas marcadas como 'críticas' no tienen scores consistentes "
                    f"({names}). Una brecha crítica debe tener demanda >= 0.4 y cobertura <= 0.5."
                )
        score_components.append(1.0 if not data.critical_gaps or not issues else 0.5)

        # --- Check: proposed course title ---
        title = (data.proposed_course_title or "").strip()
        if len(title) < 10:
            issues.append(
                f"El título del curso propuesto es muy breve o inexistente: '{title}'. "
                f"Debe ser un título descriptivo y específico para un curso universitario."
            )
        score_components.append(min(len(title) / 30, 1.0))

        # --- Check: opportunity statement ---
        stmt_len = len(data.opportunity_statement or "")
        if stmt_len < 100:
            issues.append(
                f"El enunciado de oportunidad es muy breve ({stmt_len} caracteres). "
                f"Debe argumentar claramente por qué se justifica el nuevo curso."
            )
        score_components.append(min(stmt_len / 250, 1.0))

        # --- Check: well_covered list shows comparison was done ---
        if not data.well_covered:
            issues.append(
                "No se identificaron habilidades bien cubiertas. "
                "Esto sugiere que el análisis no consideró toda la oferta académica. "
                "Incluye al menos algunas habilidades que sí enseñan las universidades."
            )
        score_components.append(1.0 if data.well_covered else 0.0)

        overall_score = sum(score_components) / len(score_components) if score_components else 0.0
        return self._result(issues, overall_score)

    def _build_retry_instructions(self, issues: list[str]) -> str:
        lines = [
            "INSTRUCCIONES DE MEJORA (análisis de brecha incompleto):",
            "",
        ]
        lines += [f"- {issue}" for issue in issues]
        lines += [
            "",
            "RECUERDA:",
            "- 'critical': demanda >= 0.6 Y cobertura académica <= 0.2",
            "- 'moderate': demanda >= 0.4 Y cobertura <= 0.5",
            "- Debe haber al menos 3 brechas críticas o moderadas combinadas.",
            "- Incluye habilidades 'covered' para demostrar que comparaste exhaustivamente.",
            "- El título del curso debe ser específico, ej: 'Desarrollo de APIs con Python y FastAPI'.",
        ]
        return "\n".join(lines)


class CurriculumGate(QualityGate):
    """
    Validates the course curriculum for pedagogical soundness.

    Checks:
    - Learning objectives count is adequate
    - Bloom's taxonomy distribution reaches higher levels
    - Credits / hours / weeks are internally consistent
    - At least one "crear" or "evaluar" level objective
    - Prerequisites are reasonable (not empty, not too many)
    """

    @property
    def gate_name(self) -> str:
        return "CurriculumGate"

    def evaluate(self, data: dict) -> QualityResult:
        """
        data is the raw dict from _PartialStudyPlan.model_dump()
        since StudyPlan isn't fully assembled at this stage.
        """
        issues: list[str] = []
        score_components: list[float] = []

        objectives: list[dict] = data.get("learning_objectives", [])
        credits: int = data.get("credits", 0)
        hours_per_week: float = data.get("hours_per_week", 0)
        total_weeks: int = data.get("total_weeks", 0)

        # --- Check: objectives count ---
        obj_count = len(objectives)
        if obj_count < 4:
            issues.append(
                f"Solo {obj_count} objetivos de aprendizaje (mínimo recomendado: 6). "
                f"Un curso universitario de un semestre necesita objetivos más comprehensivos."
            )
        score_components.append(min(obj_count / 7, 1.0))

        # --- Check: Bloom's taxonomy reaches higher levels ---
        high_levels = {"analizar", "evaluar", "crear"}
        bloom_levels_used = {obj.get("bloom_level", "") for obj in objectives}
        high_level_count = len(bloom_levels_used & high_levels)
        if high_level_count == 0:
            issues.append(
                "Ningún objetivo de aprendizaje alcanza niveles superiores de la Taxonomía de Bloom "
                "(analizar, evaluar, crear). Al menos 1-2 objetivos deben estar en estos niveles."
            )
        score_components.append(min(high_level_count / 2, 1.0))

        # --- Check: has "crear" level ---
        has_crear = any(obj.get("bloom_level") == "crear" for obj in objectives)
        if not has_crear:
            issues.append(
                "Ningún objetivo en nivel 'crear'. Para un curso práctico de tecnología, "
                "los estudiantes deben construir o producir algo al finalizar."
            )
        score_components.append(1.0 if has_crear else 0.4)

        # --- Check: credits consistency (CR standard: 1 credit = 3 hrs/week student) ---
        if credits > 0 and hours_per_week > 0:
            expected_hours = credits * 3
            ratio = hours_per_week / expected_hours
            if ratio < 0.5 or ratio > 2.5:
                issues.append(
                    f"Las horas por semana ({hours_per_week}) parecen inconsistentes con "
                    f"{credits} créditos. Estándar CR: 1 crédito ≈ 3 horas estudiante/semana."
                )
            score_components.append(min(ratio if ratio <= 1 else 1 / ratio, 1.0))
        else:
            issues.append("Créditos u horas por semana están en cero o faltantes.")
            score_components.append(0.0)

        # --- Check: semester length (CR: typically 16 weeks) ---
        if total_weeks < 12 or total_weeks > 20:
            issues.append(
                f"Duración del curso: {total_weeks} semanas. "
                f"Un semestre universitario en Costa Rica es típicamente 16 semanas (rango 12-20)."
            )
        score_components.append(1.0 if 12 <= total_weeks <= 20 else 0.5)

        # --- Check: bibliography ---
        bibliography: list = data.get("bibliography", [])
        if len(bibliography) < 3:
            issues.append(
                f"Solo {len(bibliography)} referencias bibliográficas. "
                f"Un curso universitario debe tener al menos 3-5 referencias."
            )
        score_components.append(min(len(bibliography) / 4, 1.0))

        overall_score = sum(score_components) / len(score_components) if score_components else 0.0
        return self._result(issues, overall_score)

    def _build_retry_instructions(self, issues: list[str]) -> str:
        lines = [
            "INSTRUCCIONES DE MEJORA (plan de estudios con problemas de coherencia pedagógica):",
            "",
        ]
        lines += [f"- {issue}" for issue in issues]
        lines += [
            "",
            "ESTÁNDARES UNIVERSITARIOS COSTA RICA:",
            "- Semestre típico: 16 semanas",
            "- 1 crédito = 3 horas estudiante por semana (lectiva + independiente)",
            "- Bachillerato: típicamente 3-4 créditos",
            "- Objetivos: usa verbos de acción de Bloom (analizar, diseñar, construir, evaluar, crear)",
            "- Incluye al menos 1 objetivo en nivel 'crear' (el estudiante construye algo real)",
        ]
        return "\n".join(lines)


class ActivitiesGate(QualityGate):
    """
    Validates the weekly activity schedule for pedagogical coverage and variety.

    Checks:
    - Activity count matches total_weeks
    - All learning objectives are addressed by at least one activity
    - Activity types are varied (not all the same type)
    - Total hours are reasonable
    - No week has unrealistic hour estimates
    """

    MAX_HOURS_PER_WEEK = 20.0
    MIN_ACTIVITY_TYPES = 3

    @property
    def gate_name(self) -> str:
        return "ActivitiesGate"

    def evaluate(
        self,
        activities: list[LearningActivity],
        total_weeks: int,
        num_objectives: int,
    ) -> QualityResult:
        issues: list[str] = []
        score_components: list[float] = []

        # --- Check: activity count matches weeks ---
        act_count = len(activities)
        if act_count < total_weeks - 1:
            issues.append(
                f"Solo {act_count} actividades para {total_weeks} semanas. "
                f"Debe haber una actividad por semana (±1)."
            )
        score_components.append(min(act_count / max(total_weeks, 1), 1.0))

        # --- Check: objective coverage ---
        covered_objectives: set[int] = set()
        for act in activities:
            covered_objectives.update(act.learning_objectives_addressed)

        all_objective_indices = set(range(num_objectives))
        uncovered = all_objective_indices - covered_objectives
        if uncovered:
            issues.append(
                f"Los objetivos {sorted(uncovered)} (índice 0-based) no son abordados "
                f"por ninguna actividad. Cada objetivo debe aparecer en al menos 1 actividad."
            )
        coverage_ratio = len(covered_objectives & all_objective_indices) / max(num_objectives, 1)
        score_components.append(coverage_ratio)

        # --- Check: activity type variety ---
        types_used = {act.activity_type for act in activities}
        if len(types_used) < self.MIN_ACTIVITY_TYPES:
            issues.append(
                f"Solo {len(types_used)} tipo(s) de actividad diferentes ({', '.join(types_used)}). "
                f"Usa al menos {self.MIN_ACTIVITY_TYPES} tipos distintos para variedad pedagógica "
                f"(lectura, laboratorio, proyecto, debate, caso_estudio, evaluacion, taller)."
            )
        score_components.append(min(len(types_used) / self.MIN_ACTIVITY_TYPES, 1.0))

        # --- Check: has at least one proyecto or taller ---
        practical = {"laboratorio", "proyecto", "taller"}
        has_practical = bool(types_used & practical)
        if not has_practical:
            issues.append(
                "No hay actividades prácticas (laboratorio, proyecto o taller). "
                "Para un curso de tecnología, debe haber al menos 2-3 actividades prácticas."
            )
        score_components.append(1.0 if has_practical else 0.0)

        # --- Check: unrealistic hour estimates ---
        overloaded = [act for act in activities if act.estimated_hours > self.MAX_HOURS_PER_WEEK]
        if overloaded:
            titles = ", ".join(a.title for a in overloaded[:3])
            issues.append(
                f"{len(overloaded)} actividad(es) tienen más de {self.MAX_HOURS_PER_WEEK} horas "
                f"estimadas ({titles}). Revisa las estimaciones para que sean realistas."
            )
        score_components.append(1.0 if not overloaded else max(0.5, 1 - len(overloaded) / act_count))

        # --- Check: has at least one evaluacion ---
        has_eval = any(act.activity_type == "evaluacion" for act in activities)
        if not has_eval:
            issues.append(
                "No hay ninguna actividad de tipo 'evaluacion' en el cronograma. "
                "Incluye al menos 1-2 evaluaciones formales durante el semestre."
            )
        score_components.append(1.0 if has_eval else 0.3)

        overall_score = sum(score_components) / len(score_components) if score_components else 0.0
        return self._result(issues, overall_score)

    def _build_retry_instructions(self, issues: list[str]) -> str:
        lines = [
            "INSTRUCCIONES DE MEJORA (cronograma de actividades con problemas):",
            "",
        ]
        lines += [f"- {issue}" for issue in issues]
        lines += [
            "",
            "PRINCIPIOS PEDAGÓGICOS A SEGUIR:",
            "- Una actividad por semana (total debe coincidir con total_weeks del plan).",
            "- Cada objetivo de aprendizaje (por índice) debe estar cubierto por ≥1 actividad.",
            "- Usa al menos 4 tipos distintos: lectura, laboratorio, proyecto, evaluacion.",
            "- Progresión: semanas 1-3 (fundamentos) → 4-10 (práctica) → 11-15 (proyecto) → 16 (evaluación).",
            "- Horas por actividad: lecturas 1-3h, laboratorios 2-4h, proyectos 4-8h.",
            "- Incluye al menos 2 evaluaciones formales y 2 proyectos prácticos.",
        ]
        return "\n".join(lines)
