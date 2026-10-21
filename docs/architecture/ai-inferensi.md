# AI Inferensi: recognition-core, AI Service, Edge/STB Agent

Satu pipeline Python di `libs/recognition-core` dipakai ulang edge dan central.
Tanpa FastAPI di core. Threshold identitas tidak punya default produksi — wajib
kalibrasi lokal (lihat [pengujian](../pengujian.md) dan
[models](../models.md)). Jangan salin threshold dari internet sebagai nilai
final.

## recognition-core: pipeline dan stages

Urutan `RecognitionPipeline`: preprocess → detect → quality assessment →
alignment → liveness → embedding → gallery matching → temporal decision. Frame
tidak aman/tidak cukup berhenti sebelum stage mahal/sensitif. Temporal decision
memiliki tracking window, threshold match, ambiguity policy, dan frontal retry;
`MultiFrameDecisionEngine` implementasi lokalnya: sampling sebelum inference,
agregat frame kualitas-terbaik per track ID stabil, reset evidence saat
identitas pemenang berganti atau kualitas tak acceptable. Butuh N frame sepakat
terkonfigurasi; tiap evidence frame dan rata-rata frame terpilih harus lolos
cosine Top-1 dan margin Top-1−Top-2.

Margin ambigu → state domain `retry_frontal` / `NEED_FRONTAL_RETRY`, tidak
pernah auto-accept. Kandidat satu identitas distinct
(`single_identity_gallery`) juga non-accepting: tanpa runner-up, margin Top-1/
Top-2 undefined sehingga similarity saja tidak bisa accept. Pipeline re-query
matcher dengan limit lebih lebar bila truncasi menyembunyikan runner-up (satu
siswa punya beberapa template dalam `max_candidates` ketat); temporal engine
tetap otoritatif atas accept/reject pada set lebar. Gallery satu identitas
genuin tetap fail-closed — guru menutup via presensi manual.

Liveness eksplisit di `RecognitionPipeline`: disabled = skip anti-spoof;
enabled butuh model + cutoff `min_live_score` terkalibrasi. Required=True
memblokir accept saat skor missing/inconclusive/gagal (plus guard fail-closed
kedua terhadap custom temporal engine); optional = observasional. Kandidat
`anti-spoof-mn3` (ONNX Runtime) hanya evaluasi: lisensi/training-dataset
(CelebA-Spoof, non-commercial research) belum cleared untuk operasional —
repo tanpa weights, tanpa download. Produksi tanpa liveness cleared wajib
kontrol fisik/sesi terdokumentasi.

Kontrak stage = protokol Python (FaceDetection, FaceQuality, FaceEmbedding,
CandidateMatch, RecognitionDecision, TrackDecision); adapter OpenCV/ONNX bisa
diganti. Install default tanpa runtime eksternal; extra `opencv` untuk
YuNet/SFace. Path model dari konfigurasi deployment; tidak ada download saat
runtime. `FaceEmbedding` menyimpan model name/version + vector; core tidak
persist vector. Cosine [-1, 1]; confidence/quality [0, 1]; margin ternormalisasi
[0, 1]. Fake stages deterministik di `recognition_core.testing` hanya untuk
unit test framework-free; adapter produksi dilarang import fake tersebut.
Matcher cosine tanpa threshold default; kebijakan temporal/bisnis memakai
threshold hasil evaluasi lokal.

## ai-service (AI_CENTRAL)

Host inference pusat, bukan API bisnis kedua. STB/edge tepercaya mengirim burst
kronologis via LAN privat; service verifikasi UUID + bearer device, rate/body
limit, decode aman bounded-memory (hanya JPEG/PNG/WebP), lalu menjalankan
recognition-core. Auth fail-closed: tanpa `device_tokens` terkonfigurasi →
`503 auth_misconfigured` + startup warning. Open auth hanya opt-in eksplisit
saat gallery validation didelegasikan ke `CoreApiGalleryProvider` (mode Core
API), bukan registry lokal. Respons: track state/outcome, kandidat UUID,
confidence, reason code, observation count, model version, skor liveness
opsional — tanpa frame/embedding.

```mermaid
sequenceDiagram
  participant Edge as Trusted edge device
  participant AI as Central AI service
  participant Core as recognition-core
  participant API as Core API
  Edge->>AI: Bearer + device UUID + frame burst
  AI->>AI: Size/rate/auth; decode aman
  AI->>Core: Frame + gallery sesi aktif
  Core-->>AI: Track decision + kandidat
  AI-->>Edge: Decision saja
  Edge->>API: Recognition event idempoten
  API->>API: Validasi sesi/roster/duplikat/grace
```

