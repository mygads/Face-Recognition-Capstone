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
4. **Mode ringan (`light=true`)**: `POST .../session` menerima `light` di body,
   `GET /display` dan `/kiosk-display` menerima `?light=true`, dan
   `POST .../rotate` selalu membalas snapshot ringan. Snapshot ringan
   mengosongkan `students: []` (hitungan + spotlight tetap ada) agar roster
   penuh tidak pernah keluar untuk kiosk — frontend selalu memakai mode ini.
   Snapshot awal non-light hanya tersisa untuk kompatibilitas; jangan dipakai
   alur kiosk baru.

## Keterbatasan yang diketahui

- httpx `ASGITransport` mem-buffer seluruh body: SSE tak berujung tidak dapat
  dibaca lewat transport itu (test memakai endpoint + generator langsung).
  Lewat HTTP nyata (uvicorn/nginx) stream mengalir normal.
- Koneksi DB validasi ditutup sebelum stream dimulai; generator membuka sesi
  singkat per tick agar kiosk tidak menahan koneksi pool berjam-jam.

## Token display: TTL 8 jam + rotasi proaktif

- `DISPLAY_TOKEN_TTL_HOURS = 8` (`api/security/dependencies.py`). Frontend
  menjadwalkan rotasi pada `ttl - 1800` detik (min 30 detik) via
  `POST /display/rotate` / `POST /kiosk-display/rotate` (body
  `{display_token}`): PIN tidak diminta ulang, tetapi lab/perangkat
  (`_require_lab_stream_target`) dicek ulang sebelum token baru diterbitkan
  (kind/subject/lab sama). Token lama tetap hidup sampai kedaluwarsa;
  rotasi yang gagal diabaikan — stream lama berjalan sampai 401.
- **Risiko yang diterima (didokumentasikan, bukan diabaikan)**: token display
  tetap lewat URL query pada endpoint GET/stream (tercatat pada riwayat
  browser, log server/proxy, sistem pemantauan). PIN pembuka awal dikirim via
  POST body; token di query adalah trade-off `EventSource` (tidak bisa set
  header), jadi endpoint GET snapshot dan GET stream tetap menerima token di
  query, sedangkan rotasi memakai POST body. Mitigasi: TTL 8 jam + rotasi proaktif, token hanya
  baca kesiapan + hasil tersaring (tanpa roster/gallery/embedding/riwayat),
  revoke menutup layar (401), PIN salah 5x kunci 5 menit. Bila deployment
  memakai proxy yang me-log query string, matikan log query atau pindahkan
  stream ke header/cookie — dicatat sebagai tindak lanjut deployment, bukan
  perilaku default kode.

## Operasional kiosk (PC lab)

- Jalankan browser fullscreen terkunci: `chromium --kiosk http://localhost:5173/display`
  (atau URL deploy). Agent jalan sebagai service systemd
  (`apps/edge-agent/deploy/presensi-edge-agent*.service`), bukan terminal terbuka.
- Autostart + watchdog via systemd/user-session sesuai OS lab.
- Nyalakan `PRESENSI_EDGE_PERFORMANCE_LOGS=1`, ukur `camera_read_fps`,
  `detect_ms`, `embed_ms`, `pipeline_total_ms` (p50/p95) sebelum klaim FPS.
- Checklist tuning (default kode sudah operasi, bukan diagnostik):
  capture 640x480 @ 15fps, `detection_max_width: 640`, FOURCC MJPG best-effort
  di `OpenCVCamera.open()` (fallback diam bila driver menolak; mode negosiasi
  tercatat di `reported_mode().fourcc`).
- Koreksi penting: YuNet/SFace berjalan via OpenCV DNN, BUKAN ONNX Runtime,
  jadi tidak ada `SessionOptions` untuk keduanya — tuasnya resolusi capture +
  `detection_max_width`. `intra_op_num_threads` = jumlah core fisik hanya
  berlaku untuk sesi ORT model anti-spoof liveness
  (`libs/recognition-core/.../onnx_liveness.py`), dan hanya relevan bila
  liveness diaktifkan.
- Target UX: tangkap → konfirmasi tampil < 1 detik. Tanpa perangkat nyata,
  klaim performa bertanda `MANUAL HARDWARE TEST REQUIRED` (AGENTS.md).

## Sinyal generik "Memverifikasi" (tanpa pindah inference ke browser)

- Agent di PC kiosk yang sama menyajikan `GET /v1/kiosk-hint` (bind
  loopback-only, tanpa token, tanpa Origin allowlist — Host non-loopback
  ditolak 403). Payload hanya status generik: `session_active`,
  `camera_open`, `recognition_state`, `face_present`/`face_count`,
  `attendance_result`, `updated_at`. TIDAK PERNAH: nama, kotak wajah,
  embedding, kandidat diagnostik, kalibrasi.
- `DisplayView.vue` mem-poll hint tiap 1 detik (timeout 900ms, best-effort)
  hanya saat sesi live; saat wajah terdeteksi (`face_present`) atau kirim
  menunggu konfirmasi (`attendance_result: pending`) dan belum ada sorotan
  hasil terbaru (< 4 detik), tampil chip "Memverifikasi kehadiran - tahan
  posisi wajah…". SSE tetap satu-satunya sumber kebenaran hasil.
- Poll hint menandai konsumen (`has_kiosk_hint_consumer`, jendela 3 detik)
  sehingga `CameraFrameInspector` (deteksi + quality saja, tanpa identitas)
  tetap berjalan walau tidak ada operator membuka preview staf.
- Preflight Private Network Access dijawab `204` +
  `Access-Control-Allow-Private-Network: true` khusus path ini.
- Target UX tetap: tangkap → konfirmasi tampil < 1 detik; chip generik
  memberi rasa respons < 1 detik tanpa mengorbankan kepastian server.

## File terkait

- `apps/api/src/presensi_api/api/v1/routers/public_display.py`
  (`KioskLiveUpdate`, `_build_live_update`, `_live_event_generator`,
  `/display/stream`, `/kiosk-display/stream`).
- `apps/web/src/views/DisplayView.vue` (video lokal, EventSource, tanpa
  roster, poll hint generik + chip "Memverifikasi").
- `apps/edge-agent/src/presensi_edge_agent/local_preview.py`
  (`/v1/kiosk-hint`, `kiosk_hint()`, `has_kiosk_hint_consumer()`).
- Test: `apps/edge-agent/tests/test_local_preview.py` (hint tanpa identitas,
  freshness, 403 non-loopback, preflight PNA).
- Test: `apps/api/tests/test_public_display_stream.py`,
  `apps/api/tests/test_scope_gaps_p1p3.py` (light + rotate + TTL),
  `apps/web/src/views/DisplayView.test.ts` (termasuk rotasi fake-timer).
- Kontrak SSE di OpenAPI: `StreamingResponse` tak punya `response_model`,
  jadi `main.py::_openapi_with_kiosk_stream()` mendaftarkan
  `KioskSpotlight`/`KioskLiveUpdate` ke components dan memberi kedua endpoint
  stream `responses[200]` content `text/event-stream` `$ref KioskLiveUpdate`.
  `schema.d.ts` diregen via openapi-typescript dari `app.openapi()` langsung.
