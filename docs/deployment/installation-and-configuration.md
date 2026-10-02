# Instalasi dan konfigurasi: dari clone sampai production

Dokumen ini menjelaskan urutan pemasangan, siapa mengatur tiap konfigurasi, dan
status kemampuan yang benar-benar tersedia. Untuk perintah deployment lengkap,
ikuti runbook khusus di bagian akhir; contoh nilai domain/IP bukan nilai siap pakai.

## 1. Komponen sistem

| Komponen | Fungsi | Di mana berjalan |
| --- | --- | --- |
| `apps/web` | Vue dashboard untuk akun, kelas, siswa, jadwal, sesi, enrollment, perangkat, dan laporan. Browser hanya mengakses kamera untuk enrollment. | Vite native saat development; file statis di belakang Nginx saat production. |
| `apps/api` (Core API) | Login/RBAC, master data, session roster, enrollment, device auth, attendance validation, audit, reports. Hanya API ini yang membuat keputusan presensi final. | Docker Compose development/production di server. |
| PostgreSQL | Menyimpan data sekolah, audit, recognition events, attendance, dan embedding terenkripsi. | Container jaringan privat server; jangan buka port DB ke Internet. |
| `apps/edge-agent` — `AI_EDGE` | Membuka webcam, mengambil frame, menjalankan `recognition-core`, cache roster, mengirim event, dan antrekan offline. | Native di PC yang memiliki kamera. Model inference ada di PC itu. |
| `apps/edge-agent` — `STB_GATEWAY` | Membuka webcam UVC, sampling/motion gate ringan, mengirim burst JPEG ke AI Central, meneruskan hasil. Tidak mengenali identitas lokal. | Native di STB ARM64 dengan image Linux yang didukung, misalnya Armbian yang sudah diuji. |
| `apps/ai-service` — `AI_CENTRAL` | Menerima burst dari STB, melakukan inference dengan shared `recognition-core`, mengembalikan keputusan kandidat. | Server Ubuntu; hanya dipakai pada profile central. |
| `libs/recognition-core` | Pipeline Python bersama untuk detection, quality, alignment, embedding, matching, dan temporal decision. Bukan service yang dijalankan sendiri. | Dipanggil edge-agent atau AI service. |
| Nginx/reverse proxy | TLS, Vue static hosting, dan routing `/api`; pada central profile juga proxy terbatas untuk AI. | Server Ubuntu production. |

`AI_EDGE` dan `AI_CENTRAL` adalah lokasi inference. `STB_GATEWAY` adalah mode
kamera ringan yang mengirim frame ke AI_CENTRAL. Satu laptop development dapat
menjalankan beberapa proses lokal, tetapi tidak menambah profile recognition.

## 2. Yang dikonfigurasi lewat web, CLI, dan file

| Pengaturan | Dashboard web | Installer/CLI | `.env` atau YAML / operator |
| --- | --- | --- | --- |
| User, role, class, student, lab, schedule/session | Ya | — | — |
| Device UUID/profile/lab dan credential | Ya; credential ditampilkan sekali | Installer memvalidasi credential dan mengambil profile dari API | Token disimpan pada file terlindungi di host kamera. |
| URL Core API | Setup perangkat/admin | Ya, installer kamera menanyakan origin Core API | Tetap harus dapat dijangkau dari host kamera. `127.0.0.1` hanya untuk mesin yang sama. |
| URL AI Central untuk STB | Tidak mengatur service lokal STB | Ya, installer Linux menanyakannya untuk `STB_GATEWAY` | Ditulis ke `stb-gateway.yaml`. |
| Kamera index, ukuran capture, FPS, backend | Web tidak dapat enumerasi kamera pada komputer lain | **Belum ada pilihan kamera di wizard.** Installer menampilkan daftar yang ditemukan dan memakai default YAML. | Pilih/edit index, resolusi, FPS, backend di YAML pada host kamera; preview/calibration utility berjalan di host itu. |
| Unduh model YuNet/SFace | Tidak ada tombol download | Otomatis pada startup development dan installer `AI_EDGE`; bukan pada `STB_GATEWAY` | AI Central production diprovision dengan downloader checksum-pinned saat setup server; model tidak diunduh saat service production boot. |
| Threshold Top-1 dan Top-1/Top-2 margin | **Belum bisa diubah di dashboard.** Halaman AI & kamera hanya menampilkan status. | Installer belum meminta threshold | Harus diisi dari hasil kalibrasi untuk profile/model yang tepat di environment AI Central atau YAML AI_EDGE. Nilai kosong berarti inference belum siap. |
| Camera quality, sampling, burst, retry, cache | Tidak | Wizard belum menawarkan semua pilihan ini | Nilai awal berada di profile YAML; tune/ukur pada kamera dan ruangan sebenarnya. |
| Liveness | Tidak | Tidak | Tetap nonaktif pada contoh. Kandidat model perlu persetujuan lisensi dan kalibrasi terpisah. |
| Start/restart service production | Tidak; tidak ada tombol restart service | Installer saat ini hanya menawarkan menjalankan agent di terminal | Restart AI/API lewat Docker Compose supervisor; restart kamera production lewat systemd sesuai runbook. |
| Domain, TLS, firewall, backup, secret store | Tidak | Tidak ada wizard production satu-perintah | Dikonfigurasi operator server mengikuti runbook sekolah. |

