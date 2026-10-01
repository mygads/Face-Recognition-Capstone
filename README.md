# Presensi Praktikum Face Recognition

Monorepo untuk sistem presensi praktikum berbasis face recognition. Kedua deployment profile berbagi Vue SPA, Core API/domain, PostgreSQL, dan `libs/recognition-core`.

## Prasyarat

- Docker Desktop (Windows) atau Docker Engine + Compose plugin (Linux).
- Node.js 22.22.2+, 24.15+, atau 26+ dan npm 10+ untuk tooling web.
- Python 3.11+ untuk task runner.

## Siapkan environment

`.env.example` tidak berisi password atau signing secret. Task runner membuat password PostgreSQL dan signing key JWT acak di `.env` yang diabaikan Git:

```powershell
# Windows PowerShell
Copy-Item .env.example .env
```

```bash
# Linux
cp .env.example .env
```

Jalankan `dev-up` task runner sebelum perintah `docker compose` langsung agar `.env` lokal sudah dibuat dan diisi.

## Perintah development

Perintah ini sama di Windows dan Linux; gunakan `py -3` di Windows dan `python3` di Linux:

| Tujuan | Windows PowerShell | Linux |
| --- | --- | --- |
| PostgreSQL + Core API | `py -3 scripts/dev.py dev-up` | `python3 scripts/dev.py dev-up` |
| Tambahkan central AI service | `py -3 scripts/dev.py dev-up --central` | `python3 scripts/dev.py dev-up --central` |
| Tambahkan web dalam Docker | `py -3 scripts/dev.py dev-up --web-container` | `python3 scripts/dev.py dev-up --web-container` |
| Hentikan services | `py -3 scripts/dev.py dev-down` | `python3 scripts/dev.py dev-down` |
| Build web + test API/AI | `py -3 scripts/dev.py test` | `python3 scripts/dev.py test` |

`dev-up` default hanya menjalankan PostgreSQL dan Core API. AI service tersedia terpisah melalui Compose profile `central`. Edge agent dan webcam tidak dimasukkan ke Compose. `dev-down` mempertahankan named volume PostgreSQL.

## Web development dengan HMR

Native Vite direkomendasikan untuk hot reload:

```powershell
cd apps/web
npm ci
npm run dev
```

Saat Core API berjalan, generate ulang tipe client dari OpenAPI setelah kontrak backend berubah:

```sh
npm run api:generate
```

Frontend menggunakan `openapi-fetch` untuk request bertipe terhadap schema hasil generator. Access token hanya
berada di memori tab browser; reload halaman meminta pengguna masuk kembali.

Perintah yang sama berlaku di Linux. Jika ingin seluruh UI berjalan dalam container, gunakan opsi `--web-container`; service itu memakai polling file watcher agar perubahan bind mount Windows tetap terdeteksi. Jangan jalankan web native dan container bersamaan pada port yang sama.

## URL dan health checks

- Web native: `http://127.0.0.1:5173`
- Core API: `http://127.0.0.1:8000/health`
- API v1 health: `http://127.0.0.1:8000/api/v1/health`
- FastAPI OpenAPI: `http://127.0.0.1:8000/openapi.json`
- PostgreSQL: `127.0.0.1:5432` (dapat diubah lewat `.env`)
- Central AI (profile `central`): `http://127.0.0.1:8001/health`

AI_EDGE camera agent runs natively on the lab PC, not in default Compose. Setup,
Windows/Linux commands, and camera diagnostics are in
[apps/edge-agent/README.md](apps/edge-agent/README.md). Its roster/template cache
provider is currently blocked by the Core API's metadata-only 501 and the
approved storage decision; see [edge-agent architecture](docs/architecture/edge-agent.md).

Compose menunggu PostgreSQL sehat sebelum memulai API dan menggunakan healthcheck untuk API serta AI service. Skema awal API dikelola dengan Alembic. Setelah service siap, terapkan migration dan seed role:

```sh
docker compose run --rm api alembic upgrade head
docker compose run --rm api python -m presensi_api.db.seed_roles
```

`scripts/dev.py dev-up` membuat password PostgreSQL dan signing key JWT acak pada `.env` lokal jika nilainya kosong. Untuk login development, buat akun awal setelah seed role:

