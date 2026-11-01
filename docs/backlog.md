# Backlog — Presensi Face Recognition

Basis: audit 2026-10-21 pada HEAD `4154e4d` + komit lanjutan `6cea52a`.
Kolom **Pemilik** diisi saat delegasi. Status sahih hanya setelah
`scripts/check.py` hijau + tes pendamping lolos.

Legenda status: `Belum` · `Dikerjakan` · `Menunggu verifikasi` · `Selesai`

## Sisa tugas

| # | Tugas | Lokasi kode | Status | Pemilik |
|---|-------|-------------|--------|---------|
| P0-5 | Jalankan kalibrasi threshold lokal (harness `tests/ai-benchmark`) + gate sebelum threshold produksi. `MANUAL HARDWARE TEST REQUIRED` | `tests/ai-benchmark/` | Belum | |
| P2-1 | Eksekusi `docs/pengujian.md` protokol lapangan + deployment-benchmark di hardware target (min 5 lintasan/relawan/profile), artefak lokal pseudonim. `MANUAL HARDWARE TEST REQUIRED` | `tests/deployment-benchmark/`, hardware lab | Belum | |
| P2-2 | 1 integration hidup edge→API→AI di Postgres + 1 skenario Playwright vs API nyata (kontrak in-process + spec live gated sudah ada; run Postgres/Playwright nyata butuh hardware/lab). Keputusan produksi: `GALLERY_MAX_AGE_SECONDS=300` eksplisit di `infra/deployment/*`, `.env.example`, compose. | `apps/edge-agent`, `apps/api`, `apps/ai-service`, `apps/web/e2e` | Dikerjakan | |

## Selesai (riwayat)

