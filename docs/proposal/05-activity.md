# 05 — Activity Diagram

> Satu diagram per fitur. Judul gambar laporan: "Activity Diagram \<kode fitur>".
> Ringkasan per role ada di §5.13–§5.14.

## 5.1 Login (F-01)

```mermaid
flowchart TD
  S([Mulai]) --> I[/Input email dan password/]
  I --> C{Kredensial valid?}
  C -- Tidak --> E1[Gagal: pesan umum tanpa bocorkan akun]
  E1 --> I
  C -- Ya --> W{Wajib ganti password?}
  W -- Ya --> P[/Password baru min 12 char/]
  P --> V{Valid?}
  V -- Tidak --> P
  V -- Ya --> T[Terbitkan akses 15 mnt dan sesi cookie 24 jam]
  W -- Tidak --> T
  T --> D([Masuk dashboard sesuai role])
```

## 5.2 Master data + import (F-02)

```mermaid
flowchart TD
  S([Admin siapkan CSV atau XLSX]) --> U[/Unggah file max 5 MiB, XLSX max 25 MiB/]
  U --> L{Ukuran dan baris lolos? max 10rb}
  L -- Tidak --> R1[Tolak 413 dengan alasan]
  R1 --> S
  L -- Ya --> P[Preview: validasi per baris]
  P --> V{Ada baris invalid?}
  V -- Ya --> R2[Tampilkan error per baris 422]
  R2 --> S
  V -- Tidak --> C[Commit: simpan siswa-kelas-lab]
  C --> E([Selesai tanpa audit])
```

> Commit import tidak menulis `audit_logs`; validasi dan commit hanya
> mengembalikan ringkasan baris valid atau invalid.

## 5.3 Enrollment wajah (F-03)

```mermaid
flowchart TD
  S([Operator pilih siswa]) --> K{Status template?}
  K -- enrolled --> R[Revoke SEMUA template aktif batch ini]
  R --> C
  K -- not enrolled --> C[/Capture 3 sampai 10 frame max 3 MB/]
  C --> Q{Lolos quality gate?}
  Q -- Tidak --> C
  Q -- Ya --> N{Minimal 3 diterima?}
  N -- Tidak --> F([Gagal: ulangi capture])
  N -- Ya --> M[Simpan maks 5 template AES-256-GCM + model name-version]
  M --> D{Mirip siswa lain di atas 0,85?}
  D -- Ya --> W[Peringatan duplicate: verifikasi manual]
  D -- Tidak --> E([Selesai dan audit])
  W --> E
```

> `POST /enrollments` metadata-only (tanpa capture) ditolak 422
> `captures_required`; gunakan `POST /enrollments/captures`. Revoke
> template per batch mencatat jumlah + audit; siswa dinonaktifkan ikut
> me-revoke template aktifnya.

## 5.4 Jadwal praktikum (F-04)

```mermaid
flowchart TD
  S([Admin atau guru isi jadwal]) --> V{Jadwal valid dan referensi aktif?}
  V -- Tidak --> R[Tolak 422]
  R --> S
  V -- Ya --> B{Bentrok kelas-lab-guru termasuk rentang tanggal?}
  B -- Ya --> C[Tolak 409 schedule_conflict]
  C --> S
  B -- Tidak --> E([Jadwal aktif tersimpan])
```

> Operasi jadwal (CRUD) tidak menulis `audit_logs`.

## 5.5 Buka dan tutup sesi (F-05)

```mermaid
flowchart TD
  S([Jadwal eligible hari ini]) --> M{Mode guru?}
  M -- automatic dan dalam jendela --> W[Worker 10 detik auto-open]
  W --> R{Roster kelas kosong?}
  R -- Ya --> SKIP[Lewati: tanpa sesi]
  R -- Tidak --> WA[Status active; opened_by null]
  WA --> D
  M -- manual atau di luar jendela --> O[Guru atau laboran tekan Buka Sesi]
  O --> T[Transaksi: attendance_sessions + snapshot roster aktif]
  T --> G1{Manual-open di dalam jendela?}
  G1 -- Ya --> SA[Status active]
  G1 -- Tidak --> SO[Status manual_override]
  SA --> D
  SO --> D([Dashboard live aktif; device tarik gallery])
  D --> CL{Akhir jadwal atau tutup manual?}
  CL -- Ya --> CSD[Tutup: hanya berjalan ke closed + closed_at]
  CSD --> E([Selesai])
  CL -- Tidak --> D
  SKIP --> E
```

> Guru hanya membuka jadwal miliknya (di luar itu 404 `schedule_not_found`);
> manual-open selalu tersedia sebagai jalur override dan tidak digate `mode`
> policy. Auto-open worker langsung
> berstatus `active` dengan `opened_by` null; hanya jalur manual yang dinilai
> masuk/di luar jendela (`active` vs `manual_override`). Auto-open melewati
> roster kosong (tidak membuat sesi). Tutup hanya bertransisi dari status
> berjalan (`active`, `manual_override`) ke `closed`; sesi yang sudah
> `closed` atau `cancelled` dikembalikan apa adanya tanpa perubahan.

