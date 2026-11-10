# Pemetaan 1:1 — Role, Fitur, Halaman, API, Alur

Dokumen ini hasil audit berulang dari kode (FE+BE), bukan dari rencana.
Sumber: `roles.py`, `scope.py`, `router/index.ts`, `Sidebar.vue`, OpenAPI
(92 paths di `schema.d.ts`), `seed-demo.py`, dan rancangan target §1–§9.
Diagram di `docs/diagrams/` dimutakhirkan audit docs 2026-11-10 (regenerasi
penuh: mermaid + plantuml + bpmn + drawio + xmi); sisa delta ke depan
dicatat di `docs/perubahan-diagram.md`.

Terakhir diaudit: 2026-11-10 malam (sesi 9: sweep UAT 149 PNG u9 — admin 72/guru ±40/laboran ±30/kiosk 3, fix kontras link aktif navy + waktu roster lokal, 4 session-detail diperbaiki via scroll h1, overflow 390 nol di 6 halaman tabel, console jinak (401/403/8765), NEXTCloud menunggu link; sesi 8: audit docs menyeluruh — 03/04/05/07/
08/09/01/02/10 + README proposal + ERD 18→24 tabel + diagram regenerasi;
hapus `uat-guru.log`, `.playwright-cli/`, `_placeholder.py` tak terpakai;
fakultas: 21 halaman/26 path guarded, 18 permission, 18 router, 24 migrasi,
24 tabel, 92 path OpenAPI, gate 491 pytest + 103 vitest).

Sebelumnya 2026-11-10 (sesi 7: G1+G2 beres terverifikasi live — modal konfirmasi
buka sesi (admin: buka→tutup→Riwayat, unmarked 10→absen) + gating aksi sesi/jadwal per izin
(budi operate: Buka/Tutup ada, Manual/Koreksi disembunyikan + catatan izin; cabut operate:
mode pantau, tanpa Buka + catatan izin; jadwal: tanpa +Tambah/Ubah + note baca-saja);
grant operate dicabut/dikembalikan atomik; data UAT dihapus via DB (sesi+jadwal HAPUS,
audit append-only); responsif 390 nol overflow sesi/jadwal; bukti `/tmp/uat/u7-*`).

Sebelumnya 2026-11-08 (sesi 6: verifikasi 1:1 per halaman vs 50 frame Stitch —
siswa/kelas/jadwal/sesi/koreksi+detail-Tiket/laporan/EWS+drawer-tindak-lanjut/
perangkat/preview/ai-setup/akun+buat-akun/audit/profil/enrollment/dashboard
guru+laboran semua 1:1 struktur; temu+perbaikan: drawer siswa +Catatan Data
& Ubah (FE-only), audit tampil nama aktor via map akun (fallback UUID),
`.st-btnlink` nowrap; skala teks 21.6/16/14-15px konsisten; animasi drawer/
modal/drawer+`prefers-reduced-motion` OK; responsif 390/768/1366/2560 nol
overflow (tabel scroll di kartu); bukti `/tmp/uat/u6-*`).

Sebelumnya 2026-11-07 (sesi 5: audit 1:1 Stitch + responsif —
`.st-list__item` wrap (roster/koreksi tak lagi terpotong di 390px), tombol
aksi penuh di mobile; verifikasi 390/768/1366/2560 tanpa overflow halaman;
koreksi/EWS/kiosks/policy/display/forbidden 1:1 struktur frame Stitch;
RBAC ulang dewi (1 kelas, cross-class 403) + budi (koreksi/akun 403,
sidebar sesuai grant); bukti `/tmp/uat/uat5-*`).
Cakupan: 3 role staf + identitas teknis, 18 permission, 26 path guarded +
kiosk publik `/presensi` (alias `/display`), 92 path OpenAPI. Gate: pytest 491 passed, vitest 103 passed,
`vue-tsc` bersih, eslint bersih, prettier bersih. Gate sesi 6: pytest 291, vitest 101.
Gate sesi 7: backend 293 passed (8 grup, ruff+mypy bersih setelah rapikan E501 uji),
frontend vitest 103 passed (29 berkas) + Sessions/Schedule 11 passed pasca-prettier,
`vue-tsc` bersih, eslint bersih, prettier bersih. Detail perubahan di
`docs/perubahan-diagram.md` baris 55–60.

