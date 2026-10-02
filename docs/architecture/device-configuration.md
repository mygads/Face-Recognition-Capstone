# Konfigurasi server dan device kamera

Dokumen ini membedakan pengaturan satu kali di server, pilihan saat instalasi
kamera, dan tuning yang perlu dikalibrasi per lokasi. Profile `AI_EDGE` dan
`STB_GATEWAY` memakai agent, API attendance, model domain, dan alur event yang
sama; lokasi inference menentukan setting mana yang berlaku.

## Pembagian konfigurasi

| Pengaturan | AI_EDGE pada PC lab | STB_GATEWAY pada Armbian | Lokasi saat ini |
| --- | --- | --- | --- |
| URL Core API | Wajib; harus dapat dijangkau PC kamera | Wajib; harus dapat dijangkau STB | Di setup bundle/perangkat, lalu tersimpan di YAML lokal |
| URL AI Central | Tidak dipakai | Wajib; harus dapat dijangkau STB | Di setup bundle/perangkat, lalu tersimpan di YAML lokal |
| Device UUID dan credential | Satu credential per kamera/PC | Satu credential per STB, dipakai ke Core API dan AI Central | Dibuat pada halaman Perangkat; token ditampilkan sekali dan disimpan installer ke file berizin terbatas |
| Kamera, resolusi, FPS | Wajib | Wajib, batas runtime 1280×720 dan 15 FPS | Installer kini menawarkan wizard kamera; dapat diulang dengan `configure-camera` |
| Model wajah | YuNet dan SFace berada di host PC | Tidak ada model recognition di STB; model berada di AI Central | Installer AI_EDGE mengunduh model pin/checksum; server AI Central diprovision saat setup server |
| Face quality | Minimum ukuran wajah, blur/Laplacian, rentang brightness | Gate ringan brightness dan sharpness sebelum burst | YAML device; belum diedit dari web |
| Identitas dan threshold | Top-1, margin Top-1–Top-2, jumlah frame setuju, stride sampling | Dipilih/dievaluasi oleh AI Central; STB tidak menghitung identitas | YAML AI_EDGE atau environment AI Central; threshold harus berasal dari kalibrasi, bukan tebakan |
| Liveness | Configurable pada proses local recognition | Dijalankan pada service recognition pusat jika model/policy aktif; bukan setting inference STB | Config service dan model yang disetujui; belum ada editor web |
| Sampling/burst | Stride sampling dan pemilihan frame terbaik untuk recognition lokal | Motion/periodic gate, jumlah frame burst dan interval JPEG ke AI Central | YAML lokal; nilai berbeda karena tujuan dan kapasitas hardware berbeda |
| Cache dan offline | Gallery sesi di memory; batas freshness dan event outbox SQLite | Informasi sesi/response sementara di memory; event final di outbox SQLite | TTL/cache/retry di YAML lokal; gallery hilang saat proses restart |
| Auto-start setelah reboot | Perlu service manager OS | systemd pada Armbian | Bukan bagian installer commissioning saat ini; gunakan runbook production |

## Kenapa beberapa opsi hanya ada di satu profile

`AI_EDGE` menjalankan seluruh recognition-core di PC kamera. Karena itu ia
memerlukan YuNet/SFace, threshold kecocokan, kualitas wajah untuk model, dan
sampling temporal. Yang disebut “beberapa frame” pada profile ini adalah bukti
multi-frame untuk satu track; tidak ada upload burst ke service AI.

`STB_GATEWAY` hanya menangkap gambar ringan dan mengirim burst kandidat ke AI
Central. Config-nya memang memiliki camera index/resolusi/FPS, filter brightness
dan sharpness, trigger gerakan/periodik, jumlah burst, kualitas JPEG, reconnect,
cache session, batas offline, dan outbox/retry event. STB tidak memiliki
threshold identitas, gallery embedding, atau model liveness lokal karena
keputusan itu berada di AI Central. Nilai threshold dan versi model disetel
seragam pada service pusat agar enrollment dan inference memakai versi sama.

`quality` dan `gateway` memakai nama section terpisah sebab pengukuran serta
ambang batasnya berbeda. AI_EDGE mengukur kualitas face crop untuk mencegah
embedding dari wajah terlalu kecil/buram/gelap. STB menghitung proxy ringan
pada frame downsampled untuk menghindari upload burst yang tidak perlu.

## Wizard kamera

Installer Windows untuk AI_EDGE dan installer Linux untuk kedua profile kini
menanyakan apakah operator ingin mengatur kamera. Wizard:

