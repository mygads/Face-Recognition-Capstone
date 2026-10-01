# Protokol uji lapangan walk-through

## Tujuan dan batasan

Protokol ini membandingkan perilaku presensi walk-through dan fallback frontal
pada `AI_EDGE` dan `AI_CENTRAL` dalam sesi uji terkontrol. Catat hasil per
kondisi, termasuk kegagalan dan percobaan ulang. Dokumen ini bukan persetujuan
untuk memakai biometrik siswa, bukan bukti kepatuhan hukum, dan bukan dasar
memilih threshold produksi tanpa kalibrasi dan tinjauan sekolah.

Uji awal memakai relawan dewasa yang menyetujui partisipasi. Jangan memakai data
wajah siswa/minor dalam cloud, CI, atau laporan ini. Pengujian dengan siswa
memerlukan persetujuan serta kebijakan sekolah yang berlaku, pemberitahuan yang
jelas, pilihan presensi manual tanpa penalti, dan penanggung jawab yang
ditetapkan sekolah.

Yang diuji adalah hasil operasional dari frame pertama sampai keputusan yang
terlihat di UI, termasuk retry. Benchmark offline tetap digunakan untuk
mengukur inference murni. Uji ini tidak merekam foto, video, audio, embedding,
nama, NIS/NISN, tanggal lahir, atau UUID siswa/device ke formulir hasil.

## Aturan privasi dan keselamatan

- Jalankan pada akun, kelas, roster, jadwal, dan attendance session khusus uji;
  jangan menulis hasil ke presensi kelas aktif.
- Minta persetujuan sebelum enrolment dan sebelum setiap sesi. Relawan dapat
  berhenti atau memilih presensi manual kapan saja tanpa perlu menjelaskan
  alasan.
- Beri setiap relawan kode acak seperti `P01`. Gunakan kode roster uji yang
  sama pada formulir; jangan menyimpan tabel penghubung kode dengan nama.
- Jangan mengambil screenshot, foto, video, atau rekaman layar. Formulir hanya
  mencatat kode, kategori kondisi, status, dan durasi. Jangan menyalin
  embedding, payload API, token, UUID, atau raw recognition event ke dokumen.
- Template biometrik uji tetap merupakan data sensitif walau relawan memakai
  kode. Batasi akses, gunakan masa retensi pendek yang disetujui, lalu revoke
  template dan bersihkan akun/session uji sesuai prosedur sekolah. Catat jumlah
  template yang dibersihkan, bukan vektornya.
- Bekukan model/version, threshold, quality gate, grace period, dan konfigurasi
  sampling sebelum run. Jangan mengubah threshold di tengah run. Perubahan
  konfigurasi memerlukan `run_id` baru dan enrolment uji yang konsisten.
- Jika sistem membuat final attendance untuk orang yang salah, menghitung satu
  orang dua kali, atau menerima wajah non-roster, hentikan automated run,
  simpan kode kondisi dan hasil minimum untuk investigasi, lalu gunakan
  presensi manual. Jangan menghapus audit record untuk menutupi kegagalan.

## Persiapan

1. Tetapkan penanggung jawab, operator kamera, pencatat, dan petugas yang dapat
   menghentikan run. Operator dan pencatat boleh orang yang sama pada uji kecil.
2. Siapkan relawan dewasa, persetujuan, kode `Pxx`, serta roster uji yang
   menghubungkan kode itu ke akun dummy. Untuk uji kemiripan, hanya gunakan
   pasangan yang secara sukarela bersedia; jangan memilih atau melabeli orang
   berdasarkan etnis, hubungan keluarga, atau dugaan identitas.
3. Pilih satu profile per run. Catat `AI_EDGE` atau `AI_CENTRAL`, kode lab uji,
   app version, model name/version, device app version, dan konfigurasi kamera.
   Jangan mencatat token atau secret.
