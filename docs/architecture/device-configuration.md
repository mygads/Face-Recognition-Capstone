# Konfigurasi server dan device kamera

Dokumen ini membedakan konfigurasi server, pilihan kamera saat instalasi, dan
kebijakan pengenalan yang bisa dikelola admin dari web. `AI_EDGE` dan
`STB_GATEWAY` tetap memakai API/domain attendance dan recognition-core yang sama;
lokasi inference menentukan setting yang berlaku.

## Pembagian konfigurasi

| Pengaturan | AI_EDGE pada PC lab | STB_GATEWAY pada Armbian | Lokasi pengaturan |
| --- | --- | --- | --- |
| URL Core API | Wajib; harus dapat dijangkau PC kamera | Wajib; harus dapat dijangkau STB | Bundle saat instalasi, tersimpan lokal di YAML |
| URL AI Central | Tidak dipakai | Wajib; harus dapat dijangkau STB | Bundle saat instalasi, tersimpan lokal di YAML |
| UUID dan credential device | Satu credential per PC kamera | Satu credential per STB untuk Core API dan AI Central | Dibuat di Perangkat; token ditampilkan satu kali dan disimpan ke token file terlindungi |
| Kamera, resolusi, FPS | Wajib | Wajib, batas runtime 1280×720 dan 15 FPS | Wizard installer di host kamera; dapat diulang dengan `configure-camera` |
| YuNet/SFace dan versi model | Berada di PC kamera | Berada di server AI Central, bukan di STB | Dipasang saat provisioning; path/checksum bukan setting dashboard |
| Kualitas enrollment | Min ukuran wajah, sharpness, dan brightness | Sama; enrollment tetap diproses Core API | AI & kamera di dashboard; revisi berlaku pada capture berikutnya |
| Kualitas presensi | Min ukuran wajah, Laplacian sharpness, rentang brightness | Filter proxy brightness dan sharpness pada gateway | AI & kamera; tersinkron per device atau server |
| Identitas dan threshold | Top-1, margin Top-1–Top-2, jumlah frame setuju, stride sampling | Dipilih AI Central; STB tidak menghitung identitas | AI & kamera; threshold butuh referensi laporan kalibrasi |
| Burst gateway | Tidak dipakai | Motion/periodic gate, burst count/interval, JPEG quality | AI & kamera; konfigurasi per STB |
| Liveness | Model dan policy lokal | Model dan policy di AI Central | Tetap pada konfigurasi service sampai model/izin disetujui; tidak diedit dashboard |
| Cache/offline/retry | Gallery memory dan SQLite outbox | Session cache dan SQLite outbox | YAML lokal; ditujukan untuk operasi perangkat, bukan kalibrasi kualitas |

## Perbedaan setting antar-profile

`AI_EDGE` menjalankan YuNet/SFace dan `recognition-core` pada PC kamera. Quality
gate menilai face crop sebelum matching; threshold dan temporal agreement juga
berada pada PC tersebut. Perubahan dari dashboard dikirim ke satu device, lalu
pipeline dimuat ulang secara lokal oleh agent.

`STB_GATEWAY` hanya menangkap gambar, menghitung proxy brightness/sharpness dan
motion, lalu mengirim burst ke AI Central. Threshold identitas, face quality
untuk recognition, model, dan liveness berada pada AI Central. Gateway hanya
memakai setting capture/burst yang sesuai kemampuan hardware.

## Wizard kamera

Installer Windows untuk AI_EDGE dan installer Linux untuk kedua profile
menawarkan wizard kamera. Wizard menampilkan index kamera yang terdeteksi, bukan
meminta operator menebak dan mengetik index bebas. Nama/serial kamera tidak
tersedia konsisten dari backend OpenCV pada semua OS, sehingga pilihan diberi
label index. Wizard juga menawarkan resolusi dan FPS, mencoba mengirim beberapa
frame, lalu menunjukkan resolusi hasil negosiasi driver serta FPS aktual.

Mode yang disimpan adalah permintaan kepada driver. Bila driver memilih resolusi
lain, wizard meminta konfirmasi sebelum menyimpan. Batas STB 1280×720 dan 15 FPS
tetap ditegakkan. Setelah mengganti kamera atau kabel, jalankan lagi wizard:

