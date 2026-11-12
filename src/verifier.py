"""Deterministic Evidence & Anomaly Verifier for SIGNALTRACE.

Performs:
1. Whitespace/case-normalized substring verification of `evidence_quote` against original CV text.
2. Automatic downgrade of `evidence_verified = False`, `confidence = "low"`, and caveat injection
   when a quote is missing or hallucinated.
3. Date parsing and overlap/ambiguity detection across `experience` items.
4. Verification of unsubstantiated skill claims (`has_practical_evidence == False`).
5. Deterministic enforcement of `human_review_required`.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from src.models import ExperienceItem, SignalTraceCandidateAssessment

MONTH_MAP: Dict[str, int] = {
    "jan": 1,
    "januari": 1,
    "january": 1,
    "feb": 2,
    "februari": 2,
    "february": 2,
    "mar": 3,
    "maret": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "mei": 5,
    "may": 5,
    "jun": 6,
    "juni": 6,
    "june": 6,
    "jul": 7,
    "juli": 7,
    "july": 7,
    "agu": 8,
    "agustus": 8,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "okt": 10,
    "oktober": 10,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "des": 12,
    "desember": 12,
    "dec": 12,
    "december": 12,
}

PRESENT_TOKENS = {"sekarang", "present", "current", "now", "kini"}
DEFAULT_PRESENT_YM = (2026, 11)

VAGUE_IMPACT_PATTERNS = [
    r"secara signifikan",
    r"sangat signifikan",
    r"secara drastis",
]


def normalize_text(text: Optional[str]) -> str:
    """Collapse all whitespace sequences into a single space and lowercase."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip().lower()


def is_verbatim_substring(quote: Optional[str], source_cv_text: str) -> bool:
    """Return True iff `quote` is a non-empty verbatim substring of `source_cv_text` after normalization."""
    norm_quote = normalize_text(quote)
    norm_cv = normalize_text(source_cv_text)
    if not norm_quote or not norm_cv:
        return False
    return norm_quote in norm_cv


def _append_unique_caveat(caveats: List[str], message: str) -> None:
    """Append a caveat if an identical message is not already present."""
    if message not in caveats:
        caveats.append(message)


def is_year_only_date(date_str: Optional[str]) -> bool:
    """Return True if the date string only specifies a 4-digit year without a month."""
    if not date_str:
        return False
    return bool(re.fullmatch(r"\d{4}", date_str.strip()))


def parse_date_to_ym(
    date_str: Optional[str], is_end: bool = False
) -> Tuple[Optional[int], bool]:
    """Parse a date string into a linear month index (year * 12 + month) and year-only flag.

    Returns:
        (ym_index, is_year_only)
    """
    if not date_str:
        return None, False

    cleaned = date_str.strip().lower()
    if cleaned in PRESENT_TOKENS:
        y, m = DEFAULT_PRESENT_YM
        return y * 12 + m, False

    # Year-only format: e.g. "2022"
    if re.fullmatch(r"\d{4}", cleaned):
        year = int(cleaned)
        month = 12 if is_end else 1
        return year * 12 + month, True

    # Month + Year format: e.g. "Jan 2023", "Okt 2023"
    match = re.match(r"^([a-zA-Z]+)\s+(\d{4})$", cleaned)
    if match:
        month_token, year_token = match.group(1), match.group(2)
        month = MONTH_MAP.get(month_token)
        if month is not None:
            year = int(year_token)
            return year * 12 + month, False

    return None, False


def detect_experience_date_anomalies(
    experiences: List[ExperienceItem],
) -> Tuple[bool, List[str]]:
    """Inspect experience items for overlapping date ranges and ambiguous year-only dates.

    Returns:
        (has_overlap, anomaly_messages)
    """
    anomalies: List[str] = []
    has_overlap = False

    parsed_intervals: List[Tuple[int, ExperienceItem, int, int, bool]] = []

    for idx, exp in enumerate(experiences):
        start_ym, start_year_only = parse_date_to_ym(exp.start_date, is_end=False)
        end_ym, end_year_only = parse_date_to_ym(exp.end_date, is_end=True)

        if start_year_only or end_year_only:
            anomalies.append(
                f"Ambiguous date granularity (year-only without month) on experience "
                f"'{exp.role}' at '{exp.company}' ({exp.start_date} - {exp.end_date})."
            )

        if start_ym is not None and end_ym is not None:
            if start_ym > end_ym:
                anomalies.append(
                    f"Invalid date order (start_date after end_date) on experience "
                    f"'{exp.role}' at '{exp.company}' ({exp.start_date} - {exp.end_date})."
                )
            else:
                parsed_intervals.append(
                    (idx, exp, start_ym, end_ym, start_year_only or end_year_only)
                )

    # Check all pairs for overlapping timelines
    n = len(parsed_intervals)
    for i in range(n):
        _, exp_a, start_a, end_a, year_only_a = parsed_intervals[i]
        for j in range(i + 1, n):
            _, exp_b, start_b, end_b, year_only_b = parsed_intervals[j]
            overlap_start = max(start_a, start_b)
            overlap_end = min(end_a, end_b)

            # Strict overlap across months (or concurrent full-time roles)
            if overlap_start <= overlap_end:
                # Ignore pure boundary touch on year-only freelance unless strict month overlap
                if (year_only_a or year_only_b) and overlap_start == overlap_end:
                    continue
                has_overlap = True
                overlap_months = overlap_end - overlap_start + 1
                anomalies.append(
                    f"Overlapping employment dates detected ({overlap_months} month(s) overlap): "
                    f"'{exp_a.role}' at '{exp_a.company}' ({exp_a.start_date} - {exp_a.end_date}) "
                    f"overlaps with '{exp_b.role}' at '{exp_b.company}' ({exp_b.start_date} - {exp_b.end_date})."
                )

    return has_overlap, anomalies


