# Presensi Praktikum Face Recognition

Monorepo aplikasi presensi praktikum sekolah. Frontend Vue, Core API,
database, dan pipeline pengenalan dipisah menjadi service. Presensi final hanya
dibuat Core API setelah memeriksa sesi, snapshot roster, perangkat, grace period,
dan idempotency.

## Mulai di satu komputer

Untuk development pada Windows atau Ubuntu, jalankan database dan API dalam
Docker, web Vite native, serta edge-agent native agar webcam diakses langsung
oleh OS. Webcam tidak dipasang ke Docker Compose default.

| Bagian | Windows | Ubuntu |
| --- | --- | --- |
| Prasyarat | Docker Desktop + WSL2, Python 3.11+, Node sesuai engines di apps/web/package.json, npm 10+ | Docker Engine + Compose plugin, Python 3.11+, Node sesuai engines di apps/web/package.json, npm 10+ |
| Jalankan API, database, dan web | `py -3 scripts/start-local.py` | `python3 scripts/start-local.py` |
| Setup database dan admin lokal | Otomatis; `.env` lokal dibuat dengan secret acak | Otomatis; `.env` lokal dibuat dengan secret acak |
| Web | Dependency dipasang otomatis bila perlu; Vite native untuk HMR | Sama |
| URL | Web http://127.0.0.1:5173, API http://127.0.0.1:8000 | Sama |

Clone lalu jalankan satu command ini dari PowerShell/terminal:

```powershell
git clone https://github.com/mygads/Face-Recognition-Capstone.git
cd Face-Recognition-Capstone
py -3 scripts/start-local.py
```

Pada peluncuran pertama, script menanyakan pilihan AI_EDGE (API/web saja) atau
AI_CENTRAL (API/web plus AI service). Pilihan disimpan di `.env`; berikutnya
script menjalankan pilihan yang sama. Untuk menggantinya, jalankan
`py -3 scripts/start-local.py --profile edge` atau `--profile central` di
Windows; di Ubuntu gunakan `python3 scripts/start-local.py --profile edge` atau
`--profile central`. Flag lama `--central` tetap tersedia. Model harus
diprovisikan pada host inference dan threshold harus diisi dari laporan
kalibrasi melalui halaman admin **AI & kamera** sebelum inference dipakai.

Pada setup lokal pertama, YuNet/SFace otomatis diunduh (~39 MB), diverifikasi
dengan checksum, lalu dipasang ke `models/weights/`. Gunakan
`py -3 scripts/start-local.py --skip-model-download` untuk melewati unduhan dan
`py -3 scripts/start-local.py --download-models` untuk mengunduhnya kemudian
(ganti `py -3` dengan `python3` di Ubuntu). Installer perangkat AI_EDGE juga
otomatis mengunduh model. File model tidak ikut `git clone`. Untuk AI_CENTRAL
production, ikuti provisioning pada runbook. SFace masih untuk evaluasi hingga
izin sekolah ditinjau; threshold recognition harus dikalibrasi. Pada AI_CENTRAL
lokal, model sudah dipasang tetapi inference belum siap sampai konfigurasi
berkalibrasi diterbitkan dari dashboard **AI & kamera**.

Satu command startup menyimpan pilihan profile, membuat `.env` lokal jika belum
ada, menghasilkan secret development, menjalankan migration dan role seed,
membuat akun admin lokal hanya jika belum ada akun, memasang dependency web bila
perlu, lalu menjalankan Vite. Buka terminal di root repository. Untuk instalasi lokal, login dengan
`admin@local.test` / `123456789abcd`; aplikasi wajib mengganti kata sandi pada
login pertama. Kredensial tetap ini hanya untuk Compose development di mesin
lokal. Jangan expose server sebelum kata sandi diganti dan jangan gunakan
bootstrap development untuk deployment production. Production tidak membuat
akun bawaan.

Prasyarat Windows: Git, Docker Desktop dengan WSL2, Python 3.11+, dan Node/npm
sesuai `apps/web/package.json`. Jika Python belum tersedia, jalankan `py install 3.12`, buka ulang PowerShell, lalu gunakan `py -3` (jangan pin `py -3.12` jika
runtime itu belum terpasang). Prasyarat Ubuntu: Git, Docker Engine + Compose,
Python 3.11+, dan Node/npm sesuai package web. Perintah startup memeriksa tool
host yang hilang dan menampilkan nama yang harus dipasang; ia tidak memasang
Docker, Python, atau Node pada komputer server/web. Tekan Ctrl+C untuk
menghentikan Vite; jalankan `py -3 scripts/dev.py dev-down` di Windows atau
`python3 scripts/dev.py dev-down` di Ubuntu untuk menghentikan API/database.

