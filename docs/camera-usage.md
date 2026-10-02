# Kamera dan model lokal

Untuk pembagian konfigurasi AI_EDGE/STB, pengaturan mana yang dapat diubah,
dan batas dashboard saat ini, lihat [panduan konfigurasi device](architecture/device-configuration.md).

Panduan ini membedakan tiga hal yang sering terlihat sama: kamera di halaman
enrollment browser, kamera untuk pengenalan saat presensi, utility kalibrasi,
dan preview operasional lokal. Edge-agent menyediakan satu preview loopback yang
bisa dibuka dashboard ADMIN/LABORANT pada host AI_EDGE. Live video tidak dikirim
ke dashboard guru/komputer lain.

## Model YuNet dan SFace

Setup lokal dan installer AI_EDGE mengunduh model ini secara otomatis. Untuk
pemulihan atau provisioning server production, jalankan downloader dari root
repository:

~~~powershell
# Windows PowerShell
py -3 scripts/download_face_models.py
~~~

~~~bash
# Ubuntu
python3 scripts/download_face_models.py
~~~

Model disimpan di `models/weights/`, folder yang diabaikan Git. Script mengambil
file OpenCV Zoo yang versinya dan SHA-256-nya dipatok; ukuran/checksum yang tidak
cocok akan ditolak. File ini tidak masuk Git atau image container; installer menaruhnya pada host model yang sesuai dan Docker membacanya melalui volume read-only.

YuNet dipakai untuk deteksi dan kotak wajah. SFace dipakai untuk embedding dan
pencocokan. File YuNet sesuai adapter OpenCV 4 saat ini. SFace sudah terunduh
untuk local development/evaluation, tetapi jangan deploy sebelum sekolah meninjau
ketidakjelasan provenance/izin pretrained weight yang dicatat di
[models.md](models.md). File model bukan threshold terkalibrasi dan belum
membuktikan akurasi di webcam kelas.

## Preview kamera lokal untuk posisi/pencahayaan

Preview diagnostik membuka webcam langsung melalui OpenCV di komputer tempat
command dijalankan. Ia menampilkan FPS terukur, kotak wajah YuNet, ukuran wajah,
blur, brightness proxy, dan peringatan sederhana. Preview ini tidak membuat
attendance dan tidak menyimpan frame. Tutup dengan `Q` atau `Esc`.

Perlu virtual environment terpisah: preview memakai `opencv-python` dengan
jendela desktop, sementara agent/API development memakai OpenCV headless. Jangan
pasang dua varian OpenCV itu dalam virtual environment yang sama.

Windows PowerShell:

```powershell
py -3 -m venv .venv-camera-calibration
.\.venv-camera-calibration\Scripts\Activate.ps1
python -m pip install -e "apps/edge-agent[camera-preview]" -e "libs/recognition-core"
py -3 scripts/download_face_models.py
presensi-camera-calibration --list-cameras --scan-max-index 1
presensi-camera-calibration --yunet-model models/weights/face_detection_yunet_2023mar.onnx --camera-index 0 --duration-seconds 60 --report camera-calibration.json
```

Ubuntu Desktop:

```bash
python3 -m venv .venv-camera-calibration
. .venv-camera-calibration/bin/activate
python -m pip install -e 'apps/edge-agent[camera-preview]' -e 'libs/recognition-core'
python3 scripts/download_face_models.py
presensi-camera-calibration --list-cameras --scan-max-index 1
presensi-camera-calibration --yunet-model models/weights/face_detection_yunet_2023mar.onnx --camera-index 0 --duration-seconds 60 --report camera-calibration.json
```

Pilih index yang dilaporkan `--list-cameras`, lalu ganti `--camera-index` bila
perlu. Tutup service/agent yang sedang memakai kamera sebelum membuka preview.
JSON report hanya berisi agregat dan mode kamera; simpan report di lokasi
privat. Preview pada Ubuntu tanpa desktop/GUI tidak dapat membuka jendelanya.

## Development: enrollment camera di browser

