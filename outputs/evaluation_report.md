# SIGNALTRACE — Multi-Metric Evaluation Report

**Target Role:** `AI & Automation Engineer — Sekolah Karir`  
**Evaluation Philosophy:** Setiap dimensi kualitas dievaluasi secara **terpisah** (tidak digabung menjadi satu skor tunggal) untuk memastikan transparansi antara kemampuan ekstraksi LLM dan ketangguhan guardrail deterministik.

---

## 1. Ringkasan 5 Metrik Evaluasi Utama

| # | Metrik Evaluasi | Skor | Detail Lulus / Total | Catatan Evaluasi |
| :-: | :--- | :-: | :-: | :--- |
| 1 | **`schema_validity`** | **100.00%** | 3 / 3 CVs | Persentase output JSON yang lolos validasi Pydantic & JSON Schema ketat tanpa error tipe data. |
| 2 | **`extraction_correctness`** | **100.00%** | 15 / 15 Checks | Akurasi ekstraksi identitas profil, pendidikan, target role, dan jumlah pengalaman kerja dibanding ground_truth_eval.json. |
| 3 | **`evidence_accuracy`** | **96.15%** *(Raw Quote)* / **100.00%** *(Verifier)* | 25 / 26 Verbatim (26/26 Verified Flags) | Persentase kutipan `evidence_quote` yang merupakan substring verbatim dari CV asli (25/26 = 96.15% karena 1 halusinasi sengaja ditanam pada CV 03), serta akurasi Deterministic Verifier dalam menandai `evidence_verified` (26/26 = 100.00%). |
| 4 | **`uncertainty_handling`** | **100.00%** | 15 / 15 Checks | Persentase deteksi anomali (skill tanpa bukti di CV 02, tanggal tumpang tindih, tahun ambigu & halusinasi kutipan di CV 03, information_gaps netral, dan human_review_required=True). |
| 5 | **`recommendation_quality`** | **100.00%** | 9 / 9 Checks | Kesesuaian status rekomendasi dengan ground truth, argumen berbasis bukti (non-otomatis), dan pertanyaan interview terarah. |

---

## 2. Breakdown Hasil Per Skenario Kandidat

| Skenario CV | Nama Kandidat | Schema Valid | Pengalaman (Actual/GT) | Verbatim Quotes | Deteksi Verifier | Unsubstantiated Skills | Overlapping Dates | Human Review | Status Rekomendasi (Actual vs GT) | Match Score |
| :--- | :--- | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :--- | :-: |
| `cv_01_strong_verified` | Nadya Putri Maharani | PASS | 2 / 2 | 8 / 8 (100.0%) | 100.0% | `False` | `False` | `True` | `proceed_to_interview` (GT: `proceed_to_interview`) | 90/100 |
| `cv_02_unsubstantiated` | Dimas Arya Pratama | PASS | 2 / 2 | 10 / 10 (100.0%) | 100.0% | `True` | `False` | `True` | `proceed_with_verification` (GT: `proceed_with_verification`) | 28/100 |
| `cv_03_ambiguous_overlap` | Raka Wijaya Kusuma | PASS | 3 / 3 | 7 / 8 (87.5%) | 100.0% | `False` | `True` | `True` | `hold_for_human_review` (GT: `hold_for_human_review`) | 58/100 |

---

## 3. Analisis Mendalam Edge-Cases & Bukti Guardrail Deterministik

### A. Skenario 1 (`cv_01_strong_verified` — Nadya Putri Maharani)
- **Hasil Ekstraksi & Bukti:** 8/8 kutipan (`education`, `experience`, `skills`) terverifikasi 100% verbatim terhadap teks CV asli.
- **Penanganan Information Gaps:** Meskipun kandidat sangat kuat (skor `90/100`), sistem tidak mengasumsikan kemampuan yang belum tertulis. Persyaratan *Preferred* seperti `Vector Database` dan `RAG` dicatat secara netral pada `information_gaps` untuk dikonfirmasi saat wawancara.
- **Keputusan:** `proceed_to_interview` dengan `human_review_required: true` sebagai bagian dari prinsip *Human-in-the-Loop*.

### B. Skenario 2 (`cv_02_unsubstantiated` — Dimas Arya Pratama)
- **Deteksi Klaim Tanpa Bukti (*Keyword Stuffing*):** Kandidat mencantumkan `Python`, `LangChain`, `RAG`, `OpenAI API`, `Prompt Engineering`, dan `Vector Database` pada bagian `KEAHLIAN`, tetapi pengalaman kerja hanya berisi administrasi Microsoft Excel dan Customer Support.
- **Mekanisme Guardrail:** Sistem membedakan antara `evidence_verified: true` (kata kunci memang tertulis di CV) dan `has_practical_evidence: false` (tidak ada bukti proyek/pengalaman kerja nyata). Enam skill teknis diturunkan ke `confidence: "low"` dan dicatat di `caveats`.
- **Keputusan:** `proceed_with_verification` (meminta portofolio GitHub / tes teknis singkat tanpa mendiskualifikasi otomatis).

### C. Skenario 3 (`cv_03_ambiguous_overlap` — Raka Wijaya Kusuma)
- **Penangkapan Halusinasi Kutipan oleh `verifier.py`:** Pada simulasi ekstraksi `experience[0]` (*Full-time AI Engineer*), LLM menyisipkan angka palsu `"sebesar 45%"` yang tidak ada di CV asli. Modul `verifier.py` mendeteksi ketidakcocokan substring, mengubah `evidence_verified` dari `true` menjadi `false`, menurunkan `confidence` menjadi `low`, dan menambahkan peringatan `"Unverified extraction quote detected by deterministic verifier"` ke `caveats`.
- **Deteksi Anomali Tanggal:** `verifier.py` mendeteksi tumpang tindih 8 bulan (`Mar 2023 - Okt 2023`) antara dua pekerjaan *Full-time* (`PT Solusi Cerdas Digital` & `PT Karya Tech Indonesia`), serta mendeteksi format tanggal ambigu tanpa bulan (`2022 - 2023`) pada peran *Freelance Automation Consultant*.
- **Deteksi Klaim Dampak Subjektif:** Klaim `"Meningkatkan efisiensi operasional perusahaan secara signifikan"` tanpa metrik angka terdeteksi dan dimasukkan ke `caveats`.
- **Keputusan:** `hold_for_human_review` dengan `human_review_required: true`.
