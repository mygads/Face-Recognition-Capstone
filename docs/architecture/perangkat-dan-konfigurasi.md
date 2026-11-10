# Perangkat dan Konfigurasi

Core API memiliki device registry. `device_id` = UUID `devices.id` dipakai
konfigurasi agent dan recognition event. Setiap device terikat satu lab aktif
dan terdaftar sebagai `AI_EDGE` (`edge_pc`) atau `STB_GATEWAY`
(`camera_gateway`). Field ini mencatat profile kamera; versi model yang
dilaporkan gateway boleh kosong karena versioning inference milik AI service.

## Registrasi

ADMIN membuat device di `/app/devices` (tipe + lab + profile). Kredensial
bearer high-entropy per device diprovision/rotasi admin: API mengembalikan raw
secret SATU KALI (panel copy/download; panel ditutup → hilang dari halaman,
tidak ada endpoint/UI pengambilan ulang) dan menyimpan hash verifier SHA-256
saja. Bundle setup satu kali (`device UUID, profile, Core API origin, opsional
Central AI origin, model version, raw credential`) diunduh dari dashboard;
transfer via channel tepercaya, pasang di device itu saja, hapus setelah
setup. Installer memakai profile registry untuk memilih inference lokal
AI_EDGE vs forwarding STB_GATEWAY; tidak memutuskan threshold.

Heartbeat `POST /api/v1/devices/{device_id}/device-heartbeat` (kredensial
device) me-refresh `last_seen_at` jam API; body opsional: profile (harus cocok
registry), app/model version, status kamera (`unknown/online/offline/error`),
agregat `p50_ms/p95_ms` — tanpa image/embedding/frame. Heartbeat memperbarui
kredensial expiring bila agent memakai `token_file` terlindungi; verifier lama
overlap 24 jam untuk replace file aman-crash. Discovery sesi aktif + fetch
gallery roster/model cocok memakai kredensial yang sama.
Gallery aktif memakai refresh kondisional (`known_generated_at` → `304` tanpa
re-parse); preview off-session tanpa versi server sehingga agent memakai ulang
cache valid lokal agar tidak full-download tiap poll. Ketidakcocokan pin sesi
gateway vs discovery tercatat `gateway_session_pinned_mismatch`. Reassignment lab
menulis `device.laboratory_assigned` (aktor + UUID lama/baru); assign ke lab
yang sama tidak menambah audit duplikat. Route admin manual
`POST /devices/{id}/heartbeat` tersedia untuk update kesehatan manual.

Freshness: `PRESENSI_DEVICE_HEARTBEAT_TIMEOUT_SECONDS` (default 60, clamp
5–3600; `DEVICE_ONLINE_THRESHOLD_SECONDS` fallback lama). Status dihitung saat
baca: Offline (nonaktif / belum check-in / heartbeat basi), Warning (heartbeat
segar tapi kamera non-online), Online (aktif + segar + kamera online).
Registry refresh tiap 15 detik dan membaca profile server aktif dari AI
readiness; form hanya menawarkan profile yang didukung server. Single-PC
AI_EDGE mengizinkan satu device kamera aktif; AI_CENTRAL mengizinkan STB
gateway lab. Penghapusan = deaktivasi lunak (revoke kredensial kini +
sebelumnya, kamera offline, audit `device.deactivated`); history recognition/
attendance tetap tertaut. Device nonaktif disembunyikan default (filter
**Tampilkan perangkat nonaktif**); reaktivasi wajib provision kredensial baru.

## Konfigurasi per profile

| Pengaturan | AI_EDGE di PC lab | STB_GATEWAY di Armbian | Lokasi |
| --- | --- | --- | --- |
| URL Core API | Wajib, terjangkau PC kamera | Wajib, terjangkau STB | Bundle instalasi → YAML lokal |
| URL AI Central | Tidak dipakai | Wajib, terjangkau STB | Bundle → YAML lokal |
| UUID + kredensial device | Satu per PC | Satu per STB (Core API + AI Central) | Perangkat; token ke file terlindungi |
| Kamera, resolusi, FPS | Wajib | Wajib, batas 1280×720 & 15 FPS | Wizard installer di host kamera |
| YuNet/SFace + versi model | Di PC kamera | Di server AI Central, bukan STB | Provisioning; checksum bukan setting dashboard |
| Kualitas enrollment | Min face size/sharpness/brightness | Sama (enrollment tetap via Core API) | AI & kamera; revisi berlaku capture berikut |
| Kualitas presensi | Min face size, Laplacian sharpness, rentang brightness | Proxy brightness/sharpness di gateway | AI & kamera; sync per device/server |
| Identitas + threshold | Top-1, margin Top-1−Top-2, frame sepakat, stride | Dipilih AI Central; STB tak hitung identitas | AI & kamera; butuh referensi laporan kalibrasi |
| Burst gateway | Tidak dipakai | Motion/periodic gate, burst count/interval, JPEG quality | AI & kamera per STB |
| Liveness | Model + policy lokal | Model + policy di AI Central | Config service; tidak diedit dashboard |
| Cache/offline/retry | Gallery memory + SQLite outbox | Session cache + SQLite outbox | YAML lokal |