Setelah login sebagai admin, buka menu **Kelola akun staf** untuk membuat akun
Guru atau Laboran tanpa command line. Sistem membuat kata sandi acak sementara
dan hanya menampilkannya setelah akun dibuat; berikan kepada pemilik akun agar
mereka menggantinya saat login pertama. Menu **Profil** dapat digunakan untuk
mengganti kata sandi setelahnya.
Unduh model evaluasi checksum-pinned dengan `python scripts/download_face_models.py`.
Threshold tetap harus dikalibrasi. Lihat
[panduan kamera dan model](docs/camera-usage.md) serta
[panduan satu komputer](docs/deployment/single-pc.md) untuk preview webcam,
enrollment, edge-agent, dan alur pengujian. SFace belum cleared untuk deployment
sekolah sampai provenance/license weight ditinjau.

### Jalankan kamera AI_EDGE dan lihat preview lokal

Untuk satu-PC Windows development, jalankan API/web seperti di atas, lalu
jalankan satu edge-agent native agar ia menjadi satu-satunya pemilik webcam:

```powershell
.\.venv-edge-agent\Scripts\presensi-edge-agent.exe --config apps/edge-agent/config/edge-agent.yaml run
```

Jika installer membuat executable pada direktori virtual environment lain,
gunakan path executable yang ditampilkan installer. Jangan jalankan utility
calibration atau halaman enrollment bersamaan dengan agent pada kamera fisik
yang sama. Dengan browser pada komputer AI_EDGE, buka **Perangkat → Preview
kamera**. Halaman menampilkan satu preview dari frame yang sudah diambil agent;
ia tidak meminta izin kamera atau membuka webcam kedua. Preview dibatasi ke
loopback dan akun ADMIN/LABORANT. Gambar hanya berada di memori agent/browser,
tidak ditulis ke disk. Hentikan agent dengan Ctrl+C untuk kembali memakai
webcam melalui halaman enrollment.

Untuk melihat nama siswa, harus ada sesi praktikum aktif dan template untuk
model/version yang sedang dipakai. Sistem hanya menampilkan nama setelah
recognition-core menerima identitas berdasarkan threshold Top-1 dan margin yang
diambil dari laporan kalibrasi. Selama threshold belum dikalibrasi, preview
tetap tersedia tetapi statusnya **menunggu kalibrasi**; sistem tidak menebak
identitas dan tidak mengirim presensi.

## Tiga topologi penggunaan

Project tetap memiliki dua profil pengenalan: **AI_EDGE** dan
**STB_GATEWAY + AI_CENTRAL**. Single-computer adalah topologi development/demo
yang memakai salah satu profil, bukan profil algoritma ketiga.

| Topologi | Penempatan | Kapan dipakai | Panduan |
| --- | --- | --- | --- |
| Edge computer + VPS | VPS Ubuntu menjalankan PostgreSQL, Core API, dan web. PC lab Ubuntu menjalankan edge-agent dan inference lokal. | Pilot dengan PC kamera di setiap lab; profil awal yang direkomendasikan setelah model, threshold, hardware, dan kebijakan sekolah siap. | [AI_EDGE deployment](docs/deployment/ai-edge.md) |
| STB gateway + AI server | Server pusat Ubuntu menjalankan PostgreSQL, Core API, dan AI service. STB ARM64 dengan image Armbian yang cocok menjadi gateway kamera. | Lab memakai gateway hemat daya dan server pusat punya resource inference. | [AI_CENTRAL + STB deployment](docs/deployment/ai-central-stb.md) |
| Satu komputer | Laptop/PC yang sama menjalankan server lokal, web, webcam, dan edge-agent. Windows untuk development/demo; Ubuntu untuk demo satu host atau deployment terbatas. | Development, demonstrasi, commissioning awal; bukan high availability. | [Panduan satu komputer](docs/deployment/single-pc.md) |

