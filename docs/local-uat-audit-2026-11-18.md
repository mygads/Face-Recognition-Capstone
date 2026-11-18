# Audit lokal setelah sinkronisasi GitHub — 2026-11-18

## Sinkronisasi dan perubahan upstream

- `main` diperbarui fast-forward dari `134f838` ke `41c18b9` (`origin/main`),
  mencakup 11 commit upstream dan 61 file (+3.127/-689 baris).
- Tidak ada perubahan framework atau pergantian arsitektur. Perubahan utama
  memperketat keputusan koreksi presensi berdasarkan state sesi, provenance
  input manual, pairing perangkat fail-closed, autentikasi/TTL dan isolasi
  stream kiosk per lab, serta allowlist CORS.
- UI mengikuti perubahan itu: pengelolaan staf per role dan relasi kelas/lab,
  preview enrollment, overlay wajah yang menyesuaikan ukuran frame, perbaikan
  input konfigurasi threshold, dan penyesuaian sejumlah flow E2E.
- Tidak ada migration/framework baru yang perlu dijalankan di luar migration
  startup normal. `docker compose config --quiet` lolos.

## Kondisi runtime lokal

- API dan PostgreSQL Docker sehat; web Vite aktif pada `127.0.0.1:5173` dan API
  pada `127.0.0.1:8000`. Database dipetakan lokal pada port `5433`.
- Perangkat AI_EDGE `tes-local` mengirim heartbeat dan agent kamera terhubung.
  Preview lokal terbaca pada 640×480.
- Angka FPS yang terlihat tidak konsisten (sekitar 10 FPS di preview, target/
  driver 15 FPS, dan dashboard sempat menunjukkan sekitar 1 FPS). Ini bukan
  pengukuran performa yang cukup untuk klaim realtime; perlu pengukuran stabil
  pada hardware target.
- Saat audit tidak ada sesi presensi aktif, jadi penerimaan recognition menjadi
  `attendance_records` tidak diuji melalui kamera. Cache sesi/galeri yang
  menjawab 404 ketika tidak ada sesi aktif sesuai kondisi tersebut.
- `.env` lokal memiliki 72 nama key yang sama dengan `.env.example`; model YuNet
  dan SFace lolos pemeriksaan checksum. File `.env`, token perangkat, model, dan
  frame kamera tidak dimasukkan ke repository atau laporan ini.

## Verifikasi

| Pemeriksaan | Hasil |
| --- | --- |
| `py -3 scripts/check.py` | Ruff lint/format dan mypy lolos; 558 tes API lulus (1 warning). |
| `npm --prefix apps/web run build` | Lolos dengan lockfile upstream. |
| `npm --prefix apps/web run lint` | Lolos. |
| `npm --prefix apps/web run typecheck:e2e` | Lolos. |
| `npm --prefix apps/web run test:unit` | 144 tes lulus. |
| Playwright E2E, 2 workers | 20 lulus, 1 live-stack test dilewati sesuai konfigurasi. |
| Playwright E2E, 4 workers | 19 lulus, 1 dilewati, 1 timeout sementara saat tombol tema terlepas dari DOM; tes itu lulus saat dijalankan sendiri dan seluruh suite lulus saat diulang dengan 2 workers. |
| `npm --prefix apps/web audit --omit=dev` | 0 kerentanan pada dependency produksi. |
| `npm audit` penuh | 21 kerentanan dependency development: 12 moderate, 9 high. Perbaikan otomatis meminta perubahan versi major dan memunculkan lima error nullable TypeScript di `DevicesView.vue`; perubahan lockfile otomatis dibatalkan. Tidak menjalankan `--force`. |
| Format frontend | Gate `scripts/check.py` melaporkan 100 file frontend tidak sesuai Prettier; file-file tersebut tidak diformat massal dalam tugas ini. |

## Catatan sebelum uji operasional

- **MANUAL HARDWARE TEST REQUIRED** untuk Ubuntu/laptop target, walk-through dan
  frontal fallback, kalibrasi threshold dengan benchmark lokal, pengukuran
  latensi/FPS, serta alur presensi nyata dengan data relawan dewasa yang
  menyetujui. Jangan gunakan data siswa/minor untuk pengujian ini.
- Liveness pada konfigurasi lokal nonaktif. Model SFace yang tersedia dipakai
  untuk evaluasi lokal dan perlu review persetujuan/lisensi sekolah sebelum
  deployment operasional.
- Bukti kalibrasi lokal pada konfigurasi yang sedang tersimpan belum dapat
  diverifikasi hanya dari aplikasi. Jangan anggap nilai threshold yang tersimpan
  sudah tervalidasi.

## Panduan akun awal

Database kosong membuat satu admin development (`admin@local.test`, password
awal `1234abcd`, wajib ganti menjadi minimal 12 karakter). Seed role hanya
membuat definisi role; guru dan laboran harus dibuat dari menu **Akun Staf**.
Langkah lengkap ada di [panduan akses awal](first-run-access.md).
