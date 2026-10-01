# ADR-001: Satu recognition core dan domain API untuk dua deployment profile

- **Status:** Accepted
- **Tanggal:** 2026-10-01
- **Konteks:** Sistem harus berjalan sebagai AI_EDGE (inference pada PC lab) dan AI_CENTRAL (STB sebagai gateway, inference di server pusat). Desain v2 meminta kedua profil dapat dibandingkan dan tidak berkembang menjadi dua aplikasi berbeda.

## Keputusan

1. Kedua profile menggunakan package Python `libs/recognition-core` yang sama untuk preprocessing, face quality, liveness, embedding, matching, dan keputusan track/multi-frame.
2. Kedua profile memakai satu Core API FastAPI, API contract, vocabulary/domain model, dan aturan attendance yang sama.
3. AI service central bertugas menjalankan inference dan mengembalikan hasil recognition. Edge agent di kedua mode bertugas menangani kamera/transport dan mengirim event. Komponen tersebut tidak membuat aturan attendance duplikat.
4. Core API menjadi otoritas final untuk memvalidasi session, snapshot roster, device, grace period, duplikasi, idempotency, dan pembentukan `attendance_records`.
5. `recognition_events` tetap terpisah dari `attendance_records`. Hasil ambigu memerlukan retry/fallback dan tidak boleh auto-accept menjadi presensi final.

## Konsekuensi

- Perbedaan kedua profile terbatas pada lokasi inference, koneksi kamera, cache, transport, dan mode offline.
- Threshold/model/config dapat berbeda bila hardware menuntutnya, tetapi pipeline dan semantics API tetap satu; perbedaan konfigurasi harus eksplisit dan terversi.
- Benchmark membandingkan deployment dengan domain/output yang sama.
- Offline queue dapat menunda sinkronisasi event AI_EDGE, tetapi tidak mengubah aturan keputusan final Core API.
- Perubahan yang memisahkan core atau business rules memerlukan ADR baru dan analisis parity sebelum implementasi.

## Alternatif yang ditolak

- **Pipeline recognition terpisah di PC dan server:** berisiko membuat hasil dan bug berbeda serta merusak perbandingan benchmark.
- **API/domain model attendance terpisah per profile:** menduplikasi aturan session/roster/duplicate dan menghambat dashboard/reporting lintas lab.
- **Membuat AI service sebagai otoritas attendance:** mencampur inference dengan validasi bisnis dan membuka jalan ke aturan final yang berbeda dari Core API.
