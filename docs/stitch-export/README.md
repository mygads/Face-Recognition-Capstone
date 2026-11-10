# Export Stitch → Vue (slice 1)

Tanggal export: 2026-11-07. Proyek: `Presensi Praktikum Lab Kimia`
(`https://stitch.google.com/projects/9233580222882268642`).
Metode: Playwright Chromium headless (tanpa login Google) membaca iframe
`app-companion` + `about:srcdoc`, lalu menyimpan HTML frame ke `/tmp`.

## Yang berhasil diidentifikasi
- 87 judul frame unik, ±60 layar (B01 login/dashboard, B02 master/kelas/jadwal,
  B03 sesi/koreksi, B04 laporan/EWS, B05 perangkat/preview/kiosk, B06 pendaftaran
  wajah, B07 kiosk publik).
- Token: Primary `#14665b`/`#004d44`, Secondary `#24536a`/`#36647b`,
  Tertiary `#884a37`, Neutral `#162525`, canvas `#f5f7f8`, surface `#ffffff`,
  success `#155b43`, warning `#784700`, danger `#9d2c32`, info `#24536a`.
- Font `Inter`, ikon `Material Symbols Outlined`, layout `aside+header+main+nav`,
  kartu `bg-surface rounded-xl shadow-sm`, tombol primer `primary-container`.

## File mentah (tidak dicommit, ada di /tmp)
- `/tmp/companion.html` (±4.7MB): daftar frame + palette.
- `/tmp/frame_*.html`: 13 frame viewport (Dashboard Admin/Guru/Laboran, Kiosk).
- `/tmp/stitch_*.png`: screenshot galeri + fokus B06-03.

## Slice 1 yang diterapkan di repo
- `apps/web/src/styles/stitch-tokens.css`: variabel `--st-*` (tidak menabrak Gentelella).
- `apps/web/src/components/ui/`: `UiButton`, `UiCard`, `UiBadge`, `UiField`,
  `UiInput`, `UiEmptyState` ala-shadcn tapi Vue SFC + token Stitch.
- `apps/web/src/views/LoginView.vue`: judul “Portal Khusus Staf”, tombol primer
  penuh, state error validasi jelas. Logika auth tidak diubah.
- `apps/web/index.html` + `main.ts`: theme `#14665b`, font Inter/Material Symbols.

## Verifikasi slice 1
- `npm run typecheck` → hijau.
- `npm run lint` → hijau.
- `npm run test:unit -- --run` → 92 passed.
- Screenshot `/tmp/new_login.png` vs teks Stitch F19 (“Portal Khusus Staf…”).

## Lanjutannya (diluar slice ini)
- AppShell/Sidebar/Topbar → token Stitch per-role.
- Dashboard Admin/Guru/Laboran, Kelas Saya, Sesi, Koreksi, Laporan+EWS,
  Pendaftaran Wajah, Preview, Display/Kiosk — satu slice per halaman agar review
  1:1 tetap akurat. Full 60 layar tidak dikerjakan sekaligus.

## Slice 2 — seluruh shell + layar publik (2026-11-07)
- `stitch-shell.css`: remap variabel Gentelella → Stitch (sidebar terang,
  primer `#14665b`, radius 8/12/16, badge/tombol/panel) + impor sesudah
  `style.scss` agar menang. Mode gelap tidak diubah.
- `Sidebar.vue`: brand “Presensi Praktikum / SMA Taruna Nusantara”.
- `Topbar.vue`: konteks “Presensi Praktikum / SMA Taruna Nusantara”,
  nama + role pengguna, tautan Profil, tombol Keluar (logout + kembali login).
- `DisplayView.vue`: papan kiosk terang ala Stitch — sorotan “Hasil
  dikonfirmasi + waktu”, nama singkat (`Raka P.` via `utils/displayName.ts`),
  tanpa nomor siswa penuh. Polling 5 detik dan PIN tetap sama.
