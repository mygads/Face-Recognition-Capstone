# ADR-003: Mode pembukaan sesi per guru, manual override, dan auto-close selalu

- **Status:** Accepted (keputusan tim 2026-10-21); implementasi: Belum.
- **Konteks:** ADR-002 menetapkan mode pembukaan sesi global (`manual`/`automatic`)
  yang dipilih admin. Kebutuhan operasional sekolah menghendaki kontrol per guru:
  tiap guru memilih sesi mereka dibuka otomatis mengikuti jadwal atau dibuka manual
  oleh guru sendiri. Selain itu, guru harus bisa membuka sesi secara manual bahkan
  ketika jendela otomatis sedang tertutup (misalnya jadwal tambahan), tanpa
  mematikan penutupan otomatis pada akhir jadwal.
- **Pelaksana:** tim backend + frontend (butuh migrasi Alembic, worker
  auto-open/auto-close, dan UI pengaturan guru). Lihat backlog P1-9, P1-10.

## Keputusan

1. Setiap guru memiliki pengaturan `opening_mode`: `automatic` atau `manual`.
   Nilai default adalah `manual` (perilaku saat ini tidak berubah bila guru tidak
   mengatur apa pun).
2. Worker otomatis hanya membuka sesi untuk jadwal milik guru dengan mode
   `automatic`, memakai jendela dan aturan snapshot roster yang sama dengan
   ADR-002. Guru mode `manual` membuka sesi sendiri seperti sekarang.
3. Guru boleh membuka sesi secara manual kapan pun — termasuk di luar jendela
   otomatis (misalnya jadwal sedang tutup). Sesi yang dibuka paksa seperti ini
   berstatus **`manual_override`** (bukan `active` biasa) agar dasbor dan audit
   menunjukkan bahwa sesi berjalan atas intervensi guru.
4. Status `manual_override` tetap tunduk pada penutupan otomatis: worker
   auto-close menutupnya pada jam akhir jadwal seperti sesi `active`. Guru juga
   tetap bisa menutup manual kapan pun.
5. Grace period mengikuti aturan yang sudah ada: sesi otomatis (termasuk yang
   dibuka worker) dihitung dari jam mulai jadwal; sesi yang dibuka guru secara
   manual memakai grace sejak sesi dibuka.
6. Semua transisi (auto-open, manual open, override, auto-close, manual close)
   diaudit dengan aktor (`system` vs user id guru) agar delegasi tugas dan
   investigasi insiden jelas.

## Konsekuensi

- Skema `attendance_sessions.status` bertambah satu nilai (`manual_override`).
  Semua pembaca status (dasbor guru, live dashboard, agent gallery scope,
  laporan) harus memperlakukannya sebagai "sesi berjalan" untuk matching dan
  presensi, tetapi menampilkannya berbeda dari `active`.
- Worker auto-close harus menutup `active` DAN `manual_override` pada akhir
  jadwal; worker auto-open tidak boleh menimpa/menutup sesi `manual_override`
  yang sedang berjalan.
- Pengaturan per guru membutuhkan UI baru di dasbor (radio automatic/manual per
  guru yang login) dan endpoint penyimpanan preferensi.
- Jika guru mode `automatic` tidak kunjung dibuka worker (API down, jadwal di
  luar jendela), guru tetap bisa memakai jalur manual override — tidak ada jalan
  buntu operasional.
- Keputusan ini tidak mengubah aturan fail-closed lain: matching tetap dibatasi
  roster snapshot, ambiguitas tetap retry, duplikat tetap ditolak.