## 1. Pengguna dan role (3 role staf + identitas teknis, seed `scripts/seed-demo.py`)

| Akun                                                       | Role                                                                           | Cakupan seed                            | Mode / catatan                          |
| ---------------------------------------------------------- | ------------------------------------------------------------------------------ | --------------------------------------- | --------------------------------------- |
| `admin@local.test`                                         | ADMIN (semua 18 permission)                                                    | sekolah                                 | proteksi admin terakhir + diri sendiri  |
| `dewi.guru@sekolah.test`                                   | TEACHER (13 permission)                                                        | kelas XII-RPL-1 (Lab Komputer 1)        | `opening_mode=automatic`                |
| `agus.guru@sekolah.test`                                   | TEACHER (13 permission)                                                        | kelas XII-TKJ-1 (Lab Fisika)            | `opening_mode=manual`                   |
| `budi.laboran@sekolah.test`                                | LABORANT (4 bawaan + grant `schedule_read`, `session_view`, `session_operate`, `reports_read`) | LAB-RPL1, LAB-FIS | 2 lab + 4 grant |
| `nolab@sekolah.test` (dibuat saat UAT, lalu dinonaktifkan) | LABORANT (4 bawaan, 0 lab, 0 grant)                                            | —                                       | pesan ramah "Belum ada penugasan…"      |
| Perangkat edge/STB                                         | identitas teknis (device token, bukan role staf)                               | per lab                                 | kredensial sekali tampil, rotasi        |
| Layar kiosk                                                | sesi kiosk (PIN, bukan login staf)                                             | 1 lab + 1 device                        | PIN sekali tampil, revoke menutup layar |
| Siswa/tamu                                                 | tanpa login                                                                    | layar `/presensi` yang sudah diaktivasi | hanya status + hasil tersaring          |

Penugasan guru→kelas berperiode (`teacher_class_assignments`: `starts_on`,
`ends_on`, `is_substitute`; pengganti/substitute didukung). Penugasan
laboran→lab (`laborant_lab_assignments`, N lab per laboran; 0 lab = empty
state ramah). Relasi kelas↔lab untuk enrollment (`class_laboratories`).
Semua dikelola admin via `/api/v1/accounts/...` dalam satu transaksi
(penugasan + grant disimpan atomik; UI pratinjau menu sebelum simpan).

## 2. Permission (18) dan dependensi grant

`LABORANT_GRANTABLE_PERMISSIONS` (10 — master/akun/setting/device/enrollment
tidak dapat didelegasikan): `schedule_read`, `session_view`,
`session_operate`, `attendance_manual`, `attendance_read`,
`attendance_correct`, `reports_read`, `reports_export`, `ews_read`,
`ews_follow_up`. Prasyarat (`PERMISSION_PREREQUISITES`, ditegakkan
`grant_missing_prerequisite`):
`session_operate`/`attendance_manual` butuh `session_view`;
`attendance_correct` butuh `session_view` atau `reports_read`;
`reports_export` butuh `reports_read`; `ews_follow_up` butuh `ews_read`.

TEACHER bawaan (13, tanpa `manage_*`, `device_operate`,
`enrollment_manage`): `roster_read`, `laboratory_read`, `schedule_read`,
`schedule_manage`, `session_view`, `session_operate`, `attendance_manual`,
`attendance_read`, `attendance_correct`, `reports_read`, `reports_export`,
`ews_read`, `ews_follow_up`.
LABORANT bawaan (4): `roster_read`, `laboratory_read`, `device_operate`,
`enrollment_manage`.

### 2a. Matriks kemampuan vs spec §2 (terverifikasi di `roles.py` + `scope.py` + guard)

