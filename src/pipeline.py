"""Main candidate intelligence pipeline for SIGNALTRACE.

Implements the end-to-end architecture flow:
CV Input + Job Description
  -> Text Extraction & Normalization
  -> LLM Structured Extraction (Dual-Mode: Live API or Deterministic Mock LLM)
  -> Pydantic / JSON Schema Validation
  -> Deterministic Evidence Verification (Substring Check & Date/Skill Anomaly Detection)
  -> Competency & Role Mapping, Uncertainty Handling, Recommendation & Human Review Flagging
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Literal, Optional

import jsonschema

from src.models import SignalTraceCandidateAssessment, load_json_schema
from src.verifier import verify_candidate_assessment

ExecutionMode = Literal["mock", "live", "auto"]

DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


def load_system_prompt(prompt_path: Optional[Path] = None) -> str:
    """Load the system prompt from `prompts/extraction_system_prompt.md`."""
    if prompt_path is None:
        prompt_path = (
            Path(__file__).resolve().parent.parent
            / "prompts"
            / "extraction_system_prompt.md"
        )
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read().strip()


def _build_mock_llm_response(cv_text: str, jd_text: str) -> Dict[str, Any]:
    """Deterministic Mock LLM Engine simulating structured JSON extraction for the 3 test scenarios.

    Note:
    - All `evidence_verified` flags emitted by the raw LLM stage are overwritten by `verifier.py`.
    - Scenario 3 (`Raka Wijaya Kusuma`) intentionally includes 1 hallucinated quote on `experience[0]`
      (claiming a fabricated '45%' metric not present in the source CV) to demonstrate how
      `verifier.py` deterministically catches LLM hallucinations and flips `evidence_verified=False`.
    """
    normalized_cv = cv_text.lower()

    # Scenario 1: cv_01_strong_verified.txt (Nadya Putri Maharani)
    if "nadya putri maharani" in normalized_cv:
        return {
            "candidate_profile": {
                "full_name": "Nadya Putri Maharani",
                "email": "nadya.maharani.mock@example.com",
                "location": "Bandung, Indonesia",
                "current_title": "Junior AI & Automation Developer",
            },
            "education": [
                {
                    "institution": "Institut Teknologi Bandung",
                    "degree": "S1 Teknik Informatika",
                    "graduation_year": "2023",
                    "evidence_quote": "S1 Teknik Informatika, Institut Teknologi Bandung (Lulus 2023)",
                    "evidence_verified": False,
                    "confidence": "high",
                }
            ],
            "experience": [
                {
                    "role": "Junior AI & Automation Developer",
                    "company": "PT Edutech Nusantara",
                    "start_date": "Jan 2024",
                    "end_date": "Sekarang",
                    "key_outcomes": [
                        "Mengembangkan pipeline ekstraksi silabus otomatis menggunakan Python dan Gemini API dengan output JSON terstruktur untuk 1.200+ dokumen kursus.",
                        "Membangun sistem validasi otomatis untuk mendeteksi halusinasi ringkasan materi dan menurunkan tingkat error dari 18% menjadi 3%.",
                        "Mengintegrasikan workflow otomasi internal menggunakan Python dan n8n untuk tim kurikulum.",
                    ],
                    "evidence_quote": "Mengembangkan pipeline ekstraksi silabus otomatis menggunakan Python dan Gemini API dengan output JSON terstruktur untuk 1.200+ dokumen kursus.",
                    "evidence_verified": False,
                    "confidence": "high",
                },
                {
                    "role": "Data & Python Intern",
                    "company": "CV Digital Kreasi",
                    "start_date": "Jul 2023",
                    "end_date": "Des 2023",
                    "key_outcomes": [
                        "Membuat skrip Python (pandas) untuk pembersihan data peserta pelatihan dan otomasi laporan mingguan."
                    ],
                    "evidence_quote": "Membuat skrip Python (pandas) untuk pembersihan data peserta pelatihan dan otomasi laporan mingguan.",
                    "evidence_verified": False,
                    "confidence": "high",
                },
            ],
            "skills": [
                {
                    "skill_name": "Python",
                    "has_practical_evidence": True,
                    "evidence_quote": "Mengembangkan pipeline ekstraksi silabus otomatis menggunakan Python dan Gemini API dengan output JSON terstruktur untuk 1.200+ dokumen kursus.",
                    "evidence_verified": False,
                    "confidence": "high",
                },
                {
                    "skill_name": "LLM API Integration (Gemini, OpenAI)",
                    "has_practical_evidence": True,
                    "evidence_quote": "Mengembangkan pipeline ekstraksi silabus otomatis menggunakan Python dan Gemini API dengan output JSON terstruktur untuk 1.200+ dokumen kursus.",
                    "evidence_verified": False,
                    "confidence": "high",
                },
                {
                    "skill_name": "Structured JSON Output",
                    "has_practical_evidence": True,
                    "evidence_quote": "Mengembangkan pipeline ekstraksi silabus otomatis menggunakan Python dan Gemini API dengan output JSON terstruktur untuk 1.200+ dokumen kursus.",
                    "evidence_verified": False,
                    "confidence": "high",
                },
                {
                    "skill_name": "Prompt Evaluation",
                    "has_practical_evidence": True,
                    "evidence_quote": "Membangun sistem validasi otomatis untuk mendeteksi halusinasi ringkasan materi dan menurunkan tingkat error dari 18% menjadi 3%.",
                    "evidence_verified": False,
                    "confidence": "high",
                },
                {
                    "skill_name": "n8n Automation",
                    "has_practical_evidence": True,
                    "evidence_quote": "Mengintegrasikan workflow otomasi internal menggunakan Python dan n8n untuk tim kurikulum.",
                    "evidence_verified": False,
                    "confidence": "high",
                },
            ],
            "role_match": {
                "target_role": "AI & Automation Engineer",
                "match_score_0_to_100": 90,
                "matched_requirements": [
                    {
                        "requirement": "Pengalaman praktis membangun aplikasi/workflow dengan Python (min. 1 tahun)",
                        "supporting_evidence": "Memiliki ~2 tahun pengalaman praktis Python di PT Edutech Nusantara (Jan 2024 - Sekarang) dan CV Digital Kreasi (Jul 2023 - Des 2023).",
                    },
                    {
                        "requirement": "Pengalaman menggunakan LLM APIs (OpenAI, Gemini, atau Anthropic) dan structured JSON extraction",
                        "supporting_evidence": "Mengembangkan pipeline ekstraksi silabus otomatis menggunakan Python dan Gemini API dengan output JSON terstruktur untuk 1.200+ dokumen kursus.",
                    },
                    {
                        "requirement": "Pemahaman tentang evaluasi AI / pengujian kualitas output",
                        "supporting_evidence": "Membangun sistem validasi otomatis untuk mendeteksi halusinasi ringkasan materi dan menurunkan tingkat error dari 18% menjadi 3%.",
                    },
                    {
                        "requirement": "Nilai tambah (Preferred): Pengalaman membangun automation workflow (n8n, Zapier, atau custom scripts)",
                        "supporting_evidence": "Mengintegrasikan workflow otomasi internal menggunakan Python dan n8n untuk tim kurikulum.",
                    },
                ],
                "missing_or_unverified_requirements": [
                    "Pengelolaan database vektor (Vector Database) — Preferred requirement belum disebutkan di CV",
                    "Implementasi spesifik arsitektur RAG (Retrieval-Augmented Generation) belum dirinci pada pengalaman kerja",
                ],
            },
            "information_gaps": [
                "Tidak ditemukan informasi mengenai pengelolaan database vektor (Vector Database) pada CV; perlu dikonfirmasi saat screening.",
                "Tidak ditemukan informasi mengenai pengalaman merancang pipeline RAG (Retrieval-Augmented Generation) pada CV; perlu dikonfirmasi saat screening.",
                "Tidak ditemukan informasi mengenai kesiapan bekerja Hybrid di Jakarta (lokasi kandidat saat ini di Bandung, Indonesia); perlu dikonfirmasi saat screening.",
            ],
            "recommendation": {
                "status": "proceed_to_interview",
                "summary_rationale": (
                    "Kandidat memenuhi seluruh kualifikasi utama (Python >1 tahun, integrasi Gemini API dengan "
                    "structured JSON output pada 1.200+ dokumen, evaluasi anti-halusinasi terukur dari 18% ke 3%, "
                    "serta otomasi n8n di industri Edutech). Direkomendasikan lanjut ke tahap interview teknis "
                    "dengan konfirmasi ringan terkait Vector Database/RAG dan kesiapan kerja Hybrid Jakarta."
                ),
                "suggested_interview_questions": [
                    "Bisa jelaskan desain sistem validasi otomatis yang Anda bangun di PT Edutech Nusantara hingga mampu menurunkan tingkat error halusinasi dari 18% menjadi 3%?",
                    "Pada CV belum disebutkan penggunaan Vector Database atau RAG. Apakah Anda pernah mengimplementasikan retrieval berbasis vector database di luar proyek yang tercantum?",
                    "Bagaimana kesiapan dan preferensi Anda untuk skema kerja Hybrid di Jakarta mengingat domisili saat ini di Bandung?",
                ],
            },
            "caveats": [
                "Terdapat information gap minor pada kriteria nilai tambah (Vector Database & RAG); tetap memerlukan human oversight sebelum keputusan rekrutmen."
            ],
            "human_review_required": True,
        }

    # Scenario 2: cv_02_unsubstantiated.txt (Dimas Arya Pratama)
    if "dimas arya pratama" in normalized_cv:
        return {
            "candidate_profile": {
                "full_name": "Dimas Arya Pratama",
                "email": "dimas.arya.mock@example.com",
                "location": "Surabaya, Indonesia",
                "current_title": "Staf Administrasi Operasional",
            },
            "education": [
                {
                    "institution": "Universitas Airlangga",
                    "degree": "S1 Sistem Informasi",
                    "graduation_year": "2023",
                    "evidence_quote": "S1 Sistem Informasi, Universitas Airlangga (Lulus 2023)",
                    "evidence_verified": False,
                    "confidence": "high",
                }
            ],
            "experience": [
                {
                    "role": "Staf Administrasi Operasional",
                    "company": "PT Maju Bersama Logistik",
                    "start_date": "Feb 2024",
                    "end_date": "Agu 2024",
                    "key_outcomes": [
                        "Mengelola input data pengiriman barang harian menggunakan Microsoft Excel.",
                        "Membantu pembuatan jadwal pengiriman dan koordinasi dokumen surat jalan dengan tim gudang.",
                    ],
                    "evidence_quote": "Mengelola input data pengiriman barang harian menggunakan Microsoft Excel.",
                    "evidence_verified": False,
                    "confidence": "high",
                },
                {
                    "role": "Magang Customer Support",
                    "company": "Toko Online Sejahtera",
                    "start_date": "Agu 2023",
                    "end_date": "Nov 2023",
                    "key_outcomes": [
                        "Menjawab pertanyaan pelanggan melalui platform chat dan mencatat keluhan harian ke spreadsheet."
                    ],
                    "evidence_quote": "Menjawab pertanyaan pelanggan melalui platform chat dan mencatat keluhan harian ke spreadsheet.",
                    "evidence_verified": False,
                    "confidence": "high",
                },
            ],
            "skills": [
                {
                    "skill_name": "Python",
                    "has_practical_evidence": False,
                    "evidence_quote": "Python, LangChain, RAG (Retrieval-Augmented Generation), OpenAI API, Prompt Engineering, Vector Database, Microsoft Excel.",
                    "evidence_verified": False,
                    "confidence": "low",
                },
                {
                    "skill_name": "LangChain",
                    "has_practical_evidence": False,
                    "evidence_quote": "Python, LangChain, RAG (Retrieval-Augmented Generation), OpenAI API, Prompt Engineering, Vector Database, Microsoft Excel.",
                    "evidence_verified": False,
                    "confidence": "low",
                },
                {
                    "skill_name": "RAG (Retrieval-Augmented Generation)",
                    "has_practical_evidence": False,
                    "evidence_quote": "Python, LangChain, RAG (Retrieval-Augmented Generation), OpenAI API, Prompt Engineering, Vector Database, Microsoft Excel.",
                    "evidence_verified": False,
                    "confidence": "low",
                },
                {
                    "skill_name": "OpenAI API",
                    "has_practical_evidence": False,
                    "evidence_quote": "Python, LangChain, RAG (Retrieval-Augmented Generation), OpenAI API, Prompt Engineering, Vector Database, Microsoft Excel.",
                    "evidence_verified": False,
                    "confidence": "low",
                },
                {
                    "skill_name": "Prompt Engineering",
                    "has_practical_evidence": False,
                    "evidence_quote": "Python, LangChain, RAG (Retrieval-Augmented Generation), OpenAI API, Prompt Engineering, Vector Database, Microsoft Excel.",
                    "evidence_verified": False,
                    "confidence": "low",
                },
                {
                    "skill_name": "Vector Database",
                    "has_practical_evidence": False,
                    "evidence_quote": "Python, LangChain, RAG (Retrieval-Augmented Generation), OpenAI API, Prompt Engineering, Vector Database, Microsoft Excel.",
                    "evidence_verified": False,
                    "confidence": "low",
                },
                {
                    "skill_name": "Microsoft Excel",
                    "has_practical_evidence": True,
                    "evidence_quote": "Mengelola input data pengiriman barang harian menggunakan Microsoft Excel.",
                    "evidence_verified": False,
                    "confidence": "high",
                },
            ],
            "role_match": {
                "target_role": "AI & Automation Engineer",
                "match_score_0_to_100": 28,
                "matched_requirements": [
                    {
                        "requirement": "Latar belakang akademik bidang komputasi / sistem informasi",
                        "supporting_evidence": "S1 Sistem Informasi, Universitas Airlangga (Lulus 2023)",
                    }
                ],
                "missing_or_unverified_requirements": [
                    "Pengalaman praktis membangun aplikasi/workflow dengan Python (min. 1 tahun) — Hanya diklaim di daftar skill tanpa bukti proyek/kerja",
                    "Pengalaman menggunakan LLM APIs (OpenAI, Gemini, atau Anthropic) dan structured JSON extraction — Klaim tanpa bukti praktis",
                    "Pemahaman tentang evaluasi AI / pengujian kualitas output — Tidak ditemukan bukti di CV",
                    "Pengalaman membangun automation workflow (n8n, Zapier, atau custom scripts) dan pengelolaan database vektor — Klaim tanpa bukti praktis",
                ],
            },
            "information_gaps": [
                "Tidak ditemukan informasi mengenai proyek portofolio, skripsi, atau repositori kode yang membuktikan penggunaan praktis Python, LangChain, RAG, OpenAI API, dan Vector Database pada CV; perlu dikonfirmasi saat screening.",
                "Tidak ditemukan informasi mengenai pengalaman structured JSON extraction dan evaluasi kualitas output AI pada CV; perlu dikonfirmasi saat screening.",
                "Tidak ditemukan informasi mengenai pengalaman membangun automation workflow (seperti n8n atau Zapier) pada CV; perlu dikonfirmasi saat screening.",
            ],
            "recommendation": {
                "status": "proceed_with_verification",
                "summary_rationale": (
                    "Kandidat mencantumkan banyak keyword AI relevan (Python, LangChain, RAG, OpenAI API, "
                    "Prompt Engineering, Vector Database) pada daftar Keahlian, namun riwayat pengalaman kerja "
                    "hanya mencakup administrasi operasional (Microsoft Excel) dan Customer Support tanpa bukti "
                    "proyek teknis. Sesuai prinsip 'Absence of Evidence != Evidence of Absence', direkomendasikan "
                    "'proceed_with_verification' untuk meminta bukti portofolio/GitHub atau tes teknis awal sebelum "
                    "keputusan wawancara."
                ),
                "suggested_interview_questions": [
                    "Anda mencantumkan Python, LangChain, RAG, OpenAI API, dan Vector Database di daftar keahlian. Bisa tunjukkan proyek pribadi, tugas akhir, atau repositori GitHub tempat Anda menerapkan teknologi tersebut?",
                    "Apakah selama bekerja sebagai Staf Administrasi Operasional atau Magang CS Anda pernah mengotomasi pengolahan spreadsheet menggunakan skrip Python?",
                    "Bagaimana cara Anda memastikan output dari OpenAI API mengikuti skema JSON tertentu dan tidak berhalusinasi?",
                ],
            },
            "caveats": [
                "Unsubstantiated skill claims detected: Python, LangChain, RAG (Retrieval-Augmented Generation), OpenAI API, Prompt Engineering, dan Vector Database hanya tertulis di bagian KEAHLIAN tanpa bukti nyata pada PENGALAMAN KERJA.",
                "Pengalaman kerja praktis di bidang pengembangan Python/AI belum mencapai syarat minimal 1 tahun.",
            ],
            "human_review_required": True,
        }

    # Scenario 3: cv_03_ambiguous_overlap.txt (Raka Wijaya Kusuma)
    if "raka wijaya kusuma" in normalized_cv:
        return {
            "candidate_profile": {
                "full_name": "Raka Wijaya Kusuma",
                "email": "raka.wijaya.mock@example.com",
                "location": "Jakarta, Indonesia",
                "current_title": "Full-time AI Engineer",
            },
            "education": [
                {
                    "institution": "Universitas Indonesia",
                    "degree": "S1 Ilmu Komputer",
                    "graduation_year": "2022",
                    "evidence_quote": "S1 Ilmu Komputer, Universitas Indonesia (Lulus 2022)",
                    "evidence_verified": False,
                    "confidence": "high",
                }
            ],
            "experience": [
                {
                    "role": "Full-time AI Engineer",
                    "company": "PT Solusi Cerdas Digital",
                    "start_date": "Mar 2023",
                    "end_date": "Sekarang",
                    "key_outcomes": [
                        "Mengembangkan chatbot layanan pelanggan menggunakan Python dan OpenAI API.",
                        "Meningkatkan efisiensi operasional perusahaan secara signifikan melalui otomasi AI.",
                    ],
                    # Intentionally slightly hallucinated quote (fabricating 'sebesar 45%')
                    # so deterministic verifier in `src/verifier.py` catches and flags it!
                    "evidence_quote": "Mengembangkan chatbot layanan pelanggan menggunakan Python dan OpenAI API serta meningkatkan efisiensi operasional perusahaan sebesar 45% melalui otomasi AI.",
                    "evidence_verified": True,
                    "confidence": "high",
                },
                {
                    "role": "Full-time Backend Developer",
                    "company": "PT Karya Tech Indonesia",
                    "start_date": "Jan 2023",
                    "end_date": "Okt 2023",
                    "key_outcomes": [
                        "Membangun REST API menggunakan Python FastAPI dan PostgreSQL untuk aplikasi internal."
                    ],
                    "evidence_quote": "Membangun REST API menggunakan Python FastAPI dan PostgreSQL untuk aplikasi internal.",
                    "evidence_verified": False,
                    "confidence": "high",
                },
                {
                    "role": "Freelance Automation Consultant",
                    "company": "Freelance / Self-Employed",
                    "start_date": "2022",
                    "end_date": "2023",
                    "key_outcomes": [
                        "Membantu klien membuat skrip otomasi alur kerja."
                    ],
                    "evidence_quote": "Membantu klien membuat skrip otomasi alur kerja.",
                    "evidence_verified": False,
                    "confidence": "medium",
                },
            ],
            "skills": [
                {
                    "skill_name": "Python",
                    "has_practical_evidence": True,
                    "evidence_quote": "Mengembangkan chatbot layanan pelanggan menggunakan Python dan OpenAI API.",
                    "evidence_verified": False,
                    "confidence": "high",
                },
                {
                    "skill_name": "FastAPI",
                    "has_practical_evidence": True,
                    "evidence_quote": "Membangun REST API menggunakan Python FastAPI dan PostgreSQL untuk aplikasi internal.",
                    "evidence_verified": False,
                    "confidence": "high",
                },
                {
                    "skill_name": "OpenAI API",
                    "has_practical_evidence": True,
                    "evidence_quote": "Mengembangkan chatbot layanan pelanggan menggunakan Python dan OpenAI API.",
                    "evidence_verified": False,
                    "confidence": "high",
                },
                {
                    "skill_name": "PostgreSQL",
                    "has_practical_evidence": True,
                    "evidence_quote": "Membangun REST API menggunakan Python FastAPI dan PostgreSQL untuk aplikasi internal.",
                    "evidence_verified": False,
                    "confidence": "high",
                },
            ],
            "role_match": {
                "target_role": "AI & Automation Engineer",
                "match_score_0_to_100": 58,
                "matched_requirements": [
                    {
                        "requirement": "Pengalaman praktis membangun aplikasi/workflow dengan Python (min. 1 tahun)",
                        "supporting_evidence": "Membangun REST API menggunakan Python FastAPI dan PostgreSQL serta chatbot layanan pelanggan menggunakan Python.",
                    },
                    {
                        "requirement": "Pengalaman menggunakan LLM APIs (OpenAI, Gemini, atau Anthropic)",
                        "supporting_evidence": "Mengembangkan chatbot layanan pelanggan menggunakan Python dan OpenAI API.",
                    },
                ],
                "missing_or_unverified_requirements": [
                    "Structured JSON extraction dari LLM belum disebutkan secara eksplisit di CV",
                    "Pemahaman tentang evaluasi AI / pengujian kualitas output dan guardrails belum disebutkan di CV",
                    "Nilai tambah (Preferred): Pengelolaan database vektor (Vector Database) dan tools workflow (n8n/Zapier) belum terverifikasi",
                ],
            },
            "information_gaps": [
                "Tidak ditemukan informasi mengenai pengalaman structured JSON extraction pada CV; perlu dikonfirmasi saat screening.",
                "Tidak ditemukan informasi mengenai mekanisme evaluasi kualitas output AI dan guardrails/human-in-the-loop pada CV; perlu dikonfirmasi saat screening.",
                "Tidak ditemukan informasi mengenai penggunaan Vector Database atau platform otomasi spesifik (seperti n8n/Zapier) pada CV; perlu dikonfirmasi saat screening.",
            ],
            "recommendation": {
                "status": "hold_for_human_review",
                "summary_rationale": (
                    "Meskipun kandidat memiliki bukti teknis penggunaan Python, FastAPI, dan OpenAI API, "
                    "terdapat anomali krusial yang wajib ditinjau perekrut manusia ('hold_for_human_review'): "
                    "(1) dua pekerjaan Full-time berjalan bersamaan secara tumpang tindih pada periode Mar 2023 - Okt 2023, "
                    "(2) periode kerja Freelance (2022 - 2023) tidak mencantumkan bulan spesifik, "
                    "(3) klaim peningkatan efisiensi operasional bersifat subjektif tanpa metrik terukur, dan "
                    "(4) terdapat kutipan ekstraksi yang gagal verifikasi deterministik."
                ),
                "suggested_interview_questions": [
                    "Pada CV tertulis Anda bekerja Full-time sebagai AI Engineer di PT Solusi Cerdas Digital (Mar 2023 - Sekarang) sekaligus Full-time Backend Developer di PT Karya Tech Indonesia (Jan 2023 - Okt 2023). Bisa klarifikasi status dan pembagian waktu kedua peran penuh waktu tersebut pada rentang Mar 2023 - Okt 2023?",
                    "Untuk peran Freelance Automation Consultant (2022 - 2023), kapan bulan mulai dan berakhirnya secara spesifik, serta tools otomasi apa yang digunakan?",
                    "Terkait klaim 'Meningkatkan efisiensi operasional perusahaan secara signifikan melalui otomasi AI', metrik konkret apa yang diukur (misal waktu respons, jumlah tiket, atau penghematan biaya)?",
                ],
            },
            "caveats": [
                "Terdapat tumpang tindih (overlapping dates) antara dua posisi Full-time: Full-time AI Engineer di PT Solusi Cerdas Digital (Mar 2023 - Sekarang) dan Full-time Backend Developer di PT Karya Tech Indonesia (Jan 2023 - Okt 2023)."
            ],
            "human_review_required": True,
        }

    # Generic fallback parser for any unseen CV in mock mode
    lines = [line.strip() for line in cv_text.splitlines() if line.strip()]
    first_line = lines[0] if lines else "Unknown Candidate"
    name_match = re.search(r"NAMA:\s*(.+)", first_line, flags=re.IGNORECASE)
    full_name = name_match.group(1).strip() if name_match else first_line

    return {
        "candidate_profile": {
            "full_name": full_name,
            "email": None,
            "location": None,
            "current_title": None,
        },
        "education": [],
        "experience": [],
        "skills": [],
        "role_match": {
            "target_role": "AI & Automation Engineer",
            "match_score_0_to_100": 50,
            "matched_requirements": [],
            "missing_or_unverified_requirements": [
                "Membutuhkan verifikasi manual untuk CV kustom pada mode mock"
            ],
        },
        "information_gaps": [
            "Tidak ditemukan informasi lengkap pada mode fallback mock; perlu dikonfirmasi saat screening."
        ],
        "recommendation": {
            "status": "hold_for_human_review",
            "summary_rationale": "Profil diekstrak melalui fallback mode mock dan memerlukan peninjauan langsung oleh rekruter.",
            "suggested_interview_questions": [
                "Bisa ceritakan pengalaman praktis Anda terkait Python dan integrasi LLM API?"
            ],
        },
        "caveats": ["Diekstrak menggunakan generic mock fallback."],
        "human_review_required": True,
    }


def _call_live_llm(cv_text: str, jd_text: str, system_prompt: str) -> Dict[str, Any]:
    """Call Live LLM API (Gemini Interactions API or OpenAI API) in structured JSON mode."""
    schema_dict = load_json_schema()
    # Remove draft-07 meta keys not needed inside interaction response_format schema
    clean_schema = {
        k: v for k, v in schema_dict.items() if k not in ("$schema", "title")
    }

    user_prompt = (
        "Analisis teks CV berikut terhadap Job Description (JD) dan kembalikan "
        "objek JSON yang mematuhi JSON Schema secara ketat.\n\n"
        f"=== JOB DESCRIPTION ===\n{jd_text.strip()}\n\n"
        f"=== CANDIDATE CV ===\n{cv_text.strip()}\n"
    )

    gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")

    if gemini_key:
        from google import genai

        client = genai.Client(api_key=gemini_key)
        interaction = client.interactions.create(
            model=os.environ.get("SIGNALTRACE_GEMINI_MODEL", DEFAULT_GEMINI_MODEL),
            system_instruction=system_prompt,
            input=user_prompt,
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": clean_schema,
            },
        )
        raw_text = interaction.output_text
        if not raw_text:
            raise ValueError("Empty response received from Gemini Interactions API.")
        return json.loads(raw_text)

    if openai_key:
        from openai import OpenAI

        client = OpenAI(api_key=openai_key)
        completion = client.chat.completions.create(
            model=os.environ.get("SIGNALTRACE_OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"{system_prompt}\n\n"
                        f"Output JSON WAJIB mengikuti JSON Schema berikut:\n{json.dumps(clean_schema, ensure_ascii=False)}"
                    ),
                },
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
        )
        content = completion.choices[0].message.content
        if not content:
            raise ValueError("Empty response received from OpenAI API.")
        return json.loads(content)

    raise RuntimeError(
        "No GEMINI_API_KEY, GOOGLE_API_KEY, or OPENAI_API_KEY found in environment."
    )


def validate_against_json_schema(
    payload: Dict[str, Any], schema_path: Optional[Path] = None
) -> None:
    """Validate dictionary payload against `schemas/candidate_schema.json`."""
    schema = load_json_schema(schema_path)
    jsonschema.validate(instance=payload, schema=schema)


def run_candidate_pipeline(
    cv_text: str,
    jd_text: str,
    mode: ExecutionMode = "mock",
    schema_path: Optional[Path] = None,
    prompt_path: Optional[Path] = None,
) -> SignalTraceCandidateAssessment:
    """Execute the full SIGNALTRACE pipeline on a single candidate CV and Job Description.

    Steps:
    1. Extract structured JSON via LLM (live mode or deterministic mock mode).
    2. Validate schema & data types using Pydantic (`SignalTraceCandidateAssessment`).
    3. Run deterministic verifier (`verify_candidate_assessment`) for verbatim substring checking,
       date overlap/ambiguity detection, unsubstantiated skill detection, and human review gating.
    4. Validate final serialized output against `schemas/candidate_schema.json`.
    """
    system_prompt = load_system_prompt(prompt_path)

    effective_mode = mode
    if mode == "auto":
        has_api_key = bool(
            os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
        )
        effective_mode = "live" if has_api_key else "mock"

    if effective_mode == "live":
        try:
            raw_payload = _call_live_llm(cv_text, jd_text, system_prompt)
        except Exception as exc:
            # Graceful fallback to deterministic mock mode if API key is missing or network fails
            print(
                f"[SIGNALTRACE WARNING] Live LLM call unavailable ({exc}). "
                "Falling back to Deterministic Mock LLM Mode."
            )
            raw_payload = _build_mock_llm_response(cv_text, jd_text)
    else:
        raw_payload = _build_mock_llm_response(cv_text, jd_text)

    # Step 2: Pydantic Schema Validation
    assessment = SignalTraceCandidateAssessment.model_validate(raw_payload)

    # Step 3: Deterministic Evidence Verification & Anomaly Detection
    verified_assessment = verify_candidate_assessment(assessment, cv_text)

    # Step 4: Canonical JSON Schema Validation
    final_dict = verified_assessment.model_dump(mode="json")
    validate_against_json_schema(final_dict, schema_path=schema_path)

    return verified_assessment
