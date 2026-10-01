# Presensi Praktikum Face Recognition

Monorepo untuk sistem presensi praktikum berbasis face recognition. Kedua deployment profile berbagi Vue SPA, Core API/domain, PostgreSQL, dan `libs/recognition-core`.

## Prasyarat

- Docker Desktop (Windows) atau Docker Engine + Compose plugin (Linux).
- Node.js 20.19+ dan npm 10+ untuk web native.
- Python 3.11+ untuk task runner.

## Siapkan environment

`.env.example` berisi nilai development lokal, bukan credential untuk lingkungan bersama/production. Salin sebelum menjalankan Compose langsung:

```powershell
# Windows PowerShell
Copy-Item .env.example .env
```

```bash
# Linux
cp .env.example .env
```

Task runner di bawah akan membuat `.env` dari contoh tersebut bila belum ada.

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

Perintah yang sama berlaku di Linux. Jika ingin seluruh UI berjalan dalam container, gunakan opsi `--web-container`; service itu memakai polling file watcher agar perubahan bind mount Windows tetap terdeteksi. Jangan jalankan web native dan container bersamaan pada port yang sama.

## URL dan health checks

- Web native: `http://127.0.0.1:5173`
- Core API: `http://127.0.0.1:8000/health`
- PostgreSQL: `127.0.0.1:5432` (dapat diubah lewat `.env`)
- Central AI (profile `central`): `http://127.0.0.1:8001/health`

Compose menunggu PostgreSQL sehat sebelum memulai API dan menggunakan healthcheck untuk API serta AI service. API saat ini belum membaca/menulis database; koneksi/schema dibuat pada task database berikutnya.

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

Baca [arsitektur](docs/architecture/overview.md), [ADR-001](docs/adr/ADR-001-shared-recognition-core.md), dan [AGENTS.md](AGENTS.md) sebelum mengubah struktur/domain. Compose hanya untuk development, bukan deployment production.
