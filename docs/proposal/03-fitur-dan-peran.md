# 03 — Fitur, Peran, dan Matriks Akses

Sumber: `apps/web/src/router/index.ts` (21 halaman: 26 path `/app/*` guarded + 2 auth + 1 publik `/presensi`; alias lama `/display` redirect ke `/presensi`),
`apps/api/.../api/security/roles.py` (3 role, 18 permission + grant opsional laboran),
`apps/api/.../api/v1/router.py` (18 router, termasuk `public_display`, `kiosks`, `audit`).

## 3.1 Aktor

| Aktor | Login | Tanggung jawab |
|---|---|---|
| ADMIN | Ya | Master data, akun staf, perangkat, AI config, policy EWS, semua laporan, audit |
| TEACHER (guru) | Ya | Jadwal miliknya, buka/tutup sesi miliknya, presensi manual, ajukan koreksi, laporan + EWS kelasnya |
| LABORANT | Ya | Pendaftaran wajah, perangkat + preview kamera di lab yang ditugaskan; TANPA sesi/jadwal/laporan/EWS kecuali diberi hak opsional (ceklist per akun) |
| DEVICE (service account) | Bearer per-device | Discovery gallery, kirim recognition event, heartbeat — tidak bisa baca laporan |
| Siswa | Tidak | Objek presensi; tidak login |

Hak akses (18 permission): `manage_master_data`, `manage_accounts`,
`manage_settings`, `roster_read`, `laboratory_read`, `device_operate`,
`schedule_read`, `schedule_manage`, `session_view`, `session_operate`,
`attendance_manual`, `enrollment_manage`, `attendance_read`,
`attendance_correct`, `reports_read`, `reports_export`, `ews_read`,
`ews_follow_up`.

- TEACHER (13 permission): `roster_read`, `laboratory_read`, `schedule_read`,
  `schedule_manage`, `session_view`, `session_operate`, `attendance_manual`,
  `attendance_read`, `attendance_correct`, `reports_read`, `reports_export`,
  `ews_read`, `ews_follow_up`.
  TANPA `manage_*`, `device_operate`, `enrollment_manage`.
- LABORANT (default, 4 permission): `roster_read`, `laboratory_read`,
  `device_operate`, `enrollment_manage`. TANPA sesi, jadwal, laporan, EWS,
  koreksi, `manage_*` — route memakai `requiredPermissions`; tanpa grant, guard
  router mengarahkan ke `/app/forbidden`, dan backend mengembalikan 403 bila
  endpoint dipanggil langsung.
- LABORANT + hak opsional (grant per akun oleh ADMIN; yang boleh diberikan
  (10, `LABORANT_GRANTABLE_PERMISSIONS`): `schedule_read`, `session_view`,
  `session_operate`, `attendance_manual`, `attendance_read`,
  `attendance_correct`, `reports_read`, `reports_export`, `ews_read`,
  `ews_follow_up`; tersimpan di `user_permission_grants`,
  tampil di `GET /auth/me` → `permissions`, sidebar + guard router dirender
  dari permission; prasyarat ditegakkan `grant_missing_prerequisite`).
  Dengan semua 10 grant ≈ akses guru (sesuai lab yang ditugaskan) +
  perangkat/enrollment; tetap TANPA `manage_*` (tidak bisa membuat staf /
  konfigurasi AI) dan tanpa `schedule_manage`/`device_operate`/
  `enrollment_manage` (tidak dapat didelegasikan).
- Penugasan laboran → lab: `laborant_lab_assignments` (1 laboran → N lab);
  laboran hanya melihat/mengoperasikan lab yang ditugaskan (perangkat, preview,
  pendaftaran wajah).
- ADMIN: semua permission.

## 3.2 Fitur terimplementasi (F-01–F-24) — arsitektur JANGAN diubah

