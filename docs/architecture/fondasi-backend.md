# Fondasi Backend: Auth, Kontrak API, Skema, Master Data, Jadwal

Kontrak HTTP di bawah `/api/v1`, dideskripsikan FastAPI OpenAPI di
`/openapi.json`. Model Pydantic v2 adalah source of truth; handler
mengembalikan model respons, bukan ORM SQLAlchemy. Semua error memakai satu
`ErrorEnvelope` (`validation_error`, `ApiProblem` berkode, atau pesan publik
generik untuk 500). `/health` adalah alias process-health tersembunyi dari
OpenAPI; `/api/v1/health` adalah operasi berversi.

Contoh error:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed.",
    "details": [{ "field": "body.student_number", "message": "...", "code": "..." }]
  }
}
```

Frontend memakai `openapi-typescript` (deklarasi) + `openapi-fetch` (typed
client). Setelah mengubah skema API, regenerate dari `apps/web`:

```sh
npm run api:generate
```

File generated (`src/api/generated/schema.d.ts`) adalah output tool, jangan
diedit manual, dan commit bersama perubahan kontrak. Perubahan aditif
kompatibel tetap di v1; rename/hapus field, ubah tipe, atau ubah semantik
resource wajib kontrak `/api/v2` baru dengan rencana migrasi/depresiasi.

## Auth dan RBAC

Login: `POST /api/v1/auth/login` (OAuth2 password form; field `username` =
email). Browser menyertakan header `X-Presensi-Session: browser` untuk meminta
cookie sesi HttpOnly `presensi_session` (absolut 24 jam, server-side di
`auth_sessions`, revoke saat logout/ganti password); klien non-browser bisa
omit dan tidak menerima cookie. Password Argon2 via `pwdlib`; akun tak dikenal
memakai dummy Argon2 lokal agar tetap ada verifikasi. Akun sukses menerima
bearer HS256 klaim `sub/iat/exp/jti/iss/token_use=access`, default 15 menit
(5–60 via config). Vue menyimpan bearer di memori Pinia saja, tidak di
storage/URL/log; reload menukar cookie sesi via `POST /api/v1/auth/refresh`.

`JWT_SECRET` minimal 32 byte, di luar Git; `.env.example` mengosongkannya dan
task runner mengisi acak lokal. Login sukses/gagal menulis audit
`auth.login.succeeded/failed` tanpa email, password, token, IP, atau biometrik.
Login/ganti-password gagal berbagi satu pesan error generik.

Baseline role: `ADMIN` (semua permission), `TEACHER` (katalog baca, jadwal +
sesi miliknya, presensi/laporan jadwalnya, ajukan koreksi), `LABORANT`
(katalog baca, operasi device/sesi, enrollment via roster kelas terpilih).
Roster global dan detail roster kelas: ADMIN-only (`MANAGE_MASTER_DATA`).
Route memakai `require_permissions(...)`; role di luar enum baseline tidak
memberi permission implisit. Teacher dibatasi jadwal/sesi miliknya;
`SESSION_OPERATE` untuk operasi sesi; device memakai kredensial terpisah
(bearer device ≠ JWT manusia).

Bootstrap lokal: migrasi + seed role, lalu `admin@local.test` hanya bila tabel
user kosong. Password awal `1234abcd` (override `PRESENSI_BOOTSTRAP_PASSWORD`
di `.env`), hanya untuk `APP_ENV=development`, wajib diganti (min 12 karakter)
sebelum akses API normal; token bootstrap dibatasi endpoint ganti password.
Bootstrap tidak pernah me-reset akun yang sudah ada. Production: buat akun
pertama dengan prompt password tersembunyi:

```sh
docker compose run --rm api python -m presensi_api.auth.create_user \
  --email admin@example.edu --full-name "School Administrator" --role ADMIN
