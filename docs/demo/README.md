# Demo & UAT Terpandu untuk Dosen (data 100% sintetis)

Bukti visual: `/tmp/shots/` (23 PNG desktop 1440px: 2 publik + 8 admin +
4 guru + 6 laboran + 3 master-tab) + `rekap.csv` / `rekap.xlsx` (hasil unduh
laporan asli). UAT browser **5/5 HIJAU** + `seed-demo` **24–25/24–25 HIJAU** (25 bila koreksi contoh baru dibuat)
(Playwright Chromium). Arsip lama per halaman tetap di `screenshots/` (40 PNG
+ 2 tablet).

> Catatan 6 Nov malam: sesi demo pertama auto-tutup melewati akhir jadwal
> (domain: backend selalu menutup sesi di akhir jadwal — by design). Seed
> dibuat sadar-waktu (`demo_window()`: mulai-30 mnt s/d +2 jam, dijepit
> 23:59 bila lewat tengah malam; jadwal kedaluwarsa digeser via PATCH,
> jadwal yang masih menutupi jam jalan dipakai ulang). 30 screenshot
> halaman-panjang diretake setelah layout shell fixed→sticky + tabel
> laporan wrap (sidebar/topbar benar di full-page capture, 9 kolom muat).

## 1. Cara mereproduksi

```bash
# stack dev menyala (postgres :5432, API :8000, web :5173)
python3 scripts/seed-demo.py   # idempoten, 24-25 checks: akun→lab/kelas/siswa→jadwal→device→2 sesi→heartbeat→PIN→assignment→grant→mode guru→EWS follow-up→koreksi
```

Akun demo: `admin@local.test` / `DemoAdmin2026!x`;
`dewi.guru@sekolah.test`, `agus.guru@sekolah.test` / `GuruDemo2026!x`;
`budi.laboran@sekolah.test` / `LabDemo2026!x`.
Data: lab LAB-RPL1 + LAB-FIS; kelas XII-RPL-1 (10 siswa NIS 20260101–10) +
XII-TKJ-1 (8 siswa NIS 20260201–08); jadwal mengikuti jam jalan (mulai-30 mnt s/d +2 jam, maks 23:59);
device `edge-pc-rpl-01` + `stb-fis-01`; sesi RPL AKTIF (5 event face-recognition
+ 1 ambiguous + manual present/late/excused/absent + 1 belum tercatat) dan sesi
TKJ DITUTUP (4 present + 1 late + 1 excused + 2 absen otomatis); PIN layar `1234`
di kedua lab; Budi ditugaskan ke 2 lab + 3 grant (`schedule_read`,
`session_operate`, `reports_read`); Dewi mode otomatis, Agus manual;
1 EWS follow-up; 1 koreksi approved (contoh).

## 2. Matriks role → menu (terverifikasi di router + sidebar + 13 permission)

| Menu | ADMIN (10+profil) | TEACHER (4+dashboard) | LABORANT (4 default + hingga 3 grant) |
|---|---|---|---|
| Layar publik `/display` | n/a (tanpa login: lab + PIN) | n/a | n/a |
| Ringkasan | ✔ semua | ✔ miliknya | ✔ khusus laboran |
| Data master (tab Siswa/Kelas/Lab) | ✔ kelola | — | — |
| Kelola akun staf | ✔ (+ aktif/nonaktif, reset, grant, penugasan, mode guru) | — (forbidden) | — |
| AI & kamera | ✔ | — | — |
| Preview kamera | ✔ (+ pilih perangkat/lab) | — | ✔ (lab-nya + pilih perangkat/lab) |
| Jadwal praktikum | ✔ semua | ✔ miliknya | ✔ via grant `schedule_read` |
| Sesi presensi | ✔ semua | ✔ miliknya (+ manual & ajukan koreksi) | ✔ via grant `session_operate` |
| Pendaftaran wajah | ✔ | — | ✔ (lab-nya) |
| Perangkat (+ PIN layar) | ✔ kelola penuh | — | ✔ pantau (tombol kelola disembunyikan) |
| Laporan kehadiran (+ Terlambat, EWS tindak lanjut) | ✔ semua | ✔ miliknya | ✔ via grant `reports_read` |
| Profil | ✔ | ✔ | ✔ |

## 3. Urutan UAT (beres berurutan, semua tombol dicoba)

### 3.1 ADMIN — sesi & presensi manual (`40`, `40b`, `41`)

1. `/app/devices`: 2 baris tampil di API; UI memfilter profile AI_EDGE aktif
   → `40b-admin-perangkat-2row.png` (STB-FIS tersembunyi = by design).
