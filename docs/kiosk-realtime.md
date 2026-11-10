# Kiosk realtime: video lokal + push SSE + tanpa roster

Keputusan arsitektur kiosk (hasil audit performa): browser hanya me-render,
inference tetap di edge-agent native (Python/ONNX). Tiga perubahan:

1. **Video lokal** via `getUserMedia` di `DisplayView.vue` (kamera USB menempel
   di PC kiosk itu sendiri). Nol network, ~30 FPS, tanpa beban server.
   Syarat: halaman dibuka dalam **secure context** (HTTPS atau localhost);
   bila tidak, preview nonaktif dan layar tetap menampilkan hasil.
   Satu webcam dipakai dua konsumen (browser tampil + agent nalar):
   gunakan `v4l2loopback` untuk split device di Linux, atau biarkan agent
   yang serve MJPEG diagnostik bila split belum lolos uji hardware.
2. **Hasil di-push** via SSE `GET /public/display/stream` dan
   `/public/kiosk-display/stream` (token display di query, seperti polling).
   Payload ringan `KioskLiveUpdate`: hitungan + 1 sorotan, **tanpa roster**.
   Tick 1 detik, kirim hanya saat hash berubah, komentar `: ping` tiap 15 detik.
   Fallback otomatis ke polling 5 detik bila `EventSource` tak tersedia/gagal.
3. **Roster dihapus dari layar**: tidak ada daftar nama/NIS; tinggal spotlight
   1 hasil + hitungan menunggu. Memangkas render dan menaikkan privasi.

## Keterbatasan yang diketahui

- httpx `ASGITransport` mem-buffer seluruh body: SSE tak berujung tidak dapat
  dibaca lewat transport itu (test memakai endpoint + generator langsung).
  Lewat HTTP nyata (uvicorn/nginx) stream mengalir normal.
- Koneksi DB validasi ditutup sebelum stream dimulai; generator membuka sesi
  singkat per tick agar kiosk tidak menahan koneksi pool berjam-jam.

## Operasional kiosk (PC lab)

- Jalankan browser fullscreen terkunci: `chromium --kiosk http://localhost:5173/display`
  (atau URL deploy). Agent jalan sebagai service systemd
  (`apps/edge-agent/deploy/presensi-edge-agent*.service`), bukan terminal terbuka.
- Autostart + watchdog via systemd/user-session sesuai OS lab.
- Nyalakan `PRESENSI_EDGE_PERFORMANCE_LOGS=1`, ukur `camera_read_fps`,
  `detect_ms`, `embed_ms`, `pipeline_total_ms` (p50/p95) sebelum klaim FPS.
- Checklist tuning: capture 640x480, `detection_max_width`, model ONNX
  quantized, `intra_op_num_threads` = jumlah core fisik, format MJPEG di USB.
- Target UX: tangkap → konfirmasi tampil < 1 detik. Tanpa perangkat nyata,
  klaim performa bertanda `MANUAL HARDWARE TEST REQUIRED` (AGENTS.md).

## File terkait

- `apps/api/src/presensi_api/api/v1/routers/public_display.py`
  (`KioskLiveUpdate`, `_build_live_update`, `_live_event_generator`,
  `/display/stream`, `/kiosk-display/stream`).
- `apps/web/src/views/DisplayView.vue` (video lokal, EventSource, tanpa roster).
- Test: `apps/api/tests/test_public_display_stream.py`,
  `apps/web/src/views/DisplayView.test.ts`.