def detect_vague_outcome_claims(experiences: List[ExperienceItem]) -> List[str]:
    """Detect unquantified / vague impact claims in experience outcomes."""
    warnings: List[str] = []
    for exp in experiences:
        for outcome in exp.key_outcomes:
            has_number = bool(re.search(r"\d", outcome))
            if not has_number:
                for pattern in VAGUE_IMPACT_PATTERNS:
                    if re.search(pattern, outcome, flags=re.IGNORECASE):
                        warnings.append(
                            f"Unquantified impact claim on '{exp.role}' ({exp.company}): "
                            f'"{outcome}" lacks measurable metrics.'
                        )
                        break
    return warnings


def verify_candidate_assessment(
    assessment: SignalTraceCandidateAssessment,
    source_cv_text: str,
) -> SignalTraceCandidateAssessment:
    """Run deterministic verification on a candidate assessment against original CV text.

    Modifies and returns the validated `SignalTraceCandidateAssessment` instance:
    - Verifies `evidence_quote` on all `education`, `experience`, and `skills` entries.
    - Sets `evidence_verified = False`, `confidence = "low"`, and appends the mandatory caveat
      `"Unverified extraction quote detected by deterministic verifier"` whenever a quote fails.
    - Detects unsubstantiated skills (`has_practical_evidence == False`) and logs caveats.
    - Detects overlapping employment dates, year-only ambiguous dates, and vague claims.
    - Enforces `human_review_required`.
    """
    # 1. Verify Education Quotes
    for edu in assessment.education:
        if is_verbatim_substring(edu.evidence_quote, source_cv_text):
            edu.evidence_verified = True
        else:
            edu.evidence_verified = False
            edu.confidence = "low"
            _append_unique_caveat(
                assessment.caveats,
                f"Unverified extraction quote detected by deterministic verifier "
                f"[education: {edu.degree} - {edu.institution}]: "
                f'quote "{edu.evidence_quote}" not found verbatim in CV.',
            )

    # 2. Verify Experience Quotes
    for exp in assessment.experience:
        if is_verbatim_substring(exp.evidence_quote, source_cv_text):
            exp.evidence_verified = True
        else:
            exp.evidence_verified = False
            exp.confidence = "low"
            _append_unique_caveat(
                assessment.caveats,
                f"Unverified extraction quote detected by deterministic verifier "
                f"[experience: {exp.role} at {exp.company}]: "
                f'quote "{exp.evidence_quote}" not found verbatim in CV.',
            )

    # 3. Verify Skill Quotes & Unsubstantiated Skill Claims
    unsubstantiated_skills: List[str] = []
    for skill in assessment.skills:
        if is_verbatim_substring(skill.evidence_quote, source_cv_text):
            skill.evidence_verified = True
        else:
            skill.evidence_verified = False
            skill.confidence = "low"
            _append_unique_caveat(
                assessment.caveats,
                f"Unverified extraction quote detected by deterministic verifier "
                f"[skill: {skill.skill_name}]: "
                f'quote "{skill.evidence_quote}" not found verbatim in CV.',
            )

        if not skill.has_practical_evidence:
            skill.confidence = "low"
            unsubstantiated_skills.append(skill.skill_name)

    if unsubstantiated_skills:
        skills_joined = ", ".join(unsubstantiated_skills)
        has_existing_unsubstantiated_note = any(
            "unsubstantiated" in c.lower() or "tanpa bukti" in c.lower()
            for c in assessment.caveats
        )
        if not has_existing_unsubstantiated_note:
            _append_unique_caveat(
                assessment.caveats,
                f"Unsubstantiated skill claims detected without practical project/work evidence: {skills_joined}.",
            )

    # 4. Verify Experience Dates (Overlaps & Ambiguity)
    _, date_anomalies = detect_experience_date_anomalies(assessment.experience)
    for anomaly in date_anomalies:
        _append_unique_caveat(assessment.caveats, anomaly)

    # 5. Check Vague / Unquantified Impact Claims
    vague_warnings = detect_vague_outcome_claims(assessment.experience)
    for warning in vague_warnings:
        _append_unique_caveat(assessment.caveats, warning)

    # 6. Enforce Human Review Guardrail
    has_unverified = (
        any(not e.evidence_verified for e in assessment.education)
        or any(not e.evidence_verified for e in assessment.experience)
        or any(not s.evidence_verified for s in assessment.skills)
    )
    in_grey_zone = 40 <= assessment.role_match.match_score_0_to_100 <= 85

    if (
        assessment.caveats
        or assessment.information_gaps
        or has_unverified
        or bool(unsubstantiated_skills)
        or in_grey_zone
        or assessment.recommendation.status != "proceed_to_interview"
    ):
        assessment.human_review_required = True

    return assessment
