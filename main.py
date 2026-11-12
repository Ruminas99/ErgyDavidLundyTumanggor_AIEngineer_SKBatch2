"""CLI Entry Point for SIGNALTRACE Candidate Intelligence & Evaluation Pipeline.

Usage:
    python main.py                  # Runs in default deterministic mock mode (or auto)
    python main.py --mode mock      # Explicitly run deterministic mock LLM mode
    python main.py --mode live      # Run with live Gemini / OpenAI API (falls back to mock if no key)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict

from src.evaluator import (
    evaluate_all_scenarios,
    generate_evaluation_report_markdown,
    load_ground_truth,
)
from src.models import SignalTraceCandidateAssessment
from src.pipeline import ExecutionMode, run_candidate_pipeline

SCENARIO_FILE_MAP = {
    "cv_01_strong_verified": (
        "cv_01_strong_verified.txt",
        "sample_output_cv01.json",
    ),
    "cv_02_unsubstantiated": (
        "cv_02_unsubstantiated.txt",
        "sample_output_cv02.json",
    ),
    "cv_03_ambiguous_overlap": (
        "cv_03_ambiguous_overlap.txt",
        "sample_output_cv03.json",
    ),
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for SIGNALTRACE runner."""
    parser = argparse.ArgumentParser(
        description="SIGNALTRACE — AI-Powered Candidate Intelligence & Multi-Metric Evaluator"
    )
    parser.add_argument(
        "--mode",
        choices=["mock", "live", "auto"],
        default="mock",
        help="Execution mode: 'mock' (default deterministic mode), 'live' (Gemini/OpenAI API), or 'auto'.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "mock_data",
        help="Directory containing job_description.txt, mock CVs, and ground_truth_eval.json.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "outputs",
        help="Directory to write sample JSON outputs and evaluation_report.md.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the end-to-end SIGNALTRACE pipeline and 5-metric evaluation."""
    args = parse_args(argv)
    mode: ExecutionMode = args.mode
    data_dir: Path = args.data_dir
    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    jd_path = data_dir / "job_description.txt"
    jd_text = jd_path.read_text(encoding="utf-8")

    print("=" * 78)
    print("SIGNALTRACE - AI-Powered Candidate Intelligence & Evidence Verifier")
    print(f"Execution Mode : {mode.upper()}")
    print("Target Role    : AI & Automation Engineer (Sekolah Karir)")
    print("=" * 78)

    results: Dict[str, SignalTraceCandidateAssessment] = {}
    cv_texts: Dict[str, str] = {}

    for scenario_id, (cv_filename, output_filename) in SCENARIO_FILE_MAP.items():
        cv_path = data_dir / cv_filename
        cv_text = cv_path.read_text(encoding="utf-8")
        cv_texts[scenario_id] = cv_text

        assessment = run_candidate_pipeline(
            cv_text=cv_text,
            jd_text=jd_text,
            mode=mode,
        )
        results[scenario_id] = assessment

        output_path = output_dir / output_filename
        output_path.write_text(
            json.dumps(
                assessment.model_dump(mode="json"),
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

        total_quotes = (
            len(assessment.education)
            + len(assessment.experience)
            + len(assessment.skills)
        )
        verified_quotes = (
            sum(1 for e in assessment.education if e.evidence_verified)
            + sum(1 for e in assessment.experience if e.evidence_verified)
            + sum(1 for s in assessment.skills if s.evidence_verified)
        )

        print(f"\n[{scenario_id}] {assessment.candidate_profile.full_name}")
        print(f"  - Match Score           : {assessment.role_match.match_score_0_to_100}/100")
        print(f"  - Verified Quotes       : {verified_quotes}/{total_quotes}")
        print(f"  - Information Gaps      : {len(assessment.information_gaps)}")
        print(f"  - Caveats Flagged       : {len(assessment.caveats)}")
        print(f"  - Human Review Required : {assessment.human_review_required}")
        print(f"  - Recommendation Status : {assessment.recommendation.status}")
        print(f"  - Saved Artifact        : {output_path.relative_to(Path(__file__).resolve().parent)}")

    # Run 5-Metric Evaluation
    ground_truth = load_ground_truth(data_dir / "ground_truth_eval.json")
    eval_data = evaluate_all_scenarios(
        results=results,
        cv_texts=cv_texts,
        ground_truth=ground_truth,
    )

    report_md = generate_evaluation_report_markdown(eval_data)
    report_path = output_dir / "evaluation_report.md"
    report_path.write_text(report_md, encoding="utf-8")

    print("\n" + "=" * 78)
    print("MULTI-METRIC EVALUATION SUMMARY (5 INDEPENDENT DIMENSIONS)")
    print("=" * 78)
    metrics = eval_data["metrics"]
    print(
        f"  1. schema_validity        : {metrics['schema_validity']['score_pct']:6.2f}% "
        f"({metrics['schema_validity']['passed']}/{metrics['schema_validity']['total']} valid schemas)"
    )
    print(
        f"  2. extraction_correctness : {metrics['extraction_correctness']['score_pct']:6.2f}% "
        f"({metrics['extraction_correctness']['passed']}/{metrics['extraction_correctness']['total']} field checks)"
    )
    print(
        f"  3. evidence_accuracy      : {metrics['evidence_accuracy']['score_pct']:6.2f}% raw verbatim quotes "
        f"({metrics['evidence_accuracy']['passed']}/{metrics['evidence_accuracy']['total']}) | "
        f"{metrics['evidence_accuracy']['verifier_detection_accuracy_pct']:6.2f}% verifier detection accuracy"
    )
    print(
        f"  4. uncertainty_handling   : {metrics['uncertainty_handling']['score_pct']:6.2f}% "
        f"({metrics['uncertainty_handling']['passed']}/{metrics['uncertainty_handling']['total']} anomaly & guardrail checks)"
    )
    print(
        f"  5. recommendation_quality : {metrics['recommendation_quality']['score_pct']:6.2f}% "
        f"({metrics['recommendation_quality']['passed']}/{metrics['recommendation_quality']['total']} alignment & HITL checks)"
    )
    print("-" * 78)
    print(f"Evaluation Report saved to  : {report_path.relative_to(Path(__file__).resolve().parent)}")
    print("=" * 78)

    return 0


if __name__ == "__main__":
    sys.exit(main())
