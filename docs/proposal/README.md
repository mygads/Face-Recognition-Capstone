# Proposal & Rancangan Sistem — Presensi Praktikum Face Recognition + EWS

> Satu paket rancangan untuk dikirim ke tim penulis laporan (Word / Bab IV).
> Teman Anda tidak perlu membaca kode — cukup render diagram Mermaid → screenshot
> sebagai Gambar, dan salin tabel ke Word.

## Aturan pengikat (jangan dilanggar saat menulis laporan)

1. Arsitektur mengikuti sistem yang sudah ±80% berjalan: Vue 3 + FastAPI +
   PostgreSQL + `libs/recognition-core`; profil `AI_EDGE` default + `AI_CENTRAL`
   opsional. Otoritas attendance tunggal: Core API.
2. **Metode pengembangan = Prototype** (lihat [02](02-metode-prototype.md)) —
   ada siklus dengar → mockup → uji coba → review → revisi. Bukan waterfall,
   bukan incremental-iteratif ala sprint.
3. Yang boleh ditambah hanya **EWS tahap 2** dan hal non-arsitektur.
4. `recognition_events` (bukti audit) ≠ `attendance_records` (keputusan final).
5. Fakta wajah: raw image transient (tidak disimpan default); embedding
   AES-256-GCM; log/queue/respons bebas gambar, embedding, token, password,
   secret. Tanpa data wajah siswa nyata/minor di repo/cloud/CI. Template wajib
   menyimpan model name/version. Threshold dikalibrasi lokal, bukan dari internet.

## Peta file

| File | Isi — untuk laporan |
|---|---|
| [01-pendahuluan.md](01-pendahuluan.md) | Latar belakang, rumusan, batasan, tujuan, manfaat (Bab I) |
| [02-metode-prototype.md](02-metode-prototype.md) | Metode Prototype + siklus review/uji-coba (Bab III) |
| [03-fitur-dan-peran.md](03-fitur-dan-peran.md) | Daftar fitur F-01–F-14 + usulan U-01–U-04, aktor, matriks akses |
| [04-use-case.md](04-use-case.md) | Use case per aktor + relasi `include`/`extend` |
| [05-activity.md](05-activity.md) | Activity diagram per fitur + ringkasan per role |
| [06-proses-bisnis-dan-alur.md](06-proses-bisnis-dan-alur.md) | Alur end-to-end, sequence, state machine, tabel keputusan |
| [07-data-dan-class.md](07-data-dan-class.md) | Class diagram per fitur + ringkasan 18 tabel |
| [08-arsitektur.md](08-arsitektur.md) | Container, pipeline AI, keamanan wajah, ADR, batas hardware |
| [09-ews.md](09-ews.md) | EWS tahap 1 (jalan) + tahap 2 (usulan): UC, activity, data |
| [10-kesesuaian-bab1-3.md](10-kesesuaian-bab1-3.md) | Catatan penyelarasan draf Bab I–III |
| [schema-erd.sql](schema-erd.sql) | DDL tanpa data → bahan gambar ERD |

## Cara pakai untuk Word

1. Setiap blok ` ```mermaid ` dirender (Mermaid Live Editor / MermaidChart /
   plugin Mermaid di Word) lalu screenshot sebagai **Gambar** + beri nomor
   (Gambar 4.x) dan judul sesuai sub-bab.
2. `schema-erd.sql`: buat database PostgreSQL kosong → jalankan file → buat
   ER diagram (DBeaver/pgAdmin reverse-engineer) → screenshot sebagai gambar ERD.
   File ini BUKAN migrasi — perubahan skema tetap lewat Alembic.
3. Setiap tabel `| Kode | ... |` bisa disalin langsung menjadi tabel Word.

## Status kebenaran (hasil audit kode + docs, 2026-10-25)

- Seluruh `docs/` dibaca (15 file). Dua fakta basi diperbaiki di tempat:
  `siklus-presensi.md` (worker auto-close/open tiap **10 detik**, bukan 30;
  grace auto-open dihitung dari **jam mulai jadwal**) dan `ADR-003`
  (status implementasi **Selesai**, migrasi `f4e5d6c7b8a9`).
- Semua angka di dokumen ini diverifikasi dari kode (`apps/api`,
  `apps/edge-agent`, `apps/ai-service`, `libs/recognition-core`,
  `apps/web`) — lihat catatan sumber per file.
- Angka yang HANYA bisa diisi dari hardware nyata ditandai
  `MANUAL HARDWARE TEST REQUIRED` (nilai threshold, latency, walk-through
  vs frontal) — jangan diisi asumsi.
- Revisi 03–08 selesai diterapkan: matriks peran izin, use case UML
  (`flowchart` + boundary + asosiasi `---` + `<<include>>`/`<<extend>>`),
  activity per fitur dan per role, sequence/state machine dan tabel keputusan,
  class diagram per fitur, serta container/sequence arsitektur dengan arah
  request terverifikasi dari kode (pull: edge/AI service → Core API; probe:
  Core API → AI service; preview: browser → PC `:8765`).
- Status validasi final (belum selesai): render Mermaid (Live Editor /
  MermaidChart / plugin Word) dan pengujian repo (unit, lint/type per
  paket, integration/E2E lintas service) masih perlu validasi final
  sebelum laporan dikunci.