4. Kunci posisi kamera, tinggi kamera, jarak jalur, fokus, resolusi/FPS, dan
   konfigurasi model untuk semua sel yang dibandingkan. Tandai jalur dan titik
   berhenti dengan tape di lantai. Catat lux di sekitar bidang wajah/kamera
   menggunakan lux meter bila tersedia.
5. Jalankan satu warm-up yang sama sebelum pengukuran. Pastikan sesi aktif,
   roster sudah tersnapshot, setiap relawan terdaftar sebagai identitas yang
   berbeda, dan UI menampilkan status sesi yang benar.
6. Lakukan setiap sel minimal **5 lintasan per relawan per profile**. Acak urutan
   sel jika aman agar kelelahan atau perubahan cahaya tidak selalu menimpa
   kondisi yang sama. Catat jumlah percobaan aktual; jangan mengisi percobaan
   yang tidak dilakukan.
7. Ulangi langkah yang sama pada profile kedua dengan roster uji dan kondisi
   semirip mungkin. Jangan menganggap hasil dua host sebanding bila kamera,
   model, gallery, posisi, atau pencahayaan berbeda; tulis perbedaannya.

Lima lintasan per sel cukup untuk menemukan masalah operasional awal, bukan
untuk menyatakan akurasi atau false-accept rate populasi. Laporkan selalu
pembilang, penyebut, dan kondisi yang diuji. Tidak ditemukannya false accept
pada sampel kecil tidak membuktikan `FAR = 0`.

## Prosedur lintasan

Untuk setiap lintasan, pencatat sudah mengetahui kode relawan yang akan masuk.
Relawan mulai di garis yang sama, berjalan melalui zona kamera, dan tidak
berhenti kecuali instruksi fallback muncul. Jangan menyebut nama/nomor siswa di
depan kamera sebagai bagian dari identifikasi.

1. Mulai stopwatch/marker waktu saat frame pertama lintasan dikirim kamera.
2. Amati status pada UI/operator panel: accepted, late, retry frontal, rejected,
   timeout, atau tidak ada keputusan. Catat identitas uji yang dikenali sebagai
   `Pxx`, `NONE`, atau `MULTI`; jangan mengisi nama akun.
3. Jika sistem meminta frontal retry, relawan berhenti di marker frontal,
   menghadap kamera, dan melakukan **satu** retry. Catat durasi sampai status
   akhir. Jika masih belum ada keputusan yang benar, gunakan fallback manual.
4. Hentikan timer keputusan saat UI menampilkan status terminal. Jika UI juga
   menunggu final attendance dari API, catat terpisah waktu sampai status final
   presensi terlihat.
5. Verifikasi hasil terhadap kode relawan dan catat apakah final record tepat
   satu kali, terlambat, tidak ada, atau salah identitas. Pemeriksaan ini
   dilakukan oleh operator, bukan berdasarkan ingatan relawan.
6. Lanjutkan ke baris berikutnya. Tunggu track/session state siap sebelum
   lintasan berikutnya agar bukti temporal dari dua percobaan tidak tercampur.

## Matriks kondisi

