# 03 — Fitur, Peran, dan Matriks Akses

Sumber: `apps/web/src/router/index.ts` (14 halaman + guard),
`apps/api/.../api/security/roles.py` (3 role, 13 permission),
`apps/api/.../api/v1/router.py` (16 router).

## 3.1 Aktor

| Aktor | Login | Tanggung jawab |
|---|---|---|
| ADMIN | Ya | Master data, akun staf, perangkat, AI config, policy EWS, semua laporan, audit |
| TEACHER (guru) | Ya | Jadwal miliknya, buka/tutup sesi miliknya, presensi manual, ajukan koreksi, laporan + EWS kelasnya |
| LABORANT | Ya | Enrollment wajah, perangkat, preview kamera, buka sesi operasional |
| DEVICE (service account) | Bearer per-device | Discovery gallery, kirim recognition event, heartbeat — tidak bisa baca laporan |
| Siswa | Tidak | Objek presensi; tidak login |

Hak akses (13 permission): `manage_master_data`, `manage_accounts`,
`manage_settings`, `roster_read`, `laboratory_read`, `device_operate`,
`schedule_read`, `schedule_manage`, `session_operate`, `enrollment_manage`,
`attendance_read`, `attendance_correct`, `reports_read`.

- TEACHER: roster/laboratory/schedule read + `schedule_manage` +
  `session_operate` + `attendance_read` + `attendance_correct` + `reports_read`.
  TANPA `enrollment_manage`, `device_operate`, `manage_*`.
- LABORANT: `roster_read`, `laboratory_read`, `device_operate`,
  `session_operate`, `enrollment_manage`, `attendance_read`, `reports_read`.
  TANPA `schedule_manage`, `attendance_correct`, `manage_*`.
- ADMIN: semua permission.

## 3.2 Fitur terimplementasi (F-01–F-14) — arsitektur JANGAN diubah

| Kode | Fitur | Halaman / endpoint | Status |
|---|---|---|---|
| F-01 | Auth + bootstrap admin + wajib ganti password | `/auth/login`, `/auth/change-password`; akses 15 mnt (HS256), sesi cookie 24 jam, Argon2 | Jalan |
| F-02 | Master siswa/kelas/lab + import CSV/XLSX | `/app/master-data`; preview + commit; file ≤5 MiB, XLSX ≤25 MiB uncompressed, ≤10.000 baris | Jalan |
| F-03 | Enrollment wajah | `/app/enrollment`; 3–10 capture (@≤3 MB, total ≤15 MB); minimal 3 capture lolos; maks 5 template aktif/siswa; semua capture satu siswa harus memakai model + versi yang sama; peringatan wajah mirip default 0,85; kualitas default: wajah min 80 px, ketajaman 45,0, kecerahan 25–235; revoke per batch | Jalan |
| F-04 | Jadwal praktikum mingguan + anti-bentrok | `/app/schedules`; 409 `schedule_conflict` bila kelas/lab/guru bertabrakan (termasuk rentang tanggal efektif) | Jalan |
| F-05 | Buka/tutup sesi + snapshot roster + opening_mode per guru + manual_override | `/app/sessions`; roster per siswa `GET /sessions/{id}/roster`; worker 10 dtk auto-open/auto-close; tutup hanya → `closed`; baca policy butuh `SESSION_OPERATE`, publikasi policy hanya ADMIN (`MANAGE_SETTINGS`) | Jalan |
| F-06 | Presensi walk-through otomatis | edge-agent/STB → `POST …/recognition-events` (idempoten via event UUID) | Jalan, threshold menunggu kalibrasi hardware |
| F-07 | Presensi manual + koreksi pending | SessionsView; manual butuh `SESSION_OPERATE`; koreksi butuh `ATTENDANCE_CORRECT`, status **pending saja** (belum ada endpoint putusan) | Jalan |
| F-08 | Live dashboard sesi | `/app/dashboard`; snapshot + WebSocket per 2 dtk; panel at-risk | Jalan |
| F-09 | Laporan + ekspor CSV/XLSX | `/app/reports`; maks 50.000 baris; anti formula-injection; tanpa skor AI. Catatan: `GET /attendance` masih 501, laporan memakai `GET /reports/attendance*` | Jalan |
| F-10 | EWS tahap 1: at-risk watchlist | Panel "Siswa perlu perhatian" + `GET /reports/attendance/at-risk[/policy]`; reasons `tingkat_absen`/`sering_terlambat` | Jalan, tanpa notifikasi (by design) |
| F-11 | Perangkat + heartbeat + kamera | `/app/devices`; daftar perangkat butuh `DEVICE_OPERATE`; daftar/ubah/nonaktif + provision/rotate kredensial hanya ADMIN (`MANAGE_MASTER_DATA`); jeda/aktifkan kamera hanya ADMIN (`MANAGE_SETTINGS`); heartbeat/discovery/galeri/renew memakai kredensial perangkat; health offline/warning/online (timeout 60 dtk); tombol kelola disembunyikan dari LABORANT di UI | Jalan |
| F-12 | AI config + preview pra-sesi | `/app/ai-setup` (ADMIN saja; readiness `GET /admin/system/ai-readiness` butuh `MANAGE_SETTINGS`), `/app/camera-preview` (ADMIN + LABORANT; via komputer lab 127.0.0.1:8765); galeri preview hanya AI_EDGE, hanya saat tidak ada sesi aktif, terbatas jadwal lab hari ini (mulai 15 mnt sebelum kelas); preview tidak mencatat presensi | Jalan |
| F-13 | Akun & role staf | `/app/accounts` (ADMIN saja); email unik; ganti password paksa | Jalan |
| F-14 | Audit log | Tertulis otomatis di setiap perubahan penting; write-only (tanpa endpoint/UI baca — dibaca langsung dari DB) | Jalan |