1. membuka kamera yang terdeteksi dan menawarkan index OpenCV yang tersedia;
2. menawarkan resolusi dan FPS awal yang sesuai profile;
3. meminta kamera mengirim beberapa frame, lalu menunjukkan resolusi hasil
   negosiasi driver, FPS dari driver, dan FPS pengukuran singkat;
4. menyimpan setting yang dipilih ke `edge-agent.yaml` atau `stb-gateway.yaml`.

Nama/serial kamera tidak tersedia secara konsisten dari backend OpenCV untuk
semua OS, sehingga pilihan memakai index. Nilai yang dipilih adalah request
kepada driver; kamera dapat menegosiasikan mode berbeda. Untuk STB, wizard
menolak mode aktual di atas batas 1280×720. Resolusi/FPS yang tersedia pada
kamera tetap harus dipastikan pada perangkat nyata.

Jika installer dilewati atau perlu mengubah kamera kemudian:

```powershell
.\.venv-edge-agent\Scripts\presensi-edge-agent.exe --config apps/edge-agent/config/edge-agent.yaml configure-camera
```

```bash
.venv-edge-agent/bin/presensi-edge-agent --config apps/edge-agent/config/stb-gateway.yaml configure-camera
```

Perintah `cameras` hanya menemukan index. Wizard di atas mencoba mode dan
menyimpan pilihan. Preview kalibrasi (`presensi-camera-calibration`) adalah alat
terpisah untuk menilai framing, blur, brightness, ukuran wajah, dan lampu; ia
tidak mengganti setting attendance secara otomatis.

## Setup deployment dan alamat jaringan

Core API adalah control plane bersama untuk kedua profile. Pilihan deployment
server (lokal/dev atau production) dilakukan saat menyiapkan server. Device
harus diberi origin yang benar-benar dapat dijangkau dari jaringan kamera:

- `127.0.0.1` hanya tepat jika kamera dan API berada pada komputer yang sama;
- PC/STB lain harus memakai alamat LAN/VPN atau hostname HTTPS yang dapat
  dirutekan dari VLAN kamera;
- `localhost` pada konfigurasi kamera selalu menunjuk ke kamera itu sendiri;
- Cloudflare Access/service identity belum didukung oleh agent. Jangan gunakan
  tunnel publik sebagai pengganti jalur privat yang belum diuji.

Halaman Perangkat menyediakan default Core API/AI Central origin sebelum device
dibuat dan dapat menggunakannya kembali pada setup selanjutnya. Default itu
disimpan di browser admin (`localStorage`) agar tidak menyimpan secret ke API;
ia tidak dibagi ke browser admin lain dan bukan system-wide server setting.
Setiap bundle tetap dapat mengubah URL untuk device/lab yang berbeda. Halaman
`/app/ai-setup` adalah readiness status, bukan editor config atau tombol restart
service. Runtime setting per device masih ditulis ke YAML di host kamera.
Production service configuration tetap dikelola pada host AI server dengan
runbook.

Untuk menghindari mengetik ulang URL dan credential di host kamera, gunakan
tombol **Unduh paket setup perangkat**. Bundle satu device memuat origin,
profile, UUID, model version, dan token, lalu command hasil dashboard membacanya
dari `Downloads/presensi-device-<device-uuid>-setup.json`. Jika operator
membuat bundle di komputer lain, pindahkan melalui USB/SCP ke folder Downloads
host kamera sebelum menjalankan command. Hapus bundle setelah dipakai. Command
tidak menaruh token ke shell history/process arguments. Bootstrap manual yang
dijalankan tanpa bundle tetap meminta URL/credential melalui prompt tersembunyi.

## Perubahan setting lewat dashboard

Dashboard belum mendorong setting runtime ke agent. Satu host kamera memiliki
config lokal dan mungkin sedang offline; perubahan jarak jauh butuh protokol
versi/config, validasi, audit, persetujuan restart, dan rollback agar nilai
threshold/model tidak berubah diam-diam. Sampai mekanisme itu tersedia:

- pengaturan server AI Central diubah lewat secret/environment yang dilindungi
  dan service direstart sesuai runbook;
- setting device diedit pada YAML lokal lalu agent direstart;
- threshold hanya diisi dari laporan benchmark/kalibrasi berversi;
- jangan menyalin threshold antar kamera/lab tanpa validasi.

Provision model AI Central dilakukan sebagai bagian provisioning host server
dengan `python3 scripts/download_face_models.py --directory
/srv/presensi/models`, diikuti `--check`. Downloader memverifikasi ukuran dan
checksum. Service production tidak mengunduh file ketika start/restart; hal ini
membuat startup tidak bergantung pada internet dan perubahan model tetap menjadi
langkah deployment yang bisa ditinjau. Runbook production menyediakan perintah
tersebut sebelum Compose dijalankan.
