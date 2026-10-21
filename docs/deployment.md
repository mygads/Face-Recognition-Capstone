# Deployment: dari Clone sampai Production

Satu file ini menggantikan folder `docs/deployment/` lama. Otoritas kontrol
keamanan: [security-and-privacy](security-and-privacy.md). Jangan expose stack
development ke Internet. Jangan nyatakan siap operasi sebelum acceptance
checklist lolos; hardware yang belum tersedia = **MANUAL HARDWARE TEST
REQUIRED**. Ganti semua hostname/IP/commit contoh sebelum menjalankan perintah.

## 0. Router: pilih topologi

| Deployment | Sisi kamera | Sisi server | Mulai dari |
| --- | --- | --- | --- |
| AI_EDGE + VPS | Satu native AI_EDGE agent + YuNet/SFace per PC lab; Ubuntu target dokumentasi | Ubuntu VPS: PostgreSQL + Core API (Compose production), Vue statis di Nginx/TLS | Bagian 3 |
| AI_CENTRAL + STB | Satu native STB_GATEWAY per STB ARM64; burst JPEG via LAN tepercaya | Ubuntu server: PostgreSQL + Core API + AI service pusat; Nginx HTTPS | Bagian 4 |
| Satu komputer (dev) | Native edge-agent akses webcam lokal | PostgreSQL/Core API Compose lokal; Vite native; AI service opsional | Bagian 2 |
| Satu host Ubuntu (demo/deploy terbatas) | Native systemd AI_EDGE di host yang sama | Compose production + Nginx + Vue build lokal | Bagian 2 lalu 3 |

Ubuntu Linux adalah target dokumentasi untuk PC edge, semua server, dan STB
(Armbian minimal/server baseline; CasaOS opsional, bukan runtime teruji).
Windows hanya untuk development lokal dan demo supervised — repo tidak
menyediakan installer/service Windows production yang hardened. Pengembangan
dan deployment adalah mode operasi berbeda (hot reload + secret lokal vs rilis
terpin + secret terlindungi + migrasi + backup). Cloudflare Tunnel/domain
bukan pengganti autentikasi FastAPI atau RBAC (lihat Lampiran).

## 1. Konfigurasi kanonis (7 langkah)

1. Clone repo, pasang prasyarat host (Git, Docker + Compose, Python 3.11+,
   Node/npm sesuai `apps/web/package.json`; Windows perlu Docker Desktop +
   WSL2 dan izin kamera desktop; Ubuntu perlu akses device kamera/V4L2).
2. Pilih profile: `1 — AI_EDGE` (Core API/web saja) atau `2 — AI_CENTRAL`
   (+ AI service). Pilihan tersimpan di `.env` (`--profile edge|central`
   untuk mengganti; flag lama `--central` tetap ada).
3. Jalankan startup lokal (buat `.env` + secret acak, migrasi, seed role,
   bootstrap admin, install dependency web, Vite) — detail di Bagian 2.
4. Login `admin@local.test` / `1234abcd` (atau `PRESENSI_BOOTSTRAP_PASSWORD`),
   ganti password (min 12 karakter). Buat lab, kelas, siswa, akun staf,
   jadwal (lihat [fondasi backend](architecture/fondasi-backend.md)).
5. Daftarkan device kamera di **Perangkat**, buat kredensial satu kali,
   unduh bundle setup, jalankan installer di host kamera (lihat
   [perangkat dan konfigurasi](architecture/perangkat-dan-konfigurasi.md)).
6. Terbitkan threshold Top-1 + margin dari laporan kalibrasi lokal di
   **AI & kamera** (tanpa ini recognition degraded/nonaktif; jangan pakai
   nilai tebakan). Selesaikan school approval (tujuan, notice/dasar hukum
   minor, akses, retensi, fallback manual, koreksi, insiden).
7. Jalankan acceptance checklist (Bagian 3/4) sebelum sesi siswa nyata.

