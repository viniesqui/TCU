from typing import Literal
from pydantic import BaseModel, Field


class SkillGap(BaseModel):
    skill_name: str
    market_demand_score: float = Field(ge=0.0, le=1.0, description="How in-demand this skill is (0-1)")
    academic_coverage_score: float = Field(ge=0.0, le=1.0, description="How well universities cover it (0-1)")
    gap_severity: Literal["critical", "moderate", "minor", "covered"]
    notes: str = Field(description="Brief explanation of the gap or coverage")
    market_depth_required: Literal["basico", "intermedio", "avanzado"] = "intermedio"


class GapAnalysis(BaseModel):
    sector: str
    critical_gaps: list[SkillGap] = Field(description="Skills urgently missing from academia")
    moderate_gaps: list[SkillGap] = Field(description="Skills partially addressed but insufficient")
    well_covered: list[SkillGap] = Field(description="Skills already well taught by universities")
    opportunity_statement: str = Field(description="Narrative in Spanish: why a new course is justified")
    proposed_course_title: str = Field(description="Working title for the proposed course")
    proposed_course_rationale: str = Field(description="One paragraph in Spanish explaining the proposed course")
    proposed_course_depth: Literal["basico", "intermedio", "avanzado"] = "intermedio"