CasaOS bukan prasyarat: jalankan agent STB sebagai service native pada OS/image
yang kompatibilitasnya sudah diverifikasi. Panduan memilih Armbian sebagai
baseline gateway; CasaOS hanya dashboard opsional dan belum menjadi target uji
hardware repository ini.

Database tidak boleh diakses dari Internet. Untuk domain dan tunnel, baca
[panduan domain dan Cloudflare Tunnel](docs/deployment/cloudflare-tunnel.md).

## Development berbeda dari deployment

Development menggunakan hot reload, port localhost, dan secret acak lokal.
Deployment menggunakan rilis yang disetujui, secret terlindungi, migration
terkontrol, HTTPS/reverse proxy, backup, retensi, dan service restart saat boot.
Untuk development, Docker menjalankan PostgreSQL dan Core API; AI Central
ditambahkan hanya dengan profile `central`, Vue memakai Vite native secara
default, dan agent kamera berjalan native. Untuk production, Compose menjalankan
PostgreSQL/Core API dan AI Central bila profile central dipakai; Vue dibuild
sebagai file statis di reverse proxy. AI_EDGE dan STB_GATEWAY tetap native pada
host kameranya—keduanya tidak memerlukan Docker.
Untuk uraian komponen dan konfigurasi dari clone sampai production, lihat
[panduan instalasi dan konfigurasi](docs/deployment/installation-and-configuration.md).
Lihat [development dan deployment satu komputer](docs/deployment/single-pc.md)
serta [index runbook deployment](docs/deployment/README.md).

### Urutan setup pertama dan perangkat kamera

1. Clone repository, pasang prasyarat host, lalu jalankan satu command startup
   development di atas. Itu menyiapkan `.env` lokal, database, migrasi, role,
   admin awal, dependency web, dan server Vite.
2. Login admin. Buat laboratorium, kelas/tahun ajaran, data siswa, dan akun
   TEACHER/LABORANT melalui UI. Untuk uji kamera gunakan data sintetis atau
   relawan dewasa yang setuju.
3. YuNet/SFace otomatis diunduh dan checksum-diverifikasi saat setup lokal
   pertama dan saat installer memasang kamera AI_EDGE. `git clone` tidak
   mengunduh model. Untuk AI_CENTRAL production, provision model di server
   dengan langkah checksum-pinned pada [runbook AI Central](docs/deployment/ai-central-stb.md).
   Jika setup lokal melewati unduhan atau unduhannya gagal, jalankan salah satu
   command berikut dari root repository:

   ```powershell
   py -3 scripts/start-local.py --download-models
   ```

   ```bash
   python3 scripts/start-local.py --download-models
   ```

   STB_GATEWAY tidak memerlukan model lokal. SFace masih untuk evaluasi sampai
   sekolah meninjau izin penggunaannya; threshold harus dikalibrasi terpisah.
4. Buka **Perangkat**, daftarkan device dengan laboratorium dan profile yang
   benar, lalu buat kredensial. Token hanya tampil sekali. Pilih OS dan koneksi
   pada panel setup. Simpan default URL Core API dan AI Central sekali di panel
   atas halaman Perangkat; default berada hanya pada browser admin ini, bukan
   konfigurasi server. Bundle dapat memakai default atau override per device.
   Download paket setup. Paket ini adalah file rahasia berisi
   alamat, UUID, profile, dan token device. Untuk komputer kamera yang sama,
   file sudah berada di Downloads. Untuk host lain, pindahkan file ke folder
   Downloads di kamera lewat USB/SCP. Lalu salin command dari halaman itu.
   Command tidak mengandung token dan installer tidak meminta UUID/token/URL
   lagi. Untuk satu PC `AI_EDGE`, pilih localhost
   agar memakai checkout yang sudah ada. Untuk STB atau host kamera lain,
   bootstrap mengambil source sendiri.
