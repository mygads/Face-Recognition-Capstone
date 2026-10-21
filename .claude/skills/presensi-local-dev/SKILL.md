---
name: presensi-local-dev
description: Jalankan stack lokal presensi, atasi login bootstrap gagal, dan verifikasi perubahan
---

# Presensi — Local Dev & Login Troubleshooting

## Startup standar (fresh clone)

Windows: `py -3 scripts/start-local.py` · Ubuntu: `python3 scripts/start-local.py`.
Perintah ini: buat `.env`, migrasi Alembic, seed role, bootstrap admin (hanya bila
tabel user kosong), pasang dependency web, jalankan Vite. Web `http://127.0.0.1:5173`,
API `http://127.0.0.1:8000`.

## Kredensial awal

- Email `admin@local.test`, password `1234abcd` (default `BOOTSTRAP_DEFAULT_PASSWORD`
  di `apps/api/src/presensi_api/auth/bootstrap_admin.py`).
- Override: set `PRESENSI_BOOTSTRAP_PASSWORD` di `.env` (lihat `.env.example`).
- Login pertama wajib ganti password, minimal 12 karakter. Token awal dibatasi
  hanya untuk endpoint ganti password.

## Login gagal — urutan cek

1. Password yang dicoba harus `1234abcd` (atau nilai `PRESENSI_BOOTSTRAP_PASSWORD`),
   bukan password lama `123456789abcd`.
2. Bootstrap tidak me-reset akun yang sudah ada. Bila DB dev sudah berisi akun:
   masuk dengan password yang dulu dibuat, atau reset volume dev
   (`scripts/dev.py dev-down` lalu `docker compose down -v`, data dev hilang)
   dan jalankan `start-local.py` lagi.
3. Setelah login awal, ikuti redirect ganti password (min 12 karakter) lalu masuk kembali.
4. `APP_ENV` harus `development` agar bootstrap diizinkan (compose sudah mengaturnya).

## Verifikasi wajib sebelum klaim selesai (AGENTS.md)

- `py -3 scripts/check.py` (atau `python3` di Ubuntu) — harus hijau.
  Baseline 2026-10-21: ruff + format + mypy (133 file) + 281 pytest;
  web: `vue-tsc --noEmit` + eslint + 26 Vitest.
- Tes terkait: `py -3 -m pytest apps/api/tests/test_auth.py -q` untuk perubahan auth.
- Jangan klaim hasil hardware/performance tanpa perangkat nyata;
  tandai `MANUAL HARDWARE TEST REQUIRED`.
- Semua perubahan behavior wajib disertai test; perubahan DB wajib via migrasi Alembic.

## Arti status fail-closed (jangan dianggap bug)

- Burst AI balas `503 auth_misconfigured` → device_tokens belum dikonfigurasi;
  bukan error jaringan. Open auth hanya sah di mode Core API.
- Keputusan `NEED_FRONTAL_RETRY` dengan `single_identity_gallery` → kandidat
  tunggal tanpa runner-up; sistem menolak accept dari similarity saja.
  Di produksi, guru menutupnya via presensi manual.
- `401/403` dari edge agent tidak di-retry — perbarui kredensial perangkat,
  jangan tunggu backoff.

## Jangan

- Jangan commit dataset wajah, raw image, embedding, token, atau secret.
- Jangan pakai kredensial bootstrap untuk production.
- Jangan expose stack development ke internet sebelum password diganti.
