# 01 — Pendahuluan (bahan Bab I)

## 1.1 Identitas sistem

| Aspek | Isi |
|---|---|
| Nama | Sistem Presensi Praktikum Berbasis Face Recognition + Early Warning System |
| Lokasi | Laboratorium kimia (2 ruang paralel), SMA Taruna Nusantara Kampus Cimahi |
| Jadwal khas | Praktikum terjadwal Jumat (setelah salat Jumat + makan siang + istirahat); praktikum lain mengikuti kebutuhan guru |
| Pengguna login | ADMIN, TEACHER (guru), LABORANT |
| Akun non-manusia | DEVICE (service account bearer per perangkat) |
| Bukan pengguna | Siswa = objek presensi, tidak login |

## 1.2 Latar belakang

1. Mobilitas siswa antar-jam pelajaran cepat (budaya semi-militer); pemanggilan
   nama satu per satu memakan waktu praktikum.
2. Riwayat kehadiran dan alasan absen tercecer di catatan manual sehingga sulit
   dilacak (siswa terlambat karena tertidur, kegiatan sekolah, dsb.).
3. Pemeriksaan absen berulang membutuhkan konfirmasi manual ke banyak pihak.
4. Guru membutuhkan pantauan dini (early warning) atas siswa yang pola
   absen/terlambatnya memburuk, tanpa menjadikannya sanksi otomatis.
5. Solusi harus berjalan di perangkat lab yang heterogen (ada PC memadai, ada
   yang tidak) sehingga dibutuhkan dua profil deployment dengan core AI yang sama.

## 1.3 Rumusan masalah

1. Bagaimana membangun presensi walk-through yang cepat tetapi tidak
   auto-accept saat wajah ambigu?
2. Bagaimana menjamin satu event pengenalan tidak menghasilkan presensi ganda,
   dan presensi hanya lahir dari sesi + roster yang sah?
3. Bagaimana mendukung dua kondisi lab (PC memadai vs STB gateway) tanpa
   menduplikasi logika AI dan aturan attendance?
4. Bagaimana melindungi data wajah (tanpa menyimpan foto default, embedding
   terenkripsi) sekaligus menjaga jejak audit?
5. Bagaimana menyajikan daftar pantauan dini (at-risk) yang bisa dijelaskan
   ambangnya dan tidak berfungsi sebagai sanksi otomatis?

## 1.4 Batasan masalah

1. Objek hanya presensi **praktikum terjadwal** (bukan presensi harian sekolah).
2. Dua profil deployment (`AI_EDGE`, `AI_CENTRAL`) memakai
   `libs/recognition-core` yang sama dan satu otoritas attendance (Core API).
3. Raw image tidak disimpan secara default; embedding AES-256-GCM; tidak ada
   data wajah siswa nyata/minor di repository, cloud, atau CI.
4. Threshold identitas tidak memakai angka dari internet — wajib kalibrasi
   lokal (`MANUAL HARDWARE TEST REQUIRED`).
5. Tidak memakai face-recognition SaaS cloud; tidak membuka endpoint biometrik
   ke publik; tidak menyimpan foto siswa by default.
6. Koreksi kehadiran tahap berjalan = pengajuan **pending** beraudit
   (workflow keputusan persetujuan belum diimplementasikan).
7. Status `cancelled` pada sesi dicadangkan di skema tetapi belum ada endpoint
   penulisnya; penutupan sesi hanya menghasilkan `closed`.

## 1.5 Tujuan

1. Menghasilkan presensi walk-through (fast path) dengan fallback frontal look.
2. Menghasilkan keputusan presensi final yang hanya lahir setelah validasi
   sesi, roster snapshot, device, grace period, dan anti-duplikasi.
3. Menyediakan dashboard live, laporan + ekspor, dan watchlist at-risk yang
   ambangnya transparan.
4. Merancang EWS tahap 2 (tindak lanjut, notifikasi internal, eskalasi) tanpa
   mengubah arsitektur.

## 1.6 Manfaat

- Guru: buka sesi dari jadwal, pantau kehadiran live dari dalam/luar lab,
  presensi manual + koreksi beraudit.
- Laboran: enrollment wajah, operasi perangkat, preview kamera pra-sesi.
- Admin/sekolah: master data, akun, kebijakan AI & ambang EWS, audit log.
- BK/wali kelas (tahap 2): riwayat tindak lanjut + eskalasi berjenjang.