- Test baru: `displayName.test.ts`, `DisplayView.test.ts` (nama singkat,
  tanpa NIS, spotlight TERLAMBAT). `App.test.ts` + `UiBadge` diselaraskan.

## Slice 3 — kit lengkap + dashboard peran + verifikasi (2026-11-07)
- Kit `ui/`: tambah `UiAvatar`, `UiDrawer`, `UiModal`, `UiPageHeader`,
  `UiPagination`, `UiSearchInput`, `UiSelect`, `UiStat`, `UiTabs`, `UiTextarea`
  + `index.ts`. `UiButton` dapat prop `size` (`md` 44px default, `sm` 36px
  untuk aksi tabel); `.button` global diselaraskan (44px, `.button--sm` 36px).
- `PasswordChangeForm.vue`: `UiField`/`UiInput`/`UiButton`; id
  `profile-*-password`, `form`, `[role=alert]` dipertahankan (dipakai test).
- `DashboardView.vue`: dashboard per peran ala Stitch (admin: KPI + kartu lab +
  antrean koreksi + EWS; guru: sapaan + sesi + kelas + EWS; laboran: banner
  penugasan + perangkat + delegasi). `Topbar.vue`: label cakupan
  (semua lab / kelas penugasan / lab penugasan).
- `App.test.ts` diselaraskan (PageHeader generik dilepas; penanda baru
  `dashboard-page` + breadcrumb); `DashboardView.test.ts` ditulis ulang
  mengikuti struktur baru.

## Verifikasi slice 3
- `npm run typecheck` → hijau.
- `npm run lint` → hijau.
- `npm run test:unit -- --run` → 23 berkas, 83 passed.
- Screenshot: `docs/stitch-export/new_login.png` (`/auth/login`),
  `docs/stitch-export/new_display.png` (`/display`) — dev server `:5173`.

## Slice 4 — seluruh halaman memakai kit + gate hijau (2026-11-07)
- Konversi template-only (logika/testid tidak diubah) ke kit:
  `Display` (2 select + PIN + 2 tombol), `Enrollment` (select kelas + 4 tombol;
  checkbox identitas dan kartu siswa tetap native), `CameraPreview`
  (2 tombol aksi; 2 select pola `:value`/`@change` tetap native karena butuh
  semantik event), `Reports` (6 tombol + 3 input + 4 select v-model),
  `Accounts` (11 tombol + 5 input + 7 select + PageHeader→UiPageHeader;
  select boolean `editActive` tetap native), `AiSetup` (8 tombol + 35 input +
  1 select + PageHeader→UiPageHeader), `Devices` (26 tombol + 11 input +
  3 select v-model + PageHeader→UiPageHeader; 2 select pola event tetap native),
  `AttendancePolicy` (6 input angka), `Audit` (1 tombol + 2 input filter),
  `Ews` (tombol baris + input catatan), `Kiosks` (2 input + 2 select).
- Aturan: class `button--*`/`table`/testid dipertahankan sebagai passthrough
  agar selektor test lama tetap cocok; checkbox/radio/file dan select boolean
  atau pola `:value`+`@change` tetap native (perilaku runtime sama persis).
- Kit: `UiButton` dapat `size` (`md` 44px / `sm` 36px); `.button` global
  diselaraskan; `UiPageHeader` dapat prop `eyebrow`; `UiInput`/`UiSelect`/
  `UiTextarea` menerima `null` (+`number` untuk input) agar cocok dengan
  `v-model.number` dan field opsional.
- Koreksi insiden: 5 select pola event yang sempat terkonversi terbukti
  menimpa `value` (select menampilkan '') — dikembalikan ke native,
  test Devices (`same-host`) kembali hijau.

## Verifikasi slice 4
- `npm run typecheck` → hijau.
- `npm run lint` → hijau (2 fungsi mati warisan rewrite dihapus:
  `rosterStatusClass`/`unmarkedCount` di Sessions, `statusClass` di Reports).
