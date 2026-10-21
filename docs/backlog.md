# Backlog — Presensi Face Recognition

Basis: audit 2026-10-21 pada HEAD `4154e4d` + komit lanjutan `6cea52a`.
Kolom **Pemilik** diisi saat delegasi. Status sahih hanya setelah
`scripts/check.py` hijau + tes pendamping lolos.

Legenda status: `Belum` · `Dikerjakan` · `Menunggu verifikasi` · `Selesai`

## Sisa tugas

| # | Tugas | Lokasi kode | Status | Pemilik |
|---|-------|-------------|--------|---------|
| P0-5 | Jalankan kalibrasi threshold lokal (harness `tests/ai-benchmark`) + gate sebelum threshold produksi. `MANUAL HARDWARE TEST REQUIRED` | `tests/ai-benchmark/` | Belum | |
| P1-1 | Tambah test pendamping 4 komit behavior (camera-health, matching perf, edge-match, confidence preview) | `apps/api/tests/test_device_runtime.py`, `CameraPreviewView` | Belum | |
| P1-4 | Sertakan `model_name` di `BurstDecisionResponse` + event payload; guard recognizer diagnostik tak bisa enqueue event | `apps/ai-service/.../main.py:844-862`, `gateway.py:613`, `service.py:730-747` | Belum | |
| P1-5 | Ekspos skor/sinyal quality di respons burst; promosikan operating point YuNet + quality gate ke config terkalibrasi | `apps/ai-service/.../config.py:40-43`, `inference.py:170` | Belum | |
| P1-6 | Konversi error auth/device ke `ApiProblem` berkode; dokumentasikan pengecualian automatic-mode di ADR; tolak roster kosong manual | `routers/auth.py`, `session_lifecycle.py:115-244` | Belum | |
| P2-1 | Eksekusi `docs/pengujian.md` protokol lapangan + deployment-benchmark di hardware target (min 5 lintasan/relawan/profile), artefak lokal pseudonim. `MANUAL HARDWARE TEST REQUIRED` | `tests/deployment-benchmark/`, hardware lab | Belum | |
| P2-2 | 1 integration hidup edge→API→AI di Postgres + 1 skenario Playwright vs API nyata; tetapkan `GALLERY_MAX_AGE_SECONDS` produksi | `apps/edge-agent`, `apps/api`, `apps/ai-service`, `apps/web/e2e` | Belum | |

## Selesai (riwayat)

| Tanggal | Item |
|---------|------|
| 2026-10-21 | Audit 7 dimensi + 8 memori; 9 area PASS (core reuse, gallery provisioning, auth/RBAC, migrasi, gate, UI Gentelella, akurasi docs, setup README) |
| 2026-10-21 | Defect roster ADMIN-only diperbaiki (direktori global + roster kelas; laborant via enrollment-status) |
| 2026-10-21 | P0-1 fail-closed auth, P0-2 single-identity + re-query, P0-3 FakePipeline + check hijau, P0-4 savepoint race, P1-2 401/403 non-retryable, P1-7 revoke-all |
| 2026-10-21 | P1-9/P1-10 opening_mode per guru + manual_override + migrasi `f4e5d6c7b8a9`; P1-11 manual-marks + audit; P1-12 parity threshold/NaN/timezone/unduhan |
| 2026-10-22 | Bootstrap default `1234abcd` + override env + troubleshooting login + tes parity README |
| 2026-10-21 | Gate: 312 pytest, 32 Vitest, ruff/mypy/vue-tsc/eslint hijau |

Catatan `docs/final-audit.md` (2026-10-02): snapshot 9 area PASS saat itu;
defect roster ADMIN-only di atas sudah diperbaiki. Command verifikasi lama di
file tersebut adalah arsip tanpa klaim berlaku kini — file dihapus saat
konsolidasi docs; gate berjalan dicatat di README.

Catatan grep: `scripts/check.py` tidak menyentuh `.md`, dan tidak ada
referensi `backlog`/`final-audit` dari `scripts/`, skills, `apps/` src,
maupun `tests/` — penghapusan `final-audit.md` aman.
