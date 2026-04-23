from typing import Literal
from pydantic import BaseModel, Field, model_validator


class LearningObjective(BaseModel):
    bloom_level: Literal["recordar", "comprender", "aplicar", "analizar", "evaluar", "crear"]
    description: str = Field(description="Full objective description in Spanish")


class LearningActivity(BaseModel):
    week: int = Field(ge=1, description="Week number in the course")
    title: str
    activity_type: Literal["lectura", "laboratorio", "proyecto", "debate", "caso_estudio", "evaluacion", "taller"]
    description: str = Field(description="Detailed description in Spanish")
    estimated_hours: float = Field(gt=0)
    learning_objectives_addressed: list[int] = Field(
        default_factory=list,
        description="Indices (0-based) of learning objectives this activity addresses"
    )


class EvaluationCriteria(BaseModel):
    component: str = Field(description="e.g. 'Proyecto Final', 'Examen Parcial'")
    weight_percent: float = Field(gt=0, le=100)
    rubric_items: list[str] = Field(description="Bullet-point criteria for full marks")
    passing_threshold: float = Field(default=70.0, description="Minimum score to pass this component")


class Evaluator(BaseModel):
    evaluation_components: list[EvaluationCriteria]
    competency_matrix: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Maps skill name -> list of activity titles that develop it"
    )

    @model_validator(mode="after")
    def check_weights_sum(self) -> "Evaluator":
        total = sum(c.weight_percent for c in self.evaluation_components)
        if total == 100.0:
            return self
        delta = 100.0 - total
        if abs(delta) <= 2.0:
            # Within the fuzzy tolerance [98.0, 102.0]: pin the largest component so sum == 100.0
            largest = max(self.evaluation_components, key=lambda c: c.weight_percent)
            largest.weight_percent += delta
            return self
        raise ValueError(f"Evaluation weights must sum to 100, got {total:.1f}")


class StudyPlan(BaseModel):
    course_title: str
    course_code: str = Field(description="e.g. 'TCU-501'")
    credits: int = Field(ge=1)
    hours_per_week: float = Field(gt=0)
    total_weeks: int = Field(ge=1)
    target_audience: str = Field(description="Description in Spanish of who this course is for")
    prerequisites: list[str] = Field(default_factory=list)
    learning_objectives: list[LearningObjective]
    weekly_schedule: list[LearningActivity]
    evaluator: Evaluator
    bibliography: list[str] = Field(default_factory=list, description="List of references/resources")

    @model_validator(mode="after")
    def check_activity_objective_refs(self) -> "StudyPlan":
        """Ensure all activity objective indices are valid references into learning_objectives."""
        num_objectives = len(self.learning_objectives)
        for act in self.weekly_schedule:
            for idx in act.learning_objectives_addressed:
                if idx < 0 or idx >= num_objectives:
                    raise ValueError(
                        f"Activity '{act.title}' (week {act.week}) references objective index {idx}, "
                        f"but only {num_objectives} objectives exist (valid indices: 0–{num_objectives - 1})."
                    )
        return self
