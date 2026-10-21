# Pengujian: Lapangan, Benchmark, dan Privasi Uji

Satu file ini menggantikan folder `docs/test-plans/` (protokol manual) dan
meringkas harness di `tests/`. README di tiap folder `tests/` tetap menjadi
spesifikasi harness; ringkasan benchmark deployment yang ter-generate
(`summary.md`) diabaikan Git. Otoritas privasi: [security-and-privacy](security-and-privacy.md);
keputusan model: [models](models.md).

## Protokol lapangan: walk-through vs frontal

Membandingkan perilaku walk-through dan fallback frontal pada AI_EDGE dan
AI_CENTRAL dalam sesi uji terkontrol. Catat hasil per kondisi termasuk gagal
dan retry. Dokumen ini bukan persetujuan biometrik siswa, bukti kepatuhan
hukum, atau dasar memilih threshold produksi.

Aturan privasi: uji akun/kelas/roster/jadwal/sesi khusus uji (jangan tulis ke
presensi aktif); relawan dewasa dengan persetujuan (boleh berhenti/pilih
manual kapan pun); kode acak `Pxx` tanpa tabel penghubung nama; tanpa
screenshot/foto/video/embedding/payload/token/UUID di formulir; bekukan
model/version, threshold, quality gate, grace, sampling per `run_id` (ubah
config = `run_id` baru); template uji = data sensitif (retensi pendek,
revoke + cleanup terverifikasi, catat count bukan vector); FA/duplikat/
auto-accept → hentikan automated run, simpan minimum untuk investigasi, pakai
manual, jangan hapus audit.

Persiapan: tetapkan penanggung jawab/operator/pencatat/penghenti; roster uji
kode `Pxx`; satu profile per run (catat profile, lab, app version,
model/version, kamera, tanpa token/secret); kunci posisi/tinggi/resolusi/FPS
kamera (tandai tape; catat lux bila ada meter); satu warm-up yang sama; tiap
sel minimal **5 lintasan per relawan per profile**, acak urutan; ulangi profile
kedua semirip mungkin (tulis perbedaannya). Lima lintasan menemukan masalah
operasional awal — bukan klaim akurasi/FAR populasi.

Prosedur lintasan: mulai timer saat frame pertama; amati status UI
(accepted/late/retry/rejected/timeout/tanpa keputusan; recognized `Pxx`/
`NONE`/`MULTI`); bila retry frontal → relawan berhenti di marker, menghadap
kamera, SATU retry, catat durasi; hentikan timer saat status terminal + catat
terpisah waktu final presensi; verifikasi tepat-satu-final-record oleh
operator; tunggu track siap sebelum lintasan berikut.

Matriks: `NORM` (jalan alami; first-pass tanpa retry = sukses), `FAST` (jalan
cepat aman, bukan lari), `YAW0/±15/±30` (frontal baseline vs sudut; ambigu
wajib retry/reject, bukan auto-accept), `EYE_LOW/MID/HIGH` (band eye line
relawan dewasa; tanpa ubah kamera), `GLASS_ON/OFF` (bila nyaman; jangan paksa
lepas), `LIGHT_AM/MID/PM` (bucket waktu + lux + backlight; tanpa ubah
exposure/threshold), `PAIR_NEAR` (dua relawan <1 detik + kontrol jarak normal;
maks satu final record benar per orang), `LOOKALIKE` (hanya pasangan dewasa
sukarela; tanpa auto-merge; FA final = hentikan run), `FRONTAL_FB` (retry
setelah retry-trigger; gagal → fallback manual).

Definisi: success walk-through (setelah ≤1 frontal retry) + first-pass rate
terpisah; retry rate per kondisi; FA (keputusan/final otomatis untuk kode
salah atau auto-accept non-roster; per impostor challenge) dengan count+rate;
FR (enrolled tanpa identitas+final benar setelah batas retry) dengan
count+rate (salah identitas boleh dihitung FA sekaligus FR — laporkan aturan
terbuka); decision latency detik frame-pertama→keputusan AI terminal (p50/p95
+ count timeout); end-to-end latency sampai final presensi di UI (p50/p95
terpisah); enrollment time capture→konfirmasi backend (p50/p95 + gagal).
Selalu tampilkan count + denominator; `NOT TESTED` untuk sel tanpa
relawan/peralatan. Penutupan: pisahkan first-pass/fallback/manual; bandingkan
profile per sel setara + config/lux/host; ekspor bebas PII; revoke enrollment
uji + tutup sesi uji; lampirkan anomali; sign-off (operator berkode, run ID
per profile, pass count aktual, FA/FR, fallback/manual, verifikasi cleanup,
approver + tanggal).

## Harness ai-benchmark (verifikasi 1-ke-1)

Evaluasi lokal YuNet/SFace sebagai baseline verifikasi: manifest CSV
(`path,person_id,condition`) → semua pasangan unordered → similarity cosine
genuine vs impostor. Tanpa image/model di repo (`datasets/`, aset, `reports/`
diabaikan Git); hanya data lawful; siswa/minor dilarang di CI cloud. Report
tanpa path/ID (label kondisi + agregat boleh); pair-score CSV = artefak
sensitif lokal. Tiap image tepat satu wajah terdeteksi; baris buruk
menggagalkan run (denominator tidak diubah diam-diam).

