# Kamera dan model lokal

Panduan ini membedakan tiga hal yang sering terlihat sama: kamera di halaman
enrollment browser, kamera untuk pengenalan saat presensi, dan preview lokal
untuk memasang kamera. Tidak ada live video kamera edge yang dikirim ke
dashboard guru.

## Unduh model YuNet dan SFace

Dari root repository:

```powershell
# Windows PowerShell atau terminal Ubuntu dengan Python project aktif
python scripts/download_face_models.py
```

Model disimpan di `models/weights/`, folder yang diabaikan Git. Script mengambil
file OpenCV Zoo yang versinya dan SHA-256-nya dipatok; ukuran/checksum yang tidak
cocok akan ditolak. File ini tidak ikut build/deploy otomatis kecuali volume
model dipasang dan path dikonfigurasi.

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
python scripts/download_face_models.py
presensi-camera-calibration --list-cameras --scan-max-index 1
presensi-camera-calibration --yunet-model models/weights/face_detection_yunet_2023mar.onnx --camera-index 0 --duration-seconds 60 --report camera-calibration.json
```

Ubuntu Desktop:

```bash
python3 -m venv .venv-camera-calibration
. .venv-camera-calibration/bin/activate
python -m pip install -e 'apps/edge-agent[camera-preview]' -e 'libs/recognition-core'
python scripts/download_face_models.py
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
`run` mulai capture dan inference tanpa jendela preview. Ubuntu memakai perintah
`python3 -m ...` yang sama dan backend `v4l2`. Device harus terdaftar dan
credential tersimpan di file yang ACL/permission-nya dibatasi. Jangan isi nilai
threshold tebakan: agent memang menolak config AI_EDGE bila dua threshold belum
diisi.

Pada STB_GATEWAY, kamera tetap dibuka native oleh edge-agent tetapi inference
berjalan di AI service pusat. Letakkan YuNet/SFace di host AI server dan set
path Compose berikut; jangan salin model ke STB untuk attendance:

```dotenv
PRESENSI_AI_MODELS_DIR=./models/weights
PRESENSI_AI_YUNET_MODEL_PATH=/models/face_detection_yunet_2023mar.onnx
PRESENSI_AI_SFACE_MODEL_PATH=/models/face_recognition_sface_2021dec.onnx
PRESENSI_AI_MODEL_VERSION=opencv-zoo-sface-2021dec
PRESENSI_AI_MIN_TOP1_SIMILARITY=
PRESENSI_AI_MIN_TOP1_TOP2_MARGIN=
```

Jalankan development central stack dengan:

```sh
python scripts/start-local.py --central
```

Untuk production, lihat runbook [AI_EDGE](deployment/ai-edge.md)
atau [AI_CENTRAL + STB](deployment/ai-central-stb.md) untuk provisioning
credential, service systemd, dan upgrade.

Untuk produksi, systemd menjalankan agent headless setelah boot. Tidak ada
endpoint live-preview pada dashboard atau systemd service. Jalankan utility
calibration secara manual pada sesi desktop lokal sebelum menyalakan service;
hentikan service terlebih dahulu bila ia sedang memegang webcam. Pada STB
gateway, gunakan capture hemat CPU dari contoh `STB_GATEWAY`; STB tidak memuat
SFace/YuNet untuk inference. Preview diagnostik tetap alat lokal terpisah, bukan
stream jaringan.

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