### Kamera yang dimaksud ada dua

1. **Enrollment:** halaman web meminta izin kamera browser operator, lalu mengirim
   beberapa capture sementara untuk diproses API. Capture tidak dijadikan video
   atau file wajah tersimpan secara default.
2. **Presensi:** webcam terhubung ke PC edge atau STB; proses native edge-agent
   yang membuka device kamera. Dashboard tidak bisa memilih kamera remote atau
   menampilkan preview live kamera lab. Gunakan CLI/calibration utility langsung
   di host kamera.

## 3. Setup development dari fresh clone

Windows membutuhkan Git, Docker Desktop + WSL2, Python 3.11+, dan Node/npm versi
sesuai `apps/web/package.json`. Jika `py -3` belum punya runtime, jalankan
`py install 3.12`, buka ulang PowerShell, lalu gunakan `py -3`. Ubuntu membutuhkan
Git, Docker Engine + Compose, Python 3.11+, dan Node/npm.

Dari terminal di root repo:

~~~powershell
git clone https://github.com/mygads/Face-Recognition-Capstone.git
cd Face-Recognition-Capstone
py -3 scripts/start-local.py
~~~

Di Ubuntu, ganti perintah terakhir dengan `python3 scripts/start-local.py`.
Startup pertama meminta profile:

- `1 — AI_EDGE`: local Core API + PostgreSQL + Vue; tidak menjalankan AI Central.
  Untuk kamera, pasang edge-agent native di mesin yang terhubung ke webcam.
- `2 — AI_CENTRAL`: stack di atas ditambah AI service lokal dalam Docker Compose.
  Cocok untuk menguji STB_GATEWAY flow, tetapi bukan uji kinerja STB/server nyata.

Pilihan disimpan dalam `.env`. Ubah dengan `py -3 scripts/start-local.py
--profile edge` atau `--profile central`; Ubuntu memakai `python3`. Setup lokal
pertama mengunduh YuNet/SFace (~39 MB), memeriksa SHA-256, menjalankan migration
DB/seed role, menyiapkan admin development, memastikan dependency web, dan
menjalankan Vite. Lewati model dengan `--skip-model-download`; unduh setelahnya
dengan `--download-models`. File model berada di `models/weights/`, diabaikan Git.

Buka `http://127.0.0.1:5173`. Akun development awal adalah
`admin@local.test` / `123456789abcd`; ganti password saat login pertama. Jangan
memakai akun ini untuk production. AI Central atau AI Edge tidak akan melakukan
recognition hanya karena bobot model terpasang: thresholds tetap harus
terkalibrasi dan dikonfigurasi.

Hentikan proses Vite/agent dengan Ctrl+C. Hentikan API/database development:

~~~powershell
py -3 scripts/dev.py dev-down
~~~

~~~bash
python3 scripts/dev.py dev-down
~~~

## 4. Install device kamera

### Sebelum membuka installer

1. Di web, buat lab dan data kelas/siswa yang diperlukan.
2. Buka **Perangkat**, buat device pada lab yang tepat, pilih profile:
   `AI_EDGE` untuk PC yang menjalankan model lokal atau `STB_GATEWAY` untuk STB
   yang mengirim burst ke central server.