| Kemampuan                              | Admin             | Guru                                  | Laboran dasar                          | Izin tambahan laboran                                   |
| -------------------------------------- | ----------------- | ------------------------------------- | -------------------------------------- | ------------------------------------------------------- |
| Dashboard                              | seluruh sekolah   | kelas sendiri                         | infra lab sendiri                      | kartu akademik sesuai izin                              |
| Data master siswa/kelas/lab            | kelola            | baca via Kelas Saya                   | daftar minimum untuk enrollment lab    | — (tidak didelegasikan)                                 |
| Pendaftaran wajah                      | kelola            | —                                     | ambil ulang/daftar/cabut dalam lingkup | —                                                       |
| Status perangkat + preview staf        | semua lab         | ringkas sesi sendiri                  | lab penugasan                          | —                                                       |
| Registrasi device/kredensial/konfig AI | kelola            | —                                     | —                                      | tidak dapat didelegasikan                               |
| Jadwal                                 | semua             | kelola untuk kelas penugasan          | —                                      | Lihat Jadwal (`schedule_read`)                          |
| Sesi                                   | semua             | pantau + operasikan tanggung jawabnya | —                                      | Pantau (`session_view`), Operasikan (`session_operate`) |
| Tandai manual                          | semua             | sesi tanggung jawabnya                | —                                      | `attendance_manual` (butuh `session_view`)              |
| Koreksi                                | ajukan + putuskan | ajukan sesi kewenangannya             | —                                      | `attendance_correct` (butuh view/laporan)               |
| Laporan + ekspor                       | semua + ekspor    | kelas penugasan                       | —                                      | Lihat (`reports_read`), Ekspor (`reports_export`)       |
| EWS + tindak lanjut                    | semua + atur      | kelas penugasan + catat               | —                                      | Lihat (`ews_read`), Catat (`ews_follow_up`)             |
| Kelola staf, audit, PIN kiosk          | ya                | —                                     | —                                      | tidak dapat didelegasikan                               |

Cakupan data: Kelas Saya + roster memakai penugasan aktif (periode
`starts_on/ends_on`); buka/tutup/manual/koreksi menuntut guru = pemilik
jadwal atau pengganti pertemuan itu. Tanpa lab → laboran melihat empty
state; tanpa filter kelas, grant berlaku untuk semua kelas sah dalam lab
penugasan. API menyamarkan keberadaan objek di luar penugasan (404, bukan
bocor). Setelah pencabutan, API langsung 403 dan koneksi live memeriksa
ulang izin.

## 3. Halaman web → guard → API utama (26 path guarded + kiosk publik)

| Route                                                | Guard (`requiredPermissions`) | API utama                                                                                     | Kelompok nav    |
| ---------------------------------------------------- | ----------------------------- | --------------------------------------------------------------------------------------------- | --------------- |
| `/app/dashboard`                                     | login                         | ringkasan per peran                                                                           | Ruang kerja     |
| `/app/profile`                                       | login                         | `GET /auth/me`, `PUT /sessions/opening-preference`                                            | Menu akun       |
| `/app/master-data` (+students/classes/laboratories)  | `manage_master_data`          | `/students`, `/classes`, `/laboratories`, impor CSV/XLSX                                      | Akademik        |
| `/app/my-classes`, `/app/my-classes/:classId`        | `roster_read`                 | `GET /my-classes`, `GET /my-classes/{class_id}`                                               | Akademik (guru) |
| `/app/accounts`                                      | ADMIN                         | `/accounts` + assignment + grant + reset + nonaktif                                           | Administrasi    |
| `/app/ai-setup`                                      | ADMIN                         | `/admin/settings/...`, `/admin/system/ai-readiness`                                           | Infrastruktur   |
| `/app/camera-preview`                                | `device_operate`              | `GET /devices/{id}/preview-gallery`, heartbeat; pemilih Lab→Device                            | Infrastruktur   |
| `/app/devices`                                       | `device_operate`              | `/devices`, kredensial sekali tampil, heartbeat, camera-control                               | Infrastruktur   |
| `/app/kiosks`                                        | `device_operate`              | `/kiosks`, `/kiosks/{id}/pin`, revoke                                                         | Infrastruktur   |
| `/app/reports`                                       | `reports_read`                | `/reports/attendance`, `/records`, `/export` (maks 50rb), prefill `?student_number=` dari EWS | Pemantauan      |
| `/app/ews`                                           | `ews_read`                    | `/at-risk`, policy, follow-ups (+`ews_follow_up` untuk catat/selesai)                         | Pemantauan      |
| `/app/schedules`                                     | `schedule_read`               | `/schedules`, `/schedules/teachers`                                                           | Akademik        |
| `/app/sessions`, `/app/sessions/:sessionId`          | `session_view`                | `/sessions`, openable, open/close 2-langkah, roster, policy                                   | Presensi        |
| `/app/enrollment`                                    | `enrollment_manage`           | `/enrollments`, `/face-templates`, revoke + dampak lintas lab                                 | Presensi        |
| `/app/corrections`, `/app/corrections/:correctionId` | `attendance_correct`          | `/attendance/corrections`, decision atomik, detail sebelum/sesudah, `incident_ref`            | Presensi        |
| `/app/attendance-policy`                             | ADMIN                         | `/sessions/policy`, at-risk policy, contoh lokal + tutup otomatis                             | Administrasi    |
| `/app/audit`                                         | ADMIN                         | `/audit/activity` (redaksi sandi/PIN/token/gambar/embedding; kolom detail Sebelum/Sesudah)    | Administrasi    |
| `/app/forbidden`                                     | login                         | —                                                                                             | —               |
| `/presensi` (tanpa login)                            | PIN lab/kiosk                 | `/public/laboratories`, `/public/kiosk-screens`, `/public/display`, `/public/kiosk-display`   | Kiosk siswa     |
| `/display`                                           | —                             | alias lama `/presensi`, tetap didukung                                                        | Kiosk siswa     |