5. Jalankan command hasil halaman Perangkat pada host kamera. Installer membaca
   bundle lokal, memvalidasi profile ke Core API, menyiapkan dependency/config,
   otomatis mengunduh model bila profile AI_EDGE, lalu menawarkan wizard untuk
   memilih kamera, resolusi, dan FPS. Pilihan ditulis ke YAML device. Setelah
   itu installer memeriksa status dan menawarkan menjalankan agent. Pilih
   **Armbian Linux** untuk STB dan **Windows** atau **Ubuntu** untuk AI_EDGE.

   Installer menulis token ke lokasi terlindungi, memeriksa kamera/status, lalu
   menawarkan menjalankan agent di terminal agar koneksi/heartbeat terlihat.
   Hapus bundle setup setelah pemasangan. Jangan tempel token ke command line.
   Bootstrap mengambil source dari branch
   `main`; untuk production gunakan versi yang sudah ditinjau dan langkah
   systemd pada runbook. Jalur domain publik dan Cloudflare untuk koneksi agent
   belum diaktifkan karena agent belum mendukung identitas Cloudflare Access dan
   jalur device mengakses template biometrik; gunakan LAN/VPN privat. Di Windows,
   Git dan Python dipasang melalui winget bila belum tersedia; launcher `py`
   dapat memasang runtime Python 3.12. Di Ubuntu/Armbian, bootstrap membutuhkan
   Bash, koneksi internet, dan akses `sudo`; ia memasang `curl`, Python, atau Git
   dari apt bila belum tersedia.

6. Installer AI_EDGE memasang model checksum-verified otomatis. Untuk
   AI_CENTRAL production, provision model saat setup server sesuai runbook.
   Isi threshold Top-1 dan margin dari laporan kalibrasi pada halaman admin
   **AI & kamera** sebelum presensi. Untuk `STB_GATEWAY`, pastikan AI
   Central dan Core API sehat serta STB menjangkau keduanya melalui LAN.
   Setelah heartbeat muncul **Online**, buat jadwal, buka sesi sebagai guru,
   lalu uji event dan dashboard.

Pada dev single-PC, URL kamera harus `http://127.0.0.1:8000` dan agent harus
berjalan di komputer yang sama. API dev sengaja hanya bind ke loopback. Untuk
kamera di host lain, deploy server dengan LAN/DNS dan reverse proxy HTTPS
terlebih dahulu; jangan membuka port API development ke jaringan publik.

Lihat [panduan instalasi kamera](apps/edge-agent/README.md) untuk perintah
Windows/Ubuntu/Armbian dan [matriks konfigurasi profile](docs/architecture/device-configuration.md)
untuk batas opsi dashboard/installer. Ini adalah installer commissioning yang menyiapkan
agent dan konfigurasi lokal. Untuk layanan produksi yang berjalan setelah reboot,
ikuti runbook systemd AI_EDGE atau STB. Tidak ada installer produksi satu
perintah yang otomatis memilih domain, TLS, secret store, firewall, backup,
model, threshold, dan kebijakan sekolah; langkah server production tetap
terkendali di [runbook deployment](docs/deployment/README.md).

Halaman admin **AI & kamera** menampilkan readiness dan mengelola kualitas
enrollment, kualitas frame, sampling, jumlah frame yang perlu sepakat, threshold
terkalibrasi AI_EDGE/AI_CENTRAL, serta filter/burst STB. Pengaturan dibuat
sebagai revisi, dicatat di audit log, lalu ditarik otomatis oleh service tanpa
restart. Dashboard menampilkan revisi yang diminta dan diterapkan. Kamera,
resolusi/FPS, model/checksum/version, token, URL service, dan liveness model
tetap dikonfigurasi pada host; wizard installer mendeteksi pilihan kamera yang
tersedia. Halaman ini tidak mengunduh model atau memulai ulang service.

## Status kesiapan pengenalan wajah

| Item | Status repository | Persiapan untuk tes fisik |
| --- | --- | --- |
| YuNet + SFace | Adapter tersedia; downloader memprovision file lokal ke direktori ignored dengan SHA-256 terverifikasi. SFace weight masih perlu review provenance sebelum operasi. | Setup lokal dan installer AI_EDGE mengunduh otomatis; AI_CENTRAL production diprovision dari runbook. Catat versi/checksum dan selesaikan review institusi sebelum deployment. |
| Threshold Top-1/margin | Tidak ada nilai final default; agent dapat berjalan aman dalam status `waiting_for_calibration`, tetapi tidak mengenali atau mengirim presensi. | Kalibrasi pada data berizin yang mewakili kamera kelas. Prioritaskan false acceptance rendah; laporkan FMR/FNMR. |
| Webcam/PC lab/STB | Utility kamera dan test mock tersedia; uji lapangan belum dilakukan. | Uji webcam UVC, posisi, pencahayaan, dan OS target; ukur CPU/RAM/suhu STB nyata. |
| Liveness | Adapter/code path tersedia tetapi contoh nonaktif. Kandidat yang terdokumentasi belum cleared untuk operasi sekolah. | Tinjau lisensi/provenance, uji code path dan threshold sendiri, atau operasikan kontrol fisik/sesi yang disetujui. |
| Template metadata lama | Migration mencabut template aktif tanpa ciphertext agar tidak dianggap enrolled. | Setelah migration diterapkan pada database lama, siswa terkait perlu enrollment baru. |