| Kode | Fitur | Halaman / endpoint | Status |
|---|---|---|---|
| F-01 | Auth + bootstrap admin + wajib ganti password | `/auth/login`, `/auth/change-password`; akses 15 mnt (HS256), sesi cookie 24 jam, Argon2 | Jalan |
| F-02 | Master siswa/kelas/lab + import CSV/XLSX | `/app/master-data`; preview + commit; file ≤5 MiB, XLSX ≤25 MiB uncompressed, ≤10.000 baris | Jalan |
| F-03 | Enrollment wajah | `/app/enrollment`; 3–10 capture (@≤3 MB, total ≤15 MB); minimal 3 capture lolos; maks 5 template aktif/siswa; semua capture satu siswa harus memakai model + versi yang sama; peringatan wajah mirip default 0,85; kualitas default: wajah min 80 px, ketajaman 45,0, kecerahan 25–235; revoke per batch | Jalan |
| F-04 | Jadwal praktikum mingguan + anti-bentrok | `/app/schedules`; 409 `schedule_conflict` bila kelas/lab/guru bertabrakan (termasuk rentang tanggal efektif) | Jalan |
| F-05 | Buka/tutup sesi + snapshot roster + opening_mode per guru + manual_override | `/app/sessions`; roster per siswa `GET /sessions/{id}/roster`; worker 10 dtk auto-open/auto-close; tutup hanya → `closed`; baca policy butuh `SESSION_VIEW`, publikasi policy hanya ADMIN (`MANAGE_SETTINGS`); `mode` di policy hanya default administratif — worker memakai `users.opening_mode` tiap guru dan manual-open tidak digate policy | Jalan |
| F-06 | Presensi walk-through otomatis | edge-agent/STB → `POST …/recognition-events` (idempoten via event UUID) | Jalan, threshold menunggu kalibrasi hardware |
| F-07 | Presensi manual + koreksi penuh 2 kasus + putusan ADMIN | SessionsView; manual butuh `SESSION_OPERATE` (siswa roster tanpa record, sesi berjalan). Koreksi butuh `ATTENDANCE_CORRECT`: kasus (a) sudah punya record → `attendance_record_id` + `corrected_status`; kasus (b) tanpa record setelah sesi ditutup → `session_id` + `student_id` (previous = absen turunan). `previous_status` otomatis; `reason` wajib; awal `pending`; daftar + setujui/tolak hanya ADMIN (`POST …/corrections/{id}/decision`); approve kasus (b) membuat `AttendanceRecord(manual)`; jejak previous→corrected, pengaju, pemeriksa, waktu tersimpan | Jalan |
| F-08 | Live dashboard sesi | `/app/dashboard`; snapshot + WebSocket per 2 dtk; panel at-risk | Jalan |
| F-09 | Laporan + ekspor CSV/XLSX + kolom Catatan | `/app/reports`; maks 50.000 baris; anti formula-injection; tanpa skor AI; kolom `Catatan` memuat `note` manual-mark (baris JSON + CSV/XLSX + UI); `GET /api/v1/attendance` tersedia (daftar final records + filter sesi/siswa, hapus 501) | Jalan |
| F-10 | EWS tahap 1: at-risk watchlist + tindak lanjut | Panel "Siswa perlu perhatian" + `GET /reports/attendance/at-risk[/policy]`; reasons `tingkat_absen`/`sering_terlambat`; tindak lanjut manual per siswa (`GET/POST /reports/attendance/at-risk/{student_id}/follow-ups`, tabel `ews_follow_ups` + migrasi); tautan siswa → riwayat laporan (filter NIS) | Jalan, tanpa notifikasi/eskalsi otomatis (by design: tahap 1 = watchlist + catatan) |
| F-11 | Perangkat + heartbeat + kamera | `/app/devices`; daftar perangkat butuh `DEVICE_OPERATE`; daftar/ubah/nonaktif + provision/rotate kredensial hanya ADMIN (`MANAGE_MASTER_DATA`); jeda/aktifkan kamera hanya ADMIN (`MANAGE_SETTINGS`); heartbeat/discovery/galeri/renew memakai kredensial perangkat; health offline/warning/online (timeout 60 dtk); tombol kelola disembunyikan dari LABORANT di UI | Jalan |
| F-12 | AI config + preview pra-sesi | `/app/ai-setup` (ADMIN saja; readiness `GET /admin/system/ai-readiness` butuh `MANAGE_SETTINGS`), `/app/camera-preview` (ADMIN + LABORANT; via komputer lab 127.0.0.1:8765); galeri preview hanya AI_EDGE, hanya saat tidak ada sesi aktif, terbatas jadwal lab hari ini (mulai 15 mnt sebelum kelas); preview tidak mencatat presensi | Jalan |
| F-13 | Akun & role staf | `/app/accounts` (ADMIN saja); email unik; ganti password paksa | Jalan |
| F-14 | Audit log | Tertulis otomatis di setiap perubahan penting; dibaca ADMIN via `/app/audit` + `GET /api/v1/audit/activity` (butuh `MANAGE_SETTINGS`, filter action/entity/actor, redaksi secret/PIN/token/embedding) | Jalan |
| F-15 | Layar kiosk presensi per lab (tanpa login) | `/presensi` fullscreen (kanonis; `/display` alias lama tetap didukung): pilih lab → pilih kamera kiosk → PIN layar → board status. API pairing `/kiosks` + PIN per layar (`POST /kiosks/{id}/pin`, sekali tampil) dan `GET /public/kiosk-display?device_id&pin`; kartu siswa SUDAH MASUK / TERLAMBAT / IZIN / BELUM MASUK; untuk siswa di lab (tanpa identitas login) | Jalan |
| F-16 | Hak opsional laboran (grant per akun) | AccountsView ceklist grant (subset 10 permission) + `GET/PUT /accounts/{id}/permission-grants`; `GET /auth/me` mengembalikan `permissions` gabungan; sidebar + router memakai permission; backend 403 tanpa grant | Jalan |
| F-17 | Penugasan laboran → laboratorium | `laborant_lab_assignments` + `GET/POST/DELETE /accounts/{id}/laborant-assignments`; laboran hanya beroperasi di lab yang ditugaskan | Jalan |
| F-18 | PIN layar per lab | `laboratories.display_pin_hash` + `POST /laboratories/{id}/display-pin` (min 4 karakter, hash); panel PIN di DevicesView; dipakai `/display` | Jalan |
| F-19 | Watermark TERLAMBAT + menit keterlambatan | Roster sesi + laporan: badge TERLAMBAT + `minutes_late` + `recorded_at` ("telat N mnt"); kolom Terlambat di laporan | Jalan |
| F-20 | Pendaftaran wajah (rename + beda makna) | Judul/halaman "Pendaftaran wajah" (bukan "Pendaftaran siswa"): (1) data master siswa = identitas + keanggotaan kelas; (2) pendaftaran wajah = data acuan wajah. Menu + docs dibedakan | Jalan |
| F-21 | Preview kamera multi-perangkat/lab | CameraPreview: dropdown pilih perangkat/lab yang ditugaskan (video tetap loopback PC ini); label kebijakan per lab | Jalan |
| F-22 | Mode pembukaan sesi per guru (caption jelas) | Schedule/Sessions: pilihan global hanya kompatibilitas (caption eksplisit "tidak lagi diberlakukan"); radio guru: "Saya membuka sesi sendiri" / "Sesi saya dibuka otomatis sesuai jadwal"; worker memakai `users.opening_mode`; admin bisa lihat mode tiap guru di daftar jadwal | Jalan |
| F-23 | Kelola akun staf lengkap | AccountsView: status aktif/nonaktif (`is_active`; admin tidak bisa menonaktifkan diri sendiri), reset sandi sementara oleh admin, mode pembukaan per guru, penugasan lab laboran (F-17), ceklist grant (F-16) | Jalan |
| F-24 | Guru: kelas + siswa + koreksi miliknya | Guru hanya melihat kelas/jadwal/siswa yang diassign ke dia; mengajukan koreksi manual miliknya (diputus admin); admin bisa mengoreksi semua | Jalan |