- `npm run test:unit -- --run` → 26 berkas, 93 passed.
- Screenshot ulang: `docs/stitch-export/new_login.png`, `new_display.png`.
- Belum disentuh sesi ini (milik alur paralel): `SessionsView`,
  `ScheduleView`, `DashboardView`, `Topbar` — strukturnya sudah kit-based.

## Slice 5 — audit gap nol + uji peran 1:1 (2026-11-07)
- Sweep seluruh `views/*.vue`: tidak ada tombol/input/select mentah yang
  tertinggal selain yang disengaja (checkbox/radio/file, select boolean,
  select pola `:value`+`@change`, tombol kartu `enrollment-view__student`,
  aksi baris `st-rowbtn`/`st-link`, chip filter `st-scope--active`,
  RouterLink bergaya tombol). Semua pola tercatat konsisten antar halaman.
- Menu sidebar mencakup 33 tautan: admin 17, guru 7, laboran 8; seluruh route
  `/app/*` terjangkau dari menu + Topbar (Profil/Keluar) + publik `/display`.
- Perbaikan kecil: hapus impor `UiCard` tak terpakai di DevicesView (lint).
- Uji visual dengan backend dev + seed demo (admin/guru/laboran), 35 screenshot
  1440x900 di `docs/stitch-export/uad1-1/`: dashboard 3 peran, master-data,
  sesi, perangkat, koreksi, EWS, enrollment, preview, kelas saya, forbidden.
  Hasil: satu bahasa visual (kartu, badge, tabel, tombol primer/sekunder/teks,
  chip cakupan peran di Topbar). State kosong/error tampil ramah
  ("Tidak ada sesi aktif", "Preview belum tersedia", "Akses tidak tersedia").

## Verifikasi slice 5
- `npm run typecheck` → hijau.
- `npm run lint` → hijau.
- `npm run test:unit -- --run` → 26 berkas, 93 passed.

## Slice 6 — audit total + UAT 3 peran + responsif (2026-11-07)
Audit ini memakai aplikasi berjalan (API :8000, web :5173, seed demo), bukan
hanya baca kode. Hasil screenshot lama `uad1-1` terbukti basi untuk EWS
(menampilkan tombol "Unduh Berita Acara" yang sudah tidak ada di kode);
bukti baru di `uad1-2/`.

UAT navigasi (Playwright, Chromium):
- Admin 17/17 halaman render + h1 benar, 0 error alert. Guru: halaman
  admin-only (master-data, accounts, ai-setup, camera-preview, devices,
  kiosks, enrollment, attendance-policy, audit) → `/forbidden` ✓; halaman
  guru (my-classes, reports, ews, schedules "Jadwal Saya", sessions,
  corrections "Koreksi Saya", profile) ✓. Laboran: sesuai grant (tanpa
  ews/corrections/audit; dengan camera-preview, devices, kiosks, enrollment,
  schedules, sessions) ✓.
- Interaksi: tab master-data (Siswa/Kelas/Laboratorium + URL), tab koreksi
  (pending 3 / disetujui 16-17 / ditolak), buka detail Tinjau → tombol
  Setujui/Tolak + catatan keputusan + validasi "alasan penolakan wajib" ✓.
  Tidak ada `pageerror` di semua alur.
- Console 401 `auth/refresh` = probe session tanpa cookie (ditangkap silent,
  tanpa toast) — jinak. `ERR_CONNECTION_REFUSED` = companion AI_EDGE tidak
  ada di mesin uji — diharapkan.

Perbaikan dari temuan audit:
- `utils/previewFetch.ts`: `TypeError` "Failed to fetch" → pesan Indonesia
  "Agent preview tidak terjangkau…" + unit test baru.
- `UiEmptyState.vue`: judul memakai `h2` (halaman forbidden kini punya
  heading); copy ForbiddenView "role atau izin" (guard memakai keduanya).