2. `/app/sessions` → Status sesi Praktikum Pemrograman Web → roster 10 siswa
   (snapshot) → `40-admin-roster.png`.
3. Tandai manual Sinta Maharani = Hadir + catatan → toast sukses; rerun:
   form manual hilang ("semua sudah tercatat"), roster langsung
   `Hadir + catatan` → `41-admin-manual-sinta.png`. ✔

### 3.2 ADMIN — CRUD siswa + akun (`43`, `43b`, `44`)

1. Master data → Tambah siswa (NIS unik + nama) → cari → baris muncul →
   `43-admin-tambah-siswa.png`; Ubah nama → Simpan perubahan →
   `43b-admin-ubah-siswa.png`. Tabel paginasi 10/baris. ✔
2. Kelola akun → buat akun LABORAN → panel sandi sementara (satu-satunya
   penayangan) → `44-admin-buat-akun.png`. Email duplikat ditolak. ✔

### 3.3 ADMIN — jadwal anti-bentrok + laporan + ekspor (`45`, `47`, `48`)

1. Tambah jadwal Jumat 18–19 (kelas+lab+guru bertabrakan) → 409
   "Jadwal bertabrakan…" → `45-admin-jadwal-konflik.png`. ✔
2. Laporan: 18 baris, kolom `Catatan` memuat note manual-mark;
   filter kelas; Unduh CSV + XLSX → `47-*.png`, `48-*.png`,
   `rekap.csv`/`rekap.xlsx` (16 kolom, UTF-8 BOM, anti formula-injection). ✔

### 3.4 GURU — sesi miliknya + laporan + profil (`60`, `61`, `62`, `25`)

Roster sesi, laporan scope guru, profil (info + form ubah sandi);
`/app/accounts` → halaman forbidden → `25-guru-forbidden-akun.png`. ✔

### 3.5 LABORAN + responsif tablet (`30–36`, `50`, `51`, `70`)

Dashboard, sesi operasional, perangkat pantau (tanpa tombol kelola),
enrollment TKJ, preview kamera (fail-closed "gagal memuat" tanpa agent
loopback 127.0.0.1:8765 = by design), profil, forbidden laporan (via API
diizinkan, tanpa menu = by design). Tablet 1024px: `50`, `51`. ✔

### 3.6 Jelajah per-role (klik tiap menu, tiap role)

`00–01` layar publik (login + board RPL); `10–19` semua halaman ADMIN
(master 3 tab, akun, perangkat+PIN, jadwal, sesi+koreksi, laporan+EWS,
enrollment, preview); `20–23` GURU (dashboard, jadwal, sesi+koreksi,
laporan+EWS); `30–35` LABORAN (dashboard, perangkat, preview, enrollment,
sesi via grant, laporan via grant). ✔

### 3.7 Fitur baru (pemetaan UAT → bukti)

- Layar publik: `00` form lab+PIN → `01` board 10 siswa (SUDAH MASUK /
  TERLAMBAT / IZIN). ✔
- Grant laboran: `34` sesi + `35` laporan/EWS terbuka untuk Budi
  (tanpa grant → 403 backend). ✔
- Koreksi penuh: `16`/`22` panel ajukan (record + tanpa record) + daftar +
  putusan ADMIN; seed membuat 1 approved. ✔
- EWS tindak lanjut: `17`/`23`/`35` panel + catat; seed membuat 1 catatan. ✔
- PIN layar: `14` panel PIN per lab (diatur `1234`). ✔
- Watermark TERLAMBAT + "telat N mnt": roster `16`/`22` + laporan `17`. ✔
- Preview multi-perangkat: `19`/`32` dropdown perangkat/lab. ✔

## 4. Bonus: profile AI_CENTRAL (`80`, `81`)

`PRESENSI_LOCAL_AI_PROFILE=central docker compose up -d api` → halaman
Perangkat hanya menampilkan `stb-fis-01` (STB Gateway · AI central), dan
panel AI & kamera menjadi "AI Central · server" (central unreachable =
wajar tanpa service AI central). Cerminan dari mode EDGE (`40b`: hanya
edge-pc). Setelah itu kembalikan `docker compose up -d api` (edge) +
`python3 scripts/seed-demo.py` (heartbeat segar).

## 5. Yang sengaja tidak live (butuh hardware lab — P2-1)

Preview kamera butuh agent loopback; threshold final butuh kalibrasi benchmark
lokal; field test + benchmark PC/STB. Status: `MANUAL HARDWARE TEST REQUIRED`.
Galeri preview hanya AI_EDGE, hanya saat tidak ada sesi aktif.
