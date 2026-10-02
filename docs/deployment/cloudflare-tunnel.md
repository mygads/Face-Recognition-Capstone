# Domain dan Cloudflare Tunnel

Panduan ini untuk memberi akses terbatas ke web presensi tanpa membuka port
database atau service mentah ke Internet. Sesuaikan contoh domain dengan domain
sekolah yang dimiliki dan dikelola institusi. Tunnel, DNS, dan Access tidak
menggantikan autentikasi FastAPI, RBAC, atau persetujuan tata kelola data.

## Topologi dan hostname contoh

Gunakan satu hostname web yang diarahkan ke reverse proxy. Reverse proxy
menyajikan Vue dan meneruskan prefix /api/ ke Core API. Untuk STB atau edge
agent, utamakan DNS internal/VPN langsung ke reverse proxy supaya request
perangkat tidak melewati halaman login interaktif Access.

| Hostname contoh | Pengguna | Tujuan |
| --- | --- | --- |
| presensi.sekolah.example | Browser operator | Cloudflare Tunnel -> Nginx -> Vue dan prefix /api/ ke Core API |
| presensi.internal.sekolah.example | Edge agent di jaringan sekolah | DNS internal ke Nginx dengan TLS; jalur API perangkat yang terautentikasi |
| ai.internal.sekolah.example | STB gateway di VLAN kamera | DNS internal ke proxy untuk AI Central; batasi firewall ke VLAN yang perlu |
| Tidak ada hostname publik | Database | PostgreSQL hanya di jaringan container/private; port 5432 tidak dipublikasikan |

Ganti nama domain contoh, alamat internal, serta certificate sesuai infrastruktur
sekolah. Atur split DNS sehingga klien dalam sekolah memakai alamat internal.
Jangan arahkan endpoint AI, database, metrik, OpenAPI, atau halaman dokumentasi
interaktif ke hostname publik.

~~~mermaid
flowchart LR
  Staff[Browser operator] -->|HTTPS| Tunnel[Named Cloudflare Tunnel]
  Tunnel -->|origin lokal| Proxy[Nginx: Vue + /api/]
  Proxy --> API[Core API]
  API --> DB[(PostgreSQL private)]
  Edge[Edge PC / STB di LAN] -->|DNS internal + TLS| Proxy
  Edge -->|private network only| AI[AI Central bila dipakai]
~~~

## Prasyarat

1. Domain milik sekolah telah terdaftar dan DNS dikelola oleh pihak yang
   berwenang. Gunakan akun Cloudflare Zero Trust yang disetujui organisasi bila
   DNS/domain berada di Cloudflare.
2. Nginx atau reverse proxy lain melayani web dan API dari alamat loopback pada
   server. Ikuti [AI_EDGE runbook](ai-edge.md) atau
   [AI_CENTRAL + STB runbook](ai-central-stb.md) untuk mengaktifkan server.
3. Pilih TLS yang tervalidasi untuk browser dan perangkat. Edge agent saat ini
   mengautentikasi perangkat ke service, tetapi belum mengimplementasikan
   Cloudflare Access service token.
4. Sekolah menyetujui aliran data yang melalui penyedia tunnel sebelum data
   biometrik atau data siswa nyata diproses. Panduan ini bukan penetapan
   kepatuhan hukum.

## Siapkan domain sekolah

Gunakan domain yang dimiliki sekolah, misalnya presensi.nama-sekolah.ac.id.
Jangan mendaftarkan domain produksi atas akun pribadi tanpa persetujuan sekolah.
Jika sekolah belum punya domain, minta pengelola TI memilih registrar dan
menangani kepemilikan, perpanjangan, serta pemulihan akun terlebih dahulu.

Untuk public hostname melalui Cloudflare Tunnel, tambahkan domain atau
subdomain yang didelegasikan ke zona Cloudflare sesuai wizard resmi, lalu
pastikan administrator domain memperbarui nameserver/DNS delegation di
registrar bila diperlukan. Setelah hostname diarahkan ke named Tunnel, uji
resolusi DNS dari jaringan luar dan jaringan sekolah. Alternatif untuk jaringan
lokal saja adalah internal DNS sekolah dengan sertifikat TLS yang dipercaya
oleh browser dan agent; domain publik tidak wajib untuk development.

## Named Tunnel untuk browser operator

Buat named Tunnel lewat dashboard Cloudflare Zero Trust atau CLI resmi,
pasang connector cloudflared pada server, lalu tambahkan public hostname yang
mengarah ke origin Nginx lokal. Origin umumnya loopback port 80/443; jangan
arahkan Tunnel langsung ke port development Vite, port API, AI service, atau
PostgreSQL. Pasang connector sebagai service sesuai OS dan simpan tunnel token
sebagai secret dengan ACL terbatas.