URL bisa diubah manual pasca-provisioning tanpa reinstall: AI_EDGE edit
`api.base_url` (YAML) atau `PRESENSI_EDGE_API_BASE_URL`; STB edit
`api.base_url` + `central_ai.base_url` (atau env `PRESENSI_EDGE_API_BASE_URL` /
`PRESENSI_EDGE_AI_BASE_URL`); server AI Central memakai
`PRESENSI_AI_CORE_API_BASE_URL`. Env mengalahkan YAML. `127.0.0.1` hanya untuk
mesin yang sama — jangan pakai dari PC/STB lain. Default URL di halaman
Perangkat hanya mengisi bundle berikutnya (tersimpan di localStorage browser
admin, bukan setting server). Contoh:

```yaml
# host kamera terpisah
api:
  base_url: https://attendance.example.edu
central_ai:
  base_url: https://ai.attendance.example.edu
```

### Peta env override → kunci YAML (edge-agent & STB gateway)

Setiap `PRESENSI_EDGE_*` mengalahkan kunci YAML di bawahnya; YAML tetap
permukaan utama di PC lab/STB. Token langsung (`*_TOKEN`) mengalahkan
`token_file`; token AI jatuh kembali ke token API bila keduanya kosong.

| Env | Kunci YAML | Catatan |
| --- | --- | --- |
| `PRESENSI_EDGE_CONFIG` | (argumen `--config` CLI) | Path file YAML yang dibaca |
| `PRESENSI_EDGE_DEVICE_ID` | `device_id` | Wajib per perangkat |
| `PRESENSI_EDGE_MODE` | `mode` | `AI_EDGE` / `STB_GATEWAY` |
| `PRESENSI_EDGE_API_BASE_URL` | `api.base_url` | URL Core API |
| `PRESENSI_EDGE_API_TOKEN` | (langsung, tanpa kunci YAML) | Mengalahkan `api.token_file` |
| `PRESENSI_EDGE_API_TOKEN_FILE` | `api.token_file` | File kredensial perangkat |
| `PRESENSI_EDGE_AI_BASE_URL` | `central_ai.base_url` | URL AI Central (STB) |
| `PRESENSI_EDGE_AI_TOKEN` | (langsung, tanpa kunci YAML) | Mengalahkan `central_ai.token_file` |
| `PRESENSI_EDGE_AI_TOKEN_FILE` | `central_ai.token_file` | Jatuh kembali ke token API |
| `PRESENSI_EDGE_CACHE_MAX_OFFLINE_SECONDS` | `api.cache_max_offline_seconds` | Plafon offline lokal |
| `PRESENSI_EDGE_CAMERA_INDEX` / `_WIDTH` / `_HEIGHT` / `_FPS` | `camera.index` / `width` / `height` / `fps` | Wizard `configure-camera` |
| `PRESENSI_EDGE_SESSION_ID` / `_STARTS_AT` / `_ENDS_AT` | `gateway.session_id` / `session_starts_at` / `session_ends_at` | Filter opsional; discovery API otoritatif |
| `PRESENSI_EDGE_SAMPLE_EVERY_N_FRAMES` | `recognition.sample_every_n_frames` | Stride sampling |
| `PRESENSI_EDGE_YUNET_MODEL_PATH` | `models.yunet_path` | Tidak dibaca STB gateway |
| `PRESENSI_EDGE_SFACE_MODEL_PATH` | `models.sface_path` | Tidak dibaca STB gateway |
| `PRESENSI_EDGE_MODEL_VERSION` | `models.version` | Wajib cocok galeri |
| `PRESENSI_EDGE_MIN_TOP1_SIMILARITY` | `recognition.min_top1_similarity` | Kalibrasi lokal, berpasangan |
| `PRESENSI_EDGE_MIN_TOP1_TOP2_MARGIN` | `recognition.min_top1_top2_margin` | Kalibrasi lokal, berpasangan |
| `PRESENSI_EDGE_YUNET_SCORE_THRESHOLD` / `_NMS_THRESHOLD` | `recognition.yunet_score_threshold` / `yunet_nms_threshold` | Titik operasi detektor |
| `PRESENSI_EDGE_DETECTION_MAX_WIDTH` | `recognition.detection_max_width` | `0` = mati; untuk PC lemah |
| `PRESENSI_EDGE_LOG_LEVEL` | `runtime.log_level` | Level log proses |
| `PRESENSI_EDGE_MAX_OUTBOX_EVENTS` | `runtime.max_outbox_events` | Penuh = frame berikut retry |
| `PRESENSI_EDGE_MAX_DEAD_LETTER_EVENTS` | `runtime.max_dead_letter_events` | Cap anti-penuh disk |
| `PRESENSI_EDGE_PERFORMANCE_LOGS` | (tanpa kunci YAML, `=1`) | Log diagnostik JSON dev |

