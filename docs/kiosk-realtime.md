# Kiosk realtime: video lokal + push SSE + tanpa roster

Keputusan arsitektur kiosk (hasil audit performa): browser hanya me-render,
inference tetap di edge-agent native (Python/ONNX). Tiga perubahan:

1. **Video dari pemilik tunggal (single-owner)**: di PC lab, agent
   (`OpenCVCamera`) memegang kamera fisik untuk inference; browser kiosk
   TIDAK membuka kamera. Video tampil dari `GET /v1/kiosk-stream` (MJPEG
   multipart agent, loopback-only) — frame yang sama dengan inference,
   plus `FaceOverlay` (box + skeleton 5 titik). `getUserMedia` hanya
   fallback diagnostik bila stream agent gagal ("Pakai kamera perangkat").
   Split webcam via `v4l2loopback` DITOLAK: justru dihindari dengan
   single-owner; tidak ada rencana overlay browser + inference bersamaan
   tanpa uji hardware baru.
2. **Hasil di-push** via SSE `GET /public/display/stream` dan
   `/public/kiosk-display/stream`. Transport utama: `fetch` +
   `ReadableStream` dengan token di header `Authorization: Bearer`
   (tidak tercatat di URL/riwayat/proxy); `EventSource` dengan token query
   hanya fallback lawas bila fetch streaming tak tersedia/gagal.
   Payload ringan `KioskLiveUpdate`: hitungan lab + 1 sorotan, **tanpa roster**,
   plus `grace_period_minutes` dari sesi aktif (UI memakai nilai ini, bukan
   hardcode 15 menit).
   - Stream lab (`display/stream`): sorotan = record terbaru lab (beserta
     `source` + `recognition_event_id` untuk dedup; record manual tetap
     berlabel `manual`, bukan hasil scan).
   - Stream kiosk (`kiosk-display/stream`): sorotan = hanya record
     `face_recognition` yang event-nya berasal dari perangkat kiosk itu
     (join `recognition_events.device_id` + `session_id`). Record manual dan
     record kamera lain tidak pernah menjadi sorotan scan kiosk ini.
   Push dalam proses: write path (tandai manual, keputusan recognition,
   buka/tutup sesi) menaikkan versi via `display_notify`
   sehingga generator bangun dan query ulang segera (< 100 ms, bukan
   menunggu tick). Jaring pengaman: query ulang tiap ~10 detik tanpa
   perubahan (mencakup worker/proses lain yang NOTIFY-nya hilang) + ping
   tiap 15 tick. Kirim hanya saat hash berubah (`server_time` dikecualikan).
   Isolasi antar-lab dijamin digest per-lab: bangun versi bersifat global,
   tetapi generator hanya emit bila snapshot lab-nya sendiri berubah
   (diuji `test_two_lab_streams_are_isolated`).
   Push lintas proses (tahap dua, selesai): tiap proses API memasang satu
   daemon thread `LISTEN "presensi_display_changed"` (`display_notify.py`:
   `start/stop_pg_display_listener`, dipasang di lifespan `main.py`,
   best-effort — tidak pernah crash). Write path yang sama memancarkan
   `pg_notify_display_changed` saat commit, sehingga generator SSE di proses
   lain bangun < 1 detik (poll `notifies(timeout=1.0)`, reconnect backoff).
   Tanpa Postgres (sqlite/dev) listener dilewati; safety tick tetap
   menjamin delivery. Verifikasi nyata (Postgres 16 + 2 proses, DB scratch
   `presensi_push_e2e`, data sintetis, 2026-11-17): (1) NOTIFY via write-path
   `pg_notify_display_changed` + commit membangunkan proses LISTEN lain dalam
   0,13 dtk; (2) dua worker uvicorn (8101 tulis / 8102 SSE): buka sesi via
   worker A tampil sebagai snapshot SSE di worker B dalam 0,06-0,07 dtk
   (jauh di bawah safety 10 dtk — terbukti jalur push, bukan jaring).
   Ulang 2x stabil.
   Fallback otomatis ke polling 5 detik bila fetch streaming dan
   `EventSource` tak tersedia/gagal.
3. **Roster dihapus dari layar**: tidak ada daftar nama/NIS; tinggal spotlight
   1 hasil + hitungan menunggu. Memangkas render dan menaikkan privasi.
