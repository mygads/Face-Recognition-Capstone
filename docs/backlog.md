# Backlog — Presensi Face Recognition

Basis: audit 2026-10-21 pada HEAD `4154e4d`. Kolom **Pemilik** diisi saat delegasi.
Status sahih hanya setelah `scripts/check.py` hijau + tes pendamping lolos.

Legenda status: `Belum` · `Dikerjakan` · `Menunggu verifikasi` · `Selesai`

## P0 — Kritis (30 hari)

| # | Tugas | Lokasi | Status | Pemilik |
|---|-------|--------|--------|---------|
| P0-1 | Fail-closed auth AI service: tolak burst `503 auth_misconfigured` bila `device_tokens` kosong tanpa Core API + startup warning + test | `apps/ai-service/src/presensi_ai_service/main.py` (`DeviceAuthenticator.allow_open_auth`) | Selesai (2026-10-21: fail-closed default, open hanya bila `CoreApiGalleryProvider`; 2 tes auth) | |
| P0-2 | Truncation top-2: pipeline re-query limit lebar bila runner-up terpotong; galeri 1 identitas → retry `single_identity_gallery` (fail-closed) + regression test | `libs/recognition-core/.../pipeline.py`, `temporal.py`, `tests/test_pipeline.py`, `tests/test_temporal.py` | Selesai (2026-10-21: guard temporal + re-query pipeline + 2 tes; fixture ai-service 2 kandidat) | |
| P0-3 | Perbaiki `FakePipeline` (kwarg `timing_observer`) + `uv sync` venv (`cryptography`, ruff/mypy) hingga `scripts/check.py` hijau | `apps/edge-agent/tests/test_edge_agent.py`, `apps/edge-agent/.../recognition.py:96-122` | Selesai (2026-10-21: fake terima `**_`; `check.py` hijau — 281 pytest, ruff, mypy 133 file, vue-tsc, 26 Vitest) | |
| P0-4 | Bungkus INSERT attendance dengan savepoint + handler `IntegrityError` idempoten (simpan audit, tolak duplikat bersih) | `apps/api/src/presensi_api/attendance_decision.py` | Selesai (2026-10-21: `begin_nested` + tes race-branch via `Session.flush` mock) | |
| P0-5 | Jalankan kalibrasi threshold lokal (harness `tests/ai-benchmark`) + gate sebelum threshold produksi. `MANUAL HARDWARE TEST REQUIRED` | `tests/ai-benchmark/` | Belum | |

## P1 — Penting (30–60 hari)