```powershell
# Windows PowerShell
docker compose run --rm api python -m presensi_api.auth.create_user --email admin@example.edu --full-name "School Administrator" --role ADMIN
```

Perintah yang sama berlaku di Linux. Password diminta secara interaktif dan tidak diberikan di argumen shell. API menyediakan `POST /api/v1/auth/login` (OAuth2 password form), `GET /api/v1/auth/me`, dan token bearer berumur default 15 menit. Lihat [authentication.md](docs/architecture/authentication.md) untuk permission, audit login, dan batas akses per kelas/laboratorium.

API healthcheck hanya memeriksa kesiapan proses HTTP; migration dijalankan eksplisit sebagai langkah development.

## Quality checks

Pasang dependency tooling Python dalam virtual environment dan dependency web sekali setelah clone:

```powershell
# Windows PowerShell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
npm ci --prefix apps/web
```

```bash
# Linux
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
npm ci --prefix apps/web
```

Dari root repository, satu command menjalankan Ruff lint/format check, mypy, seluruh pytest, serta ESLint, Prettier, TypeScript strict check untuk web dan E2E, dan Vitest:

```powershell
# Windows PowerShell
py -3 scripts/check.py
```

```bash
# Linux
python3 scripts/check.py
```

Playwright E2E smoke test terpisah dapat dijalankan dengan `npm --prefix apps/web run test:e2e`. Untuk instalasi browser lokal, jalankan `npm --prefix apps/web exec -- playwright install chromium` terlebih dahulu. Workflow GitHub Actions menjalankan migration PostgreSQL, seed, model/schema drift check, quality checks dan E2E tanpa langkah deployment.

## Struktur utama

```text
apps/web                 Vue 3 + Vite + TypeScript
apps/api                 FastAPI Core API
apps/edge-agent          camera/edge package (native; tidak ada di Compose default)
apps/ai-service          central inference service (Compose profile: central)
libs/recognition-core    shared Python recognition package
infra/docker             Dockerfile development untuk service Python
scripts/dev.py           task runner lintas Windows/Linux
tests/                   health tests dan ruang test berikutnya
docs/architecture/       arsitektur sistem
docs/adr/                keputusan arsitektur
docs/test-plans/         baseline dan protokol uji
```

Detail tabel, aturan integritas, index, dan migration ada di [docs/architecture/database-schema.md](docs/architecture/database-schema.md).
Strategi API versioning dan pembuatan TypeScript client dari OpenAPI dijelaskan di [docs/architecture/api-contract.md](docs/architecture/api-contract.md).
CRUD siswa, kelas, laboratorium, roster kelas, permission, dan soft-deactivation dijelaskan di [docs/architecture/master-data.md](docs/architecture/master-data.md).
Jadwal praktikum mingguan, aturan bentrok, dan batas akses guru dijelaskan di [docs/architecture/schedules.md](docs/architecture/schedules.md).
Snapshot roster, grace period, lifecycle sesi, dan batas roster untuk presensi final dijelaskan di [docs/architecture/attendance-sessions.md](docs/architecture/attendance-sessions.md).
Kontrak pipeline bersama dua deployment profile dijelaskan di [docs/architecture/recognition-core.md](docs/architecture/recognition-core.md).
Baseline YuNet + SFace, lisensi model, konfigurasi path, dan CLI benchmark dijelaskan di [docs/models.md](docs/models.md).
Shell Vue, layout router, tema, dan penggunaan token Gentelella dijelaskan di [docs/architecture/frontend-shell.md](docs/architecture/frontend-shell.md).

Harness evaluasi genuine/impostor, FAR/FMR dan FRR/FNMR pada banyak threshold,
latency per tahap, serta aturan dataset lokal ada di
[tests/ai-benchmark/README.md](tests/ai-benchmark/README.md). Data wajah, bobot
model, dan laporan benchmark lokal tidak boleh di-commit.

Baca [arsitektur](docs/architecture/overview.md), [ADR-001](docs/adr/ADR-001-shared-recognition-core.md), dan [AGENTS.md](AGENTS.md) sebelum mengubah struktur/domain. Compose hanya untuk development, bukan deployment production.