3. Buat credential device; token hanya ditampilkan sekali. Pada halaman
   Perangkat, simpan default URL Core API/AI Central di browser admin jika
   cocok untuk banyak kamera. Default ini lokal-browser saja; origin tetap dapat
   dioverride per device. Unduh bundle dari panel setup. Bundle memuat
   URL, UUID, profile, versi model, dan token. Pindahkan file ke folder
   Downloads pada host kamera jika dashboard dibuka di komputer lain.
4. Salin command yang dihasilkan Perangkat ke host kamera. Command mengunduh
   source bila host baru atau memakai checkout yang ada pada host sama. Bootstrap
   memvalidasi bundle/profile melalui Core API, memasang dependency, lalu
   installer menulis token file lokal dengan permission terbatas. Tidak perlu
   mengetik URL atau `UUID:token` lagi.

AI_EDGE otomatis mengunduh dan memeriksa YuNet/SFace. Profile STB_GATEWAY tidak
memasang model wajah lokal. Kedua installer menawarkan wizard untuk memilih
camera index, resolusi, dan FPS; kamera mengembalikan beberapa frame percobaan
agar operator melihat mode aktual yang dinegosiasikan driver. Nilai pilihan
tersimpan di YAML lokal. Wizard kemudian menjalankan status check dan menawarkan
agent di terminal.

Gunakan command PowerShell/Bash yang ditampilkan halaman Perangkat. Command itu
menunjuk ke nama file bundle khusus device di folder Downloads.

Wizard belum mengimport threshold dari laporan kalibrasi, mengubah quality/liveness
di dashboard, atau memasang service auto-start. Pengaturan advanced berada di
YAML device atau environment AI Central dan harus direstart sesuai runbook.
Service produksi setelah reboot dipasang terpisah melalui systemd runbook. Hapus
bundle rahasia setelah provisioning.

## 5. Isi konfigurasi per profile

### AI_EDGE — PC lab menjalankan inference

File awal: `apps/edge-agent/config/edge-agent.example.yaml`; installer menulis
`edge-agent.yaml`. Isinya mencakup:

- `mode`, `device_id`, Core API `base_url`, protected `token_file`;
- heartbeat, request timeout, refresh/cache age dan durable offline outbox;
- `camera.index`, `width`, `height`, `fps`, OS capture `backend`, reconnect;
- YuNet/SFace path dan `models.version`;
- quality minimum face size/blur/brightness;
- recognition sampling, frame count, threshold Top-1/margin;
- optional liveness, disabled by default.

AI_EDGE installer memasang model otomatis ke checkout host, tapi **tidak mengisi
threshold**. Calibrated threshold dan model version harus cocok dengan enrolled
template dan approved evaluation report. Deployment AI_EDGE API juga memerlukan
YuNet/SFace yang sama untuk enrollment; mount model read-only sesuai API env.

### STB_GATEWAY — kamera ringan + AI_CENTRAL

File awal: `apps/edge-agent/config/stb-gateway.example.yaml`. Isinya:

- device/lab identity via Core API credential, Core API URL dan AI Central URL;
- camera index, resolusi/FPS rendah (contoh 640×360, 10 FPS), backend `v4l2`;
- motion threshold, burst interval/count, JPEG quality, brightness/sharpness gate;
- heartbeat, retry, cache dan SQLite outbox;
- model paths kosong dan tidak dipakai; STB tidak perlu SFace/YuNet identity model.

Nilai motion/camera adalah starting point hardware-specific, bukan jaminan
kualitas. AI Central server memegang model path/version dan threshold di
`.env.ai-central`; STB mengirim burst lewat trusted LAN/TLS.

### AI_CENTRAL — server inference

Environment production template: `infra/deployment/ai-central.env.example`.
Atur origin Core API, YuNet/SFace model path/version, timeout/rate limit, dan
Top-1/margin threshold. Threshold kosong membuat `/health` degraded dan service
tidak membuat recognizer. Pada production model files diprovision saat install
server dengan checksum downloader; proses AI tidak mengunduh model saat startup.
Restrict AI route ke network perangkat; PostgreSQL dan service ports tidak
publik. Restart lewat supervisor setelah mengubah `.env`.

### Core API/server web