`SessionGalleryCache`: memory-only, key `(device_id, session_id)`, hanya
snapshot aktif timezone-aware; expiry = min(server expiry, akhir sesi,
`max_age`); invalidate per device / expire / restart (temporal track ikut
dibersihkan). `CoreApiGalleryProvider` mengambil gallery via device runtime
Core API (decrypt template sesuai scope device/lab/sesi/model); cache memory
bertahan saat Core API outage sampai expiry; restart butuh Core API lagi.
Tidak ada route upload gallery publik.

Konfigurasi: file model YuNet/SFace lokal provisioned (startup tidak pernah
download; command setup eksplisit bisa mengunduh pinned). Quality/recognition
policy (termasuk threshold terkalibrasi) diterbitkan admin di **AI & kamera**;
AI Central poll Core API via `PRESENSI_AI_CONFIG_SYNC_TOKEN`, validasi
allowlist, rebuild runner, laporkan revisi di `/health`. Tanpa runner valid
→ degraded, tanpa recognition. Outage Core API sementara → policy terakhir
tetap dipakai, sync dilaporkan unavailable; threshold kosong → tetap degraded
(tidak fallback ke nilai tebak). `/health` = process check; `/metrics` =
bounded count + p50/p95 latency burst (agregat, tanpa label student/device;
akses dibatasi jaringan operasi). Liveness default disabled.

## edge-agent / STB gateway

Dua mode runtime via `mode` di YAML. `AI_EDGE` inference lokal; `STB_GATEWAY`
jalur ringan ARM64 tanpa import/instansiasi pipeline recognition.

STB: satu device UVC mode V4L2 (contoh 640×360@10 FPS; tolak runtime di atas
1280×720/15 FPS), gate murah (frame-difference grayscale 160×90, brightness,
Laplacian-variance) + periodic sampling fallback, cooldown, encode maks 5 JPEG
quality-passing in-memory → POST ke burst endpoint AI Central terautentikasi.
Tanpa tulis disk; respons service tanpa image/embedding. Discovery sesi aktif
via Core API per lab device; tolak discovery ambigu (>1 sesi aktif). Deadline
offline lokal = min(cache API, akhir sesi jadwal). Keputusan AI diteruskan ke
Core API sebagai recognition-event allowlisted; hanya payload itu masuk outbox
SQLite FIFO terurut (+ dead-letter; 401/403 TIDAK pernah di-retry — picu
rotasi/dead-letter, tampilkan ke operator). Retry lain: backoff eksponensial
untuk network/5xx/rate-limit. Frame burst gagal tidak disimpan; sampling kamera
lanjut. Auth: bearer device high-entropy per device, provisioned sekali admin;
renewal overlap 24 jam via `token_file` (Linux: replace atomik, owner-only;
Windows service: ACL akun service).

AI_EDGE: native di PC lab; enumerasi index kamera, buka mode requested
(resolusi/FPS), `recognition-core` dengan frame stride (capture cadence ≠
sampling detector). Model YuNet/SFace dari path lokal (installer commissioning
download + checksum; runtime tidak download). Quality/sampling/temporal/margin
terkalibrasi dari dashboard per device (poll 15 detik, revision reported,
cache non-biometrik untuk restart saat outage). Single camera track; tolak
frame nol/multi-wajah. Gallery memory scope device+sesi+model/version; expiry
= min(provider expiry, akhir sesi, `cache_max_offline_seconds` default
300 dtk); restart saat offline → fail-closed (outbox SQLite tetap durable).
Outbox hanya kontrak event allowlisted + `event_id` (tolak field ekstra:
image/crop/embedding/kredensial). Event diterima-tapi-respons-hilang → retry
key sama, API kembalikan hasil tersimpan. Event sesi-yang-sudah-tutup tetap
auditable, tanpa attendance.

Preview pra-sesi AI_EDGE: endpoint loopback `127.0.0.1:8765`, hanya saat
browser operator (ADMIN/LABORANT) di host yang sama + token singkat lokal
(setelah validasi bearer operator ke Core API); tidak ada listener untuk
STB_GATEWAY. Sampling YuNet + quality assessor maks 1×/750 ms; overlay oval
hijau (lolos face-size/sharpness/brightness) vs amber (sesuaikan framing/
pencahayaan) — hijau bukan match identitas. Nama kandidat/frame/template hanya
di memory; layar depan publik hanya menampilkan roster + hasil final setelah
Core API konfirmasi. Threshold belum terkalibrasi → recognition dijeda
(`waiting_for_calibration`), preview tetap jalan.

Log diagnostik dev: `PRESENSI_EDGE_PERFORMANCE_LOGS=1` → record JSON
`edge_performance_window` tiap 10 detik (FPS capture/preview, p50/p95 per
tahap; tanpa nama/skor/frame/embedding/token). Liveness contoh disabled;
kandidat anti-spoof belum cleared (lihat models.md). Semua angka performa
menunggu hardware nyata: **MANUAL HARDWARE TEST REQUIRED**.
