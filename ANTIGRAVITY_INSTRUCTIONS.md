# ANTIGRAVITY AGENT MASTER INSTRUCTIONS
**Project:** SIGNALTRACE — AI-Powered Candidate Intelligence (Sekolah Karir Batch 2)

Gunakan file ini sebagai **System Instruction / Master Prompt** saat menjalankan agent di Antigravity IDE untuk membangun, menguji, dan merapikan seluruh artefak submission.

---

## 1. Peran & Tujuan Agent
Kamu adalah **Senior AI Systems Engineer**. Tugasmu adalah membangun prototype end-to-end **SIGNALTRACE** sesuai dengan `PRD.md`, `schemas/candidate_schema.json`, `prompts/extraction_system_prompt.md`, dan dataset di folder `mock_data/`.

Pastikan seluruh kode dapat dijalankan secara lokal maupun menggunakan API LLM (dengan fallback **Deterministic Mock LLM Mode** sehingga reviewer tetap bisa menjalankan kode tanpa perlu API Key berbayar, sesuai aturan brief).

---

## 2. Struktur Direktori Target yang Harus Dibangun
Buat dan lengkapi struktur proyek berikut di workspace Antigravity:

```text
ErgyDavidLundyTumanggor_AIEngineer_SKBatch2/
├── README.md                          # Architecture note, cara jalan, & catatan penggunaan AI
├── PRD.md                             # Product Requirements Document
├── requirements.txt                   # Dependencies (pydantic, openai/google-genai, pytest, dll)
├── schemas/
│   └── candidate_schema.json          # JSON Schema output utama
├── prompts/
│   └── extraction_system_prompt.md    # Prompt sistem untuk LLM extraction & reasoning
├── mock_data/
│   ├── job_description.txt            # JD target: AI & Automation Specialist - Sekolah Karir
│   ├── cv_01_strong_verified.txt      # Skenario 1: Lengkap & terverifikasi
│   ├── cv_02_unsubstantiated.txt      # Skenario 2: Skill tanpa bukti pengalaman
│   ├── cv_03_ambiguous_overlap.txt    # Skenario 3: Tanggal tumpang tindih & ambigu
│   └── ground_truth_eval.json         # Kunci jawaban evaluasi untuk 3 CV
├── src/
│   ├── models.py                      # Pydantic models untuk validasi schema ketat
│   ├── pipeline.py                    # Alur utama: Extract -> Validate -> Verify Evidence -> Match -> Recommend
│   ├── verifier.py                    # Verifikasi kutipan verbatim & deteksi anomali tanggal/gap
│   └── evaluator.py                   # Script evaluasi 5 metrik terpisah
├── outputs/
│   ├── sample_output_cv01.json        # Contoh hasil nyata CV 01
│   ├── sample_output_cv02.json        # Contoh hasil nyata CV 02
│   ├── sample_output_cv03.json        # Contoh hasil nyata CV 03
│   └── evaluation_report.md           # Laporan hasil pengujian 5 metrik
└── main.py                            # Entry point CLI untuk menjalankan seluruh demo & evaluasi
```

---

## 3. Instruksi Eksekusi Bertahap untuk Agent Antigravity

### Tahap 1: Setup Schema & Pydantic Models (`src/models.py`)
- Implementasikan schema sesuai `schemas/candidate_schema.json`.
- Pastikan setiap item pada `skills` dan `experience` memiliki:
  - `evidence_quote` (string kutipan persis dari CV, atau `null` jika tidak ada)
  - `evidence_verified` (boolean, diisi oleh tahap `verifier.py`, BUKAN oleh LLM)
  - `confidence` (`high` | `medium` | `low`)
- Pastikan root object memiliki:
  - `information_gaps` (list hal yang diminta JD tapi tidak ditemukan di CV — ingat prinsip: tidak tertulis != tidak bisa)
  - `caveats` (list peringatan ketidakpastian, klaim tanpa bukti, atau tanggal tumpang tindih)
  - `human_review_required` (boolean, otomatis `True` jika ada `caveats`, `evidence_verified == False`, atau skor kecocokan di area abu-abu)

### Tahap 2: Implementasi Pipeline & Verifier (`src/pipeline.py` & `src/verifier.py`)
- **Dual-Mode LLM Client:**
  - Mode 1 (`--mode live`): Menggunakan API LLM standar (misal Gemini / OpenAI via env variable) dengan `response_format` JSON.
  - Mode 2 (`--mode mock`, default jika tidak ada API key): Menggunakan simulasi respons terstruktur realistis (termasuk menyertakan 1 contoh kutipan yang sedikit meleset/halusinasi pada CV 03 untuk mendemonstrasikan bagaimana `verifier.py` menangkap kesalahan AI!).
- **Deterministic Evidence Verifier (`src/verifier.py`):**
  - Lakukan normalisasi whitespace/lowercase, lalu cek apakah `evidence_quote` benar-benar merupakan substring dari teks CV asli.
  - Jika tidak ditemukan di teks asli, ubah `evidence_verified = False`, turunkan `confidence` menjadi `low`, dan tambahkan catatan ke `caveats`: *"Unverified extraction quote detected by deterministic verifier"*.
  - Tambahkan pengecekan logika tanggal pada `experience` untuk mendeteksi *overlapping dates* secara otomatis.

### Tahap 3: Implementasi Evaluator (`src/evaluator.py`)
Hitung dan tampilkan 5 metrik secara terpisah (bukan 1 skor gabungan):
1. `schema_validity`: % output yang valid terhadap Pydantic model.
2. `extraction_correctness`: Akurasi field profil, pendidikan, dan jumlah pengalaman dibanding `ground_truth_eval.json`.
3. `evidence_accuracy`: % kutipan `evidence_quote` yang lolos verifikasi substring terhadap teks CV asli.
4. `uncertainty_handling`: % anomali yang sengaja ditanam (skill tanpa bukti di CV 02, tanggal tumpang tindih & halusinasi di CV 03) yang berhasil masuk ke `caveats` / `information_gaps` dan memicu `human_review_required = True`.
5. `recommendation_quality`: Validasi bahwa keputusan rekomendasi (`strong_proceed` / `proceed_with_caution` / `hold_for_review`) selaras dengan bukti dan tidak mengambil keputusan final otomatis.

### Tahap 4: Generate Output & Dokumentasi Submission (`README.md`)
- Jalankan `python main.py` untuk menghasilkan seluruh file di folder `outputs/`.
- Tulis `README.md` yang mencakup:
  - **Architecture Note** (Diagram Mermaid + penjelasan keputusan desain).
  - **Cara Menjalankan Prototype**.
  - **Ringkasan Sample Input/Output & Analisis Kegagalan AI (Caveats)**.
  - **Hasil Evaluasi 5 Metrik**.
  - **AI & Tools Usage Disclosure** (Catatan jujur mengenai penggunaan Antigravity IDE dan LLM dalam merancang & menguji sistem, sesuai aturan *Tools & AI Policy* di brief).

---

## 4. Checklist Validasi Sebelum Selesai
- [ ] Tidak ada API key berbayar yang hardcoded atau diwajibkan untuk menjalankan demo.
- [ ] Tidak menggunakan data pribadi nyata (100% data mock).
- [ ] Nama folder/repo siap di-rename menjadi `[NamaLengkap]_AIEngineer_SKBatch2`.
- [ ] Seluruh unit test & `main.py` berjalan tanpa error.