| Tanggal | Item |
|---------|------|
| 2026-10-21 | Audit 7 dimensi + 8 memori; 9 area PASS (core reuse, gallery provisioning, auth/RBAC, migrasi, gate, UI Gentelella, akurasi docs, setup README) |
| 2026-10-21 | Defect roster ADMIN-only diperbaiki (direktori global + roster kelas; laborant via enrollment-status) |
| 2026-10-21 | P0-1 fail-closed auth, P0-2 single-identity + re-query, P0-3 FakePipeline + check hijau, P0-4 savepoint race, P1-2 401/403 non-retryable, P1-7 revoke-all |
| 2026-10-21 | P1-9/P1-10 opening_mode per guru + manual_override + migrasi `f4e5d6c7b8a9`; P1-11 manual-marks + audit; P1-12 parity threshold/NaN/timezone/unduhan |
| 2026-10-22 | Sistem peringatan dini kehadiran (at-risk watchlist): GET/PUT `/reports/attendance/at-risk[/policy]`, panel DashboardView "Siswa perlu perhatian" (human watchlist, bukan sanksi, tanpa notifikasi), 21 pytest + 8 vitest; temuan review diperbaiki (stored window_days kini menggerakkan listing, late_count query dibatasi le=30, panel tampil tanpa sesi berjalan, cakupan teacher-filter/pagination/sort) |
| 2026-10-22 | Bootstrap default `1234abcd` + override env + troubleshooting login + tes parity README |
| 2026-10-22 | Gate: 333 pytest, 38 Vitest, ruff/mypy/vue-tsc/eslint/prettier hijau |
| 2026-10-31 | P1-1 test pendamping (camera-health matrix + clamp, matching perf budget, edge-match 1 event, preview disclaimer); P1-4 `model_name` di burst/event payload + guard recognizer diagnostik; P1-5 quality signals + YuNet operating point terkonfigurasi; P1-6 error berkode + tolak roster kosong + ADR-003 automatic-mode |
| 2026-10-31 | P2-2 parsial: kontrak hidup edge→API (`test_p22_edge_api_live_contract.py`) + spec Playwright live gated (`attendance-live-parity.spec.ts`, `PRESENSI_E2E_LIVE=1`); run Postgres/Playwright nyata tetap `MANUAL HARDWARE TEST REQUIRED` |
| 2026-10-31 | Gate: 347 pytest, 41 Vitest, ruff/mypy/vue-tsc/eslint/prettier hijau; mypy 138 file bersih (tambah `types-PyYAML/psutil/openpyxl`); DashboardView hero attendance-rate + severity chips |
| 2026-10-31 | Audit putaran 2: tolak event `occurred_at` masa depan (422 `event_occurred_at_in_future`, toleransi `PRESENSI_EVENT_FUTURE_SKEW_SECONDS=300`; edge dead-letter 4xx, anti jam perangkat ngaco); retention sweep otomatis di worker API (`PRESENSI_RETENTION_SWEEP_HOURS=24`, 0 = nonaktif); visibilitas antrean edge — kolom `pending/dead_letter_events` + migrasi `a1b2c3d4e5f6`, `queue_status` di kedua heartbeat, health `warning` saat dead-letter/backlog (`PRESENSI_DEVICE_QUEUE_WARNING_DEPTH=50`), badge antrean di DashboardView |
| 2026-10-31 | UX SessionsView: ringkasan roster sesi (semua peserta + status) dengan pencarian nama/NIS dan filter status berhitung; regen `schema.d.ts` (sinkron `DeviceQueueStatus` + field YuNet P1-5) |
| 2026-11-01 | Audit putaran 17 (robustness): submit event 200-badan-rusak jadi non-retryable (anti-poison head-of-line) + 1 uji; hapus dead-code persist kredensial; validasi schedule-conflict/LIKE-escape/YuNet-defensif; gate 409 pytest + 64 Vitest |
| 2026-11-01 | Audit putaran 16 (perf/robustness): sweep expiry temporal engine diamortisasi (O(tracks)/frame → 2×/TTL) + bound 4096 track fail-closed + 2 uji; validasi kontrak retry/schedule-conflict/idempotensi sesi/export; gate 408 pytest + 64 Vitest |
| 2026-11-01 | Audit putaran 15 (robustness/perf/UX): retry outbox berjitter anti-thundering-herd + uji; burst gateway abort saat stop + uji; dashboard commit kondisional (poll baca tak lagi buka transaksi tulis) + uji; sanitize tolak NaN + 1 vitest; gate 406 pytest + 64 Vitest |
| 2026-11-01 | Audit putaran 14 (luas: perf/correctness/UX/docs): rate-limiter sweep amortized O(1) + 4 uji; runner track-id bound 1024 + uji; Devices/Reports browser-local (lepas hardcode Jakarta) + uji util; docs arsitektur/deployment sinkron (WS/backoff/margin/preview/rate-limit); gate 403 pytest + 63 Vitest |
| 2026-11-01 | Audit putaran 13 (robustness/UX): dashboard WS hentikan reconnect storm — 4401 redirect login, 4403/4404 error final tanpa retry, backoff eksponensial+jitter anti-thundering-herd + reset per sesi/pesan + 3 vitest; gate 62 Vitest |
| 2026-11-01 | Audit putaran 12 (robustness/correctness/perf/UX): gateway margin clamp [0,2]→[0,1] (bukan drop ke None, lolos CHECK `margin<=1`) + uji; gateway `_sync_worker` outer guard `gateway_sync_cycle_failed` selaras EdgeService (worker tak lagi mati diam) + uji; `EdgeService._refresh_preview_gallery` reuse cache valid (preview tanpa 304 tak lagi full-download tiap poll) + uji; AccountsView hint truncasi 100 akun; log `gateway_session_pinned_mismatch` (pin sesi vs discovery); format `ruff format` 2 file; gate 398 pytest |
| 2026-11-01 | Audit putaran 11 (correctness/perf): pencarian `search` escape LIKE (`%`/`_`/`\\` literal) di 5 query lab/perangkat/jadwal/siswa-kelas + helper `db/search.py` + 2 uji; refresh DevicesView/AiSetupView anti-balapan via `createRefreshEpoch` + 2 vitest |
| 2026-11-01 | Audit putaran 10 (keamanan/UX): open-redirect di guard router (`?redirect=//evil…` lolos `startsWith('/')`) — predikat `isSafeRedirectPath` dipakai guard + LoginView, +3 vitest; kamera enrollment dilepas tepat setelah 4 capture aman (tidak streaming selama konfirmasi manusia) |
| 2026-11-01 | Audit putaran 9 (fungsional/robustness/perf): `GET /api/v1/attendance` diimplementasikan (hapus 501 — daftar final records + filter sesi/siswa + scope guru, ekspektasi auth 501→200, +2 uji); `decode_image` AI service toleran `Content-Type` ber-charset + uji; `openable-schedules` sembunyikan jadwal yang sudah berjalan (hindari 409) + uji; helper `todayLocalISO` dipakai ReportsView+ScheduleView +1 vitest |
| 2026-11-01 | Audit putaran 8 (correctness/perf/UX): import siswa — NIS kosong tidak lagi duplikat + uji; enrollment capture toleran `Content-Type: image/jpeg; charset=...` + uji; util `utils/dateFormat` (cache `Intl.DateTimeFormat`, fallback TZ invalid, dipakai SessionsView+DashboardView) + 3 vitest; DashboardView jam ikut `timezone_name` sesi (bukan hardcode Asia/Jakarta) |
| 2026-11-01 | Audit putaran 7 (robustness/UX): `SecurityHeadersMiddleware` (nosniff/no-referrer/DENY) + uji; `SessionGalleryCache.prune_expired()` tiap burst — tutup bocor memori sesi selesai di AI Central + uji; WS dashboard tahan `RuntimeError` saat tab ditutup antar-snapshot; ringkasan dashboard pecah Izin/Absen/Belum-hadir (`excused`/`absent` di skema+builder+UI 6 kartu responsif, rate tetap hadir tepat+terlambat) + uji builder, regen `schema.d.ts`, sinkron mock e2e; meta router akun |
| 2026-11-01 | Audit putaran 6 (fungsional/robustness): implementasi `GET /api/v1/accounts` (gantikan 501 — admin kini bisa melihat daftar akun; order email + paginasi + tanpa hash, uji `test_accounts.py` 3 kasus, perbaiki ekspektasi kontrak 501→200) + daftar akun di AccountsView (auto-refresh setelah buat akun, regen `schema.d.ts` sekalian menutup drift queue_status/yunet); bound 4096 bucket `DeviceRateLimiter` anti-bocor memori + uji; e2e typecheck hijau |
| 2026-11-01 | Audit putaran 5 (parity/perf/UX): forward `PRESENSI_RETENTION_SWEEP_HOURS`/`PRESENSI_EVENT_FUTURE_SKEW_SECONDS`/`PRESENSI_DEVICE_QUEUE_WARNING_DEPTH` ke compose AI_EDGE + contoh env (.env.example, ai-edge, ai-central) dan `PRESENSI_AI_YUNET_SCORE_THRESHOLD`/`NMS` ke overlay AI Central + guard `tests/test_deployment_env_parity.py` (3 uji); sliding expiry sesi preview loopback (tanpa re-auth tiap 5 mnt) + 1 uji; hoist `Intl.DateTimeFormat` di Dashboard/Devices/Reports; tuning appendix + docs |
| 2026-11-01 | Audit putaran 4 (bug/perf): 401/403 central-AI jadi non-retryable (selaras CoreApiClient); gateway skip burst malformed tanpa reconnect kamera; outbox `due()` cek head tanpa parse payload (FIFO tetap); `detection_max_width` (default 0=off, 640 untuk PC lemah, boxes dipetakan kembali, quality/embed tetap full-res) + env/yaml/tests; import siswa bulk 2 round-trip (maks 10rb baris); `close_expired_sessions` join-schedule (hapus N+1); versi galeri stabil (tidak lagi `now()` per request) + refresh kondisional 304 edge↔API; lampiran tuning di `docs/deployment.md` |
| 2026-11-01 | Audit putaran 3: regen skema client menutup drift YuNet (form kalibrasi AI Central/EDGE kini mengatur `yunet_score_threshold/nms`, helper dipindah ke `utils/recognitionConfig` + 5 vitest); flake batas-tengah-malam suite didokumentasikan di `docs/pengujian.md` (rerun di luar 00:00–00:30 WIB); validasi rantai migrasi linear single-head + uji `alembic upgrade head` di Postgres |

Catatan `docs/final-audit.md` (2026-10-02): snapshot 9 area PASS saat itu;
defect roster ADMIN-only di atas sudah diperbaiki. Command verifikasi lama di
file tersebut adalah arsip tanpa klaim berlaku kini — file dihapus saat
konsolidasi docs; gate berjalan dicatat di README.

Catatan grep: `scripts/check.py` tidak menyentuh `.md`, dan tidak ada
referensi `backlog`/`final-audit` dari `scripts/`, skills, `apps/` src,
maupun `tests/` — penghapusan `final-audit.md` aman.