## 5.6 Walk-through otomatis (F-06) — inti penelitian

```mermaid
flowchart TD
  S([Track ACCEPTED kirim matched + kandidat]) --> N1{Sesi dan device dikenal?}
  N1 -- Tidak --> Z404[404 session_not_found atau device_not_found; tanpa event]
  N1 -- Ya --> RP{event_id dikenal?}
  RP -- Fingerprint sama --> OLD[200 hasil tersimpan; replayed true]
  RP -- Payload beda --> C409[409 event_id_reused; tanpa event baru]
  RP -- Baru --> SV[Simpan event sebagai bukti audit]
  SV --> V1{Guru di luar jadwalnya?}
  V1 -- Ya --> R1[Event reason session_not_accessible]
  V1 -- Tidak --> V2{Device aktif, kamera on, lab sama?}
  V2 -- Tidak --> R2[Event reason device_inactive, device_camera_disabled, atau device_laboratory_mismatch]
  V2 -- Ya --> V3{Sesi berjalan?}
  V3 -- Tidak --> R3[Event reason session_inactive]
  V3 -- Ya --> V4{Kandidat di snapshot roster?}
  V4 -- Tidak --> R4[Event reason student_not_found atau student_not_in_session_roster]
  V4 -- Ya --> V5{Outcome matched dan liveness lolos?}
  V5 -- Tidak --> R5[Event reason recognition_not_matched atau liveness_failed]
  V5 -- Ya --> V6{Sudah ada record sesi dan siswa?}
  V6 -- Ya --> R6[Event reason attendance_already_recorded]
  V6 -- Tidak --> GR{occurred_at lewat grace?}
  GR -- Ya --> RL[Record late]
  GR -- Tidak --> PR[Record present]
  RL --> WS[Push WebSocket dashboard]
  PR --> WS
  WS --> E([Selesai])
  R1 --> E
  R2 --> E
  R3 --> E
  R4 --> E
  R5 --> E
  R6 --> E
  OLD --> E
  C409 --> E
  Z404 --> E
```

Status track temporal (`collecting` / `accepted` / `retry_frontal` alias
NEED_FRONTAL_RETRY / `rejected`) bukan outcome event (`matched` /
`ambiguous` / `no_match` / `error` / `redacted`). Aturan mesin:
N frame sepakat (`minimum_agreeing_frames`, terkalibrasi) + Top-1 di atas
threshold + margin Top-1 dan Top-2; galeri satu identitas tidak pernah
accept (`single_identity_gallery`, fail-closed ke retry); margin terlalu
kecil menjadi `ambiguous` + `retry_frontal`; Top-1 di bawah threshold
menjadi `rejected` (`no_match`); bila liveness required, spoof yang lolos
menjadi `rejected` dan inconclusive menjadi retry; liveness opsional yang
inconclusive tidak menghentikan embed/match.

Aturan event dan grace: sesi atau device tak dikenal → 404 tanpa event.
Ingest juga menutup sesi kedaluwarsa sebelum validasi. Jalur device bearer
melewati cek scope guru (perangkat terikat lab/sesi); cek
`session_not_accessible` hanya untuk ingest manusia oleh TEACHER non-ADMIN
di luar jadwalnya.
Event baru disimpan dulu sebagai bukti audit sebelum putusan (matched
tanpa kandidat valid disimpan sebagai `error` agar audit tetap utuh).
Replay memakai fingerprint kanonis: sama → hasil tersimpan
(`replayed: true`); `event_id` sama dengan payload berbeda → 409
`event_id_reused` tanpa event baru. Sepuluh reason resmi, dievaluasi
berurutan: `session_not_accessible`, `device_inactive`,
`device_camera_disabled`, `device_laboratory_mismatch`,
`session_inactive`, `student_not_found`,
`student_not_in_session_roster`, `recognition_not_matched`,
`liveness_failed`, `attendance_already_recorded`. Grace memakai capture time (`occurred_at`):
sesi auto-open → `scheduled_start_at + grace`; sesi manual-open →
`opened_at + grace`; tepat atau di batas = present. Duplikat konkuren
ditahan UNIQUE sesi dan siswa lewat savepoint: event audit tetap
tersimpan, reason `attendance_already_recorded`.

## 5.7 Presensi manual + koreksi (F-07)

