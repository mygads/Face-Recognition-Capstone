# Jejak Perubahan → Diagram (untuk regenerasi berikutnya)

Diagram di `docs/diagrams/` + proposal (§4–§8) digambar dari arsitektur saat
proposal ditulis. File ini mencatat perubahan perilaku pasca-proposal yang
**belum tercermin di diagram**, supaya regenerasi berikutnya tidak
kehilangan. Diagram dibiarkan apa adanya sampai ada regenerasi resmi
(`docs/diagrams/README.md` — ubah `.puml`/proposal lalu regenerate, jangan
edit hasil generate manual). Klaim angka: gate 469 pytest + 84 vitest.

## Wajib masuk diagram saat regenerasi

| # | Perubahan perilaku | Diagram terdampak |
|---|---|---|
| 1 | Buka sesi 3 lapis anti-race: SELECT-guard → `409 session_already_active` → partial unique index; UI 409 tanpa sesi ganda | `seq-01-session-attendance`, `act-e2e-business` (alur buka sesi), state sesi |
| 2 | Insert `RecognitionEvent` + `AttendanceRecord` masing-masing savepoint; duplikat `event_id` lolos pre-check → re-query pemenang + replay (`409 event_id_reused` bila isi beda), bukan 500 | `seq-01-session-attendance`, state machine keputusan |
| 3 | Gateway tekan duplikat match 120 dtk; retry-once transient 503 (~1 dtk, track id lingkup-burst); stamp duplikat hanya pasca-`enqueue` sukses; stamp gateway hanya burst `matched` | sequence STB→AI→API, `act-e2e-business` |
| 4 | Baris outbox korup dikarantina jadi dead-letter (`event_queue_row_quarantined`); cap dead-letter 5000 + `purge_dead_letter` | deployment-container (edge durability), activity gateway |
| 5 | `_gallery_version` mencakup template revoked (revoke memajukan versi; cegah 304 basi) | `seq-03-pull-probe-preview` |
| 6 | Kolom `attendance_records.note` (manual-mark) → tampil di baris laporan JSON/CSV/XLSX + UI `Catatan` | teks `07-data-dan-class.md` + `schema-erd.sql` SUDAH dimutakhirkan (kolom `note`); gambar `.puml` menunggu regenerasi |
| 7 | `GET ai-readiness` teruskan `central_ai_config_sync_error_code`; decorator pernah menempel helper (422) — guard kontrak OpenAPI↔`schema.d.ts` | deployment-container (health probe), `seq-03-pull-probe-preview` |
| 8 | Validasi startup konsensus temporal: `ceil(max_frames/sample_every) >= minimum_agreeing_frames` (central) dan `ceil(ttl×fps/stride) >= minimum` (edge); kombinasi tak-tercapai ditolak startup | activity/sequence inference, deployment-container |
| 9 | Rate-limit login (10/mnt per-email, 120/mnt per-IP, 429 + `Retry-After`, tanpa audit); `AuthSettings` divalidasi di lifespan (fail-fast) | sequence login, deployment-container |
| 10 | Preview kamera pagu 10 dtk + pesan Indonesia; timeout browser 30 dtk (`apiTimeout`); WS dashboard putus saat tab hidden + polling Devices/AiSetup dilewati (`shouldPausePolling`); `PRESENSI_SESSION_DASHBOARD_POLL_SECONDS` kanonis | `seq-03-pull-probe-preview`, sequence dashboard |
| 11 | DB KAI-scale: `PRESENSI_DB_STATEMENT_TIMEOUT_MS` + `PRESENSI_DB_POOL_DISABLED=1` (NullPool di belakang PgBouncer) | deployment-container |
| 12 | At-risk watchlist panel + policy (`tingkat_absen`/`sering_terlambat`); `GET /api/v1/attendance` (hapus 501) | use case + activity laporan (F-08/F-09/F-10) |
| 13 | EWS tahap 2 (U-01–U-04) masih usulan; ERD sudah memuat `ews_follow_ups` (belum ada tabel/model/migrasi) | ERD + class: tandai "planned", jangan digambar sebagai implemented |

## Sudah tercermin (tidak perlu diubah)

- `recognition_events` ≠ `attendance_records`; idempotensi event UUID; grace 15 mnt; retry frontal vs auto-accept; fail-closed tanpa threshold; AES-256-GCM template; retensi/redaksi event; outbox FIFO + dead-letter 4xx; `manual_override`; `opening_mode` per guru.
- Health probe Core→AI via ai-readiness; sync config 15 dtk + revision; preview loopback `127.0.0.1:8765`.

## Cara pakai

1. Terapkan baris 1–12 ke `.puml`/proposal §4–§8 + `schema-erd.sql` (kolom `note`; `ews_follow_ups` tetap planned).
2. Regenerate via generator di `docs/diagrams/README.md`; verifikasi diff semantik 1-per-1 vs tabel di atas.
3. Setelah regenerasi, pindahkan baris ke "Sudah tercermin" + catat tanggal.

## 2026-11-06 — Shell layout fixed → sticky (screenshot full-page)
- `AppShell`: sidebar/topbar `position: fixed` → sticky-in-flow; visual runtime
  identik (sidebar penuh viewport, topbar menempel), tetapi full-page capture
  kini benar (sebelumnya sidebar kepotong + topbar melayang di tengah halaman).
- Tabel laporan: sel `white-space: nowrap` → normal agar 9 kolom muat 1440px.
- Tidak mengubah alur/fitur di diagram; hanya rendering shell + tabel.