Matriks siapa-mengatur-apa:

| Pengaturan | Dashboard web | Installer/CLI | File/env operator |
| --- | --- | --- | --- |
| User, role, master data, jadwal/sesi | Ya | — | — |
| Device UUID/profile/lab + kredensial | Ya (token tampil sekali) | Validasi + ambil profile dari API | Token di file terlindungi host kamera |
| URL Core API / AI Central | Default bundle saja | Installer menanyakan origin | YAML lokal / env; bisa diubah pasca-provisioning lalu restart agent |
| Kamera index, resolusi, FPS | Tidak (browser tak bisa enum kamera remote) | Wizard installer + `configure-camera` | YAML lokal host kamera |
| Model YuNet/SFace | Tidak ada tombol download | Otomatis saat startup dev + installer AI_EDGE | Provisioning server via downloader checksum-pinned; bukan saat boot service |
| Threshold Top-1/margin | Ya, wajib referensi laporan kalibrasi | Tidak | Kosong = degraded; jangan tebak |
| Quality/sampling/temporal/burst | Ya, per device / AI Central | Tidak | Pull otomatis 15 detik, tanpa restart |
| Secret, TLS, firewall, backup, domain | Tidak | Tidak | Operator server mengikuti runbook |

Ganti URL pasca-provisioning: AI_EDGE edit `api.base_url` atau
`PRESENSI_EDGE_API_BASE_URL`; STB edit `api.base_url` + `central_ai.base_url`;
AI Central pakai `PRESENSI_AI_CORE_API_BASE_URL`. Restart agent/recreate
service setelah berubah.

Dua kamera yang berbeda: (1) **enrollment** — browser operator meminta izin
kamera, kirim capture sementara untuk diproses API; (2) **presensi** — webcam
di PC edge/STB dibuka native edge-agent. Preview AI_EDGE hanya di browser
pada host yang sama (`127.0.0.1:8765`); STB_GATEWAY tanpa preview web lokal.

## 2. Satu host: development dan deployment terbatas

Layout dev satu komputer (AI_EDGE): PostgreSQL Docker, Core API Docker,
Vue Vite native (HMR), edge-agent + webcam native, AI service opsional
(profile `central`). Jangan jalankan enrollment dan edge capture bersamaan
bila driver webcam eksklusif.

```powershell
# Windows
py -3 scripts/start-local.py
# Ubuntu
python3 scripts/start-local.py
```

Ganti profile: `--profile edge` / `--profile central`. Lewati/ambil model
menyusul: `--skip-model-download` / `--download-models` (~39 MB,
checksum-verified ke `models/weights/`, diabaikan Git). SFace tetap evaluasi
sampai sekolah meninjau izin. API/DB dev hanya bind loopback; remote kamera
butuh server LAN/reverse proxy deployment.

Kalibrasi kamera memakai venv TERPISAH (preview desktop OpenCV vs headless
agent — jangan campur dua varian OpenCV satu venv):

```bash
python3 -m venv .venv-camera-calibration
. .venv-camera-calibration/bin/activate
python -m pip install -e 'apps/edge-agent[camera-preview]' -e 'libs/recognition-core'
presensi-camera-calibration --list-cameras --scan-max-index 1
```

Untuk backend enrollment, container API membaca model via mount read-only:

```dotenv
PRESENSI_AI_MODELS_DIR=./models/weights
PRESENSI_ENROLLMENT_YUNET_MODEL_PATH=/models/face_detection_yunet_2023mar.onnx
PRESENSI_ENROLLMENT_SFACE_MODEL_PATH=/models/face_recognition_sface_2021dec.onnx
PRESENSI_ENROLLMENT_MODEL_VERSION=opencv-zoo-sface-2021dec
```