## 3.3 Fitur usulan — EWS tahap 2 (U-01–U-04, dirancang di [09](09-ews.md))

| Kode | Fitur | Keterangan |
|---|---|---|
| U-01 | Ambang EWS ditetapkan sekolah | Policy sudah ada; baru = berita acara kalibrasi |
| U-02 | Riwayat tindak lanjut | ✅ SUDAH menjadi F-10 (tabel `ews_follow_ups` + migrasi + endpoint + UI tindak lanjut di ReportsView) |
| U-03 | Notifikasi internal in-app | Tanpa sanksi otomatis; kanal luar opt-in |
| U-04 | Eskalasi berjenjang | Guru → wali kelas → BK; status workflow, bukan blokir presensi |

## 3.4 Matriks akses (untuk tabel laporan)

| Kemampuan | ADMIN | TEACHER | LABORANT (default 4; + hingga 10 grant) |
|---|---|---|---|
| Ringkasan | ✔ (semua lab/sesi/laporan) | ✔ (jadwal/sesi/kelasnya) | ✔ (dashboard khusus: perangkat + lab-nya) |
| Layar publik `/display` | n/a — tanpa login | n/a | n/a — pilih lab + PIN, fullscreen untuk siswa |
| Data master | ✔ kelola | Baca roster kelasnya | — (roster dibaca via sesi/enrollment di lab-nya) |
| Akun staf | ✔ (+ aktif/nonaktif, reset sandi, grant, penugasan lab) | — | — |
| AI & kamera config | ✔ | — | — |
| Preview kamera | ✔ (+ pilih perangkat/lab) | — | ✔ lab yang ditugaskan (+ pilih perangkat/lab) |
| Perangkat | ✔ kelola penuh + PIN layar | — | ✔ pantau lab-nya; tombol kelola disembunyikan di UI |
| Jadwal | ✔ semua | ✔ miliknya | — default; ✔ bila diberi grant `schedule_*` |
| Sesi presensi | ✔ semua | ✔ miliknya (auto/manual_override) | — default; ✔ operasional bila diberi grant `session_operate` |
| Policy pembukaan sesi | ✔ publikasikan | ✔ baca (radio mode sendiri) | ✔ baca bila punya akses sesi |
| Pendaftaran wajah | ✔ | — | ✔ lab yang ditugaskan |
| Presensi manual | ✔ | ✔ miliknya | ✔ operasional bila diberi grant `session_operate` |
| Koreksi (ajukan → putusan) | ✔ ajukan + putuskan | ✔ ajukan miliknya | — default; ✔ ajukan bila diberi grant `attendance_correct`; putusan tetap ADMIN |
| Laporan + ekspor | ✔ semua (+ kolom Terlambat) | ✔ miliknya | — default; ✔ bila diberi grant `reports_read` |
| EWS watchlist + tindak lanjut | ✔ semua + catat | ✔ kelasnya + catat | — default; ✔ bila diberi grant `ews_read` (catat bila + `ews_follow_up`) |
| Policy ambang EWS | ✔ (`MANAGE_SETTINGS`) | — | — |
| Audit aktivitas | ✔ baca via `/app/audit` + `GET /api/v1/audit/activity` (`MANAGE_SETTINGS`) | aksi tercatat | aksi tercatat |

\*) Sidebar laboran dirender dari permission: setiap kemampuan di atas yang
didapat via grant otomatis muncul di menu + lolos guard router backend
menegakkan permission yang sama (403 tanpa grant). Jadwal (UC5) dan commit
import (UC2) tidak menulis `audit_logs`; selain itu setiap perubahan penting
beraudit.
