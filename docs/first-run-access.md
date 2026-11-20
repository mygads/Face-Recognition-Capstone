# Akses awal dan akun staf

Panduan ini untuk menyiapkan akun pada instalasi development lokal yang baru.
Sistem membuat satu akun ADMIN saat database masih kosong. Akun guru dan
laboran dibuat oleh ADMIN setelah masuk; tidak ada akun demo guru/laboran atau
password bawaan untuk kedua role itu.

## Menjalankan aplikasi pertama kali

Prasyarat: Docker Desktop + WSL2 pada Windows, atau Docker Engine + Compose di
Ubuntu; Python 3.11+; Node.js 22 atau 24; dan npm.

```powershell
# Windows
git clone https://github.com/mygads/Face-Recognition-Capstone.git
cd Face-Recognition-Capstone
py -3 scripts/start-local.py --edge
```

```bash
# Ubuntu
git clone https://github.com/mygads/Face-Recognition-Capstone.git
cd Face-Recognition-Capstone
python3 scripts/start-local.py --edge
```

Tunggu sampai API dan Vite berjalan, lalu buka:

- Web: `http://127.0.0.1:5173`
- API health: `http://127.0.0.1:8000/health`

Profile `--edge` menjalankan web, API, dan PostgreSQL. Agent AI_EDGE dan webcam
adalah proses terpisah di PC kamera; inference hanya berjalan saat agent itu
dikonfigurasi dan dijalankan. Lihat [arsitektur](architecture/overview.md)
sebelum memasang kamera.

## Akun ADMIN pertama

Pada database development yang benar-benar kosong:

- Email: `admin@local.test`
- Password sementara: `1234abcd`

Login pertama wajib mengganti password menjadi minimal 12 karakter. Bila
`PRESENSI_BOOTSTRAP_PASSWORD` diatur di `.env`, gunakan nilai itu sebagai
password sementara. Bootstrap hanya membuat akun saat belum ada pengguna;
menjalankan startup lagi tidak mengubah password pada database yang sudah
berisi akun.

Kredensial ini hanya untuk development lokal. Ganti password sebelum lingkungan
diakses perangkat lain dan jangan menyebarkan password admin lewat chat grup.

## Membuat akun guru dan laboran

1. Masuk sebagai ADMIN, lalu buka menu **Akun Staf**.
2. Klik **Tambah Staff**. Isi nama lengkap, email login, pilih role **Guru** atau
   **Laboran**, lalu masukkan kata sandi minimal 8 karakter tanpa spasi.
3. Klik **Buat akun**. Berikan email dan kata sandi yang ditetapkan kepada
   pemilik akun secara pribadi. Akun dapat langsung digunakan untuk login.
4. Buka **Kelola** pada akun itu dan isi penugasan yang sesuai:
   - **Guru:** tetapkan kelas yang diajar. Jadwal, sesi, dan data kelas dibatasi
     oleh penugasan tersebut.
   - **Laboran:** tetapkan laboratorium yang menjadi tanggung jawabnya. Hak
     akses tambahan hanya diberikan bila pekerjaannya memang memerlukan.

Role guru dan laboran memiliki akses berbeda. Laboran tanpa penugasan lab tidak
bisa mengoperasikan perangkat lab; guru tanpa penugasan kelas tidak melihat
roster kelas. Berikan akses minimum yang diperlukan.

Jika password sementara staf hilang, ADMIN dapat membuka akun di **Akun Staf**
dan memilih **Reset kata sandi**. Password baru ditampilkan satu kali dan staf
wajib menggantinya saat login. Jangan menghapus volume database untuk memulihkan
password karena tindakan itu menghapus data development lainnya.