4. **Mode ringan (default `light=true` di mana-mana)**: `POST .../session`
   (body) maupun `GET /display` dan `/kiosk-display` (query) default ringan
   (`light=false` eksplisit hanya untuk operator), dan `POST .../rotate`
   selalu membalas snapshot ringan. Snapshot ringan
   mengosongkan `students: []` (hitungan + spotlight tetap ada) agar roster
   penuh tidak pernah keluar untuk kiosk — frontend selalu memakai mode ini.

## Keterbatasan yang diketahui

- httpx `ASGITransport` mem-buffer seluruh body: SSE tak berujung tidak dapat
  dibaca lewat transport itu (test memakai endpoint + generator langsung).
  Lewat HTTP nyata (uvicorn/nginx) stream mengalir normal.
- Koneksi DB validasi ditutup sebelum stream dimulai; generator membuka sesi
  singkat per tick agar kiosk tidak menahan koneksi pool berjam-jam.

## Token display: TTL 4 jam default + rotasi proaktif

- TTL display default 4 jam via `KIOSK_DISPLAY_TOKEN_TTL_HOURS` (env, 1-12 jam, `api/security/dependencies.py`; dibaca dinamis tiap penerbitan token). Frontend
  menjadwalkan rotasi pada `ttl - 1800` detik (min 30 detik) via
  `POST /display/rotate` / `POST /kiosk-display/rotate` (body
  `{display_token}`): PIN tidak diminta ulang, tetapi lab/perangkat
  (`_require_lab_stream_target`) dicek ulang sebelum token baru diterbitkan
  (kind/subject/lab sama). Token lama tetap hidup sampai kedaluwarsa;
  rotasi yang gagal diabaikan — stream lama berjalan sampai 401.
- **Risiko yang diterima (didokumentasikan, bukan diabaikan)**: transport
  utama (fetch streaming + snapshot) mengirim token via header
  `Authorization: Bearer` atau cookie `display_token` — tidak tercatat di
  URL/riwayat/proxy. Query `?token=` dipertahankan hanya sebagai fallback
  lawas untuk `EventSource` (tidak bisa set header) dan kompatibilitas;
  jangan pakai di alur baru. PIN pembuka awal dikirim via POST body.
  Mitigasi: TTL default 4 jam + rotasi proaktif, token hanya
  baca kesiapan + hasil tersaring (tanpa roster/gallery/embedding/riwayat),
  revoke menutup layar (401), PIN salah 5x kunci 5 menit. Pengetatan lebih
  jauh selesai: kolom nullable `kiosk_screens.token_ttl_hours` (CHECK 1-12,
  migrasi `c7d2e5a9b1f4`, NULL = pakai default global) + kolom
  `token_ttl_hours` di skema create/update/response kiosk. `open` dan
  `rotate` kiosk memakai TTL baris itu; PATCH dengan null eksplisit kembali
  ke default global. UI `KiosksView` menyediakan pilihan TTL per layar.

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
- Baseline sintetis CPU-only (`scripts/bench_recognition_synthetic.py`,
  BUKAN klaim hardware): matching NumPy p50/p95 sekitar 90 template 0,37/0,69 ms;
  300 template 1,3/1,4 ms; 900 template 3,9/4,3 ms (bervariasi per mesin). Temporal 40 frame
  ~0,5 ms, accept di frame ke-5; ganti orang TANPA jeda terobservasi sebagai
  identitas `campur` (single track-ID per kamera — keputusan server tetap
  fail-closed). Angka YuNet/SFace/kamera/FPS/latensi KAI tetap
  `MANUAL HARDWARE TEST REQUIRED` sampai diukur di PC lab nyata.

## Single-owner kamera + kiosk-stream (tanpa getUserMedia di PC lab)

- Satu kamera satu pemilik: di PC lab, agent (`OpenCVCamera`) memegang kamera
  fisik untuk inference. Browser kiosk TIDAK memanggil `getUserMedia`; video
  tampil dari `GET /v1/kiosk-stream` (MJPEG multipart, bind loopback-only,
  token opsional, 403 untuk Host non-loopback) yang menyajikan frame agent yang
  sama dengan inference. `<img>` + `FaceOverlay` (box + skeleton 5 titik,
  wajah terbesar disorot hijau) memberi rasa realtime tanpa inference pindah
  ke browser. Tombol "Pakai kamera perangkat (diagnostik)" hanya fallback
  saat stream lab gagal.