- `SessionsView` + `MasterDataView`: 6 tabel dibungkus `.st-tablewrap`
  (lainnya sudah) — termasuk perbaikan rantai `v-else` roster.
- `UiPageHeader`: actions wrap + full-width ≤640px. `stitch-shell.css`:
  topbar kanan wrap + scope chip ellipsis ≤640px; grid mobile
  `minmax(0,1fr)` + `.st-field` min-width 0 (opsi select sesi panjang
  memaksa kolom 486px di reports).
- Responsif terukur: hscroll 390px = 0 di 9 halaman (dashboard, sessions,
  devices, master-data, ews, corrections, reports, schedules, enrollment);
  768px = 0. Sebelumnya sessions/master-data 407px, reports 137px.

## Verifikasi slice 6
- `npm run typecheck` → hijau.
- `npm run lint` → hijau.
- `npm run test:unit -- --run` → 27 berkas, 97 passed.
- Bukti: `uad1-2/` (detail koreksi, keputusan, EWS kini, aktivasi display,
  dashboard admin, mobile 390 ×4). Log UAT: `/tmp/uataudit/uat-{admin,guru,
  laboran}.log` + `uat-interact.log`.
- Belum diuji (butuh hardware): frame kamera nyata, companion lintas-PC,
  latensi polling kiosk di perangkat nyata → `MANUAL HARDWARE TEST REQUIRED`.

## Slice 6b — uji flow mendalam per halaman (2026-11-07)
Semua flow diuji sebagai admin di aplikasi berjalan; yang mutatif
dihindari kecuali tercatat.
- Login salah → error "Email atau kata sandi tidak valid." ✓
- Jadwal: drawer "Tambah Jadwal" lengkap; submit kosong → error validasi ✓
- Sesi: "Tidak ada jadwal aktif" sesuai seed sadar-waktu; sesi aktif
  09.38 dibuka via "Pantau Sesi & Roster" → roster 10 baris + form tandai
  manual + tombol "Tutup sesi" ✓ (tutup/open tidak dieksekusi — tidak ada
  jadwal openable pada jam uji; butuh uji buka→tutup terjadwal).
- EWS: drawer detail + textarea tindak lanjut terisi lalu dibatalkan ✓
  (submit tidak dieksekusi agar tidak mengotori DB dev bersama).
- Akun: form inline + validasi required; detail laboran → 14 checkbox izin +
  bagian penugasan lab ✓.
- Master: search "Ahmad" → 10 baris; pagination 5 kontrol ✓.
- Laporan: filter terapkan → 20 baris; ekspor CSV terunduh
  `attendance-2026-11-01-2026-11-07.csv` ✓.
- Kiosk: klik "Buat/reset PIN" me-reset PIN Kiosk Lab Fisika + banner
  sekali-tampil ✓ (screenshot ber-PIN tidak diarsip). Daftar 3 layar ✓.
- Enrollment: pilih siswa → "Dipilih ✓" ✓ (capture butuh kamera nyata).
- Display: PIN salah → "PIN salah." ✓ (PIN tidak di URL).
- Audit 50 baris; policy 6 input + 2 tombol simpan ✓. Nol pageerror.
- Bukti: `uad1-3/` (17 file) + folder Nextcloud share (26 file uad1-2/3,
  tanpa screenshot ber-PIN).