URL detail (`:sessionId`, `:classId`, `:correctionId`, query laporan) dapat
dibuka ulang/refresh selama masih berwenang (401/403/404 sesuai aturan).
Satu `route dashboard` mengarah ke workspace per role; sidebar + `Sidebar.vue`
memakai daftar kemampuan efektif yang sama dengan guard route.

Rebuild UI 1:1 Stitch (2026-11-07, terverifikasi UAT admin/guru/laboran +
publik, bukti `/tmp/uat/nw-*.png`): semua halaman di atas memakai shell
`st-page` + `UiPageHeader` + komponen `components/ui` + kelas kit
`stitch-shell.css` (`.st-kpi/.st-grid2/.st-grid3/.st-table/.st-tablewrap/
.st-list/.st-def/.st-drawer/.st-field`); tidak ada atribut di luar backend.

## 4. Alur bisnis (server sebagai otoritas)

1. **Sesi**: guru/admin buka sesi dari jadwal yang boleh dibuka hari itu
   (`session_can_open_today`) → snapshot roster `session_students` → status
   `present` bila `occurred_at <= awal_efektif + grace` (default 15 mnt,
   configurable), selain itu `late`. Sesi auto-open memakai awal jadwal,
   manual memakai `opened_at`. Menit tampil = sejak awal efektif; detail
   memuat selisih terhadap toleransi. Angka detik untuk perbandingan,
   pembulatan konsisten di layar + ekspor. Tutup manual 2-langkah
   ("N belum tercatat akan menjadi absen") / otomatis di akhir jadwal;
   record final unik per sesi+siswa. Sesi berjalan: "Belum Tercatat" ≠ absen.
2. **Manual-mark**: sesi aktif + anggota roster + belum ada record + izin
   `attendance_manual`; `occurred_at` opsional (tidak default ke waktu klik;
   tanpa jam = tampil tanpa durasi). Setelah tutup → wajib alur koreksi.
3. **Koreksi**: ajukan dari roster/laporan (record ada atau pasangan
   sesi+siswa tanpa record = absen turunan, **hanya untuk sesi tertutup**
   (sesi aktif memakai tandai manual; 409 `session_still_active`);
   salah-identitas memakai `incident_ref` bersama, 2 keputusan atomik) →
   selalu `pending` → admin putuskan (kunci baris `FOR UPDATE`, cek ulang
   akses + status dasar, terapkan atomik + audit sebelum/sesudah,
   pertahankan ID record/sumber/tautan event). Satu pending aktif per
   target; idem aman; pending tidak mengubah rekap/laporan/EWS sampai
   `approved`. **Tolak wajib `decision_note`** (422 bila kosong).
   Koreksi hanya mengubah status — waktu datang tetap milik record asal
   (tidak membuat jam palsu; tanpa jam tampil tanpa durasi).