```powershell
python tests/ai-benchmark/ai_benchmark.py `
  --manifest tests/ai-benchmark/example-manifest.csv `
  --yunet-model C:/local/models/face_detection_yunet_2023mar.onnx `
  --sface-model C:/local/models/face_recognition_sface_2021dec.onnx `
  --threshold-min -1 --threshold-max 1 --threshold-steps 201 `
  --max-fmr 0.001 `
  --json-out tests/ai-benchmark/reports/baseline.json `
  --csv-out tests/ai-benchmark/reports/thresholds.csv `
  --pair-csv-out tests/ai-benchmark/reports/pairs.csv `
  --plot-out tests/ai-benchmark/reports/distributions.png
```

Output: `baseline.json`, `thresholds.csv`, `pairs.csv`,
`distributions.png`. Accepted bila `cosine >= threshold`; FAR=FMR dan
FRR=FNMR (alias) per threshold + support count, distribusi genuine/impostor,
strata condition-pair. `--max-fmr` menandai threshold yang memenuhi batas
FMR rendah — TIDAK memilih threshold atau optimasi akurasi total. Stage yang
diukur: read, YuNet detect, SFace align/embed, cosine, total per image
(bukan latency attendance end-to-end; quality/liveness/temporal/policy tidak
tercakup). Kandidat threshold wajib divalidasi pada holdout terpisah yang
representatif; FMR nol pada sampel kecil bukan bukti zero operational FA.
Tes harness (tanpa wajah/weights): `python -m pytest tests/ai-benchmark -q`.
Sign-off: evaluator + reviewer + tanggal, model name/version + SHA-256,
manifest/run ID, kandidat + ringkasan FMR/FRR, pernyataan holdout.

## Harness deployment-benchmark (AI_EDGE vs AI_CENTRAL)

Membandingkan decision p50/p95 jalur inference YuNet/SFace nyata di host
AI_EDGE vs request ke AI_CENTRAL berjalan (+ per-stage recognition-core, CPU/
RAM edge+server, bytes aplikasi per central event, throughput 1-lab +
2-lab, retry/error rate). Satu image uji operator-supply di memory (path
dihilangkan dari report; tanpa simpan image/embedding); fixture dewasa
non-sensitif yang disetujui. Bukan pengganti kalibrasi akurasi/FAR/FMR atau
evaluasi demografis.

Tanpa hardware/model/sesi → hasil `PENDING HARDWARE` jujur, nilai terukur
kosong (jangan invent angka):

```bash
python3 tests/deployment-benchmark/benchmark.py --output-dir tests/deployment-benchmark/reports/initial-pending
```

Dengan lab nyata: config AI_EDGE terkalibrasi (model lokal + threshold/
quality sesi) — image harus lolos one-face + quality check; gallery sintetis
seeded (embedding image + distractor ternormalisasi; tanpa template siswa).
AI_CENTRAL: timing switch on hanya jendela benchmark, `/metrics` reachable,
gallery sesi uji nyata per device; image = identitas uji enrolled yang
menyetujui. Token via env (`PRESENSI_BENCH_*`), tak masuk report. Iterasi 30 +
warmup 3 default contoh; satu worker per PC lab nyata untuk keputusan
deployment (2 worker satu host ≠ 2 PC lab).

```powershell
py -3 tests/deployment-benchmark/benchmark.py `
  --image C:/local/approved-fixtures/volunteer.jpg `
  --edge-config apps/edge-agent/config/edge-agent.yaml `
  --central-url https://ai.lab.example `
  --device-id $env:PRESENSI_BENCH_DEVICE_ID `
  --session-id $env:PRESENSI_BENCH_SESSION_ID `
  --lab2-device-id $env:PRESENSI_BENCH_LAB2_DEVICE_ID `
  --lab2-session-id $env:PRESENSI_BENCH_LAB2_SESSION_ID `
  --iterations 30 --warmup 3 --frames-per-decision 3 --max-bursts 5 `
  --output-dir tests/deployment-benchmark/reports/runs/pilot-01
```

Aktifkan stage timing di host AI hanya saat benchmark
(`PRESENSI_AI_BENCHMARK_TIMING_ENABLED=true` + header
`X-Benchmark-Timing: true`; respons hanya agregat), lalu disable + restart.
Batas ukur: AI_EDGE = frame decoded→track terminal; AI_CENTRAL termasuk
JPEG/base64/JSON + network round trip; maks `--max-bursts` per track; exclude
capture kamera, heartbeat, delivery event, finalisasi DB. Terminal =
`ACCEPTED`/`NEED_FRONTAL_RETRY`/`REJECTED`; `COLLECTING` di batas burst =
incomplete (bukan sukses). Percentil nearest-rank. CPU ternormalisasi
per-core (bisa >100%); network = header+body HTTP/1.1 (tanpa TLS/TCP/IP/NIC).
Kunci service/gallery/threshold/frame/fixture/host saat bandingkan run; report
mencakup revisi kode, fakta hardware/runtime, hash SHA-256 model AI_EDGE +
versi teramati (tanpa path/ID/token/embedding); catat digest image central
terpisah. Tes no-hardware: `python -m pytest tests/deployment-benchmark
apps/ai-service/tests libs/recognition-core/tests -q`.

## Privasi pengujian

Tanpa data anak di CI; tanpa foto siswa/minor di repo/fixture/laporan. Semua
formulir pseudonim `Pxx`; tanpa PII/foto/embedding/token/UUID di dokumen.
Template/biometrik uji direvoke dengan jendela retensi pendek yang disetujui;
cleanup terverifikasi (count, bukan vector). Otoritas: security-and-privacy.md
(kontrol biometrik, retensi, redaksi event) dan models.md (lisensi/kalibrasi).
P0-5 (kalibrasi threshold) dan P2-1 (field test + deployment-benchmark
hardware) berstatus **MANUAL HARDWARE TEST REQUIRED** — lihat
[backlog](backlog.md).