## Slice 6c — lifecycle penuh via API + DB (2026-11-07, izin user)
Jadwal uji "UAT Full Lifecycle TEST - HAPUS" (Sabtu, 12:00–16:00 WIB,
XII RPL 1 / Lab Komputer 1 / Dewi) dibuat → sesi dibuka (201,
`manual_override`, roster snapshot 10 siswa) → tandai manual Ahmad
`present`/`manual` (201) → koreksi guru present→late (201 pending) →
setujui admin (200, record jadi `late`) → duplikat sequential diizinkan
(201, lalu ditolak) → tolak tanpa alasan = 422 "Alasan penolakan wajib
diisi" ✓ → koreksi tanpa-record saat sesi aktif = 409
"gunakan tandai manual; hanya untuk sesi tutup" ✓ → tutup sesi (200).
EWS: guru di luar cakupan → 404; guru dalam cakupan → 200; admin → 200
(`ensure_student_read` aktif). Sesi tutup → koreksi tanpa-record 201 →
setujui → record `excused`/`manual` tercipta ✓ (`recorded_at` = waktu
keputusan, `occurred_at` null — sesuai diskusi waktu kedatangan).
RBAC API: laboran hanya melihat 2 lab penugasan (admin 4); guru hanya
1 kelas penugasan (admin 2 total); jadwal laboran 6 / guru 4 / admin 6;
buka sesi lab tak ditugaskan → 404 `schedule_not_found` ✓; konflik
jadwal (guru/kelas/lab bentrok) → 409 `schedule_conflict` ✓.
Bersih-bersih: 3 koreksi + 2 record + 20 roster + 2 sesi + 2 jadwal +
1 lab + 2 follow-up uji dihapus via DB (audit log dibiarkan append-only);
PIN kiosk yang ter-reset saat uji flow adalah operasi UAT normal.

## Slice 6d — UAD1-4: ritme spacing + kiosk gelap ala Stitch (2026-11-07)
Ritme global di `styles/stitch-shell.css`: tombol anti-wrap, aksi tabel flex
gap 6px, judul–tabel margin 12px, hover baris, form PIN lab sebaris
(`accounts-view__pin-form`). Kiosk `/display` redesain gelap B07-01/B07-07:
aktivasi (radio lab/kamera, PIN, Terminal ID), papan (bingkai kamera,
spotlight HADIR/TERLAMBAT, chips nama singkat tanpa NIS). Hscroll 390 = 0
(kiosk, devices, ews, reports, sessions). Bukti: `uad1-4/`.
Gate: typecheck hijau, lint hijau, unit 28 berkas / 101 passed.
## Slice 6e — UAD1-5: skala/animasi/container + konten halaman (2026-11-07)
Render frame Stitch langsung sebagai acuan ukuran. Skala teks disamakan
(20/16/15/13/11px, hero 28px), container 1600px untuk 2–4K, kit animasi
Stitch + reduced-motion, fix topbar mobile. Laporan/Sesi/Koreksi-detail/
Drawer-siswa dinaikkan isi + gayanya (progress bar, Kolom toggle, live
roster, before→after, cek NIS). hscroll 0 di 15 rute × 5 viewport.
Bukti: `uad1-5/`. Gate: typecheck/lint hijau, unit 28/101.
## Slice 6f — UAD1-6: dialog cabut, drawer EWS, banner pantau, Kelas Saya (2026-11-09)
Dialog “Cabut Acuan Wajah Siswa?” ala frame_9 (eyebrow kritis, identitas,
peringatan dampak, alasan wajib min 10/maks 120 + counter, Batal / Ya cabut;
unit test validasi). Drawer EWS ala frame_12 (nama+NIS, chips kelas/status,
ringkasan pemicu + risiko, sesi terkait nyata dari report rows, riwayat +
footer ganda). Banner pantau laboran ala frame_0 (izin terbatas + delegasi
guru pengampu; hanya tampil tanpa session_operate). Kartu Kelas Saya ala
frame_6 (panel lab dari jadwal, sesi terdekat, badge pengganti). Komponen
UiField: asterisk kini menempel pada label. Hscroll 390 = 0 (10 rute).
Bukti: `uad1-6/`. Gate: typecheck/lint hijau, unit 29/103.