Di Windows 11 buka **Settings → Privacy & security → Camera**, aktifkan
**Camera access** dan **Let desktop apps access your camera**. Di Windows 10,
buka **Settings → Privacy → Camera** dan izinkan akses desktop. Setelah itu,
izinkan kamera untuk `127.0.0.1` pada prompt browser. [Panduan Microsoft untuk
izin kamera Windows](https://support.microsoft.com/en-us/windows/privacy/manage-app-permissions-for-a-camera-in-windows)
menjelaskan pengaturan desktop app untuk Windows 10/11.

1. Start API/database dengan `py -3 scripts/dev.py dev-up` (Ubuntu:
   `python3 scripts/dev.py dev-up`), lalu Vite dengan
   `npm ci --prefix apps/web` dan `npm --prefix apps/web run dev`.
2. Atur `.env` agar API container dapat membaca model dari mount read-only:

   ```dotenv
   PRESENSI_AI_MODELS_DIR=./models/weights
   PRESENSI_ENROLLMENT_YUNET_MODEL_PATH=/models/face_detection_yunet_2023mar.onnx
   PRESENSI_ENROLLMENT_SFACE_MODEL_PATH=/models/face_recognition_sface_2021dec.onnx
   PRESENSI_ENROLLMENT_MODEL_VERSION=opencv-zoo-sface-2021dec
   ```

3. Jalankan `py -3 scripts/dev.py dev-up` lagi agar konfigurasi Compose dibaca.
   Model dipakai backend saat enrollment; browser tidak mengunduh ONNX.
4. Buka `http://127.0.0.1:5173`, masuk sebagai ADMIN/LABORANT, lalu buka
   **Pendaftaran siswa**. Pilih kelas dan siswa; browser akan meminta izin
   kamera ketika capture dimulai. Setelah countdown, UI menangkap empat frame
   selama beberapa detik dan mengirimkannya ke API.

Preview enrollment memakai webcam komputer yang menjalankan browser. Jika web
dibuka dari laptop operator, kamera yang dipakai adalah kamera laptop operator,
bukan webcam PC server yang jauh. Browser memerlukan izin kamera. `localhost`
dan `127.0.0.1` tersedia sebagai secure context untuk development; alamat LAN
HTTP biasa umumnya tidak. Production harus memakai HTTPS agar `getUserMedia`
tersedia dan izin browser dapat diberikan.

Kamera browser dan native edge-agent bisa berebut perangkat UVC yang sama.
Selesaikan/tinggalkan enrollment dan hentikan salah satu pemakai kamera sebelum
menjalankan yang lain.

## Development/deployment: kamera attendance native

Untuk AI_EDGE, webcam dicolok ke PC edge dan dibuka oleh native `edge-agent`,
bukan Docker Compose. Gunakan contoh config, set model path lokal, API URL,
device UUID/token, dan nilai threshold hasil kalibrasi:

```yaml
mode: AI_EDGE
camera:
  index: 0
  backend: auto # Windows: dshow atau msmf; Ubuntu: v4l2
models:
  yunet_path: ../../../models/weights/face_detection_yunet_2023mar.onnx
  sface_path: ../../../models/weights/face_recognition_sface_2021dec.onnx
  version: opencv-zoo-sface-2021dec
recognition:
  min_top1_similarity: null # wajib diisi setelah kalibrasi lokal
  min_top1_top2_margin: null # wajib diisi setelah kalibrasi lokal
```

Install extra kamera dan core ke virtual environment edge-agent:

```powershell
python -m pip install -e "apps/edge-agent[camera]" -e "libs/recognition-core[opencv]"
python -m presensi_edge_agent --config apps/edge-agent/config/edge-agent.yaml cameras
python -m presensi_edge_agent --config apps/edge-agent/config/edge-agent.yaml status
python -m presensi_edge_agent --config apps/edge-agent/config/edge-agent.yaml run
```

`cameras` enumerasi index; `status` mengecek koneksi API, config, dan kamera;
`run` mulai capture dan inference tanpa jendela kalibrasi GUI. Ubuntu memakai perintah
`python3 -m ...` yang sama dan backend `v4l2`. Device harus terdaftar dan
credential tersimpan di file yang ACL/permission-nya dibatasi. Jangan isi nilai
threshold tebakan: agent dapat berjalan dalam status `waiting_for_calibration`
tanpa threshold, tetapi inference/keputusan presensi tetap dijeda.

Saat `AI_EDGE`, agent menyalakan preview dashboard lokal pada
`http://127.0.0.1:8765` (juga menerima `localhost`) dengan bind loopback saja.
Dashboard Vite pada host yang sama menggunakan satu stream/frame yang sudah
dimiliki agent; ia tidak membuka device webcam kedua. Masuk sebagai
ADMIN/LABORANT, lalu pilih **Preview kamera** dari sidebar. Menu tersedia saat
ada perangkat AI_EDGE aktif. Gambar di-resize
hingga lebar 640 px, dikirim sebagai JPEG sementara, dan tidak disimpan ke file.
Jika dashboard development berjalan pada origin/port lain, tambahkan origin
localhost yang persis pada `preview.allowed_origins`; jangan gunakan wildcard
atau bind address `0.0.0.0`.

Preview menampilkan kamera, bounding oval kualitas frame, status sesi, dan
status pengenalan. Bagian ini tidak menjalankan diagnostik skor. Saat konfigurasi
threshold belum diterapkan, halaman menyatakan bahwa pengenalan dijeda dan
presensi tidak dicatat. Setelah threshold dikalibrasi dan diterapkan, nama siswa
hanya ditampilkan pada layar operator saat cocok dan pada layar depan setelah
Core API mengonfirmasi presensi.

Preview tetap menampilkan kamera ketika recognition belum siap. Dalam status
`waiting_for_calibration`, belum ada nama yang ditampilkan atau recognition
event yang dibuat. Setelah sesi aktif, template model/version cocok, dan admin
menerbitkan threshold Top-1 serta margin dari laporan kalibrasi, preview dapat
menampilkan nama hanya untuk keputusan `accepted`. API tetap memvalidasi dan
menetapkan attendance final.

Installer camera-device kini menawarkan wizard index kamera, resolusi, dan FPS
requested sebelum pemeriksaan status. Jika dilewati, jalankan wizard lagi dari
venv agent:

```powershell
.\.venv-edge-agent\Scripts\presensi-edge-agent.exe --config apps/edge-agent/config/edge-agent.yaml configure-camera
```

```bash
.venv-edge-agent/bin/presensi-edge-agent --config apps/edge-agent/config/stb-gateway.yaml configure-camera
```

Wizard membuka kamera dan menunjukkan resolusi aktual dari frame serta FPS
driver/pengukuran singkat. OpenCV menggunakan index, sebab label kamera tidak
seragam lintas backend. FPS/resolusi adalah request ke driver dan dapat
bernegosiasi; verifikasi kembali lewat `status` dan **Preview kamera** pada host
AI_EDGE fisik. Untuk STB, capture aktual di atas 1280×720 ditolak.

Pada STB_GATEWAY, kamera tetap dibuka native oleh edge-agent tetapi inference
berjalan di AI service pusat. Letakkan YuNet/SFace di host AI server dan set
path Compose berikut; jangan salin model ke STB untuk attendance:

```dotenv
PRESENSI_AI_MODELS_DIR=./models/weights
PRESENSI_AI_YUNET_MODEL_PATH=/models/face_detection_yunet_2023mar.onnx
PRESENSI_AI_SFACE_MODEL_PATH=/models/face_recognition_sface_2021dec.onnx
PRESENSI_AI_MODEL_VERSION=opencv-zoo-sface-2021dec
```

Jalankan development central stack dengan:

```sh
python scripts/start-local.py --central
```

Untuk production, lihat runbook [AI_EDGE](deployment/ai-edge.md)
atau [AI_CENTRAL + STB](deployment/ai-central-stb.md) untuk provisioning
credential, service systemd, dan upgrade.

Untuk produksi, systemd menjalankan agent headless setelah boot. Pada AI_EDGE,
preview lokal tetap hanya bind ke loopback dan membutuhkan otorisasi operator;
preview tidak tersedia melalui jaringan. Jalankan utility calibration secara
manual pada sesi desktop lokal sebelum menyalakan service; hentikan service
terlebih dahulu bila ia sedang memegang webcam. Pada STB gateway, gunakan
capture hemat CPU dari contoh `STB_GATEWAY`; STB tidak memuat SFace/YuNet untuk
inference. Preview diagnostik tetap alat lokal, bukan stream jaringan.

Menu **AI & kamera** di dashboard mengelola kualitas enrollment, kualitas frame,
sampling, jumlah frame yang perlu sepakat, threshold terkalibrasi untuk AI_EDGE
atau AI Central, dan burst/filter STB. Perubahan disimpan sebagai revision dan
agent/service menariknya otomatis, tanpa restart. Threshold hanya boleh diisi
dari laporan kalibrasi lokal; halaman readiness juga memperlihatkan revision
yang diterapkan. Kamera fisik, index, resolusi/FPS, model file/version, liveness,
URL, dan credential tetap dikelola pada host; jalankan ulang wizard kamera
langsung di host saat perangkat perlu diubah.

## Batas fungsi saat ini

- Halaman enrollment memiliki browser preview; dashboard attendance hanya
  menampilkan jumlah/status dan event yang sudah disaring, bukan foto/video.
- Preview calibration lokal memakai YuNet; SFace tidak dibutuhkan untuk kotak
  wajah atau pemeriksaan pencahayaan.
- Model saja belum mengaktifkan attendance. Diperlukan active session, snapshot
  roster, template terenkripsi dengan model/version yang cocok, device credential,
  nilai threshold hasil kalibrasi, dan edge-agent/AI-service yang terhubung.
- SFace belum diberi izin penggunaan operasional oleh dokumen ini; liveness
  contoh tetap nonaktif dan harus memakai kontrol sesi/fallback yang disetujui.
- Gunakan relawan dewasa yang setuju untuk uji kamera; jangan menyimpan atau
  mengirim foto siswa sebagai bukti kalibrasi.
