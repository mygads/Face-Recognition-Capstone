# ADR-002: Session opening modes and preview-only camera recognition

- **Status:** Accepted
- **Tanggal:** 2026-10-03
- **Konteks:** Guru memerlukan pilihan membuka sesi secara manual atau mengikuti jadwal. Operator juga memerlukan preview identitas sebelum sesi dimulai, sedangkan hasil preview tidak boleh menjadi presensi. Admin memerlukan cara menjeda kamera jarak jauh tanpa mencabut registrasi perangkat.

## Keputusan

1. Mode pembukaan sesi bersifat global dan dapat dipilih admin: `manual` (default) atau `automatic`.
2. Mode otomatis menggunakan jendela konfigurasi paling banyak 15 menit sebelum sampai 15 menit setelah jam mulai jadwal. Backend membuka sesi satu kali, mengambil snapshot roster yang sama dengan alur manual, menutup pada akhir jadwal, dan mencatat audit sebagai aksi sistem. Default jendela otomatis adalah 0 menit sebelum sampai 15 menit sesudah jadwal.
3. Grace period sesi otomatis dihitung dari jam mulai jadwal agar keterlambatan polling tidak menggeser batas hadir. Sesi manual mempertahankan grace period dari saat guru membuka sesi.
4. Di luar sesi aktif, AI_EDGE boleh memuat gallery preview sementara yang hanya berisi siswa bertemplate aktif pada kelas dengan jadwal valid untuk hari itu dan laboratorium device tersebut. Gallery berakhir otomatis, hanya disimpan di memory, dan hanya dipakai ketika preview lokal yang terautentikasi sedang dibuka.
5. Hasil off-session dan hasil diagnostik yang belum melewati threshold operasional ditampilkan sebagai kandidat sementara dengan label bahwa skor bukan akurasi. Jalur ini tidak menghasilkan recognition event maupun attendance record. Saat sesi aktif, gallery snapshot sesi menjadi satu-satunya sumber kandidat presensi.
6. Admin dapat mengaktifkan/menjeda kamera dari registry. Perubahan adalah desired state terpisah dari `devices.is_active`; agent menghentikan capture ketika menerima state tersebut, dan Core API menolak event baru selama kamera dijeda. Perubahan ditulis ke audit log.
7. Enrollment dan AI_EDGE menggunakan satu set quality capture yang sama di dashboard. Quality tetap diterbitkan sebagai bagian versi konfigurasi enrollment dan versi konfigurasi device agar kegagalan sinkronisasi tiap layanan terlihat.

## Konsekuensi

- Preview dapat menampilkan nama kandidat sebelum sesi aktif, tetapi hanya dari kelas terjadwal di lab yang sama dan tidak membuat presensi.
- Penundaan atau kegagalan service API dapat menunda automatic opening sampai jendela yang dikonfigurasi berakhir. Admin harus memonitor status API dan setting jadwal.
- Jeda kamera jarak jauh memerlukan agent tersambung untuk melepas camera device secara aktual; Core API tetap langsung menolak event baru setelah admin menyimpan jeda.
- Kandidat preview dapat salah; UI tidak boleh menyebut skor similarity sebagai confidence/akurasi dan tidak boleh menyatakan presensi berhasil.