Recreate API setelah ubah Compose env: `docker compose up -d --no-deps
--force-recreate api`. Simulasi STB di laptop (STB_GATEWAY + AI_CENTRAL satu
host) hanya simulasi jaringan — bukan uji performa ARM64, driver Armbian,
latency LAN, atau termal STB. Windows single-host hanya development/demo
supervised, bukan paket production unattended.

Readiness gate sebelum presensi nyata: model YuNet/SFace versi sama
enrollment+inference (checksum), threshold terkalibrasi lokal (FMR/FNMR,
prioritas false-accept rendah), satu device + kredensial unik per kamera,
uji sesi tutup/putus/retry/reboot, approval sekolah, tandai hardware yang
belum diuji sebagai MANUAL HARDWARE TEST REQUIRED.

## 3. Runbook AI_EDGE (server + PC lab)

Compose root = development; production memakai
`infra/deployment/compose.ai-edge.yml` (DB, API, migrator; tanpa mapping port
DB; API hanya loopback). Migrator memakai kredensial DB owner; API berjalan
sebagai role aplikasi terpisah (tanpa hak schema). Semua contoh di bawah dari
`/opt/presensi/server` dengan helper:

```bash
cd /opt/presensi/server
dc() {
  sudo docker compose --env-file .env.ai-edge \
    --project-directory "$PWD" \
    -f infra/deployment/compose.ai-edge.yml "$@"
}
```

Proteksi env: salin `infra/deployment/ai-edge.env.example` →
`.env.ai-edge` (`root:root`, `0600`); isi `PRESENSI_RELEASE_TAG` (revisi
terreview), `PRESENSI_MODELS_DIR` absolut, `POSTGRES_IMAGE` digest yang
disetujui, password DB owner ≠ password role API, `JWT_SECRET` ≥32 byte acak,
keyring `PRESENSI_FACE_TEMPLATE_KEYS` + active key ID. Simpan di secret
manager sekolah; backup DB tanpa keyring tak bisa memulihkan template.

Model: provision ke `/srv/presensi/models` via downloader checksum-pinned,
verifikasi (`sha256sum --check SHA256SUMS`); versi SFace YAML edge =
`PRESENSI_ENROLLMENT_MODEL_VERSION` API; sama di semua PC lab. Threshold
kosong = agent waiting, tanpa recognition.

```bash
dc config --quiet && dc build api && dc up -d db
dc --profile ops run --rm migrate
dc run --rm api python -m presensi_api.db.seed_roles
dc run --rm -it api python -m presensi_api.auth.create_user \
  --email admin@example.edu --full-name "School Administrator" --role ADMIN
dc up -d api
curl --fail --show-error http://127.0.0.1:8000/health
sudo ss -lntp | grep -E ':(5432|8000|443)\b'  # 5432 tidak boleh ada; API loopback
```

Nginx (satu varian contoh): Vue build versioned (`npm ci && npm run build` →
`/var/www/presensi/releases/<sha>` + symlink `current`), `map` WebSocket,
log `presensi_safe` (`$uri`, bukan `$request`; tanpa body/Authorization),
`client_max_body_size 17m`, deny `/docs|/redoc|/openapi.json` di semua vhost
publik, proxy hanya `/api/` + `/health`:

```nginx
location /api/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_read_timeout 3600s;
    proxy_send_timeout 60s;
}
location ~ ^/(docs|redoc|openapi\.json) { return 404; }
```

Registrasi: di `/app/devices` buat satu device `edge_pc`/AI_EDGE per lab
(jangan share UUID); **Kredensial → Buat token pertama**; simpan langsung ke
token file PC itu (bukan shell/tiket/log); renewal otomatis bila file writable
service account.

systemd per PC lab: akun `presensi-edge` + grup `video`; software
root-owned; model read-only untuk service; hanya token/outbox writable.
Install venv rilis-lokal, salin `edge-agent-ai-edge.example.yaml` →
`/etc/presensi-edge-agent/edge-agent.yaml`, env UUID, token via prompt
tersembunyi, unit `presensi-edge-agent-ai-edge.service` → enable --now;
cek `active (running)` + device Online di dashboard. Windows hanya demo
supervised (service wrapper sekolah, akun non-admin, ACL `C:\ProgramData\Presensi`).