- Hint `faces` + `face_count` menggerakkan overlay dan badge "1 wajah / N
  wajah" di kiosk; bila N > 1 tampil imbauan "Satu siswa di depan kamera".
  Overlay hilang saat frame stale (> 3 detik) atau kamera offline.
- Aturan yang sama untuk enrollment: sumber "Kamera lab via agent" membaca
  stream agent + capture via canvas (tanpa membuka kamera kedua); sumber
  "Kamera perangkat ini" memakai `getUserMedia` untuk perangkat operator yang
  berbeda. Bingkai panduan statis + skeleton yang sama dipakai agar UI
  konsisten walau tanpa deteksi live di browser.

## Sinyal generik "Memverifikasi" (tanpa pindah inference ke browser)

- Agent di PC kiosk yang sama menyajikan `GET /v1/kiosk-hint` (bind
  loopback-only, token opsional bila dikonfigurasi; Host non-loopback
  ditolak 403; bila `preview.kiosk_allowed_origins` diisi, hanya origin
  dalam daftar yang menerima header ACAO). Payload hanya status generik: `session_active`,
  `camera_open`, `recognition_state`, `face_present`/`face_count`,
  `faces` (maks 5: box + landmark ternormalisasi + flag kualitas, TANPA
  identitas), `attendance_result`, `updated_at`. TIDAK PERNAH: nama,
  embedding, kandidat diagnostik, kalibrasi.
- `DisplayView.vue` mem-poll hint tiap 1 detik (timeout 900ms, best-effort)
  hanya saat sesi live; saat wajah terdeteksi (`face_present`) atau kirim
  menunggu konfirmasi (`attendance_result: pending`) dan belum ada sorotan
  hasil terbaru (< 4 detik), tampil chip "Memverifikasi kehadiran - tahan
  posisi wajah…". SSE tetap satu-satunya sumber kebenaran hasil.
- Poll hint menandai konsumen (`has_kiosk_hint_consumer`, jendela 3 detik)
  sehingga `CameraFrameInspector` (deteksi + quality saja, tanpa identitas)
  tetap berjalan walau tidak ada operator membuka preview staf.
- Token stream kios opsional: `preview.kiosk_stream_token` (config) atau
  `PRESENSI_EDGE_KIOSK_STREAM_TOKEN` (env). Default kosong = perilaku lama
  (loopback-only, tanpa token). Bila diisi, `/v1/kiosk-stream` dan
  `/v1/kiosk-hint` wajib `?token=` yang cocok (hmac compare, 401 bila
  salah). FE menyimpan token sekali via `?stream_token=` ke
  `localStorage[presensi.kiosk_stream_token]` lalu menghapusnya dari URL.
  Untuk deployment sekolah, set `preview.kiosk_stream_require_token: true`
  (atau `PRESENSI_EDGE_KIOSK_STREAM_REQUIRE_TOKEN=1`) agar akses anonim
  ditolak meski dari loopback; default false demi kompatibilitas instalasi
  lama. Param `retry=N` milik FE diabaikan server (bukan token).
  Opsional: `preview.kiosk_allowed_origins` (file config saja, mis.
  `["https://presensi.sekolah.id"]`) membatasi origin browser yang boleh
  membaca hint/stream kios — origin di luar daftar tidak menerima header
  ACAO sehingga diblokir browser; preflight-nya dijawab 403. Bila kosong,
  berlaku mode kompatibel lama (origin direfleksikan) + warning saat
  service start.
  Token staf preview TIDAK PERNAH dibagikan ke browser kios; konsumen stream
  kios (`has_kiosk_stream_consumer`, jendela 3 detik) terpisah dari sesi
  preview operator dan ikut mengaktifkan encoding JPEG (jadi kiosk tetap
  tampil tanpa halaman preview staf terbuka).
- Retry stream kios di FE (`DisplayView.vue`): error `<img>` (mis. 503 awal
  saat buffer JPEG belum ada) dijadwalkan ulang otomatis dengan backoff
  1s,2s,4s,8s lalu 15s via cache-buster `?retry=N`; hitungan direset saat
  frame termuat. Timer dibersihkan saat sesi berhenti/unmount.