Ini bukan klaim akurasi atau kepatuhan hukum. Sekolah perlu menyetujui tujuan,
notice/dasar pemrosesan, retensi, akses, fallback manual, koreksi, dan respons
insiden sebelum memakai data siswa. Gunakan data sintetis atau relawan dewasa
yang menyetujui untuk development; jangan commit foto, embedding, secret, atau
hasil benchmark privat.

## Arsitektur untuk developer baru

Mulai dari [panduan sistem dan onboarding developer](docs/architecture/developer-guide.md),
[architecture overview](docs/architecture/overview.md), dan
[ADR-001](docs/adr/ADR-001-shared-recognition-core.md). Panduan menjelaskan
komponen, alur data, domain ownership, security boundary, serta keputusan
arsitektur.

Stack utama: Vue 3 + Vite + TypeScript; FastAPI + SQLAlchemy 2 + Alembic;
PostgreSQL 16; recognition package Python; OpenCV/ONNX Runtime untuk adapter
lokal. TypeScript API types dibuat dari OpenAPI. Gentelella v4 adalah referensi
visual; interaksi tetap memakai komponen Vue.

## Quality checks dan regression

~~~sh
# Windows
py -3 scripts/check.py
py -3 scripts/regression.py

# Ubuntu
python3 scripts/check.py
python3 scripts/regression.py
~~~

Regression memakai data sintetis, tanpa webcam atau wajah siswa. Playwright E2E
terpisah: npm --prefix apps/web run test:e2e.

## Runbook dan referensi

| Topik | Dokumen |
| --- | --- |
| System, profile, dan alur | [System guide](docs/architecture/developer-guide.md), [overview](docs/architecture/overview.md) |
| Schema dan migration | [Database schema](docs/architecture/database-schema.md) |
| Auth, permission, privacy | [Authentication](docs/architecture/authentication.md), [security/privacy](docs/security-and-privacy.md) |
| Jadwal, sesi, presensi, laporan | [Schedules](docs/architecture/schedules.md), [sessions](docs/architecture/attendance-sessions.md), [decision](docs/architecture/attendance-decisions.md), [reports](docs/architecture/attendance-reports.md) |
| Enrollment dan device | [Enrollment](docs/architecture/enrollment.md), [device registry](docs/architecture/device-registry.md) |
| AI Central dan edge-agent | [AI service](docs/architecture/ai-service.md), [edge-agent](docs/architecture/edge-agent.md) |
| URL server, kamera, Docker/native | [Device configuration](docs/architecture/device-configuration.md), [installation guide](docs/deployment/installation-and-configuration.md) |
| Model dan benchmark | [Model provenance/recommendation](docs/models.md), [AI benchmark](tests/ai-benchmark/README.md) |
| Commissioning | [Walk-through field test](docs/test-plans/walkthrough-field-test.md), [deployment benchmark](tests/deployment-benchmark/README.md) |
| VPS, STB, single host, domain/tunnel | [Deployment index](docs/deployment/README.md) |

## Repository map

~~~text
apps/web                 Vue SPA
apps/api                 FastAPI Core API dan attendance authority
apps/edge-agent          Native UVC edge/gateway agent
apps/ai-service          Central inference service
libs/recognition-core    Shared, framework-independent recognition pipeline
infra/deployment         Production Compose dan database setup
infra/docker             Service Dockerfiles
scripts                  Development/check/regression task runner
tests                    Synthetic, benchmark, dan integration harness
docs/architecture        System architecture dan feature contracts
docs/deployment          Operating runbooks
docs/test-plans          Manual acceptance protocol
~~~

Detail batas implementasi terakhir ada di
[final architecture/code audit](docs/final-audit.md).