Backup GPG harian (contoh satu varian; jadwalkan, alert bila gagal, drill
restore terisolasi ≥ kuartalan):

```bash
set -o pipefail
STAMP=$(date -u +%Y%m%dT%H%M%SZ); BACKUP_DIR=/srv/backups/presensi
install -d -m 0700 "$BACKUP_DIR"
dc exec -T db sh -ec \
  'pg_dump --format=custom --no-owner --no-privileges --username="$POSTGRES_USER" --dbname="$POSTGRES_DB"' \
  | gpg --symmetric --cipher-algo AES256 --output "$BACKUP_DIR/presensi-$STAMP.dump.gpg"
sha256sum "$BACKUP_DIR/presensi-$STAMP.dump.gpg"
gpg --decrypt "$BACKUP_DIR/presensi-$STAMP.dump.gpg" | pg_restore --list >/dev/null
```

Restore mengganti isi DB — konfirmasi dua operator + rilis kode/keyring yang
cocok. Upgrade: backup dulu, checkout rilis terreview, rebuild, migrasi via
service `migrate`, verifikasi health + smoke sesi; rollback = symlink/rilis
sebelumnya + restore dump bila skema berubah.

## 4. Runbook AI_CENTRAL + STB_GATEWAY

Topologi contoh (RFC1918, sesuaikan): server `192.168.40.10` (reservasi IP);
`attendance.example.edu` + `ai.attendance.example.edu` DNS internal ke server;
STB `192.168.40.21/22` (reservasi MAC). STB butuh DNS, NTP, HTTPS ke dua
hostname. Jangan buka 5432/8000/8001 ke LAN/Internet; SSH hanya jaringan
admin. Port 443 via Nginx; `ai.*` allowlist VLAN STB.

Server: checkout rilis terreview ke `/opt/presensi/server`; provision model
(downloader checksum-pinned; catat nama/versi/sumber/checksum/tanggal);
env `.env.ai-central` (`0600`): password DB berbeda, JWT ≥32 byte, keyring
AES, `PRESENSI_AI_CORE_API_BASE_URL` HTTPS valid, `PRESENSI_AI_CONFIG_SYNC_TOKEN`
acak ≥32 char di Core API + AI Central (bukan bundle device),
`PRESENSI_AI_DEVICE_TOKENS` dikosongkan (validasi via Core API). Compose
production = base AI_EDGE + overlay AI Central; AI single-worker (cache
gallery, temporal state, limiter, metrics in-memory). Threshold Top-1/margin
dari dashboard + laporan kalibrasi; liveness contoh tetap nonaktif.

vhost `ai.*` (satu varian contoh): allowlist VLAN STB + `deny all`; `/metrics`
hanya monitoring allowlist; deny docs/openapi; burst hanya POST/DELETE:

```nginx
server {
    listen 443 ssl;
    server_name ai.attendance.example.edu;
    client_max_body_size 22m;
    allow 192.168.40.0/24; deny all;
    location = /metrics {
        allow 192.168.10.15; deny all;
        proxy_pass http://127.0.0.1:8001/metrics;
    }
    location ~ ^/(docs|redoc|openapi\.json) { deny all; }
    location ~ ^/api/v1/recognition/sessions/[0-9a-fA-F-]+/(bursts|cache)$ {
        limit_except POST DELETE { deny all; }
        proxy_pass http://127.0.0.1:8001;
        proxy_read_timeout 30s;
        proxy_send_timeout 30s;
    }
    location / { return 404; }
}
```

STB: per board daftar device `camera_gateway`/STB_GATEWAY + lab di
`/app/devices`; unduh bundle `presensi-device-<uuid>-setup.json` via USB/SCP;
bootstrap membaca bundle tanpa mengetik URL/token:

```bash
DEVICE_UUID='<device-uuid>'
export PRESENSI_DEVICE_SETUP_BUNDLE="$HOME/Downloads/presensi-device-${DEVICE_UUID}-setup.json"
curl -fsSL https://raw.githubusercontent.com/mygads/Face-Recognition-Capstone/main/scripts/bootstrap-camera-device.sh | bash
```

Flash Armbian: image ARM64 cocok board (verifikasi upstream), password awal
diganti, update OS, `timedatectl set-timezone Asia/Jakarta` + NTP, reservasi
DHCP per MAC, DNS internal, TLS valid (tanpa `curl -k`). Uji webcam 100 frame
tanpa menyimpan:

```bash
v4l2-ctl --list-devices
sudo v4l2-ctl --device=/dev/video0 --list-formats-ext
sudo v4l2-ctl --device=/dev/video0 \
  --set-fmt-video=width=640,height=360,pixelformat=MJPG \
  --stream-mmap=3 --stream-count=100 --stream-to=/dev/null
```

Unit `presensi-stb-gateway.service`: rilis di
`/opt/presensi-edge-agent/releases/<id>` (rollback = ganti symlink), akun
`presensi-edge` + grup `video`, venv `--system-site-packages`, config
`/etc/presensi-edge-agent/stb-gateway.yaml` (0640), env UUID saja (0600),
token via stdin tersembunyi (owner service, 0600, writable untuk renewal),
`cameras` → `systemd-analyze verify` → `enable --now`. Log wajib bebas
frame/embedding/password/token.

Ganti STB tanpa clone identitas: hentikan service lama, tunggu outbox
terkirim, tinjau dead-letter; nonaktifkan device lama; flash baru; reservasi
DHCP ke MAC baru; daftar UUID + token baru (jangan salin token/env/outbox);
acceptance ulang. Outbox lama terikat `device_id` lama — sinkronkan dengan
UUID/credential lama bila perlu pemulihan, lalu nonaktifkan.

Acceptance (isi per board/kamera/lab; sesi uji + data sintetis/relawan
dewasa; tanpa foto di form): fresh-install (image cocok, password diganti,
DNS/NTP/TLS valid, 5432/8000/8001 tak terjangkau dari STB, 100 frame lolos,
UUID/lab/profile cocok, token 0600, unit active, dashboard Online ≤60 dtk,
alur camera→STB→AI→API tanpa duplikat, tanpa frame/embedding di disk/log);
reboot (IP reserved + NTP, service otomatis, heartbeat ≤60 dtk, outbox utuh,
sesi aktif ditemukan, satu transaksi uji tanpa duplikat); reconnect (agent
hidup saat gagal, cache valid dipakai sampai expiry lalu fail-closed, event
valid terkirim FIFO dengan `event_id` sama, sesi uji baru lolos). Backup/
restore server mengikuti pola Bagian 3 (dump GPG + keyring terpisah).

## Lampiran: Cloudflare Tunnel (opsional)

Hanya untuk akses browser operator tanpa buka inbound router; device memakai
DNS internal/VPN + TLS (agent tidak mendukung Access service token). Named
Tunnel → origin Nginx loopback (bukan port Vite/API/AI/Postgres); tambah
aplikasi Access self-hosted (Allow grup staf + MFA bila ada; hindari Bypass);
Nginx tetap same-origin Vue + `/api/`. Quick Tunnel (`cloudflared tunnel
--url http://localhost:5171 --allowed-mail ...`) hanya demo sintetis sementara
(tanpa SLA; PIN email tak cocok untuk agent). Verifikasi: staf tak bisa
lewati Access/login; agent mencapai DNS internal tanpa halaman login HTML;
5432/8000/8001/Vite/SSH/OpenAPI/metrik tak terjangkau Internet; rotasi token
tunnel bila bocor (jangan ke Git/log/tiket).