## 3.3 Fitur usulan — EWS tahap 2 (U-01–U-04, dirancang di [09](09-ews.md))

| Kode | Fitur | Keterangan |
|---|---|---|
| U-01 | Ambang EWS ditetapkan sekolah | Policy sudah ada; baru = berita acara kalibrasi |
| U-02 | Riwayat tindak lanjut | Tabel baru `ews_follow_ups` (perlu migrasi Alembic) |
| U-03 | Notifikasi internal in-app | Tanpa sanksi otomatis; kanal luar opt-in |
| U-04 | Eskalasi berjenjang | Guru → wali kelas → BK; status workflow, bukan blokir presensi |

## 3.4 Matriks akses (untuk tabel laporan)

| Kemampuan | ADMIN | TEACHER | LABORANT |
|---|---|---|---|
| Dashboard ringkasan | ✔ | ✔ (jadwal miliknya) | ✔ |
| Data master | ✔ kelola | Baca roster | Baca roster (via enrollment-status) |
| Akun staf | ✔ | — | — |
| AI & kamera config | ✔ | — | — |
| Preview kamera | ✔ | — | ✔ |
| Perangkat | ✔ kelola penuh | — | ✔ daftar/pantau; tombol kelola disembunyikan di UI |
| Jadwal | ✔ semua | ✔ miliknya | Baca |
| Sesi presensi | ✔ semua | ✔ miliknya (auto/manual_override) | ✔ operasional |
| Policy pembukaan sesi | ✔ publikasikan | ✔ baca | ✔ baca |
| Enrollment wajah | ✔ | — | ✔ |
| Presensi manual | ✔ | ✔ miliknya | ✔ operasional (`SESSION_OPERATE`) |
| Koreksi (ajukan) | ✔ | ✔ | — (perlu `ATTENDANCE_CORRECT`); pengajuan berstatus pending saja, belum ada endpoint putusan |
| Laporan + ekspor | ✔ semua | ✔ miliknya | ✔ via API, tanpa menu UI* |
| EWS watchlist | ✔ semua | ✔ kelasnya | ✔ via API, tanpa menu UI* |
| Policy ambang EWS | ✔ (`MANAGE_SETTINGS`) | — | — |
| Audit log | Tercatat otomatis* | — | — |

\*) Write-only: sistem menulis `audit_logs` di setiap perubahan penting, tetapi
tidak ada endpoint/UI untuk membacanya — dibaca langsung dari database.

\*) Nuansa UI-vs-API (terverifikasi di router): LABORANT memegang permission
`REPORTS_READ` sehingga API mengizinkan, tetapi menu `/app/reports` hanya
untuk ADMIN + TEACHER. Jika laporan menyatakan akses LABORANT, tulis
"via API, tanpa menu UI" agar tidak salah.