- Pairing fail-closed di FE: kios yang dipasangkan ke device hanya
  menampilkan video setelah hint loopback segar dan `device_id`-nya cocok;
  bila berbeda -> banner "Kamera Tidak Sesuai", bila belum terverifikasi ->
  banner "Memverifikasi Kamera…". Hint terakhir dipertahankan saat poll
  sesaat gagal (hanya tandai stale >3 dtk) agar status mismatch tidak hilang.
  Layar rekap tanpa device terpilih mempertahankan perilaku lama.
- Koreksi pascasesi: sesi closed hanya bisa diubah dengan izin
  `attendance_correct_closed` (grantable ke laboran/guru, butuh pantau sesi;
  409 `session_inactive` bila tanpa izin; TANPA mensyaratkan izin tandai
  manual — guard router hanya mensyaratkan pantau sesi, pemeriksaan granular
  state-aware ada di `mark_manual_attendance`). Sesi cancelled TIDAK dapat
  ditulis lewat jalur ini oleh siapa pun (409 `session_inactive` meski
  pemegang izin koreksi). Catatan baru pada sesi tertutup wajib beralasan
  (422), pembaruan tetap wajib `note`, dan audit menyimpan
  `session_status` untuk membedakan koreksi pascasesi. Di UI, form koreksi
  sesi closed hanya tampil bila pemegang izin koreksi; sesi cancelled
  menampilkan pemberitahuan "tidak dapat dikoreksi".
- Provenance edit manual: update catatan via guru/aslab wajib `note`
  (alasan, 422 bila kosong), `source` menjadi `manual` dan
  `recognition_event_id` dilepas (kontrak CHECK manual->event NULL);
  `occurred_at` lama dipertahankan bila tidak dikirim. Replay edge dengan
  `event_uuid` sama tetap idempoten lewat fallback sesi+siswa HANYA bila
  metadata event sendiri `attendance_recorded`. Spotlight SSE difilter
  `recognition_events.device_id` sehingga edit manual tidak disajikan
  sebagai scan kamera lain.
- Preflight Private Network Access dijawab `204` +
  `Access-Control-Allow-Private-Network: true` khusus path ini.
- Target UX tetap: tangkap → konfirmasi tampil < 1 detik; chip generik
  memberi rasa respons < 1 detik tanpa mengorbankan kepastian server.

## File terkait

- `apps/api/src/presensi_api/api/v1/routers/public_display.py`
  (`KioskLiveUpdate`, `_build_live_update`, `_live_event_generator`,
  `/display/stream`, `/kiosk-display/stream`).
- `apps/web/src/views/DisplayView.vue` (stream agent primer + FaceOverlay,
  SSE via fetch-header dengan fallback EventSource-query, tanpa
  roster, poll hint generik + chip "Memverifikasi").
- `apps/edge-agent/src/presensi_edge_agent/local_preview.py`
  (`/v1/kiosk-hint`, `/v1/kiosk-stream`, `kiosk_hint()`,
  `has_kiosk_hint_consumer()`, `has_kiosk_stream_consumer()`,
  `kiosk_token_ok()`).
- `apps/web/src/components/FaceOverlay.vue` (box + skeleton dipakai preview,
  kiosk, dan enrollment).
- Test: `apps/edge-agent/tests/test_local_preview.py` (hint tanpa identitas,
  freshness, 403 non-loopback, preflight PNA, token kios opsional 401/200,
  konsumen stream mengisi JPEG tanpa viewer operator).
- `apps/api/src/presensi_api/display_notify.py` (notify in-process +
  LISTENer Postgres lintas proses) dan `scripts/bench_recognition_synthetic.py`.
- Test: `apps/api/tests/test_public_display_stream.py`
  (termasuk isolasi 2-lab), `apps/api/tests/test_display_notify_push.py`
  (12 test: NOTIFY lintas proses via stub koneksi),
  `apps/api/tests/test_scope_gaps_p1p3.py` (light + rotate + TTL),
  `apps/web/src/views/DisplayView.test.ts` (termasuk rotasi fake-timer).
- Kontrak SSE di OpenAPI: `StreamingResponse` tak punya `response_model`,
  jadi `main.py::_openapi_with_kiosk_stream()` mendaftarkan
  `KioskSpotlight`/`KioskLiveUpdate` ke components dan memberi kedua endpoint
  stream `responses[200]` content `text/event-stream` `$ref KioskLiveUpdate`.
  `schema.d.ts` diregen via openapi-typescript dari `app.openapi()` langsung.