| Kode | Kondisi | Pelaksanaan | Hasil aman yang diharapkan |
|---|---|---|---|
| `NORM` | Berjalan normal | Kecepatan jalan alami relawan, jalur dan jarak tetap. Catat kecepatan bila dapat diukur; jangan menyuruh berlari. | Identitas benar tanpa retry adalah lintasan first-pass sukses. |
| `FAST` | Berjalan lebih cepat | Jalan cepat yang nyaman dan aman, bukan lari. Jalankan pada jalur yang sama dengan `NORM`; catat waktu lintasan atau band kecepatan yang ditetapkan sebelum run. | Identitas tetap benar atau sistem meminta retry/fallback; tidak boleh menerima orang yang berbeda. |
| `YAW0` | Frontal | Wajah mengarah ke kamera pada marker tengah (`0°`). Badan tetap di jalur yang sama. | Identitas benar; ini baseline frontal. |
| `YAW15+`, `YAW15-` | Sudut sekitar `+15°` dan `−15°` | Gunakan marker target kiri/kanan untuk arah wajah. Pertahankan jarak dan jalur. | Hasil benar atau meminta frontal retry; keputusan ambigu tidak boleh auto-accept. |
| `YAW30+`, `YAW30-` | Sudut sekitar `+30°` dan `−30°` | Sama seperti ±15°, dengan target arah wajah sekitar ±30°. Catat arah sesuai posisi kamera, bukan kiri/kanan peserta. | Hasil benar atau retry/reject yang aman; tidak boleh salah mengaitkan identitas. |
| `EYE_LOW`, `EYE_MID`, `EYE_HIGH` | Variasi tinggi badan / eye line | Gunakan relawan dewasa dengan eye line relatif rendah, tengah, dan tinggi terhadap sumbu kamera tetap. Jangan mengubah tinggi kamera atau meminta relawan berdiri di atas benda. Catat hanya band relatif, bukan tinggi badan angka. | Kualitas/coverage konsisten atau UI meminta reposisi/fallback; tidak ada salah identitas. |
| `GLASS_ON`, `GLASS_OFF` | Kacamata | Bila relawan memakai kacamata dan nyaman, ulangi lintasan dengan kacamata dan tanpa kacamata. Jangan meminta melepas kacamata yang diperlukan untuk melihat/berjalan. | Catat retry/reject yang muncul; identitas lain tidak boleh diterima. |
| `LIGHT_AM`, `LIGHT_MID`, `LIGHT_PM` | Pencahayaan pada beberapa waktu | Ulangi sel terpilih pada pagi, tengah hari, dan sore. Catat bucket waktu dan lux terukur, sumber cahaya, serta backlight bila ada. Jangan mengubah exposure/threshold antar bucket. | Status kualitas dan keputusan terukur pada tiap kondisi; kegagalan kualitas harus tampak sebagai retry/reject, bukan salah identitas. |
| `PAIR_NEAR` | Dua siswa/relawan masuk berdekatan | Dua relawan berbeda masuk berdampingan/berurutan dengan jarak waktu yang ditetapkan (mis. kurang dari 1 detik). Ulangi juga dengan jarak normal sebagai kontrol. Catat hasil masing-masing kode. | Masing-masing paling banyak satu final record yang benar; jika beberapa wajah membuat keputusan ambigu, sistem minta pemisahan/frontal retry. Tidak ada pertukaran identitas. |
| `LOOKALIKE` | Pasangan dengan kemiripan tinggi, bila tersedia | Hanya pasangan dewasa yang menyetujui dan secara sukarela diketahui tim sebagai pasangan uji look-alike. Enrol sebagai dua kode yang berbeda; uji bergantian dalam roster uji yang sama. Jika tidak ada pasangan yang sesuai, tandai `NOT TESTED`. | Tidak ada auto-merge atau final attendance silang. Ambiguitas harus berujung retry/fallback. Salah identitas final dihitung false accept dan menghentikan automated run. |
| `FRONTAL_FB` | Fallback frontal | Lakukan setelah sistem meminta retry pada sudut/kecepatan tertentu. Relawan berhenti di marker dan menghadap kamera untuk satu retry; catat hasil awal dan hasil akhir. | Retry dapat memulihkan keputusan benar. Jika belum benar, fallback manual; jangan membuat presensi otomatis yang tidak didukung bukti. |

Untuk semua kondisi, ukur jarak dan kecepatan dengan cara yang sama di kedua
profile. Jangan menyebut nilai sudut atau lux lebih presisi daripada alat/marker
yang digunakan; tulis `approx` bila hanya estimasi visual.

## Definisi metrik

Hitung metrik keseluruhan dan pecah hasil menurut profile, kode kondisi,
relawan berkode, dan pencahayaan. Selalu tampilkan jumlah percobaan dan
penyebut.

