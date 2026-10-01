# Local development infrastructure

`docker-compose.yml` menyediakan PostgreSQL dan FastAPI Core API. Central AI service berjalan terpisah lewat profile `central`; web dapat dijalankan native untuk HMR atau memakai profile `web-container`. Kamera dan edge-agent tidak masuk ke Compose.

Copy `.env.example` menjadi `.env`, lalu jalankan `python scripts/dev.py dev-up`. Task runner juga menyediakan `dev-down` dan `test`. Data PostgreSQL disimpan pada named volume `postgres-data`; `dev-down` tidak menghapus volume.

Image Compose hanya untuk development. API healthcheck memeriksa endpoint proses `/health`; koneksi database belum dipakai oleh API scaffold saat ini.