```mermaid
flowchart TD
  S([Guru pilih siswa + status + catatan]) --> SC{Guru pemilik jadwal?}
  SC -- Bukan --> NF[404 session_not_found]
  SC -- Ya --> ST{Sesi berjalan?}
  ST -- Tidak --> SI[409 session_inactive]
  ST -- Ya --> SN{Siswa dikenal dan di snapshot?}
  SN -- Tidak --> NR[404 student_not_found atau student_not_in_session_roster]
  SN -- Ya --> DP{Record sesi dan siswa sudah ada?}
  DP -- Ya --> AR[409 attendance_already_recorded; FR tak tertimpa]
  DP -- Tidak --> SV[Record manual + audit attendance.manual_marked]
  SV --> K{Ada kesalahan?}
  K -- Tidak --> E([Selesai])
  K -- Ya --> P[POST koreksi + alasan wajib]
  P --> PE[pending + audit; record final tidak berubah]
  PE --> W([Menunggu kebijakan approval; tanpa endpoint putusan])
  NF --> E2([Selesai])
  SI --> E2
  NR --> E2
  AR --> E2
```

> Manual diizinkan pada sesi berjalan (`active` maupun `manual_override`),
> di dalam maupun di luar jendela auto-open. Guru di luar jadwalnya
> fail-closed 404 `session_not_found` (bukan 403). Record manual bersource
> `manual` dengan `recognition_event_id` null dan audit
> `attendance.manual_marked` berisi snapshot roster + catatan; varian
> `system` juga tanpa event. Record FR tidak boleh ditimpa manual (dan
> sebaliknya): duplikat sesi dan siswa, termasuk balapan konkuren lewat
> savepoint, selalu 409 `attendance_already_recorded`.
> Koreksi HANYA menghasilkan `pending` (+ audit
> `attendance.correction.requested`). Tidak ada keputusan approve atau
> reject di sistem berjalan — alur "Admin setujui" TIDAK BOLEH digambar
> sebagai fitur jalan.

## 5.8 Live dashboard (F-08)

```mermaid
flowchart TD
  S([Buka dashboard]) --> SN[Ambil snapshot sesi + roster + record]
  SN --> WS[Subscribe WebSocket; refresh tiap 2 detik]
  WS --> UP{Ada event baru?}
  UP -- Ya --> SN
  UP -- Tidak --> WS
  SN --> AR[Tampilkan panel at-risk: 25 teratas + ambang efektif]
  AR --> E([Pantau])
```

## 5.9 Laporan dan ekspor (F-09)

```mermaid
flowchart TD
  S([Pilih filter tanggal-kelas-lab-sesi]) --> B[Batasi scope: guru hanya jadwal miliknya]
  B --> A[Agregat session_students + records]
  A --> R{Baris tanpa record?}
  R -- Sesi open --> N[Tampilkan not_recorded]
  R -- Sesi closed --> AB[Tampilkan absent]
  N --> X{Ekspor?}
  AB --> X
  X -- Tidak --> T[Tabel paginasi]
  X -- Ya --> C{Lebih dari 50rb baris?}
  C -- Ya --> E1[Tolak 413: persempit filter]
  C -- Tidak --> CSV[CSV BOM atau XLSX tanpa skor AI + anti formula-injection]
  CSV --> E([Unduh])
  T --> E
```

## 5.10 EWS at-risk tahap 1 (F-10)

```mermaid
flowchart TD
  S([Buka panel Siswa perlu perhatian]) --> W[Ambil policy tersimpan atau default 30 hari + absen 20 persen + telat 3x; override query tervalidasi]
  W --> G[Agregat sesi non-cancelled: total + absen + telat + absence_pct]
  G --> F{absence_pct >= ambang ATAU telat >= ambang?}
  F -- Tidak --> B[Bersih: tidak masuk daftar]
  F -- Ya --> L[Flag + reasons + ambang efektif + revisi policy]
  L --> H[Catat tindak lanjut manual guru atau BK]
  H --> E([Catat di luar sistem pada tahap 1])
  B --> E
```

Aturan agregat: sesi `cancelled` dikecualikan; sesi closed tanpa record = absen;
sesi open tanpa record = `not_recorded` (tidak dihitung absen);
`excused` bukan absen. Urut: absence_pct desc, late desc, nama.

## 5.11 Perangkat (F-11)

```mermaid
flowchart TD
  subgraph ADM[ADMIN saja]
    A1([Registrasi device + lab + profile]) --> A2[Provision bearer sekali pakai]
    A2 --> A3[Rotate token + overlap singkat]
    A3 --> E
    A1 --> A4[Update registry atau lab assignment]
    A4 --> E
    A1 --> A5[Jeda atau aktifkan kamera: matching berhenti, heartbeat jalan]
    A5 --> E
    A1 --> A6[Nonaktif: revoke kredensial + kamera offline]
  end
  subgraph OPS[LABORANT dan device]
    B1([Heartbeat + camera_status + latency + metrik]) --> B2[Discover sesi aktif lab ini]
    B2 --> B3[Tarik gallery sesi dan kirim recognition-event idempoten]
    B3 --> B1
  end
  A6 --> E([Selesai])
```

