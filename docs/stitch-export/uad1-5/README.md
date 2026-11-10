# UAD1-5 — Skala teks, animasi, container 4K + konten per halaman ala Stitch

Acuan: render langsung frame Stitch (`stitch-ref-*.png`) + inventarisasi
87 judul B01–B07 dari `companion.html`.

## Global
- Skala teks Stitch (`styles/stitch-shell.css`, blok UAD1-5): judul halaman
  20px, judul kartu 16px, isi/tabel 15px, kecil 13px, eyebrow 11px, angka
  hero 28px. Tidak ada teks yang terlalu besar/kecil.
- Container: `.st-page` max 1600px center — laptop penuh, 2–4K tidak melar
  (`reports-wide2k-2560.png`).
- Kit animasi: pulse (dot live), ping (avatar kiosk), fade/scale-in
  (drawer/modal), scale-in kartu hasil kiosk, hormat
  `prefers-reduced-motion`.
- Bug mobile: topbar 60px terkunci menumpuk konten → tinggi otomatis
  (`reports-mobile-topbar-fixed.png`).

## Per halaman (B04-01 / B03-01 / B03-09 / B02-02)
- Laporan: tombol ikon, filter auto-fit rapat, stat + ikon + progress bar,
  banner rekonsiliasi info, header tabel + chip jumlah + "Kolom" toggle
  (sembunyi/tampil kolom, `colspan` dinamis).
- Sesi: section header + catatan kanan ("Real-time…", "Lihat Semua
  Laporan →"), kartu aktif + panel live roster (progress x/y Terdata,
  Hadir/Terlambat/Belum, CTA Pantau full-width), tile info ikon,
  tombol Buka berikon + caption.
- Koreksi detail: kembali + chip tiket, kartu putusan (Tolak/Setujui
  berikon), before→after panah, quote alasan, identitas + konteks sesi +
  jejak pengajuan. Tes lama diselaraskan ("Perubahan Status Presensi").
- Master siswa: cek NIS unik vs data dimuat ("Valid & Tersedia"),
  info box, hint nama, radio berdeskripsi. Slot `label-action` baru di
  `UiField`; tanpa data asal-asalan (tanpa foto/tingkat hadir).

## Bukti
- `hscroll-5viewports.json`: hscroll = 0 di 15 rute × mobile 390,
  tablet 768, laptop 1366, desktop 1920, wide2k 2560.
- Screenshot desktop/mobile/tablet/wide2k + 4 referensi Stitch.

## Gate
- `typecheck` hijau, `lint` hijau, `test:unit` 28 berkas / 101 passed.
