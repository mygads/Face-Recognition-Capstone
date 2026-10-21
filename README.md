# Presensi Praktikum Face Recognition

## 1. Apa ini

Sistem presensi praktikum SMA: guru membuka sesi, kamera lab mengenali siswa
walk-through, Core API memutuskan presensi final. Dua profile deployment
memakai **satu recognition-core yang sama**:

- **AI_EDGE** (default): recognition berjalan di PC tiap laboratorium.
- **AI_CENTRAL**: STB di lab menjadi camera gateway, recognition berjalan di
  server AI pusat.

Aturan inti: `recognition_events` (hasil pengenalan, selalu disimpan sebagai
audit) **bukan** `attendance_records` (hanya lahir setelah validasi sesi aktif,
snapshot roster, device, grace period, dan idempotency). Setiap sesi menyalin
snapshot roster kelas; grace period default 15 menit (bisa 0–1440). Hasil
ambigu tidak pernah auto-accept — sistem meminta retry frontal atau fallback
manual guru.

## 2. Arsitektur

```text
kamera lab -> edge-agent / STB gateway -> Core API + PostgreSQL -> dashboard guru
                     AI_EDGE: inference di PC lab | AI_CENTRAL: inference di server pusat
```

Detail lengkap (profile, batas domain, preview pra-sesi, peta repo, alur
enrollment dan session-to-attendance): [docs/architecture/overview.md](docs/architecture/overview.md).

Stack: Vue 3 + Vite + TypeScript · FastAPI + SQLAlchemy 2 + Alembic ·
PostgreSQL 16 · Python + OpenCV + ONNX Runtime via `libs/recognition-core`.

## 3. Jalan 5 menit

Prasyarat: Git, Docker + Compose, Python 3.11+, Node/npm sesuai
`apps/web/package.json`. Windows: Docker Desktop + WSL2. Ubuntu: Docker Engine
+ plugin Compose.

```powershell
# Windows
git clone https://github.com/mygads/Face-Recognition-Capstone.git
cd Face-Recognition-Capstone
py -3 scripts/start-local.py
```

```bash
# Ubuntu
git clone https://github.com/mygads/Face-Recognition-Capstone.git
cd Face-Recognition-Capstone
python3 scripts/start-local.py
```

Buka `http://127.0.0.1:5173` (API `http://127.0.0.1:8000`). Login awal:
`admin@local.test` / `1234abcd`, wajib ganti password (min 12 karakter).

Login gagal — cek tiga hal ini dulu:

1. **Password salah.** Pakai `1234abcd` (bukan `123456789abcd` versi lama),
   atau nilai `PRESENSI_BOOTSTRAP_PASSWORD` di `.env` bila dioverride.
2. **Database sudah berisi akun.** Bootstrap tidak me-reset akun yang ada;
   masuk dengan password lama, atau reset volume dev
   (`scripts/dev.py dev-down` lalu `docker compose down -v`, data dev hilang)
   dan jalankan `start-local.py` lagi.
3. **Belum ganti password pertama.** Ikuti redirect buat password baru, lalu
   masuk kembali. Jangan expose stack dev sebelum password diganti.

Readiness sebelum presensi nyata: model YuNet+SFace terprovisioning
(checksum-verified otomatis saat setup pertama); **threshold Top-1/margin
wajib dari kalibrasi lokal** di halaman **AI & kamera** (tanpa ini recognition
dijeda `waiting_for_calibration`); webcam lolos `presensi-camera-calibration`;
liveness contoh nonaktif — pakai kontrol sesi/fisik yang disetujui. Jangan
pakai data siswa nyata/minor untuk development; gunakan data sintetis atau
relawan dewasa yang menyetujui.

## 4. Cara pakai harian

**Guru:** buat jadwal (menu jadwal), buka sesi saat praktikum dimulai
(roster tersnapshot otomatis), pantau **dashboard live** (ringkasan hadir/
terlambat/belum tercatat, perangkat, 10 aktivitas terakhir via WebSocket),
tutup sesi manual bila perlu. Siswa yang gagal dikenali (kamera bermasalah,
retry berulang) ditandai manual lewat tombol per siswa yang belum tercatat.
Unduh laporan/ekspor CSV-XLSX (filter tanggal, kelas, lab, status; maks
50.000 baris per ekspor). Sesi yang masih berjalan tidak melaporkan siswa
sebagai absen dini.

