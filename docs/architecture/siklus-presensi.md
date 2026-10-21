# Siklus Presensi: Sesi, Keputusan, Laporan, Dashboard, Enrollment

`recognition_events` (evidence audit, selalu disimpan) berbeda dari
`attendance_records` (keputusan final, hanya lahir setelah validasi).
Satu event dipakai maksimal satu record; record manual tidak memakai event.

## Lifecycle sesi

Sesi adalah instance runtime bertanggal dari jadwal mingguan. Hanya jadwal
aktif untuk weekday + tanggal efektif berjalan yang bisa dibuka. Guru membuka
sesi jadwalnya sendiri; ADMIN/LABORANT bisa membuka sesi eligible untuk
operasi. Route sesi butuh `SESSION_OPERATE`.

Mode pembukaan per guru (`opening_mode`: `automatic`/`manual`, default
`manual`; lihat ADR-003): worker auto-open hanya untuk guru mode `automatic`
(dalam jendela yang dikonfigurasi, maks 15 menit sebelum/sesudah jam mulai).
Guru boleh membuka sesi kapan pun, termasuk di luar jendela otomatis — sesi
paksa ini berstatus **`manual_override`** agar dashboard/audit menunjukkan
intervensi guru. Auto-close pada jam akhir jadwal berlaku untuk `active` DAN
`manual_override` (worker lifespan tiap 30 detik, `closed_at` = jam akhir lokal
jadwal); guru tetap bisa close manual kapan pun. LABORANT scope global karena
belum ada tabel lab-to-laborant.

Membuka sesi membuat baris `attendance_sessions` + menyalin siswa aktif kelas
ke `session_students` dalam satu transaksi (nomor/nama snapshot immutable;
perubahan roster belakangan tidak mengubah snapshot). Grace period
dikonfigurasi 0–1440 menit, default 15 menit. Satu sesi aktif per jadwal
(partial unique index + respons konflik API).

UI `/app/sessions`: daftar jadwal yang bisa dibuka hari ini, grace
terkonfigurasi, status sesi, roster count, akhir terjadwal, aksi close manual.

## Ingest event-ke-record

Operator: `POST /api/v1/attendance/recognition-events`; device:
`POST /api/v1/devices/{device_id}/recognition-events` (kredensial device).
Body: event UUID, device/sesi/kandidat, outcome AI, similarity/confidence,
hasil liveness opsional, capture timestamp, model name/version. Tidak menerima
atau menyimpan image/embedding.

Endpoint menyimpan setiap event yang valid sebelum memutuskan presensi final.
Outcome `ambiguous`/`no_match`/`error` hanya evidence audit. `matched`
membuat record hanya bila 5 syarat lolos:

1. device aktif dan lab-nya sama dengan lab jadwal sesi;
2. sesi aktif saat API memproses event;
3. kandidat ada di snapshot `session_students`;
4. outcome `matched` dan cek liveness yang dilaporkan lolos (liveness opsional
   sampai kebijakan deployment mewajibkan; reported-fail menolak);
5. belum ada record untuk student+sesi itu.

Core API tidak memilih threshold similarity; konfigurasi recognition harus
menghasilkan outcome `matched` dari kebijakan terkalibrasi.

Batas grace: `opened_at + grace_period_minutes`, memakai **capture time**
(bukan waktu terima API) agar delay jaringan adil. Tepat/pada batas = `present`,
lewat = `late`.

`event_id` adalah idempotency key: replay payload sama → keputusan/record asli;
key sama isi beda → 409. Event baru untuk siswa yang sudah tercatat tetap
disimpan dengan reason `attendance_already_recorded`; constraint UNIQUE
database adalah penjaga akhir anti-duplikat. Insert record dibungkus savepoint:
pelanggaran UNIQUE ditangkap, audit tetap commit, respons melaporkan reason
duplikat bersih (bukan 500).

Presensi manual guru: `POST /attendance/sessions/{id}/manual-marks`
(`SESSION_OPERATE` + kepemilikan jadwal guru; body `{student_id,
status: present|late|absent|excused, note?}`) menulis `AttendanceRecord`
`source='manual'`, `recognition_event_id=NULL`, `device_id=NULL`,
`marked_by=<guru>` + audit `attendance.manual_marked`. Validasi: sesi berjalan
(`active`/`manual_override`), roster snapshot, duplikat. UI guru menampilkan
tombol tandai manual per siswa yang belum tercatat. Record manual tidak menimpa
record face_recognition yang sudah ada; perubahan memakai alur koreksi.

