from typing import Literal
from pydantic import BaseModel, Field


class Course(BaseModel):
    code: str | None = None
    name: str
    credits: int | None = None
    skills_taught: list[str] = Field(default_factory=list)
    description: str | None = None


class Curriculum(BaseModel):
    degree_name: str
    degree_level: Literal["bachillerato", "licenciatura", "maestria", "tecnico", "diplomado"]
    university: str
    is_public: bool
    url: str | None = None
    courses: list[Course] = Field(default_factory=list)
    last_updated: str | None = None


class AcademicLandscape(BaseModel):
    curricula_sampled: list[Curriculum] = Field(description="List of degree programs found")
    all_skills_covered: list[str] = Field(description="Flat deduplicated list of all skills taught")
    research_date: str = Field(description="ISO date string YYYY-MM-DD")
    summary: str = Field(description="Narrative paragraph summarizing academic findings in Spanish")
