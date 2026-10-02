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
| Server | py -3 scripts/dev.py dev-up | python3 scripts/dev.py dev-up |
| Setup database dan admin lokal | Otomatis oleh scripts/dev.py dev-up | Otomatis oleh scripts/dev.py dev-up |
| Web | npm ci --prefix apps/web lalu npm --prefix apps/web run dev | Perintah yang sama |
| URL | Web http://127.0.0.1:5173, API http://127.0.0.1:8000 | Sama |

Task runner membuat .env lokal jika belum ada, menghasilkan secret development,
menjalankan migration dan role seed, lalu membuat akun admin lokal hanya jika
belum ada akun pada database. Simpan kata sandi sementara yang dicetak satu
kali di terminal.
Emailnya admin@local.test; kata sandi wajib diganti sebelum aplikasi bisa
digunakan. Bootstrap ini hanya berjalan dengan Compose development; deployment
production tidak membuat akun bawaan.

Kata sandi admin/admin yang tetap bukan pilihan aman walaupun ada menu ganti
sandi: akun bisa terekspos sebelum operator sempat menggantinya. Karena itu
bootstrap development membuat kata sandi acak sementara dan memaksa pergantian
pada login pertama. Setelahnya, menu Profil menyediakan perubahan kata sandi.
Untuk menghentikan database dan API gunakan py -3 scripts/dev.py dev-down di
Windows atau python3 scripts/dev.py dev-down di Ubuntu. Volume database tetap
tersimpan.

Unduh model evaluasi checksum-pinned dengan `python scripts/download_face_models.py`.
Threshold tetap harus dikalibrasi. Lihat
[panduan kamera dan model](docs/camera-usage.md) serta
[panduan satu komputer](docs/deployment/single-pc.md) untuk preview webcam,
enrollment, edge-agent, dan alur pengujian. SFace belum cleared untuk deployment
sekolah sampai provenance/license weight ditinjau.

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
Lihat [development dan deployment satu komputer](docs/deployment/single-pc.md)
serta [index runbook deployment](docs/deployment/README.md).

Tidak ada installer satu-perintah yang aman untuk semua OS. Satu command
menyalakan Compose setelah Docker dan tool host terpasang. Model, device
credential, izin webcam, threshold, domain, dan kebijakan data disiapkan terpisah.

## Status kesiapan pengenalan wajah

| Item | Status repository | Persiapan untuk tes fisik |
| --- | --- | --- |
| YuNet + SFace | Adapter tersedia; downloader memprovision file lokal ke direktori ignored dengan SHA-256 terverifikasi. SFace weight masih perlu review provenance sebelum operasi. | Jalankan downloader untuk local evaluation; catat versi/checksum dan selesaikan review institusi sebelum deployment. |
| Threshold Top-1/margin | Tidak ada nilai final default; agent gagal terbuka jika kosong. | Kalibrasi pada data berizin yang mewakili kamera kelas. Prioritaskan false acceptance rendah; laporkan FMR/FNMR. |
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
