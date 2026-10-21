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
gallery roster/model cocok memakai kredensial yang sama. Reassignment lab
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
berhasil → runner nonaktif, readiness pending/degraded. Perubahan
quality/temporal/burst berlaku tanpa restart; URL, credential, file/versi
model, kamera tetap dikelola provisioning host. Lihat
[AI inferensi](ai-inferensi.md) dan `apps/edge-agent/README.md`.
