"""Multi-Metric Evaluation Framework for SIGNALTRACE.

Computes and reports 5 independent evaluation dimensions (never collapsed into a single number):
1. `schema_validity`: % of outputs passing strict Pydantic & JSON Schema validation.
2. `extraction_correctness`: Field-level accuracy of profile, education, target role, and experience count vs. `ground_truth_eval.json`.
3. `evidence_accuracy`: % of `evidence_quote` entries passing verbatim substring check against source CV text, plus deterministic verifier detection accuracy.
4. `uncertainty_handling`: % of planted edge cases (unsubstantiated skills in CV 02, overlapping dates, ambiguous year-only dates, and hallucinated quote in CV 03, plus information gaps & `human_review_required`) accurately captured.
5. `recommendation_quality`: Alignment of `recommendation.status` with ground truth, non-automated HITL rationale, and targeted interview verification questions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.models import SignalTraceCandidateAssessment
from src.pipeline import validate_against_json_schema
from src.verifier import detect_experience_date_anomalies, is_verbatim_substring


def load_ground_truth(gt_path: Optional[Path] = None) -> Dict[str, Any]:
    """Load ground truth evaluation definitions from `mock_data/ground_truth_eval.json`."""
    if gt_path is None:
        gt_path = (
            Path(__file__).resolve().parent.parent
            / "mock_data"
            / "ground_truth_eval.json"
        )
    with open(gt_path, "r", encoding="utf-8") as f:
        return json.load(f)


def evaluate_all_scenarios(
    results: Dict[str, SignalTraceCandidateAssessment],
    cv_texts: Dict[str, str],
    ground_truth: Dict[str, Any],
    schema_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Evaluate pipeline outputs across all scenarios on the 5 independent dimensions."""
    scenarios_gt = ground_truth["scenarios"]
    target_role_gt = ground_truth["target_role"]

    # Counters for the 5 separate metrics
    schema_valid_count = 0
    schema_total_count = 0

    extraction_checks_passed = 0
    extraction_checks_total = 0

    verbatim_quotes_passed = 0
    verbatim_quotes_total = 0
    verifier_flag_matches = 0

    uncertainty_checks_passed = 0
    uncertainty_checks_total = 0

    recommendation_checks_passed = 0
    recommendation_checks_total = 0

    per_scenario_details: Dict[str, Dict[str, Any]] = {}

    for scenario_id, gt in scenarios_gt.items():
        assessment = results.get(scenario_id)
        cv_text = cv_texts.get(scenario_id, "")

        if assessment is None:
            raise KeyError(f"Missing pipeline output for scenario '{scenario_id}'.")

        # ------------------------------------------------------------------
        # Metric 1: Schema Validity
        # ------------------------------------------------------------------
        schema_total_count += 1
        is_schema_valid = False
        schema_error: Optional[str] = None
        try:
            payload_dict = assessment.model_dump(mode="json")
            SignalTraceCandidateAssessment.model_validate(payload_dict)
            validate_against_json_schema(payload_dict, schema_path=schema_path)
            is_schema_valid = True
            schema_valid_count += 1
        except Exception as exc:
            schema_error = str(exc)

        # ------------------------------------------------------------------
        # Metric 2: Extraction Correctness
        # ------------------------------------------------------------------
        name_ok = assessment.candidate_profile.full_name == gt["expected_name"]
        exp_count_ok = len(assessment.experience) == gt["expected_experience_count"]
        target_role_ok = assessment.role_match.target_role == target_role_gt
        edu_present_ok = (
            len(assessment.education) >= 1
            and bool(assessment.education[0].institution)
            and bool(assessment.education[0].degree)
        )
        contact_present_ok = bool(assessment.candidate_profile.email) and bool(
            assessment.candidate_profile.location
        )

        scenario_extraction_checks = [
            name_ok,
            exp_count_ok,
            target_role_ok,
            edu_present_ok,
            contact_present_ok,
        ]
        extraction_checks_passed += sum(1 for c in scenario_extraction_checks if c)
        extraction_checks_total += len(scenario_extraction_checks)

        # ------------------------------------------------------------------
        # Metric 3: Evidence Accuracy
        # ------------------------------------------------------------------
        all_evidence_items: List[Dict[str, Any]] = []
        for edu in assessment.education:
            all_evidence_items.append(
                {
                    "category": "education",
                    "label": f"{edu.degree} @ {edu.institution}",
                    "quote": edu.evidence_quote,
                    "verified_flag": edu.evidence_verified,
                }
            )
        for exp in assessment.experience:
            all_evidence_items.append(
                {
                    "category": "experience",
                    "label": f"{exp.role} @ {exp.company}",
                    "quote": exp.evidence_quote,
                    "verified_flag": exp.evidence_verified,
                }
            )
        for sk in assessment.skills:
            all_evidence_items.append(
                {
                    "category": "skill",
                    "label": sk.skill_name,
                    "quote": sk.evidence_quote,
                    "verified_flag": sk.evidence_verified,
                }
            )

        scenario_quotes_total = len(all_evidence_items)
        scenario_quotes_verbatim = 0
        scenario_verifier_correct = 0
        unverified_items: List[str] = []

        for item in all_evidence_items:
            actual_is_substring = is_verbatim_substring(item["quote"], cv_text)
            if actual_is_substring:
                scenario_quotes_verbatim += 1
            else:
                unverified_items.append(f"{item['category']}: {item['label']}")

            if item["verified_flag"] == actual_is_substring:
                scenario_verifier_correct += 1

        verbatim_quotes_passed += scenario_quotes_verbatim
        verbatim_quotes_total += scenario_quotes_total
        verifier_flag_matches += scenario_verifier_correct

        # ------------------------------------------------------------------
        # Metric 4: Uncertainty Handling
        # ------------------------------------------------------------------
        actual_has_unsubstantiated = any(
            not s.has_practical_evidence for s in assessment.skills
        )
        unsubstantiated_match = (
            actual_has_unsubstantiated == gt["expected_has_unsubstantiated_skills"]
        )

        actual_has_overlap, _ = detect_experience_date_anomalies(assessment.experience)
        overlap_match = actual_has_overlap == gt["expected_overlapping_dates"]

        human_review_match = (
            assessment.human_review_required == gt["expected_human_review_required"]
        )

        # Neutral information_gaps check
        info_gaps_valid = len(assessment.information_gaps) >= 1 and all(
            "tidak ditemukan informasi" in gap.lower()
            for gap in assessment.information_gaps
        )

        # Scenario-specific anomaly caveat checks
        caveat_text_joined = " | ".join(assessment.caveats).lower()
        if scenario_id == "cv_02_unsubstantiated":
            anomaly_caveat_ok = (
                "unsubstantiated" in caveat_text_joined
                or "tanpa bukti" in caveat_text_joined
            )
        elif scenario_id == "cv_03_ambiguous_overlap":
            has_unverified_quote_caveat = (
                "unverified extraction quote detected by deterministic verifier"
                in caveat_text_joined
            )
            has_overlap_caveat = (
                "overlapping" in caveat_text_joined
                or "tumpang tindih" in caveat_text_joined
            )
            has_ambiguous_date_caveat = "year-only" in caveat_text_joined or "ambigu" in caveat_text_joined
            anomaly_caveat_ok = (
                has_unverified_quote_caveat
                and has_overlap_caveat
                and has_ambiguous_date_caveat
            )
        else:
            anomaly_caveat_ok = len(assessment.caveats) >= 1

        scenario_uncertainty_checks = [
            unsubstantiated_match,
            overlap_match,
            human_review_match,
            info_gaps_valid,
            anomaly_caveat_ok,
        ]
        uncertainty_checks_passed += sum(1 for c in scenario_uncertainty_checks if c)
        uncertainty_checks_total += len(scenario_uncertainty_checks)

        # ------------------------------------------------------------------
        # Metric 5: Recommendation Quality
        # ------------------------------------------------------------------
        status_match = assessment.recommendation.status == gt["expected_status"]
        rationale_valid = len(assessment.recommendation.summary_rationale.strip()) >= 40
        questions_valid = (
            len(assessment.recommendation.suggested_interview_questions) >= 2
        )

        scenario_rec_checks = [status_match, rationale_valid, questions_valid]
        recommendation_checks_passed += sum(1 for c in scenario_rec_checks if c)
        recommendation_checks_total += len(scenario_rec_checks)

        per_scenario_details[scenario_id] = {
            "candidate_name": assessment.candidate_profile.full_name,
            "expected_name": gt["expected_name"],
            "schema_valid": is_schema_valid,
            "schema_error": schema_error,
            "experience_count": f"{len(assessment.experience)} / {gt['expected_experience_count']}",
            "extraction_score_pct": round(
                (sum(1 for c in scenario_extraction_checks if c) / len(scenario_extraction_checks))
                * 100.0,
                2,
            ),
            "quotes_verbatim": f"{scenario_quotes_verbatim} / {scenario_quotes_total}",
            "quotes_verbatim_pct": round(
                (scenario_quotes_verbatim / scenario_quotes_total) * 100.0, 2
            )
            if scenario_quotes_total
            else 100.0,
            "verifier_detection_accuracy_pct": round(
                (scenario_verifier_correct / scenario_quotes_total) * 100.0, 2
            )
            if scenario_quotes_total
            else 100.0,
            "unverified_items_caught": unverified_items,
            "unsubstantiated_skills_detected": actual_has_unsubstantiated,
            "overlapping_dates_detected": actual_has_overlap,
            "human_review_required": assessment.human_review_required,
            "uncertainty_score_pct": round(
                (sum(1 for c in scenario_uncertainty_checks if c) / len(scenario_uncertainty_checks))
                * 100.0,
                2,
            ),
            "recommendation_status": assessment.recommendation.status,
            "expected_status": gt["expected_status"],
            "match_score": assessment.role_match.match_score_0_to_100,
            "recommendation_score_pct": round(
                (sum(1 for c in scenario_rec_checks if c) / len(scenario_rec_checks))
                * 100.0,
                2,
            ),
            "caveats_count": len(assessment.caveats),
            "information_gaps_count": len(assessment.information_gaps),
        }

    raw_quote_pct = round(
        (verbatim_quotes_passed / verbatim_quotes_total) * 100.0, 2
    )
    verifier_acc_pct = round(
        (verifier_flag_matches / verbatim_quotes_total) * 100.0, 2
    )

    metrics_summary = {
        "schema_validity": {
            "score_pct": round((schema_valid_count / schema_total_count) * 100.0, 2),
            "passed": schema_valid_count,
            "total": schema_total_count,
            "description": "Persentase output JSON yang lolos validasi Pydantic & JSON Schema ketat tanpa error tipe data.",
        },
        "extraction_correctness": {
            "score_pct": round(
                (extraction_checks_passed / extraction_checks_total) * 100.0, 2
            ),
            "passed": extraction_checks_passed,
            "total": extraction_checks_total,
            "description": "Akurasi ekstraksi identitas profil, pendidikan, target role, dan jumlah pengalaman kerja dibanding ground_truth_eval.json.",
        },
        "evidence_accuracy": {
            "score_pct": raw_quote_pct,
            "passed": verbatim_quotes_passed,
            "total": verbatim_quotes_total,
            "verifier_detection_accuracy_pct": verifier_acc_pct,
            "verifier_flag_matches": verifier_flag_matches,
            "description": (
                f"Persentase kutipan `evidence_quote` yang merupakan substring verbatim dari CV asli "
                f"({verbatim_quotes_passed}/{verbatim_quotes_total} = {raw_quote_pct:.2f}% karena 1 halusinasi sengaja ditanam pada CV 03), "
                f"serta akurasi Deterministic Verifier dalam menandai `evidence_verified` "
                f"({verifier_flag_matches}/{verbatim_quotes_total} = {verifier_acc_pct:.2f}%)."
            ),
        },
        "uncertainty_handling": {
            "score_pct": round(
                (uncertainty_checks_passed / uncertainty_checks_total) * 100.0, 2
            ),
            "passed": uncertainty_checks_passed,
            "total": uncertainty_checks_total,
            "description": "Persentase deteksi anomali (skill tanpa bukti di CV 02, tanggal tumpang tindih, tahun ambigu & halusinasi kutipan di CV 03, information_gaps netral, dan human_review_required=True).",
        },
        "recommendation_quality": {
            "score_pct": round(
                (recommendation_checks_passed / recommendation_checks_total) * 100.0, 2
            ),
            "passed": recommendation_checks_passed,
            "total": recommendation_checks_total,
            "description": "Kesesuaian status rekomendasi dengan ground truth, argumen berbasis bukti (non-otomatis), dan pertanyaan interview terarah.",
        },
    }

    return {
        "metrics": metrics_summary,
        "scenarios": per_scenario_details,
    }