Tambahkan aplikasi self-hosted Cloudflare Access untuk hostname web, lalu buat
policy Allow hanya untuk grup/staf sekolah yang disetujui. Gunakan MFA bila
tersedia dalam identity provider. Uji login staf yang diizinkan serta penolakan
akun yang tidak masuk policy. Hindari policy Bypass untuk akses umum.

Pada Nginx, pertahankan reverse proxy yang sama-origin: Vue di root dan request
web ke prefix /api/ diteruskan ke Core API. Dengan begitu browser tidak
memerlukan CORS lintas-domain. Jangan membuka dokumentasi API atau metrik secara
publik; batasi ke VPN/jaringan admin dan autentikasi operator.

Cloudflare Tunnel membuat koneksi keluar dari connector ke jaringan Cloudflare,
dan DNS hostname dapat diarahkan ke tunnel tanpa membuka inbound port router.
Namun, hostname publik tetap dapat dijangkau dari Internet; Access policy harus
diuji dan jalur aplikasi tetap wajib memakai login/RBAC.

## Jalur perangkat

Jangan melewatkan endpoint device langsung melalui aplikasi Access browser
tanpa desain autentikasi service-to-service. Agent saat ini tidak mengirim
Cloudflare Access service token. Pilihan yang didokumentasikan untuk pilot:

- Edge PC dan STB mengakses reverse proxy lewat DNS internal sekolah dengan
  TLS, dibatasi firewall/VLAN, dan menggunakan device credential aplikasi.
- Jika perangkat berada di luar LAN, gunakan VPN/jaringan privat yang dikelola
  sekolah atau implementasikan dan uji dukungan service identity secara khusus
  sebelum membuat jalur publik.
- AI Central hanya menerima request dari gateway tepercaya pada jaringan
  privat. Jangan membuat hostname AI publik untuk mempermudah koneksi.

FastAPI tetap memeriksa device credential, assignment lab/session, role, dan
idempotency. Access hanya lapisan akses tambahan untuk manusia; ia tidak
menggantikan pemeriksaan domain tersebut.

## Quick Tunnel untuk development

Quick Tunnel memberi URL acak berakhiran trycloudflare.com untuk demonstrasi
sementara dari data sintetis. URL dapat berubah, layanan ini tidak memiliki
SLA, dan bukan cara deploy produksi. Tanpa pembatasan email, siapa pun yang
memiliki URL dapat membuka service lokal tersebut. Gunakan flag allowed-mail
untuk meminta PIN email bagi browser manusia; ini tidak cocok untuk edge-agent
yang tidak dapat menyelesaikan PIN interaktif. Pembatasan email bukan pengganti
login aplikasi dan quick tunnel tetap hanya untuk data sintetis.

Contoh command resmi untuk menjalankan tunnel sementara ke web lokal:

~~~sh
cloudflared tunnel --url http://localhost:5173 --allowed-mail operator@example.edu
~~~

Vite dev server bersifat untuk development. Untuk uji web+API gunakan proxy
development yang memang dikonfigurasi di aplikasi; jangan membuat API port
terbuka untuk publik. Batasi email ke operator uji yang ditentukan, hentikan
connector setelah selesai, dan gunakan data sintetis saja.

## Acceptance dan operasi

- Pastikan web menerima HTTPS dengan hostname yang disetujui dan staf tidak
  dapat melewati Access atau login aplikasi.
- Pastikan browser memakai hostname yang sama untuk Vue dan API.
- Pastikan agent berhasil mengakses DNS internal, TLS, dan endpoint perangkat
  tanpa halaman login HTML Access.
- Pastikan koneksi dari Internet tidak dapat membuka port 5432, 8000, 8001,
  Vite, SSH, OpenAPI, atau metrik.
- Rotasi tunnel token jika bocor; jangan masukkan token, service credential,
  atau nilai secret ke Git, screenshot, tiket, dan log.
- Pantau konektor dan uji pemulihan setelah reboot server atau jaringan.

## Sumber resmi

- [Cloudflare Tunnel: Get started](https://developers.cloudflare.com/tunnel/get-started/)
- [Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)
- [Cloudflare Access policies](https://developers.cloudflare.com/cloudflare-one/access-controls/policies/)
- [Cloudflare Access application types](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/choose-application-type/)
- [Cloudflare Access application paths](https://developers.cloudflare.com/cloudflare-one/access-controls/policies/app-paths/)