## Slice 8 — reskin brand SMA Cimahi + palet Figma UI CAPSTONE (2026-11-10)
- Sumber warna: sampling piksel proto Figma `node-id=47-1082`
  (header navy `#102A43`, aksen emas `#D4A72C`, canvas `#F8FAFC`,
  info `#0284C7`/`#E0F2FE`) — dibaca via Playwright tanpa login.
- `apps/web/public/logo-sekolah.png`: crop crest dari header Figma (180px,
  ditampilkan 40px sidebar / 96px login / 48px kiosk; ganti resolusi bila sekolah
  memberi file logo resmi). Dipakai di `Sidebar.vue`, `LoginView.vue`,
  `DisplayView.vue` (kiosk publik).
- `Sidebar.vue` + `LoginView.vue`: brand memakai `<img>` logo + nama sekolah.
- `stitch-tokens.css`: primer teal → navy, tambah `--st-gold*`, teks/kanvas slate.
- `stitch-shell.css`: sidebar navy + indikator emas, tombol primer navy + garis emas,
  kiosk mark emas, var Gentelella `--sidebar-*`/`--primary*` diselaraskan.
- `index.html`: theme-color navy `#102A43` + favicon SVG navy (bukan file logo). `DisplayView.vue`: navy/gold kiosk memakai token (`var(--st-primary-container)` / `var(--st-gold)`), bukan hex hardcode.
- Verifikasi: typecheck bersih, eslint bersih, vitest 103 passed (sebelum fix CSS
  kontras link aktif — perubahan murni stylesheet), responsif 390 nol overflow.
  Bukti: `/tmp/uat/u8-02-sidebar-navy.png`, `/tmp/uat/u8-03-sidebar-fixed.png`,
  `/tmp/uat/u8-04-login-logo.png`.

## Slice 9 — UAT sweep 149 screenshot + fix kontras/waktu (2026-11-10 malam)
- Fix kontras tautan aktif sidebar navy (teks emas sulit dibaca → putih di atas
  navy) + wrap nama sekolah; bukti `/tmp/uat/u8-*`.
- Fix waktu roster mentah ISO → `displayDateTime(recorded_at, timezone)` di
  `SessionsView.vue`; typecheck + 9 tes SessionsView hijau.
- Sweep `/tmp/uat/u9-*`: 149 PNG — admin 72 (24 rute × 3 viewport 1920/1366/390),
  guru ±40, laboran ±30, kiosk 3; negatif RBAC terbukti
  (guru/laboran → "Akses tidak tersedia"); koreksi-detail + my-classes-detail OK.
- Koreksi metodologi: screenshot session-detail wajib scroll ke h1 "Detail Sesi"
  (konten di bawah fold); 4 file yang tadinya memotret list diperbaiki
  (guru desktop/laptop/hp + laboran desktop) dan terverifikasi roster 10 baris.
- Overflow 390 terukur 0 di reports, audit, corrections, ews, master-data/students
  (session-detail juga 0). Console: hanya 401 refresh (jinak, probe tanpa cookie),
  403 guard negatif (bukti RBAC), 404/409 alur yang diharapkan, dan
  ERR_CONNECTION_REFUSED companion :8765 (dijinkan, AI_EDGE tak ada di mesin uji).
  Nol pageerror.
- Branding Figma diverifikasi live: sidebar navy + logo, login navy + logo,
  dashboard admin, kiosk gelap PIN OK.
- Berkas siap upload Nextcloud di `/tmp/uat/u9-*.png` (+`u8-*`); kredensial/link
  share belum ditemukan di repo/env/history — menunggu link dari pemilik.
- Stitch hanya read-only via Playwright (edit butuh login Google): tabel map
  warna manual Primary `#102A43`, Dark `#0B2036`, Secondary `#1B4965`,
  Gold `#D4A72C`, Gold-Tint `#FEF3C7`, Canvas `#F8FAFC`, Ink `#0F172A`,
  Muted `#64748B`, Info `#0284C7` + `logo-sekolah.png`.