| Metrik | Definisi operasional |
|---|---|
| Walk-through success rate (setelah fallback) | Lintasan enrolled yang berakhir dengan tepat satu final attendance pada kode yang benar setelah maksimal satu frontal retry, dibagi seluruh lintasan enrolled yang dijalankan. Laporkan juga `first-pass success rate` tanpa fallback agar fallback tidak menyamarkan kelemahan fast path. |
| Retry rate | Lintasan yang menerima `NEED_FRONTAL_RETRY`/instruksi frontal dibagi seluruh lintasan eligible. Laporkan count dan persentasenya per kondisi. |
| False accept (FA) | Keputusan/final attendance otomatis untuk kode roster yang salah, atau auto-accept atas impostor/non-roster challenge. `FA count` adalah jumlah kejadian; `FA rate` dibagi jumlah impostor challenge yang benar-benar dijalankan. Untuk pasangan look-alike, setiap lintasan yang tertaut ke kode pasangan yang salah adalah FA. |
| False reject (FR) | Lintasan dari relawan enrolled yang tidak menghasilkan identitas dan final attendance yang benar setelah batas retry/fallback, dibagi seluruh lintasan enrolled. Hasil salah identitas dapat dihitung sebagai FA sekaligus FR untuk relawan yang benar; laporkan aturan ini dan kedua count secara terbuka. |
| Decision latency | Detik dari frame pertama yang dikirim sampai keputusan AI terminal yang terlihat. Laporkan p50 dan p95 untuk hasil terminal, serta count timeout/incomplete terpisah. |
| End-to-end attendance latency | Detik dari frame pertama sampai final status presensi terlihat di UI/API. Laporkan p50/p95 terpisah dari decision latency; ini mencakup jaringan dan finalisasi bisnis. |
| Enrollment time | Detik dari operator mulai capture/countdown untuk satu kode sampai backend mengonfirmasi enrollment dan operator mengonfirmasi identitas. Catat keberhasilan/gagal dan jumlah capture/retry; jangan menyimpan capture atau vektor. Laporkan p50/p95 untuk enrollment yang berhasil dan count yang gagal. |

Rate di atas adalah metrik pilot operasional dengan denominator dari protokol ini,
bukan estimasi terstandar untuk semua pengguna. Tetapkan target kinerja dan
kriteria penerimaan sebelum menjalankan pilot; dokumen ini tidak menetapkan
threshold recognition atau klaim legal/compliance.

## Form pencatatan

Isi satu salinan metadata untuk setiap profile/run. Formulir ini sengaja tidak
memiliki kolom nama, nomor sekolah, tinggi badan angka, foto, atau UUID. Gunakan
kode peserta uji saja.

### Metadata run

| Kolom | Isian |
|---|---|
| Run ID acak | |
| Tanggal / bucket waktu | |
| Profile (`AI_EDGE` / `AI_CENTRAL`) | |
| Kode lokasi/lab uji | |
| App version / commit | |
| Model name/version | |
| Camera resolution/FPS dan posisi tetap | |
| Model/threshold/config dibekukan sebelum run? | `Ya / Tidak` |
| Lux meter / cara estimasi cahaya | |
| Operator/pencatat berkode | |
| Persetujuan dan jalur presensi manual sudah dijelaskan? | `Ya / Tidak` |
| Catatan kondisi non-identifying | |

Catat perubahan cahaya tanpa mengaitkan nilai ke identitas selain kode uji:

| Condition code | Bucket waktu | Lux | Sumber/arah cahaya | Terukur / estimasi | Catatan |
|---|---|---:|---|---|---|
| `LIGHT_AM` | | | | | |
| `LIGHT_MID` | | | | | |
| `LIGHT_PM` | | | | | |

### Daftar relawan berkode

| Participant code | Band eye line | Kondisi kacamata yang diuji | Setuju / berhenti | Catatan non-identifying |
|---|---|---|---|---|
| P01 | `LOW / MID / HIGH` | `ON / OFF / N/A` | | |
| P02 | `LOW / MID / HIGH` | `ON / OFF / N/A` | | |
| P03 | `LOW / MID / HIGH` | `ON / OFF / N/A` | | |
| P04 | `LOW / MID / HIGH` | `ON / OFF / N/A` | | |