`infra/deployment/ai-edge.env.example` atau `ai-central.env.example` mencakup DB
owner/API role secrets, JWT secret, AES template keyring, CORS origin, model path
untuk enrollment, retention dan heartbeat timeout. Simpan file environment
production `root:root`, mode `0600` atau gunakan secret manager. Root `.env`
dan `docker-compose.yml` adalah development configuration; jangan menyalinnya
langsung ke server production.

## 6. Dashboard yang ada dan yang belum

Admin dashboard saat ini dapat mengelola akun, data master, jadwal, device/lab
assignment dan device credential. Menu **AI & kamera** adalah halaman status:
profile service lokal, file model enrollment, status AI Central, versi model yang
dilaporkan device, camera status dan heartbeat. Status edge model berasal dari
heartbeat/version report; halaman itu tidak dapat memeriksa filesystem PC remote.

Dashboard belum dapat mengunduh model, memilih kamera remote, mengubah threshold,
memuat laporan kalibrasi, mengganti YAML device, atau restart AI/API/edge services.
Untuk operasi yang tersedia, UI menggunakan API dengan RBAC; layanan tidak
memberi akses shell dari browser.

## 7. Urutan dari development ke production

Jangan expose development stack ke Internet. Sebelum real school attendance:

1. Sekolah menyetujui purpose/notice/consent or lawful basis untuk biometric
   siswa, akses operator, retention, fallback manual, incident handling dan
   key recovery. Repository bukan sertifikat legal compliance.
2. Tinjau provenance/license YuNet/SFace dan deployment fit. File dapat otomatis
   diunduh untuk evaluasi; izin model untuk operasi sekolah tetap harus dinilai.
3. Kalibrasi Top-1 dan Top-1/Top-2 margin dengan dataset lokal berizin dan kondisi
   kamera lab; laporkan FMR/FNMR dan hasil per kondisi. Jangan pakai nilai internet
   atau tebakan.
4. Lakukan commissioning kamera, field-test lighting/pose/two students, latency,
   CPU/RAM/temp/reconnect pada perangkat nyata.
5. Pilih topology:
   - **AI_EDGE + VPS:** Ubuntu VPS untuk Nginx/TLS, Vue static, Core API dan
     PostgreSQL; setiap PC lab Ubuntu menjalankan AI_EDGE/systemd. Ikuti
     [AI_EDGE runbook](ai-edge.md).
   - **AI_CENTRAL + STB:** Ubuntu central server untuk Nginx/TLS, Core API,
     PostgreSQL dan AI service; tiap STB ARM64 menjalankan STB_GATEWAY/systemd.
     Ikuti [AI_CENTRAL + STB runbook](ai-central-stb.md).
   - **Satu host Ubuntu:** deployment terbatas dengan server/API/DB + Nginx dan
     AI_EDGE pada host kamera sama; ikuti [single-PC deployment](single-pc.md).
     Windows single-host hanya development/supervised demo, bukan unattended
     production package.
6. Siapkan DNS/TLS, private network/firewall, secret store, backup/restore drill,
   reviewed release, migration, monitoring dan systemd restart policy.
7. Jalankan acceptance checklist setelah install, reboot dan network reconnect
   sebelum membuka sesi untuk siswa.

Public DNS untuk web/API biasanya memakai satu origin (mis. `presensi.sekolah.id`)
agar SPA dan `/api` same-origin. AI Central dapat memiliki hostname tersendiri
(mis. `ai.sekolah.id`) dengan route/firewall hanya untuk trusted device VLAN.
Jangan publish PostgreSQL. Cloudflare Tunnel/domain bukan shortcut yang
membuat camera credential aman otomatis; ikuti dokumentasi tunnel dan jangan
aktifkan tunnel yang membypass autentikasi/network restrictions device.

## Dokumen lengkap

- [System/developer guide](../architecture/developer-guide.md)
- [Single computer: dev dan deployment Ubuntu](single-pc.md)
- [AI_EDGE VPS/server runbook](ai-edge.md)
- [AI_CENTRAL + STB Armbian runbook](ai-central-stb.md)
- [Domain dan Cloudflare Tunnel](cloudflare-tunnel.md)
- [Security and privacy](../security-and-privacy.md)
- [Model provenance](../models.md)
- [Walkthrough field-test protocol](../test-plans/walkthrough-field-test.md)