> Registrasi, update assignment, nonaktif, provision, dan rotate kredensial
> wajib `MANAGE_MASTER_DATA` (ADMIN); jeda atau aktif kamera wajib
> `MANAGE_SETTINGS` (ADMIN); heartbeat operator dan list device memakai
> `DEVICE_OPERATE` (LABORANT, ADMIN); renew memakai kredensial device
> itu sendiri. Guru tidak punya operasi device. Heartbeat device nonaktif
> → 409 `device_inactive`; profile heartbeat tak cocok → 409
> `deployment_profile_mismatch`; gallery saat kamera dijeda → 409
> `device_camera_disabled`.

## 5.12 AI config + preview (F-12)

```mermaid
flowchart TD
  S([Admin terbitkan AI config revision]) --> P[Device poll dan terapkan: pending-applied-error]
  P --> V{Preview pra-sesi?}
  V -- Tidak --> E([Selesai])
  V -- Ya --> H{Browser di localhost atau 127.0.0.1 ke edge-agent 8765?}
  H -- Tidak --> R1[Tolak: buka dari komputer AI_EDGE]
  H -- Ya --> PR{Profil AI_EDGE?}
  PR -- Tidak --> R2[409 preview_gallery_profile_unsupported]
  PR -- Ya --> CM{Kamera enabled?}
  CM -- Tidak --> R3[409 device_camera_disabled]
  CM -- Ya --> SA{Masih tanpa sesi aktif?}
  SA -- Tidak --> R4[409 preview_gallery_session_active: gunakan snapshot sesi berjalan, bukan preview]
  SA -- Ya --> W{Maks 15 mnt sebelum mulai dan sebelum akhir?}
  W -- Tidak --> R5[404 preview_gallery_unavailable]
  W -- Ya --> G{Template aktif tersedia?}
  G -- Tidak --> R6[409 preview_gallery_empty]
  G -- Ya --> L[Overlay wajah + kandidat tanpa event; frame sekitar 15 fps, status 500 ms]
  L --> E
  R1 --> E
  R2 --> E
  R3 --> E
  R4 --> E
  R5 --> E
  R6 --> E
```

> Preview hanya AI_EDGE dari browser loopback (`localhost` atau
> `127.0.0.1`) ke edge-agent port 8765, tanpa sesi aktif, di jendela
> mulai-minus-15-menit sampai akhir jadwal lab hari itu. Kandidat
> diagnostik boleh tampil (nama + persen kemiripan model, bukan akurasi)
> tetapi tanpa event dan tanpa record; presensi hanya lahir dari Core API
> saat sesi aktif dan kebijakan pengenalan lolos. Tanpa threshold
> kalibrasi lokal → `waiting_for_calibration`, presensi tidak dibuat.
> Frame preview transient di memori browser dan tidak disimpan.

## 5.13 Akun + audit (F-13/F-14)

```mermaid
flowchart TD
  S([Admin buat akun: email unik + role]) --> A[Akun aktif; password awal wajib diganti]
  A --> C{Ganti password?}
  C -- Ya --> P[Password baru: sesi lama di-revoke semua]
  P --> E([Selesai dan audit])
  C -- Tidak --> E
```

> Ganti password berlaku untuk semua pengguna login; password sementara akun
> baru wajib diganti sebelum dipakai, dan sesi lama ikut di-revoke.

## 5.14 Ringkasan alur per role (untuk sub-bab "Akses per role")

```mermaid
flowchart LR
  subgraph Guru
    G1[Buka sesi miliknya: manual selalu, auto bila mode automatic] --> G2[Pantau live]
    G2 --> G3[Manual bila perlu di sesi berjalan]
    G3 --> G4[Ajukan koreksi: pending tanpa putusan]
    G4 --> G5[Laporan dan EWS kelasnya]
  end
  subgraph Laboran
    L1[Enrollment wajah] --> L2[Operasikan device: heartbeat dan monitor]
    L2 --> L3[Preview pra-sesi AI_EDGE tanpa event]
    L3 --> L4[Buka sesi operasional bila perlu]
  end
  subgraph Admin
    A1[Master + akun + jadwal + policy sesi] --> A2[Device registry + kredensial + kamera + AI config + policy EWS]
    A2 --> A3[Audit semua perubahan kecuali jadwal dan commit import]
  end
```

> Guru: tanpa operasi device dan enrollment; koreksi miliknya hanya
> `pending`. Laboran: tanpa registrasi atau deaktivasi device, tanpa
> rotate kredensial, tanpa camera-control, tanpa koreksi. Admin: satu-satunya
> pemegang `MANAGE_MASTER_DATA` dan `MANAGE_SETTINGS`.
