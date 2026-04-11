from typing import Literal
from pydantic import BaseModel, Field


class Skill(BaseModel):
    name: str
    category: Literal["technical", "soft", "tool", "language", "certification"]
    frequency_score: float = Field(ge=0.0, le=1.0, description="0-1, how often skill appears across postings")
    example_sources: list[str] = Field(default_factory=list, description="URLs where skill was observed")


class JobPosting(BaseModel):
    title: str
    company: str | None = None
    source_url: str
    required_skills: list[Skill] = Field(default_factory=list)
    preferred_skills: list[Skill] = Field(default_factory=list)
    seniority: Literal["junior", "mid", "senior", "lead", "any"] = "any"
    location: str = "Costa Rica"


class IndustryDemand(BaseModel):
    sector: str
    top_skills: list[Skill] = Field(description="Ranked by frequency_score descending")
    job_postings_sampled: list[JobPosting] = Field(default_factory=list)
    market_sources: list[str] = Field(description="URLs and source names consulted")
    research_date: str = Field(description="ISO date string YYYY-MM-DD")
    summary: str = Field(description="Narrative paragraph summarizing market findings in Spanish")
