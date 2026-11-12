"""Automated unit & integration test suite for SIGNALTRACE."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.evaluator import evaluate_all_scenarios, load_ground_truth
from src.models import (
    CandidateProfile,
    EducationItem,
    ExperienceItem,
    Recommendation,
    RoleMatch,
    SignalTraceCandidateAssessment,
    SkillItem,
)
from src.pipeline import run_candidate_pipeline, validate_against_json_schema
from src.verifier import (
    detect_experience_date_anomalies,
    is_verbatim_substring,
    verify_candidate_assessment,
)

MOCK_DATA_DIR = ROOT_DIR / "mock_data"


def test_verbatim_substring_normalization() -> None:
    """Verify whitespace/case-insensitive substring checker catches hallucinations."""
    cv_text = "Mengembangkan chatbot layanan pelanggan\n   menggunakan Python dan OpenAI API."
    assert is_verbatim_substring(
        "Mengembangkan chatbot layanan pelanggan menggunakan Python dan OpenAI API.",
        cv_text,
    )
    assert not is_verbatim_substring(
        "Mengembangkan chatbot layanan pelanggan menggunakan Python dan meningkat 45%.",
        cv_text,
    )


def test_date_overlap_and_year_only_detection() -> None:
    """Verify overlapping full-time dates and year-only ambiguity are caught."""
    experiences = [
        ExperienceItem(
            role="Full-time AI Engineer",
            company="PT Solusi Cerdas Digital",
            start_date="Mar 2023",
            end_date="Sekarang",
            key_outcomes=[],
            evidence_quote="Full-time AI Engineer",
        ),
        ExperienceItem(
            role="Full-time Backend Developer",
            company="PT Karya Tech Indonesia",
            start_date="Jan 2023",
            end_date="Okt 2023",
            key_outcomes=[],
            evidence_quote="Full-time Backend Developer",
        ),
        ExperienceItem(
            role="Freelance Automation Consultant",
            company="Freelance",
            start_date="2022",
            end_date="2023",
            key_outcomes=[],
            evidence_quote="Freelance Automation Consultant",
        ),
    ]
    has_overlap, anomalies = detect_experience_date_anomalies(experiences)
    assert has_overlap is True
    assert any("year-only" in a for a in anomalies)
    assert any("Overlapping employment dates detected" in a for a in anomalies)


def test_deterministic_verifier_flags_hallucinated_quote() -> None:
    """Verify `verify_candidate_assessment` flips `evidence_verified` to False and confidence to low."""
    source_cv = "NAMA: Test Candidate\nPENDIDIKAN: S1 Informatika, UI (Lulus 2023)"
    assessment = SignalTraceCandidateAssessment(
        candidate_profile=CandidateProfile(
            full_name="Test Candidate",
            email=None,
            location=None,
            current_title=None,
        ),
        education=[
            EducationItem(
                institution="UI",
                degree="S1 Informatika",
                graduation_year="2023",
                evidence_quote="S1 Informatika, UI (Lulus 2023)",
                evidence_verified=False,
                confidence="high",
            )
        ],
        experience=[
            ExperienceItem(
                role="AI Engineer",
                company="PT Test",
                start_date="Jan 2024",
                end_date="Des 2024",
                key_outcomes=["Built hallucinated metric 99%"],
                evidence_quote="This quote does not exist in source_cv",
                evidence_verified=True,
                confidence="high",
            )
        ],
        skills=[
            SkillItem(
                skill_name="Python",
                has_practical_evidence=False,
                evidence_quote="S1 Informatika, UI (Lulus 2023)",
                evidence_verified=False,
                confidence="high",
            )
        ],
        role_match=RoleMatch(
            target_role="AI & Automation Engineer",
            match_score_0_to_100=50,
            matched_requirements=[],
            missing_or_unverified_requirements=[],
        ),
        information_gaps=[],
        recommendation=Recommendation(
            status="hold_for_human_review",
            summary_rationale="Requires human review due to unverified quote.",
            suggested_interview_questions=["Can you clarify your experience?"],
        ),
        caveats=[],
        human_review_required=False,
    )

    verified = verify_candidate_assessment(assessment, source_cv)
    assert verified.education[0].evidence_verified is True
    assert verified.experience[0].evidence_verified is False
    assert verified.experience[0].confidence == "low"
    assert verified.skills[0].confidence == "low"
    assert verified.human_review_required is True
    assert any(
        "Unverified extraction quote detected by deterministic verifier" in c
        for c in verified.caveats
    )


def test_end_to_end_pipeline_and_five_metrics() -> None:
    """Run all 3 mock CV scenarios and verify 100% alignment with ground_truth_eval.json."""
    jd_text = (MOCK_DATA_DIR / "job_description.txt").read_text(encoding="utf-8")
    ground_truth = load_ground_truth(MOCK_DATA_DIR / "ground_truth_eval.json")

    scenario_files = {
        "cv_01_strong_verified": "cv_01_strong_verified.txt",
        "cv_02_unsubstantiated": "cv_02_unsubstantiated.txt",
        "cv_03_ambiguous_overlap": "cv_03_ambiguous_overlap.txt",
    }

    results = {}
    cv_texts = {}
    for sc_id, filename in scenario_files.items():
        cv_text = (MOCK_DATA_DIR / filename).read_text(encoding="utf-8")
        cv_texts[sc_id] = cv_text
        output = run_candidate_pipeline(cv_text, jd_text, mode="mock")
        validate_against_json_schema(output.model_dump(mode="json"))
        results[sc_id] = output

    eval_report = evaluate_all_scenarios(results, cv_texts, ground_truth)
    metrics = eval_report["metrics"]

    assert metrics["schema_validity"]["score_pct"] == 100.0
    assert metrics["extraction_correctness"]["score_pct"] == 100.0
    assert metrics["evidence_accuracy"]["verifier_detection_accuracy_pct"] == 100.0
    assert metrics["uncertainty_handling"]["score_pct"] == 100.0
    assert metrics["recommendation_quality"]["score_pct"] == 100.0