## Laporan

`GET /api/v1/reports/attendance` (agregat) dan
`/attendance/records` (baris paginasi). Filter: `starts_on`, `ends_on`,
`student_id`/exact `student_number`, `class_id`, `laboratory_id`,
`session_id`, `status`. Batas tanggal kalender lokal inklusif di `timezone_name`
(default `Asia/Jakarta`) → rentang UTC half-open atas `opened_at` sesi.

Semantik baris dari `session_students` (snapshot; nama/NIS + kelas/lab dari
jadwal sesi; sesi cancelled dikecualikan). Baris ber-record memakai status
record; tanpa record = `not_recorded` saat sesi aktif, `absent` setelah sesi
ditutup (siswa in-progress tidak dilaporkan absen dini). `total_rows`
menghitung student×sesi.

Akses: ADMIN semua jadwal; TEACHER (`REPORTS_READ`) dibatasi jadwal miliknya
di summary, halaman, dan ekspor. Default 25 baris, maks 100; indeks B-tree
`opened_at`. Ekspor `.../export?format=csv|xlsx` (maks 50.000 baris): CSV
UTF-8 BOM, nilai berawalan penanda formula diberi apostrof anti-eksekusi.
Ekspor hanya label presensi/jadwal — tanpa skor, embedding, image, kredensial.

## Live dashboard

Guru memuat sesi aktif, snapshot awal
`GET /api/v1/sessions/{session_id}/dashboard`, lalu
`WS /api/v1/sessions/{session_id}/updates`. Setiap pesan `snapshot` diterapkan
ke state halaman (summary, devices, 10 recent activity) tanpa reload; browser
reconnect otomatis + fetch snapshot segar saat ganti/refresh sesi.

Protokol WS: tanpa kredensial di URL; frame JSON pertama
`{"type":"authenticate","access_token":"<short-lived>"}`. Frame pertama wajib
tiba dalam 5 detik. Tutup: `4401` (auth invalid), `4403` (forbidden),
`4404` (sesi tak terakses). Scope = scope operasi sesi. Server recek
akses/kedaluwarsa token selama streaming.

Polling snapshot default tiap 2 detik (`SESSION_DASHBOARD_POLL_SECONDS`,
clamp 0,25–30). Online window device
`PRESENSI_DEVICE_HEARTBEAT_TIMEOUT_SECONDS` (default 60, clamp 5–3600;
`DEVICE_ONLINE_THRESHOLD_SECONDS` fallback lama). Summary: roster size,
`present`, `late`, `not_present` (= roster − present − late). Status device
dari lab jadwal sesi: Online (aktif + heartbeat segar + kamera online),
Warning (heartbeat segar tapi kamera non-online), Offline. Pesan WS hanya
display field (count, label, timestamp, ringkasan) — tanpa image, embedding,
atau metadata template. Token hanya di frame pertama, tidak di query/log.

## Enrollment

Layar operator untuk ADMIN/LABORANT: pilih kelas aktif, tinjau status template
per siswa (`not_enrolled` / `enrolled` / `needs_reenrollment` dari metadata;
endpoint status tidak mengembalikan image/embedding/model/quality score),
buka kamera, capture 4 frame setelah countdown 3 detik, konfirmasi identitas
sebelum lanjut ke siswa berikut. Stream berhenti saat ganti/tinggalkan
kelas, batal, atau konfirmasi identitas.

`POST /api/v1/enrollments/captures` menerima 3–10 image bounded; menolak format
tak didukung, decode gagal, nol/multi-wajah, kualitas buruk; menyimpan 3–5
embedding normalisasi terbaik untuk model YuNet/SFace terkonfigurasi,
terenkripsi AES-256-GCM (raw frame dibuang; jangan reuse template antar versi
model). Perbandingan dengan vector aktif siswa lain model/version sama:
similarity di atas warning threshold → peringatan duplicate-lookalike (tidak
merge, operator verifikasi identitas). Re-enroll: revoke menghapus SEMUA
template aktif siswa dalam satu aksi (loop batch; partial tidak mungkin),
lalu capture set baru. Revokasi diaudit. Key ring wajib tersedia sebelum
enrollment (missing/mismatch → fail-closed).

E2E memakai stream canvas sintetis + mock API (status/countdown/konfirmasi/
revoke/next-eligible) tanpa imagery siswa; tidak memvalidasi akurasi
biometrik. Aset model lokal + duplicate-warning threshold terkalibrasi tetap
input deployment.
