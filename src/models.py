"""Pydantic models for SIGNALTRACE candidate extraction and assessment schema.

Conforms strictly to `schemas/candidate_schema.json`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

ConfidenceLevel = Literal["high", "medium", "low"]
RecommendationStatus = Literal[
    "proceed_to_interview",
    "proceed_with_verification",
    "hold_for_human_review",
]


class CandidateProfile(BaseModel):
    """Basic identity and profile metadata extracted from the candidate CV."""

    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(..., min_length=1, description="Candidate full name.")
    email: Optional[str] = Field(default=None, description="Candidate email address.")
    location: Optional[str] = Field(default=None, description="Candidate city/country location.")
    current_title: Optional[str] = Field(
        default=None, description="Current or most recent professional role title."
    )


class EducationItem(BaseModel):
    """Structured education entry with verbatim quote and verification metadata."""

    model_config = ConfigDict(extra="forbid")

    institution: str = Field(..., min_length=1)
    degree: str = Field(..., min_length=1)
    graduation_year: Optional[str] = Field(default=None)
    evidence_quote: Optional[str] = Field(
        default=None,
        description="Exact verbatim substring from the original CV text.",
    )
    evidence_verified: bool = Field(
        default=False,
        description="Populated deterministically by verifier.py, NOT trusted from LLM.",
    )
    confidence: ConfidenceLevel = Field(default="medium")


class ExperienceItem(BaseModel):
    """Structured work/project experience entry with verbatim quote and verification state."""

    model_config = ConfigDict(extra="forbid")

    role: str = Field(..., min_length=1)
    company: str = Field(..., min_length=1)
    start_date: Optional[str] = Field(default=None)
    end_date: Optional[str] = Field(default=None)
    key_outcomes: List[str] = Field(default_factory=list)
    evidence_quote: Optional[str] = Field(
        default=None,
        description="Exact verbatim substring from the original CV text.",
    )
    evidence_verified: bool = Field(
        default=False,
        description="Populated deterministically by verifier.py, NOT trusted from LLM.",
    )
    confidence: ConfidenceLevel = Field(default="medium")


class SkillItem(BaseModel):
    """Structured skill claim distinguishing keyword listing vs. practical project evidence."""

    model_config = ConfigDict(extra="forbid")

    skill_name: str = Field(..., min_length=1)
    has_practical_evidence: bool = Field(
        ...,
        description="True only if substantiated by work experience, projects, or concrete outcomes.",
    )
    evidence_quote: Optional[str] = Field(
        default=None,
        description="Exact verbatim substring from the original CV text.",
    )
    evidence_verified: bool = Field(
        default=False,
        description="Populated deterministically by verifier.py, NOT trusted from LLM.",
    )
    confidence: ConfidenceLevel = Field(default="medium")


class MatchedRequirement(BaseModel):
    """Mapping between a specific Job Description requirement and candidate evidence."""

    model_config = ConfigDict(extra="forbid")

    requirement: str = Field(..., min_length=1)
    supporting_evidence: str = Field(..., min_length=1)


class RoleMatch(BaseModel):
    """Structured evaluation of candidate alignment against target Job Description."""

    model_config = ConfigDict(extra="forbid")

    target_role: str = Field(..., min_length=1)
    match_score_0_to_100: int = Field(..., ge=0, le=100)
    matched_requirements: List[MatchedRequirement] = Field(default_factory=list)
    missing_or_unverified_requirements: List[str] = Field(default_factory=list)


class Recommendation(BaseModel):
    """Decision-support recommendation for human recruiters (non-automated final decision)."""

    model_config = ConfigDict(extra="forbid")

    status: RecommendationStatus
    summary_rationale: str = Field(..., min_length=1)
    suggested_interview_questions: List[str] = Field(default_factory=list)


class SignalTraceCandidateAssessment(BaseModel):
    """Root output schema for SIGNALTRACE candidate intelligence pipeline."""

    model_config = ConfigDict(extra="forbid")

    candidate_profile: CandidateProfile
    education: List[EducationItem] = Field(default_factory=list)
    experience: List[ExperienceItem] = Field(default_factory=list)
    skills: List[SkillItem] = Field(default_factory=list)
    role_match: RoleMatch
    information_gaps: List[str] = Field(
        default_factory=list,
        description=(
            "Requirements from the Job Description not mentioned in the CV. "
            "Follows 'Absence of Evidence != Evidence of Absence'."
        ),
    )
    recommendation: Recommendation
    caveats: List[str] = Field(
        default_factory=list,
        description=(
            "Warnings on uncertainty, unsubstantiated skill claims, overlapping dates, "
            "ambiguous date formats, or failed verbatim quote checks."
        ),
    )
    human_review_required: bool = Field(
        default=True,
        description=(
            "Automatically enforced as True if caveats exist, any evidence_verified is False, "
            "unsubstantiated skills exist, or match score is in the grey zone."
        ),
    )

    @model_validator(mode="after")
    def enforce_human_review_guardrail(self) -> "SignalTraceCandidateAssessment":
        """Ensure human_review_required is automatically True when risk conditions hold."""
        has_unverified_evidence = (
            any(not item.evidence_verified for item in self.education)
            or any(not item.evidence_verified for item in self.experience)
            or any(not item.evidence_verified for item in self.skills)
        )
        has_unsubstantiated_skill = any(
            not item.has_practical_evidence for item in self.skills
        )
        in_grey_score_zone = 40 <= self.role_match.match_score_0_to_100 <= 85

        if (
            self.caveats
            or self.information_gaps
            or has_unverified_evidence
            or has_unsubstantiated_skill
            or in_grey_score_zone
            or self.recommendation.status != "proceed_to_interview"
        ):
            self.human_review_required = True
        return self


def load_json_schema(schema_path: Optional[Path] = None) -> Dict[str, Any]:
    """Load the canonical JSON Schema from `schemas/candidate_schema.json`."""
    if schema_path is None:
        schema_path = Path(__file__).resolve().parent.parent / "schemas" / "candidate_schema.json"
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)
