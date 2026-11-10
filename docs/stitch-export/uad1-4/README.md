# UAD1-4 — Audit spacing + kiosk ala Stitch (2026-11-07)

Temuan user: tombol bersebelahan nempel, judul–tabel nempel, ukuran kurang
friendly; cards/tables belum seperti Stitch; kiosk "beda banget".

## Perbaikan ritme global (`styles/stitch-shell.css`, bagian UAD1-4)
- `.st-btn` tidak wrap 2 baris (`white-space: nowrap`, cth. "Simpan PIN").
- `.st-table__actions` jadi flex `gap 6px`, wrap, rata kanan — aksi baris
  (EWS "Detail siswa / Riwayat →", Kiosks "Buat/reset PIN · Nonaktifkan ·
  Cabut") tidak nempel.
- `.st-schedule__actions` gap 8px wrap; `.st-tablewrap` margin-top 12px
  (judul–tabel tidak nempel); hover baris tabel ala Stitch.
- Form PIN per lab (`DevicesView`): class ganda `accounts-view__row` pada
  `<li>` + `<form>` dipecah — form kini `accounts-view__pin-form` (label |
  input | tombol sebaris, wrap rapi di mobile).

## Kiosk `/display` redesain gelap ala Stitch B07-01 / B07-07
- Aktivasi: header gelap + jam WIB live + pil "Menunggu Aktivasi Petugas",
  radio-card lab & kamera, PIN 6 digit, error box merah, CTA penuh
  "Mulai Layar Presensi", footer Terminal ID / handshake / keamanan.
- Papan: bingkai kamera kapsul + badge "Kamera Siap", kartu hasil
  "HASIL DIKONFIRMASI · waktu WIB" + avatar inisial + badge HADIR/TERLAMBAT
  + Waktu Kedatangan + catatan toleransi 15 mnt + countdown, roster chips
  nama singkat (tanpa NIS), `<details>` daftar tunggu & panduan.
- API, polling 5 dtk, testid (`display-board`, `display-spotlight`,
  `display-student`, `display-pin-input`) tidak berubah.

## Bukti visual (folder ini)
- `kiosk-activate-fixed.png` — aktivasi gelap, penomoran & Terminal ID benar.
- `kiosk-board-spotlight-late.png` — sesi live Lab Komputer 1: Rizky R.
  TERLAMBAT 12.13 WIB + daftar tunggu 8 belum masuk.
- `kiosk-board-waiting-contrast.png` — empty state terbaca (override `:deep`).
- `kiosk-mobile-390.png`, hscroll 390 = 0 (kiosk, devices, ews, reports, sessions).
- `devices-pin-row-fixed.png`, `ews-actions-spaced.png`, `kiosks-admin.png`.

## Gate
- `npm run typecheck --prefix apps/web` → hijau.
- `npm run lint --prefix apps/web` → hijau.
- `npm run test:unit --prefix apps/web` → 28 berkas / 101 passed.