```

## Skema PostgreSQL

Core API memiliki skema domain; semua perubahan via migrasi Alembic (jangan
ubah tabel saat process startup). Mapping SQLAlchemy 2 di
`apps/api/src/presensi_api/db/models.py` adalah metadata revisi.

| Area | Tabel | Isi |
| --- | --- | --- |
| Identitas/akses | `users`, `roles`, `user_roles` | Akun + assignment role |
| Roster/jadwal | `students`, `classes`, `class_students`, `laboratories`, `devices`, `practicum_schedules` | Master + device dengan metadata health |
| Operasi presensi | `attendance_sessions`, `session_students` | Sesi live + snapshot roster immutable |
| Evidence | `face_templates`, `recognition_events` | Template versi-model + hasil mentah idempoten |
| Final | `attendance_records`, `attendance_corrections` | Keputusan final + riwayat koreksi |
| Audit | `audit_logs` | Actor/aksi/entity + before/after JSON (tanpa biometrik/secret) |

Setiap entity mandiri memakai UUID dari aplikasi. Semua timestamp lifecycle
`timestamp with time zone`. `start_time`/`end_time` jadwal adalah wall-clock
lokal + `timezone_name` IANA. Event UUID adalah kunci idempotency retry.

Batas biometrik: `recognition_events` menyimpan outcome (`matched`,
`ambiguous`, `no_match`, `error`), model name/version, similarity/confidence/
margin, metadata quality, event UUID, device, sesi, kandidat opsional —
ditambah alasan keputusan Core API. `attendance_records` unik per
`(session_id, student_id)`; satu event dipakai maksimal satu record.
`face_templates` menyimpan vector sebagai AES-256-GCM ciphertext
(`embedding_ciphertext`, nonce acak, AAD ke template/student/model); key ring
dari `PRESENSI_FACE_TEMPLATE_KEYS` + active ID, di luar repo. Rotasi:

```sh
python -m presensi_api.biometric_key_rotation
```

Verifikasi count sebelum menghapus key lama; kehilangan semua key membuat
vector tak terpulihkan. Revokasi/deaktivasi menghapus ciphertext (metadata
audit dipertahankan). Gallery didekripsi hanya untuk device terautentikasi
pada sesi/lab aktif; respons operator dan audit log tidak pernah membawa
vector/ciphertext.

Constraint/indeks: unique email role/code, student number exact + indeks
fungsional `lower(student_number)` anti-duplikat case-only (HTTP 409
`duplicate_student_number`), composite PK join table, partial unique index
sesi aktif per jadwal, FK komposit `(session_id, student_id)` dari
`attendance_records` ke `session_students` (record final mustahil di luar
snapshot), time-series index `(session_id/device_id, occurred_at)`.

Migrasi dan seed:

```sh
docker compose run --rm api alembic upgrade head
docker compose run --rm api python -m presensi_api.db.seed_roles
```

Seed repeatable (UUID deterministik ADMIN/TEACHER/LABORANT; `LEGACY_STUDENT`
tanpa permission). Revisi baru: `alembic revision --autogenerate -m "..."`
dari `apps/api` dengan PostgreSQL reachable; review operasi sebelum commit.
CI menjalankan migrasi + `alembic check` anti-drift.

Detail batas biometrik dan retensi: [security-and-privacy](../security-and-privacy.md).

## Master data dan kanonikalisasi

Route `/api/v1`: students, classes (+roster membership), laboratories
(baca/tulis + PATCH). List: `limit` 1–100, `offset`, `search`
case-insensitive, `is_active`. Katalog kelas terbuka untuk ADMIN/TEACHER/
LABORANT; direktori siswa global + roster kelas penuh ADMIN-only. Laborant
memakai `GET /enrollments/class-status` untuk roster kelas terpilih. Tulis dan
membership butuh `MANAGE_MASTER_DATA`. Identifier siswa di-trim dan
dikanonikalisasi UPPERCASE di boundary API. Tidak ada delete siswa
(`PATCH is_active:false` sebagai deaktivasi, template ikut direvoke +
ciphertext dibersihkan). Membership hanya untuk siswa aktif di kelas aktif;
duplikat 409. Skema eksplisit Pydantic; timestamp timezone-aware.

Impor CSV/XLSX (`/students/import/preview` lalu `/students/import/commit`,
`multipart/form-data` mapping kolom): hanya `.csv`/`.xlsx`, UTF-8 (BOM boleh),
XLSX membaca sheet aktif baris pertama sebagai header. Batas: upload 5 MiB,
XLSX expanded 25 MiB, 10.000 baris data. Preview melaporkan nomor baris,
identifier kanonis, kode kelas, validasi; cek duplikat vs semua existing
(termasuk nonaktif) + duplikat dalam file. Commit revalidasi lalu insert satu
transaksi (gagal satu → rollback semua). Preview tidak disimpan server-side.
Template contoh: `docs/templates/students-import-template.csv` (nilai sintetis).

UI: `/app/master-data` (tab ADMIN: siswa, kelas, lab; search, paging,
create/edit, panel detail, kontrol roster). Error validasi/konflik tampil di
samping form/halaman.

## Jadwal (weekday 0–6, wall-clock, zona IANA)

`practicum_schedules`: weekday (Senin=0 s.d. Minggu=6), start/end wall-clock
lokal, `timezone_name`, rentang tanggal efektif inklusif. Bukan meeting record
sekali jalan. Admin bisa assign guru TEACHER mana pun; guru hanya kelola
jadwalnya sendiri. Respons menyertakan nama kelas/lab/guru agar tabel Vue
tidak join di klien.

Sebelum create/update jadwal aktif, API menolak overlap pada tiga dimensi
sekaligus: weekday + rentang tanggal efektif + interval wall-clock, bila
berbagi class, lab, ATAU guru yang sama. Slot yang mulai tepat saat slot lain
berakhir diizinkan; jadwal nonaktif tidak memblokir. Error: `409
schedule_conflict`; referensi buruk/urutan waktu/zona tak dikenal memakai
envelope validasi standar. Cek konflik berjalan di transaksi API (bukan
constraint deklaratif), jadi butuh serialisasi/strategi eksklusi sebelum
endpoint ini diandalkan untuk write konkuren tinggi.

UI jadwal: search, filter status/weekday, paging, create/edit, panel detail;
tanpa dependency kalender/drag-and-drop.
