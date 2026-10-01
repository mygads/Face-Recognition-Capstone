# Presensi Praktikum Face Recognition

Monorepo untuk sistem presensi praktikum berbasis face recognition. Foundation ini menetapkan satu web app Vue, satu Core API FastAPI, satu edge agent, satu central AI service, dan satu `recognition-core` Python yang dipakai oleh kedua profil deployment.

## Prasyarat development

- Node.js 20.19+ dan npm 10+ untuk web.
- Python 3.11+ untuk API dan AI service.
- PowerShell (Windows) atau shell POSIX.

PostgreSQL dan Docker Compose belum disiapkan pada task foundation ini. Keduanya menjadi pekerjaan environment development berikutnya. Saat ini API dan AI service hanya menyediakan endpoint health; tidak ada fitur presensi atau database.

## Jalankan web

Buka terminal pertama dari root repository:

```powershell
cd apps/web
npm install
npm run dev
```

Vite menampilkan URL lokal di terminal. Untuk build lokal:

```powershell
npm run build
```

Web menggunakan Vue 3 + Vite + TypeScript dan stylesheet Gentelella v4.1.1. Kerangka halaman dan komponen Vue akan mengikuti layout, tokens, dan pola visual Gentelella; interaksi tetap dikelola Vue.

## Jalankan Core API

Buka terminal kedua:

```powershell
cd apps/api
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
uvicorn presensi_api.main:app --reload --host 127.0.0.1 --port 8000
```

Di Linux/macOS, ganti aktivasi venv dengan `source .venv/bin/activate`. Health check tersedia di `http://127.0.0.1:8000/health`.

## Jalankan central AI service (opsional)

Buka terminal ketiga bila sedang mengerjakan profil STB + central AI:

```powershell
cd apps/ai-service
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
uvicorn presensi_ai_service.main:app --reload --host 127.0.0.1 --port 8001
```

Health check tersedia di `http://127.0.0.1:8001/health`. Endpoint inference belum dibuat.

`apps/edge-agent` dan `libs/recognition-core` saat ini hanya package shell. Fitur kamera, inference, database, dan attendance sengaja belum diimplementasikan pada foundation ini.

## Struktur

```text
apps/web                 Vue 3 SPA
apps/api                 FastAPI Core API dan domain authority
apps/edge-agent          service kamera/cache untuk kedua profil
apps/ai-service          inference service untuk profil central
libs/recognition-core    pipeline Python bersama
infra/                   deployment dan environment tooling
tests/                   automated, E2E, dan AI benchmark
docs/architecture/       arsitektur sistem
docs/adr/                keputusan arsitektur
docs/test-plans/         baseline dan protokol uji
```

Baca [arsitektur](docs/architecture/overview.md), [ADR-001](docs/adr/ADR-001-shared-recognition-core.md), dan [AGENTS.md](AGENTS.md) sebelum mengubah struktur atau domain.

## Quality checks saat ini

Audit awal menemukan tidak ada test suite atau lint configuration yang sudah ada untuk dijalankan. Ringkasan baseline ada di [repository-baseline.md](docs/test-plans/repository-baseline.md). Foundation ini menambahkan perintah build/typecheck untuk web; automated test dan lint tooling akan dipilih dan dikonfigurasi pada task quality tooling.
