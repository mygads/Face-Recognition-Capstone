# AGENTS.md — Presensi Face Recognition

## Project purpose
Sistem presensi praktikum SMA berbasis face recognition. Ada dua deployment profile yang harus tetap didukung oleh core yang sama:
1. `AI_EDGE`: recognition berjalan di PC tiap laboratorium.
2. `AI_CENTRAL`: STB di lab menjadi camera gateway, recognition berjalan di central AI server.

## Mandatory architecture
- Frontend: Vue 3 + Vite + TypeScript.
- UI design: adapt Gentelella v4 ke Vue components. Jangan memakai direct DOM mutation dari template jika bertentangan dengan Vue reactivity.
- Backend: FastAPI.
- Database: PostgreSQL. pgvector opsional untuk embedding storage/search.
- AI: Python + OpenCV + ONNX Runtime melalui `libs/recognition-core`.
- Edge and central mode MUST reuse recognition-core and attendance API/domain rules.
- `recognition_events` != `attendance_records`.
- Attendance final hanya dibuat setelah session/roster/business validation.

## Domain rules
- Guru membuka attendance session terlebih dahulu.
- Roster di-snapshot saat session dibuka.
- Matching harus dibatasi pada active session roster bila memungkinkan.
- Default grace period 15 menit, tetapi configurable.
- Duplicate attendance student+session dilarang.
- Recognition ambiguous tidak boleh auto-accept; return retry/fallback state.
- Walk-through adalah fast path, frontal look adalah fallback.

## Face data rules
- Jangan commit dataset wajah ke repository.
- Jangan log raw image, face embedding, access token, password, atau secret.
- Raw image tidak disimpan default.
- Data siswa nyata/minor tidak boleh digunakan pada test cloud/CI.
- Fixture AI development harus berupa synthetic/public legal fixture atau relawan dewasa yang menyetujui.
- Face template harus menyimpan model name/version.

## Engineering rules
- Baca docs/architecture dan ADR sebelum mengubah arsitektur.
- Satu task harus fokus; jangan refactor unrelated code.
- Tambahkan/ubah test bersama perubahan behavior.
- Semua database change melalui Alembic migration.
- Semua public API memiliki Pydantic schema dan error response konsisten.
- Gunakan timezone-aware datetime.
- Network retry harus idempotent menggunakan event UUID.
- Jangan hardcode secret, device id, URL, threshold, atau model path.
- Threshold recognition tidak boleh disalin dari internet sebagai nilai final; kalibrasikan dari benchmark lokal.

## Required verification before declaring a task done
- Run relevant unit tests.
- Run lint/type checks for touched package.
- Run integration/E2E when task changes cross-service behavior.
- Report commands executed and result.
- If hardware is required and unavailable, mark it explicitly as `MANUAL HARDWARE TEST REQUIRED`; never invent performance result.

## UI rules
- Internal dashboard, no SSR/SEO requirement.
- Keep menu limited to real features.
- Responsive at desktop and tablet widths.
- Forms must show validation/error state clearly.
- Do not expose AI internals/embedding to teacher UI.

## Stop conditions
Stop and ask before:
- changing framework choices;
- changing biometric storage policy;
- exposing biometric endpoints publicly;
- adding cloud face-recognition SaaS;
- replacing model with one whose license is unclear;
- storing student face images by default.
