# Repository baseline audit

Tanggal audit: 2026-10-01.

## Kondisi sebelum scaffold

Target `C:\Yoga\Programming\Face-Recognition-Capstone` belum ada saat task dimulai. Folder induk `C:\Yoga\Programming` berisi proyek lain, sehingga foundation dibuat sebagai subfolder terpisah. Repository GitHub `mygads/Face-Recognition-Capstone` terkonfirmasi kosong (belum memiliki default branch/commit).

Tidak ada file aplikasi, `AGENTS.md`, folder `docs/`, konfigurasi lint, dependency manifest, ataupun test suite yang sudah ada di target baru. Template `AGENTS.md`, prompt pack, rancangan teknis v2, dan workbook checklist dibaca sebagai referensi Capstone; prompt tugas berikutnya di dalamnya tidak dijalankan pada task ini.

## Lint dan test awal

Tidak ada lint/test command awal yang dapat dijalankan karena tidak ada konfigurasi/package atau test. Foundation menambahkan web typecheck/build scripts dan dua FastAPI `/health` scaffolds, tetapi tidak menambahkan test suite atau lint policy. Konfigurasi quality tooling tetap menjadi task terpisah.

## Audit struktur setelah scaffold

- Satu Vue frontend di `apps/web`; tidak ada React/Next app atau Gentelella standalone app kedua.
- FastAPI Core API tunggal di `apps/api` dan central inference process shell di `apps/ai-service`.
- Satu boundary package `libs/recognition-core` untuk kedua deployment profile.
- Deployment, tests, architecture, ADR, dan test-plan directories tersedia.
- Business attendance, biometric processing, DB, Docker, and CI belum diimplementasikan.