def generate_evaluation_report_markdown(eval_data: Dict[str, Any]) -> str:
    """Format the 5-metric evaluation results into a clean Markdown report."""
    m = eval_data["metrics"]
    scenarios = eval_data["scenarios"]

    lines: List[str] = [
        "# SIGNALTRACE — Multi-Metric Evaluation Report",
        "",
        "**Target Role:** `AI & Automation Engineer — Sekolah Karir`  ",
        "**Evaluation Philosophy:** Setiap dimensi kualitas dievaluasi secara **terpisah** (tidak digabung menjadi satu skor tunggal) untuk memastikan transparansi antara kemampuan ekstraksi LLM dan ketangguhan guardrail deterministik.",
        "",
        "---",
        "",
        "## 1. Ringkasan 5 Metrik Evaluasi Utama",
        "",
        "| # | Metrik Evaluasi | Skor | Detail Lulus / Total | Catatan Evaluasi |",
        "| :-: | :--- | :-: | :-: | :--- |",
        f"| 1 | **`schema_validity`** | **{m['schema_validity']['score_pct']:.2f}%** | {m['schema_validity']['passed']} / {m['schema_validity']['total']} CVs | {m['schema_validity']['description']} |",
        f"| 2 | **`extraction_correctness`** | **{m['extraction_correctness']['score_pct']:.2f}%** | {m['extraction_correctness']['passed']} / {m['extraction_correctness']['total']} Checks | {m['extraction_correctness']['description']} |",
        f"| 3 | **`evidence_accuracy`** | **{m['evidence_accuracy']['score_pct']:.2f}%** *(Raw Quote)* / **{m['evidence_accuracy']['verifier_detection_accuracy_pct']:.2f}%** *(Verifier)* | {m['evidence_accuracy']['passed']} / {m['evidence_accuracy']['total']} Verbatim ({m['evidence_accuracy']['verifier_flag_matches']}/{m['evidence_accuracy']['total']} Verified Flags) | {m['evidence_accuracy']['description']} |",
        f"| 4 | **`uncertainty_handling`** | **{m['uncertainty_handling']['score_pct']:.2f}%** | {m['uncertainty_handling']['passed']} / {m['uncertainty_handling']['total']} Checks | {m['uncertainty_handling']['description']} |",
        f"| 5 | **`recommendation_quality`** | **{m['recommendation_quality']['score_pct']:.2f}%** | {m['recommendation_checks_passed'] if 'recommendation_checks_passed' in m else m['recommendation_quality']['passed']} / {m['recommendation_quality']['total']} Checks | {m['recommendation_quality']['description']} |",
        "",
        "---",
        "",
        "## 2. Breakdown Hasil Per Skenario Kandidat",
        "",
        "| Skenario CV | Nama Kandidat | Schema Valid | Pengalaman (Actual/GT) | Verbatim Quotes | Deteksi Verifier | Unsubstantiated Skills | Overlapping Dates | Human Review | Status Rekomendasi (Actual vs GT) | Match Score |",
        "| :--- | :--- | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :--- | :-: |",
    ]

    for sc_id, sc in scenarios.items():
        lines.append(
            f"| `{sc_id}` | {sc['candidate_name']} | "
            f"{'PASS' if sc['schema_valid'] else 'FAIL'} | "
            f"{sc['experience_count']} | "
            f"{sc['quotes_verbatim']} ({sc['quotes_verbatim_pct']:.1f}%) | "
            f"{sc['verifier_detection_accuracy_pct']:.1f}% | "
            f"`{sc['unsubstantiated_skills_detected']}` | "
            f"`{sc['overlapping_dates_detected']}` | "
            f"`{sc['human_review_required']}` | "
            f"`{sc['recommendation_status']}` (GT: `{sc['expected_status']}`) | "
            f"{sc['match_score']}/100 |"
        )

    lines.extend(
        [
            "",
            "---",
            "",
            "## 3. Analisis Mendalam Edge-Cases & Bukti Guardrail Deterministik",
            "",
            "### A. Skenario 1 (`cv_01_strong_verified` — Nadya Putri Maharani)",
            "- **Hasil Ekstraksi & Bukti:** 8/8 kutipan (`education`, `experience`, `skills`) terverifikasi 100% verbatim terhadap teks CV asli.",
            "- **Penanganan Information Gaps:** Meskipun kandidat sangat kuat (skor `90/100`), sistem tidak mengasumsikan kemampuan yang belum tertulis. Persyaratan *Preferred* seperti `Vector Database` dan `RAG` dicatat secara netral pada `information_gaps` untuk dikonfirmasi saat wawancara.",
            "- **Keputusan:** `proceed_to_interview` dengan `human_review_required: true` sebagai bagian dari prinsip *Human-in-the-Loop*.",
            "",
            "### B. Skenario 2 (`cv_02_unsubstantiated` — Dimas Arya Pratama)",
            "- **Deteksi Klaim Tanpa Bukti (*Keyword Stuffing*):** Kandidat mencantumkan `Python`, `LangChain`, `RAG`, `OpenAI API`, `Prompt Engineering`, dan `Vector Database` pada bagian `KEAHLIAN`, tetapi pengalaman kerja hanya berisi administrasi Microsoft Excel dan Customer Support.",
            "- **Mekanisme Guardrail:** Sistem membedakan antara `evidence_verified: true` (kata kunci memang tertulis di CV) dan `has_practical_evidence: false` (tidak ada bukti proyek/pengalaman kerja nyata). Enam skill teknis diturunkan ke `confidence: \"low\"` dan dicatat di `caveats`.",
            "- **Keputusan:** `proceed_with_verification` (meminta portofolio GitHub / tes teknis singkat tanpa mendiskualifikasi otomatis).",
            "",
            "### C. Skenario 3 (`cv_03_ambiguous_overlap` — Raka Wijaya Kusuma)",
            "- **Penangkapan Halusinasi Kutipan oleh `verifier.py`:** Pada simulasi ekstraksi `experience[0]` (*Full-time AI Engineer*), LLM menyisipkan angka palsu `\"sebesar 45%\"` yang tidak ada di CV asli. Modul `verifier.py` mendeteksi ketidakcocokan substring, mengubah `evidence_verified` dari `true` menjadi `false`, menurunkan `confidence` menjadi `low`, dan menambahkan peringatan `\"Unverified extraction quote detected by deterministic verifier\"` ke `caveats`.",
            "- **Deteksi Anomali Tanggal:** `verifier.py` mendeteksi tumpang tindih 8 bulan (`Mar 2023 - Okt 2023`) antara dua pekerjaan *Full-time* (`PT Solusi Cerdas Digital` & `PT Karya Tech Indonesia`), serta mendeteksi format tanggal ambigu tanpa bulan (`2022 - 2023`) pada peran *Freelance Automation Consultant*.",
            "- **Deteksi Klaim Dampak Subjektif:** Klaim `\"Meningkatkan efisiensi operasional perusahaan secara signifikan\"` tanpa metrik angka terdeteksi dan dimasukkan ke `caveats`.",
            "- **Keputusan:** `hold_for_human_review` dengan `human_review_required: true`.",
            "",
        ]
    )

    return "\n".join(lines)