4. **Kiosk**: admin pairing device+lab + PIN sekali tampil → layar `/presensi`
   pilih lab → pilih kamera → PIN (**POST body, tidak pernah di URL**) →
   token JWT 12 jam → board fullscreen (nama sekolah, lab,
   sesi, jam lokal, indikator koneksi; hasil besar; auto-hilang ~3 dtk).
   PIN salah 5x → kunci 5 menit (429, counter persisten di DB); ganti sumber
   mengakhiri sesi + membuang pesan lama; revoke menutup layar (401);
   data lintas lab terisolasi (2 lab bersamaan OK). Token
   hanya baca kesiapan + hasil tersaring (tanpa roster/gallery/
   embedding/riwayat). Preview lintas-host butuh tahap lanjutan
   (proxy/relay + token pendek per-device); loopback hanya host sama.
5. **EWS**: watchlist absen/terlambat per ambang policy → detail sesi pemicu
   → catatan tindak lanjut (`Terbuka/Selesai`, penulis, waktu); koreksi
   disetujui mengubah agregat; catatan lama tetap terbaca walau siswa keluar
   watchlist. Agregat laboran hanya menghitung pertemuan dalam cakupannya
   (label cakupan di UI agar angka tidak dibaca sebagai riwayat sekolah).
6. **Enrollment**: cek identitas → kualitas → tangkap → tinjau → simpan
   (halaman penuh kamera; **4 frame** — keputusan: UI 4 langkah dipertahankan,
   API menerima ≥3; template terenkripsi + model/version);
   revoke menampilkan dampak lintas lab + alasan + pencatat. Template aktif
   dipakai bersama untuk siswa yang sama di kedua lab.
7. **Akun**: tambah/edit identitas, **ganti role TEACHER↔LABORANT**
   (melepas penugasan + grant tak relevan secara atomik + audit
   `released_assignments`; role ADMIN dan role diri sendiri tidak dapat
   diubah di sini), status, penugasan (guru: kelas + periode;
   laboran: N lab), grant per grup (Jadwal / Sesi-Kehadiran / Koreksi /
   Laporan-EWS + deskripsi + dependensi + "Pilih semua operasional" +
   ringkasan dampak), reset sandi sekali tampil + wajib ganti + cabut sesi,
   nonaktifkan beralasan + cabut sesi aktif; proteksi admin terakhir dan
   diri sendiri.
8. **Perangkat & preview staf**: filter lab → aktif/offline/perlu perhatian
   → detail (kamera, heartbeat + kapan terakhir, antrean, status konfig).
   Preview staf: Lab→Device→Hubungkan (auto-isi bila tunggal, label
   "Lab · Kamera"); ganti sumber melepas aliran lama + menghapus hasil lama;
   tanpa membuat event kehadiran; status "Preview teknis"/"Sesi berjalan";
   perangkat offline tetap terdaftar dengan statusnya.
9. **Laporan**: filter tanggal/lab/kelas/sesi/status + ringkasan + tabel
   (Waktu Datang, Terlambat/menit, Sumber, Catatan) + ekspor CSV/XLSX
   memakai filter sama (tampilkan bila hasil terlalu besar). Filter dapat
   dipulihkan dari URL (tautan EWS→laporan membawa `student_number` +
   periode; hanya tampil bila kedua izin ada
   (`v-if=canViewReports`). Badge tunggal (tanpa ganda
   "Terlambat + TERLAMBAT"). Zona waktu: simpan UTC, tampil zona lab.

## 5. Batasan yang masih manual

Kalibrasi threshold lokal (Top-1/margin dari benchmark lapangan — tidak
disalin dari internet), benchmark hardware target (latency tangkap→konfirmasi
vs penayangan, p50/p95), dan uji kamera fisik + preview lintas-host:
`MANUAL HARDWARE TEST REQUIRED` (lihat `docs/backlog.md` P0-5, P2-1, P2-2).
Keputusan yang masih perlu validasi mitra: toleransi, tutup otomatis per
jenis praktikum, admin tunggal menyelesaikan pengajuannya, format nama
singkat kiosk.