### Hasil lintasan

Catat status `ACCEPTED/PRESENT`, `LATE`, `NEED_FRONTAL_RETRY`, `REJECTED`,
`TIMEOUT`, `MANUAL`, atau `NONE` sesuai tampilan yang benar-benar terjadi.
Kode recognized harus `Pxx`, `NONE`, atau `MULTI`. Untuk challenge non-roster,
gunakan expected code `IMPOSTOR`; jangan buat identitas asli.

| # | Condition code | Expected code | Recognized code | Keputusan/status akhir | Frontal retry? | FA? | FR? | AI decision s | Final attendance s | Tepat satu final record? | Catatan non-identifying |
|---:|---|---|---|---|---|---|---|---:|---:|---|---|
| 1 | | | | | | | | | | | |
| 2 | | | | | | | | | | | |
| 3 | | | | | | | | | | | |
| 4 | | | | | | | | | | | |
| 5 | | | | | | | | | | | |
| 6 | | | | | | | | | | | |
| 7 | | | | | | | | | | | |
| 8 | | | | | | | | | | | |
| 9 | | | | | | | | | | | |
| 10 | | | | | | | | | | | |

### Hasil enrollment

| Participant code | Capture → backend success (s) | Capture → operator confirm (s) | Enrollment berhasil? | Retry/capture count | Template aktif setelahnya? | Catatan non-identifying |
|---|---:|---:|---:|---|---:|---|---|
| P01 | | | | | | |
| P02 | | | | | | |
| P03 | | | | | | |
| P04 | | | | | | |

### Rekap per kondisi/profile

| Condition code | Run count | Enrolled attempts | Impostor attempts | First-pass success | Success after fallback | Retry count | FA count/rate | FR count/rate | Decision p50/p95 s | Final attendance p50/p95 s |
|---|---:|---:|---:|---:|---:|---:|---|---|---|---|
| | | | | | | | | | | |
| | | | | | | | | | | |
| | | | | | | | | | | |

## Penutupan run dan laporan

- Hitung count dan rate dari percobaan yang benar-benar terjadi. Simpan
  `NOT TESTED` untuk kondisi tanpa relawan/peralatan, bukan mengisinya dengan
  nol.
- Pisahkan hasil first-pass, hasil setelah frontal fallback, dan presensi
  manual. Jangan menyingkat timeout atau hasil gagal menjadi sukses.
- Bandingkan kedua profile per sel yang setara dan sertakan denominator,
  konfigurasi/model version, lux, serta host/camera yang dipakai. Jangan
  menggabungkan hasil bila kondisi berbeda tanpa menandai perbedaan.
- Setelah ekspor, pastikan tidak ada gambar, video, embedding, nama, nomor
  sekolah, token, atau UUID di dokumen. Simpan hanya formulir pseudonim pada
  lokasi berakses terbatas sesuai masa retensi yang disetujui.
- Revoke enrollment uji, tutup session uji, dan bersihkan data uji yang tidak
  diperlukan. Verifikasi hasil cleanup tanpa menyalin template atau image.
- Lampirkan catatan anomali dan keputusan tindak lanjut. Setiap FA, duplikasi
  final record, enrollment ke kode yang salah, atau retry yang auto-accept harus
  ditinjau sebelum run otomatis berikutnya.

## Batas klaim

Uji walk-through kecil ini membantu menemukan kendala operasional dan kondisi
yang memicu fallback. Uji ini tidak menggantikan evaluasi FAR/FMR dan FRR/FNMR
dengan dataset yang memadai, analisis per kelompok, penetration/security review,
validasi model/liveness, maupun keputusan kebijakan sekolah. Threshold akhir
harus ditetapkan melalui evaluasi lokal terpisah dengan prioritas false
acceptance rendah.