```powershell
.\.venv-edge-agent\Scripts\presensi-edge-agent.exe --config apps/edge-agent/config/edge-agent.yaml configure-camera
```

```bash
.venv-edge-agent/bin/presensi-edge-agent --config apps/edge-agent/config/stb-gateway.yaml configure-camera
```

Preview kalibrasi (`presensi-camera-calibration`) alat terpisah untuk memeriksa
framing, blur, brightness, ukuran wajah, dan pencahayaan. Browser admin tidak
dapat menemukan kamera yang tersambung ke host lain.

## Pengaturan dari dashboard

Halaman **AI & kamera** (`/app/ai-setup`) memiliki tiga kelompok pengaturan:

1. **Kualitas enrollment** disimpan Core API dan digunakan pada request capture
   berikutnya. Bila belum ada revisi dashboard, Core API memakai default
   environment.
2. **PC edge & STB** menerbitkan konfigurasi kualitas/temporal AI_EDGE atau
   quality/burst STB untuk satu device terdaftar.
3. **AI Central** menerbitkan quality/threshold/temporal policy di server
   inference.

Setiap perubahan menjadi revisi baru di `runtime_configuration_versions` dan
menulis `runtime_configuration.published` ke `audit_logs`. API hanya menerima
field allowlist; setting tidak bisa mengubah secret, URL, path model, kamera,
embedding, atau liveness. Top-1 dan margin harus memiliki nilai berpasangan dan
referensi laporan kalibrasi sebelum diterbitkan. Nilai kalibrasi tidak otomatis
ditentukan dari kualitas gambar.

AI_EDGE dan STB menarik konfigurasi per-device menggunakan device credential
setidaknya setiap 15 detik. Agent melaporkan revisi yang diterapkan atau error
code aman ke Core API. Konfigurasi terakhir yang valid disimpan sebagai file JSON
non-biometrik di direktori state agent untuk digunakan setelah restart ketika
koneksi API terputus. AI Central melakukan pull ke endpoint internal Core API
menggunakan `PRESENSI_AI_CONFIG_SYNC_TOKEN`; rahasia yang sama harus tersedia pada
Core API dan AI Central. `scripts/dev.py` membuat token lokal secara otomatis.
Jika sinkronisasi AI Central belum berhasil, recognition runner tetap nonaktif
dan readiness melaporkan pending/degraded.

Status readiness/perangkat membandingkan revisi yang diminta dengan yang
diterapkan. Perubahan quality/temporal/burst berlaku tanpa restart service.
URL, credential, file model, versi model, dan kamera tetap dikelola saat
provisioning/instalasi host. Perubahan model tetap perlu provisioning dan
verifikasi checksum agar enrollment dan inference menggunakan versi sama.

## Setup deployment dan alamat jaringan

Core API adalah control plane kedua profile. Device harus diberi origin yang bisa
dijangkau dari jaringan kamera:

- `127.0.0.1` hanya tepat bila kamera dan API ada pada komputer yang sama;
- PC/STB lain perlu alamat LAN/VPN atau hostname HTTPS yang bisa dirutekan dari
  VLAN kamera;
- `localhost` pada konfigurasi kamera selalu menunjuk ke host kamera itu sendiri;
- Cloudflare Access/service identity belum didukung agent; gunakan reverse proxy
  HTTPS atau jalur privat yang sudah diuji.

Halaman Perangkat dapat menyimpan default Core API/AI Central origin di browser
admin (`localStorage`); nilai itu bukan system-wide server setting. Bundle tetap
memuat URL, profile, UUID dan credential khusus satu device. Hapus setup bundle
setelah transfer/pemasangan. Command installer tidak menaruh token pada shell
history/process arguments.

Model AI Central dipasang saat provisioning host:

```bash
python3 scripts/download_face_models.py --directory /srv/presensi/models
python3 scripts/download_face_models.py --directory /srv/presensi/models --check
```

Downloader memverifikasi ukuran dan checksum. File model tidak diunduh ulang
ketika service production start. Path file dan versi model tetap menjadi bagian
runbook deployment, bukan editor kebijakan di dashboard.