| # | Tugas | Lokasi | Status | Pemilik |
|---|-------|--------|--------|---------|
| P1-1 | Tambah test pendamping 4 komit behavior (camera-health, matching perf, edge-match, confidence preview) | `apps/api/tests/test_device_runtime.py`, `CameraPreviewView` | Belum | |
| P1-2 | Keluarkan 401/403 dari retryable edge; 401 picu rotasi, 403 langsung dead-letter | `apps/edge-agent/src/presensi_edge_agent/api.py:93-97` | Selesai (2026-10-21: 401/403 non-retryable + tes parametrized; rotasi/dead-letter ditangani konsumen `ApiCallError`) | |
| P1-3 | Hapus/hentikan secret bootstrap literal → acak per bootstrap atau wajib via env | `apps/api/src/presensi_api/auth/bootstrap_admin.py` | Selesai (2026-10-22: default `1234abcd`, override `PRESENSI_BOOTSTRAP_PASSWORD`) | |
| P1-4 | Sertakan `model_name` di `BurstDecisionResponse` + event payload; guard recognizer diagnostik tak bisa enqueue event | `apps/ai-service/.../main.py:844-862`, `gateway.py:613`, `service.py:730-747` | Belum | |
| P1-5 | Ekspos skor/sinyal quality di respons burst; promosikan operating point YuNet + quality gate ke config terkalibrasi | `apps/ai-service/.../config.py:40-43`, `inference.py:170` | Belum | |
| P1-6 | Konversi error auth/device ke `ApiProblem` berkode; dokumentasikan pengecualian automatic-mode di ADR; tolak roster kosong manual | `routers/auth.py`, `session_lifecycle.py:115-244` | Belum | |
| P1-7 | Revoke-all enrollment: `EnrollmentView` mencabut SEMUA template aktif + label tombol jelas | `apps/web/src/views/EnrollmentView.vue` | Selesai (2026-10-21: loop semua template + hitung di pesan; vue-tsc + Vitest hijau) | |
| P1-8 | Perbarui `docs/final-audit.md` (angka aktual 281 pytest / 26 Vitest + status check.py hijau 2026-10-21) | `docs/final-audit.md` | Belum | |
| P1-9 | Mode pembukaan per guru: field `opening_mode` (`automatic`/`manual`, default `manual`) + migrasi Alembic + worker auto-open hanya untuk guru automatic + UI pengaturan guru ([ADR-003](adr/ADR-003-per-teacher-opening-mode-and-manual-override.md)) | `apps/api/.../models.py`, `session_lifecycle.py`, `runtime_configuration.py`, `apps/web` | Belum | |
| P1-10 | Status `manual_override`: guru bisa buka sesi di luar jendela otomatis; auto-close mencakup `active` + `manual_override`; dasbor bedakan tampilan; audit aktor guru vs system ([ADR-003](adr/ADR-003-per-teacher-opening-mode-and-manual-override.md)) | `apps/api/.../models.py`, `session_lifecycle.py`, `routers/sessions.py`, live dashboard | Belum | |
| P1-11 | Endpoint presensi manual guru: `POST /attendance/sessions/{id}/manual-marks` (`SESSION_OPERATE` + jadwal milik guru; validasi sesi berjalan, roster, duplikat; `source='manual'`, audit) + tombol UI per siswa belum tercatat (keputusan D) | `apps/api/.../routers/attendance.py`, `attendance_decision.py` atau modul baru, `apps/web` sesi detail | Belum | |
| P1-12 | Sisa P1-7 lama: samakan validasi threshold central vs edge + guard NaN; timezone format konsisten; anchor unduhan Firefox-safe | `AiSetupView.vue`, `DashboardView.vue` | Belum | |

## P2 — 90 hari + keputusan manusia

| # | Tugas | Status | Pemilik |
|---|-------|--------|---------|
| P2-1 | Eksekusi `walkthrough-field-test.md` + deployment-benchmark di hardware target (min 5 lintasan/relawan/profil), artefak lokal pseudonim. `MANUAL HARDWARE TEST REQUIRED` | Belum | |
| P2-2 | 1 integration hidup edge→API→AI di Postgres + 1 skenario Playwright vs API nyata; tetapkan `GALLERY_MAX_AGE_SECONDS` produksi | Belum | |
| P2-3 | Stop conditions tersisa (SFace SUDAH disetujui operasional 2026-10-21, catat di `docs/models.md`; kalibrasi threshold tetap wajib): blokir `/docs`/`/metrics` di ingress, retensi biometrik, automatic-opening (lihat ADR-003), endpoint koreksi/manual (lihat P1-11), penandatangan benchmark, larangan cloud SaaS | Belum | |

## Selesai (riwayat)

| Tanggal | Item |
|---------|------|
| 2026-10-21 | Audit menyeluruh 7 dimensi + 8 memori (`memory/`, `MEMORY.md`) |
| 2026-10-22 | Default password bootstrap → `1234abcd` + override env + troubleshooting login README + tes parity README |
| 2026-10-21 | E-fixes selesai + hijau: P0-1 (fail-closed auth), P0-2 (single-identity + re-query), P0-3 (FakePipeline + check.py hijau), P0-4 (savepoint race), P1-2 (401/403 non-retryable), P1-7 revoke-all; ADR-003 + arsitektur A–D diperbarui |
