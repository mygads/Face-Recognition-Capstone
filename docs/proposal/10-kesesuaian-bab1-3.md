# 10 — Penyelarasan draf Bab I–III

> Checklist agar draf laporan konsisten dengan sistem berjalan + metode
> Prototype. Arsitektur tidak diubah.

## 10.1 Bab I — yang perlu diselaraskan

1. Sebutkan dua profil deployment (AI_EDGE default, AI_CENTRAL opsional) +
   satu otoritas attendance (Core API) — lihat [01](01-pendahuluan.md).
2. Batasan wajib memuat: tanpa foto default, embedding terenkripsi, tanpa data
   wajah nyata di repo/cloud/CI, threshold kalibrasi lokal, koreksi = pending,
   `cancelled` dicadangkan.
3. Rumusan masalah EWS: tekankan "dijelaskan ambangnya, bukan sanksi otomatis".

## 10.2 Bab II — tinjauan pustaka/teori

1. Landasan: cosine similarity, YuNet (deteksi) + SFace (embedding) OpenCV Zoo,
   temporal multi-frame consensus + margin Top-1/Top-2, liveness/PAD opsional.
2. Konsep pendukung: snapshot roster, idempotency event UUID, fail-closed,
   timezone-aware datetime, RBAC, AES-256-GCM, audit log.
3. Metode Prototype sebagai landasan metodologi (bukan waterfall):
   rujuk [02](02-metode-prototype.md) — siklus review tiap putaran + uji-coba
   kembali, pintu kalibrasi sebelum klaim angka.

## 10.3 Bab III — metode (Prototype, bukan waterfall/incremental)

1. Ganti bagan waterfall dengan siklus di [02](02-metode-prototype.md):
   observasi → prototipe → uji coba → review → revisi → final → kalibrasi →
   deployment → evaluasi → (kebutuhan baru memutar siklus baru).
2. Instrumen uji: `scripts/check.py` (lint/type/test), 17 migrasi Alembic,
   harness `tests/ai-benchmark`, protokol `docs/pengujian.md`.
3. Sampel uji: minimal 5 lintasan/relawan per profil deployment, data
   pseudonim (tanpa wajah siswa nyata).
4. Variabel terukur: threshold terkalibrasi, latency p50/p95, akurasi
   walk-through vs frontal, kepatuhan fail-closed (ambigu → retry, bukan accept).
5. Selama angka hardware belum diukur, tulis `MANUAL HARDWARE TEST REQUIRED` —
   jangan isi asumsi (lihat [08](08-arsitektur.md) §8.6).