## Wizard kamera

Installer Windows (AI_EDGE) dan Linux (kedua profile) menawarkan wizard:
index kamera terdeteksi (label index; nama/serial tidak konsisten lintas
backend OpenCV), pilihan resolusi/FPS, kirim beberapa frame percobaan,
tampilkan mode negosiasi driver vs request, minta konfirmasi bila driver
memilih lain. Batas STB tetap ditegakkan. Ulangi setelah ganti kamera/kabel:

```powershell
.\.venv-edge-agent\Scripts\presensi-edge-agent.exe --config apps/edge-agent/config/edge-agent.yaml configure-camera
```

```bash
.venv-edge-agent/bin/presensi-edge-agent --config apps/edge-agent/config/stb-gateway.yaml configure-camera
```

Kalibrasi preview (`presensi-camera-calibration`) alat terpisah untuk
framing/blur/brightness/ukuran wajah/pencahayaan. Browser admin tidak bisa
menemukan kamera di host lain.

## Pengaturan dari dashboard

Halaman **AI & kamera** (`/app/ai-setup`) tiga kelompok: (1) kualitas
enrollment (Core API, capture berikut); (2) kualitas/temporal AI_EDGE atau
quality/burst STB per device; (3) quality/threshold/temporal AI Central.
Setiap perubahan = revisi baru `runtime_configuration_versions` + audit
`runtime_configuration.published`. API hanya terima field allowlist; setting
tak bisa ubah secret, URL, path model, kamera, embedding, liveness. Top-1 dan
margin wajib berpasangan + referensi laporan kalibrasi.

AI_EDGE/STB menarik konfigurasi per device dengan kredensialnya ≥ tiap 15
detik; melaporkan revisi applied/error aman; menyimpan config terakhir valid
(JSON non-biometrik) untuk restart saat API putus. AI Central pull ke endpoint
internal Core API via `PRESENSI_AI_CONFIG_SYNC_TOKEN` (secret sama di kedua
sisi, dari secret store; `scripts/dev.py` membuat lokal otomatis). Sync belum
berhasil → runner nonaktif, readiness pending/degraded. Kegagalan apply yang valid-skema tapi ditolak worker central diteruskan sebagai `central_ai_config_sync_error_code` di `GET ai-readiness`. Perubahan
quality/temporal/burst berlaku tanpa restart; URL, credential, file/versi
model, kamera tetap dikelola provisioning host. Lihat
[AI inferensi](ai-inferensi.md) dan `apps/edge-agent/README.md`.

## Layar kiosk per lab (pairing + PIN)

Selain perangkat kamera, tiap lab dapat punya **layar kiosk** (`kiosk_screens`:
unik per pasangan device+lab, `display_name`, `camera_label`, hash PIN,
`is_active`, `last_seen_at`). Admin mendaftarkan layar di halaman
**Layar Presensi** (`/app/kiosks`), memberi nama dan label kamera, lalu
membuat/mereset PIN yang hanya tampil sekali; pencabutan akses menutup layar.
Layar siswa dibuka di route `/presensi` (tanpa login staf): pilih lab → pilih
kamera → masukkan PIN → board fullscreen. PIN salah dibatasi, data lintas lab
terisolasi, dan token kiosk hanya menerima status kesiapan + hasil tersaring
(tanpa roster, skor, embedding, atau endpoint tulis).