**Admin/laboran:** kelola akun staf, master data (siswa/kelas/lab + impor
CSV/XLSX), enrollment wajah (4 frame per siswa, template terenkripsi),
perangkat kamera (registrasi + kredensial satu kali + setup bundle), dan
kebijakan **AI & kamera** (kualitas, threshold terkalibrasi, burst STB).
Halaman guru tidak menampilkan internals AI atau embedding — hanya status,
nama roster, dan hasil final yang dikonfirmasi Core API.

## 5. Kalau error ke mana

Log aplikasi aman by design: tanpa raw image, embedding, token, password,
atau secret. Saat melapor, sertakan pesan error + kode + langkah reproduksi,
bukan payload mentah.

Cek mandiri:

```sh
python3 scripts/check.py          # gate wajib hijau (lint, type, unit)
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:8000/api/v1/health
```

Webcam/kamera: `presensi-camera-calibration --list-cameras`, wizard
`configure-camera` di host kamera, halaman **Preview kamera** (AI_EDGE,
loopback host yang sama). Auth AI `503 auth_misconfigured` = device_tokens
belum dikonfigurasi (bukan error jaringan). `401/403` edge agent tidak
di-retry — perbarui kredensial perangkat.

Tandai `MANUAL HARDWARE TEST REQUIRED` dan jangan klaim hasil bila:
threshold belum dikalibrasi lokal, uji walk-through/frontal belum jalan di
hardware target, atau benchmark deployment belum diukur di PC/STB nyata.

## 6. Roadmap singkat

Sisa tugas: **P0-5** kalibrasi threshold lokal · **P1-1** test pendamping ·
**P1-4** `model_name` di respons burst · **P1-5** skor quality + operating
point terkalibrasi · **P1-6** error berkode + tolak roster kosong ·
**P2-1** field test + benchmark hardware · **P2-2** integration hidup +
Playwright nyata. Detail status/pemilik: [docs/backlog.md](docs/backlog.md).

Catatan: `docs/final-audit.md` (2026-10-02) sudah basi dan dihapus saat
konsolidasi docs; snapshot PASS-nya tercatat sebagai arsip di backlog, bukan
klaim berlaku kini. Gate berjalan: 312 pytest, 32 Vitest, ruff/mypy/
vue-tsc/eslint hijau.

## 7. Link docs detail

| Butuh | Buka |
| --- | --- |
| Arsitektur + alur sistem | [docs/architecture/overview.md](docs/architecture/overview.md) |
| Auth, kontrak API, skema DB, master data, jadwal | [docs/architecture/fondasi-backend.md](docs/architecture/fondasi-backend.md) |
| Sesi, keputusan presensi, laporan, dashboard, enrollment | [docs/architecture/siklus-presensi.md](docs/architecture/siklus-presensi.md) |
| recognition-core, AI service, edge/STB agent | [docs/architecture/ai-inferensi.md](docs/architecture/ai-inferensi.md) |
| Registry + konfigurasi perangkat | [docs/architecture/perangkat-dan-konfigurasi.md](docs/architecture/perangkat-dan-konfigurasi.md) |
| Deployment 1 file (single-host, AI_EDGE, AI_CENTRAL/STB, tunnel) | [docs/deployment.md](docs/deployment.md) |
| Pengujian 1 file (lapangan, benchmark, privasi) | [docs/pengujian.md](docs/pengujian.md) |
| Model, lisensi, kalibrasi | [docs/models.md](docs/models.md) |
| Kontrol biometrik + retensi | [docs/security-and-privacy.md](docs/security-and-privacy.md) |
| Kamera dan model lokal | [docs/camera-usage.md](docs/camera-usage.md) |
| Lisensi Gentelella | [docs/licenses/](docs/licenses/) |
| Keputusan arsitektur | [docs/adr/](docs/adr/) |

Aturan stop (wajib tanya dulu): ganti pilihan framework · ubah kebijakan
penyimpanan biometrik · expose endpoint biometrik publik · tambah face-recognition
SaaS cloud · ganti model berlisensi tak jelas · simpan image siswa by default.
Lihat [AGENTS.md](AGENTS.md).
