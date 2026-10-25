"""Generate BPMN 2.0 (.bpmn) + Draw.io (.drawio) untuk seluruh alur bisnis.

Sumber: docs/proposal/05-activity.md (F-01..F-13), 06 §6.1, 09 §9.2.
Cara pakai:  py _gen/gen_flows.py
Import .bpmn : Visual Paradigm / Draw.io (Open/Import).
Import .drawio: Draw.io (Open) — layout otomatis, rapikan dengan Arrange bila perlu.
"""
import os

BASE = os.path.dirname(os.path.abspath(__file__))
BPMN_DIR = os.path.abspath(os.path.join(BASE, "..", "bpmn"))
DRAWIO_DIR = os.path.abspath(os.path.join(BASE, "..", "drawio"))
os.makedirs(BPMN_DIR, exist_ok=True)
os.makedirs(DRAWIO_DIR, exist_ok=True)


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))


# node: (id, kind, label) kind = start|task|xg|pg|end
# edge: (from, to, label|None)
FLOWS = [
 dict(id="f01-login", name="F-01 Login",
  nodes=[("s","start","Mulai"),("input","task","Input email dan password"),
   ("cred","xg","Kredensial valid?"),("fail","task","Gagal: pesan umum tanpa bocorkan akun"),
   ("chg","xg","Wajib ganti password?"),("new","task","Password baru min 12 char"),
   ("valid","xg","Valid?"),("issue","task","Terbitkan akses 15 mnt dan sesi cookie 24 jam"),
   ("dash","end","Masuk dashboard sesuai role")],
  edges=[("s","input",None),("input","cred",None),("cred","fail","Tidak"),
   ("cred","chg","Ya"),("fail","input",None),("chg","new","Ya"),
   ("chg","issue","Tidak"),("new","valid",None),("valid","new","Tidak"),
   ("valid","issue","Ya"),("issue","dash",None)]),
 dict(id="f02-master-import", name="F-02 Master data + import",
  nodes=[("s","start","Mulai"),("prep","task","Admin siapkan CSV atau XLSX"),
   ("up","task","Unggah file max 5 MiB, XLSX max 25 MiB"),("size","xg","Ukuran dan baris lolos? max 10rb"),
   ("r413","task","Tolak 413 dengan alasan"),("prev","task","Preview: validasi per baris"),
   ("rows","xg","Ada baris invalid?"),("r422","task","Tampilkan error per baris 422"),
   ("commit","task","Commit: simpan siswa-kelas-lab"),("e","end","Selesai tanpa audit")],
  edges=[("s","prep",None),("prep","up",None),("up","size",None),
   ("size","r413","Tidak"),("size","prev","Ya"),("r413","prep",None),
   ("prev","rows",None),("rows","r422","Ya"),("rows","commit","Tidak"),
   ("r422","prep",None),("commit","e",None)]),
 dict(id="f03-enrollment", name="F-03 Enrollment wajah",
  nodes=[("s","start","Mulai"),("pick","task","Operator pilih siswa"),
   ("tpl","xg","Status template?"),("rev","task","Revoke SEMUA template aktif batch ini"),
   ("cap","task","Capture 3 sampai 10 frame max 3 MB"),("q","xg","Lolos quality gate?"),
   ("min3","xg","Minimal 3 diterima?"),("f","end","Gagal: ulangi capture"),("save","task","Simpan maks 5 template AES-256-GCM + model name-version"),
   ("dup","xg","Mirip siswa lain di atas 0,85?"),("warn","task","Peringatan duplicate: verifikasi manual"),
   ("e","end","Selesai dan audit")],
  edges=[("s","pick",None),("pick","tpl",None),("tpl","rev","enrolled"),
   ("tpl","cap","not enrolled"),("rev","cap",None),("cap","q",None),
   ("q","cap","Tidak"),("q","min3","Ya"),("min3","f","Tidak"),
   ("min3","save","Ya"),("save","dup",None),("dup","warn","Ya"),
   ("dup","e","Tidak"),("warn","e",None)]),
 dict(id="f04-schedule", name="F-04 Jadwal praktikum",
  nodes=[("s","start","Mulai"),("fill","task","Admin atau guru isi jadwal"),
   ("v","xg","Jadwal valid dan referensi aktif?"),("r422","task","Tolak 422"),
   ("b","xg","Bentrok kelas-lab-guru termasuk rentang tanggal?"),
   ("c409","task","Tolak 409 schedule_conflict"),("saved","end","Jadwal aktif tersimpan")],
  edges=[("s","fill",None),("fill","v",None),("v","r422","Tidak"),("v","b","Ya"),
   ("r422","fill",None),("b","c409","Ya"),("b","saved","Tidak"),
   ("c409","fill",None)]),
 dict(id="f05-session", name="F-05 Buka dan tutup sesi",
  nodes=[("s","start","Mulai"),("elig","task","Jadwal eligible hari ini"),
   ("mode","xg","Mode guru?"),("w","task","Worker 10 detik auto-open"),
   ("r","xg","Roster kelas kosong?"),("skip","task","Lewati: tanpa sesi"),
   ("e1","end","Selesai"),("wa","task","Status active; opened_by null"),
   ("o","task","Guru atau laboran tekan Buka Sesi"),
   ("tx","task","Transaksi: attendance_sessions + snapshot roster aktif"),
   ("g1","xg","Manual-open di dalam jendela?"),("sa","task","Status active"),
   ("so","task","Status manual_override"),
   ("dash","task","Dashboard live aktif; device tarik gallery"),
   ("cl","xg","Akhir jadwal atau tutup manual?"),
   ("csd","task","Tutup: hanya berjalan ke closed + closed_at"),("e2","end","Selesai")],
  edges=[("s","elig",None),("elig","mode",None),("mode","w","automatic dan dalam jendela"),
   ("mode","o","manual atau di luar jendela"),("w","r",None),("r","skip","Ya"),
   ("skip","e1",None),("r","wa","Tidak"),("wa","dash",None),("o","tx",None),
   ("tx","g1",None),("g1","sa","Ya"),("g1","so","Tidak"),("sa","dash",None),
   ("so","dash",None),("dash","cl",None),("cl","csd","Ya"),("csd","e2",None),
   ("cl","dash","Tidak")]),
 dict(id="f06-walkthrough", name="F-06 Walk-through otomatis",
  nodes=[("s","start","Mulai"),("send","task","Track ACCEPTED kirim matched + kandidat"),
   ("known","xg","Sesi dan device dikenal?"),("e404","task","404 session_not_found atau device_not_found; tanpa event"),
   ("en404","end","Selesai"),("rp","xg","event_id dikenal?"),
   ("old","task","200 hasil tersimpan; replayed true"),("enold","end","Selesai"),
   ("c409","task","409 event_id_reused; tanpa event baru"),("en409","end","Selesai"),
   ("sv","task","Simpan event sebagai bukti audit"),("v1","xg","Guru di luar jadwalnya?"),
   ("r1","task","Event reason session_not_accessible"),("er1","end","Selesai"),
   ("v2","xg","Device aktif, kamera on, lab sama?"),
   ("r2","task","Event reason device_inactive, device_camera_disabled, atau device_laboratory_mismatch"),
   ("er2","end","Selesai"),("v3","xg","Sesi berjalan?"),
   ("r3","task","Event reason session_inactive"),("er3","end","Selesai"),
   ("v4","xg","Kandidat di snapshot roster?"),
   ("r4","task","Event reason student_not_found atau student_not_in_session_roster"),
   ("er4","end","Selesai"),("v5","xg","Outcome matched dan liveness lolos?"),
   ("r5","task","Event reason recognition_not_matched atau liveness_failed"),("er5","end","Selesai"),
   ("v6","xg","Sudah ada record sesi dan siswa?"),
   ("r6","task","Event reason attendance_already_recorded"),("er6","end","Selesai"),
   ("gr","xg","occurred_at lewat grace?"),("rl","task","Record late"),
   ("pr","task","Record present"),("ws","task","Push WebSocket dashboard"),("e","end","Selesai")],
  edges=[("s","send",None),("send","known",None),("known","e404","Tidak"),
   ("e404","en404",None),("known","rp","Ya"),("rp","old","Fingerprint sama"),
   ("old","enold",None),("rp","c409","Payload beda"),("c409","en409",None),
   ("rp","sv","Baru"),("sv","v1",None),("v1","r1","Ya"),("r1","er1",None),
   ("v1","v2","Tidak"),("v2","r2","Tidak"),("r2","er2",None),("v2","v3","Ya"),
   ("v3","r3","Tidak"),("r3","er3",None),("v3","v4","Ya"),("v4","r4","Tidak"),
   ("r4","er4",None),("v4","v5","Ya"),("v5","r5","Tidak"),("r5","er5",None),
   ("v5","v6","Ya"),("v6","r6","Ya"),("r6","er6",None),("v6","gr","Tidak"),
   ("gr","rl","Ya"),("gr","pr","Tidak"),("rl","ws",None),("pr","ws",None),
   ("ws","e",None)]),
 dict(id="f07-manual", name="F-07 Presensi manual + koreksi",
  nodes=[("s","start","Mulai"),("pick","task","Guru pilih siswa + status + catatan"),
   ("sc","xg","Guru pemilik jadwal?"),("nf","task","404 session_not_found"),("enf","end","Selesai"),
   ("st","xg","Sesi berjalan?"),("si","task","409 session_inactive"),("esi","end","Selesai"),
   ("sn","xg","Siswa dikenal dan di snapshot?"),
   ("nr","task","404 student_not_found atau student_not_in_session_roster"),("enr","end","Selesai"),
   ("dp","xg","Record sesi dan siswa sudah ada?"),
   ("ar","task","409 attendance_already_recorded; FR tak tertimpa"),("ear","end","Selesai"),
   ("sv","task","Record manual + audit attendance.manual_marked"),
   ("k","xg","Ada kesalahan?"),("post","task","POST koreksi + alasan wajib"),
   ("pe","task","pending + audit; record final tidak berubah"),
   ("w","end","Menunggu kebijakan approval; tanpa endpoint putusan"),("e","end","Selesai")],
  edges=[("s","pick",None),("pick","sc",None),("sc","nf","Bukan"),("nf","enf",None),
   ("sc","st","Ya"),("st","si","Tidak"),("si","esi",None),("st","sn","Ya"),
   ("sn","nr","Tidak"),("nr","enr",None),("sn","dp","Ya"),("dp","ar","Ya"),
   ("ar","ear",None),("dp","sv","Tidak"),("sv","k",None),("k","e","Tidak"),
   ("k","post","Ya"),("post","pe",None),("pe","w",None)]),
 dict(id="f08-dashboard", name="F-08 Live dashboard",
  nodes=[("s","start","Buka dashboard"),
   ("snap","task","Ambil snapshot sesi + roster + record"),
   ("ws","task","Subscribe WebSocket; refresh tiap 2 detik"),
   ("up","xg","Ada event baru?"),
   ("ar","task","Tampilkan panel at-risk: 25 teratas + ambang efektif"),
   ("e","end","Pantau")],
  edges=[("s","snap",None),("snap","ws",None),("snap","ar",None),
   ("ws","up",None),("up","snap","Ya"),("up","ws","Tidak"),
   ("ar","e",None)]),
 dict(id="f09-reports", name="F-09 Laporan dan ekspor",
  nodes=[("s","start","Mulai"),("filt","task","Pilih filter tanggal-kelas-lab-sesi"),
   ("scope","task","Batasi scope: guru hanya jadwal miliknya"),
   ("aggr","task","Agregat session_students + records"),
   ("rows","xg","Baris tanpa record?"),("nr","task","Tampilkan not_recorded"),
   ("ab","task","Tampilkan absent"),("x","xg","Ekspor?"),("tbl","task","Tabel paginasi"),
   ("big","xg","Lebih dari 50rb baris?"),
   ("e413","task","Tolak 413: persempit filter"),("e2","end","Selesai"),
   ("csv","task","CSV BOM atau XLSX tanpa skor AI + anti formula-injection"),
   ("e","end","Unduh")],
  edges=[("s","filt",None),("filt","scope",None),("scope","aggr",None),
   ("aggr","rows",None),("rows","nr","Sesi open"),("rows","ab","Sesi closed"),
   ("nr","x",None),("ab","x",None),("x","tbl","Tidak"),("tbl","e",None),
   ("x","big","Ya"),("big","e413","Ya"),("e413","e2",None),("big","csv","Tidak"),
   ("csv","e",None)]),
 dict(id="f10-ews", name="F-10 EWS at-risk tahap 1",
  nodes=[("s","start","Mulai"),("panel","task","Buka panel Siswa perlu perhatian"),
   ("pol","task","Ambil policy tersimpan atau default 30 hari + absen 20 persen + telat 3x; override query tervalidasi"),
   ("aggr","task","Agregat sesi non-cancelled: total + absen + telat + absence_pct"),
   ("thr","xg","absence_pct >= ambang ATAU telat >= ambang?"),
   ("clean","task","Bersih: tidak masuk daftar"),
   ("flag","task","Flag + reasons + ambang efektif + revisi policy"),
   ("fol","task","Catat tindak lanjut manual guru atau BK"),
   ("out","end","Catat di luar sistem pada tahap 1")],
  edges=[("s","panel",None),("panel","pol",None),("pol","aggr",None),
   ("aggr","thr",None),("thr","clean","Tidak"),("clean","out",None),
   ("thr","flag","Ya"),("flag","fol",None),("fol","out",None)]),
 dict(id="f11-device", name="F-11 Perangkat",
  nodes=[("a1","start","Registrasi device + lab + profile"),
   ("a2","task","Provision bearer sekali pakai"),
   ("a3","task","Rotate token + overlap singkat"),
   ("a4","task","Update registry atau lab assignment"),
   ("a5","task","Jeda atau aktifkan kamera: matching berhenti, heartbeat jalan"),
   ("a6","task","Nonaktif: revoke kredensial + kamera offline"),
   ("e","end","Selesai"),
   ("b1","task","Heartbeat + camera_status + latency + metrik"),
   ("b2","task","Discover sesi aktif lab ini"),
   ("b3","task","Tarik gallery sesi dan kirim recognition-event idempoten")],
  edges=[("a1","a2",None),("a2","a3",None),("a3","e",None),
   ("a1","a4",None),("a4","e",None),("a1","a5",None),("a5","e",None),
   ("a1","a6",None),("a6","e",None),
   ("b1","b2",None),("b2","b3",None),("b3","b1",None)],
  lanes=[("ADMIN saja",["a1","a2","a3","a4","a5","a6","e"]),
         ("LABORANT dan device",["b1","b2","b3"])]),
 dict(id="f12-preview", name="F-12 AI config + preview",
  nodes=[("s","start","Mulai"),("pub","task","Admin terbitkan AI config revision"),
   ("poll","task","Device poll dan terapkan: pending-applied-error"),
   ("pv","xg","Preview pra-sesi?"),("e0","end","Selesai"),
   ("host","xg","Browser di localhost atau 127.0.0.1 ke edge-agent 8765?"),
   ("r1","task","Tolak: buka dari komputer AI_EDGE"),("e1","end","Selesai"),
   ("prof","xg","Profil AI_EDGE?"),("r2","task","409 preview_gallery_profile_unsupported"),
   ("e2","end","Selesai"),("cam","xg","Kamera enabled?"),
   ("r3","task","409 device_camera_disabled"),("e3","end","Selesai"),
   ("sess","xg","Masih tanpa sesi aktif?"),
   ("r4","task","409 preview_gallery_session_active: gunakan snapshot sesi berjalan, bukan preview"),("e4","end","Selesai"),
   ("win","xg","Maks 15 mnt sebelum mulai dan sebelum akhir?"),
   ("r5","task","404 preview_gallery_unavailable"),("e5","end","Selesai"),
   ("tpl","xg","Template aktif tersedia?"),("r6","task","409 preview_gallery_empty"),
   ("e6","end","Selesai"),("ov","task","Overlay wajah + kandidat tanpa event; frame sekitar 15 fps, status 500 ms"),
   ("e7","end","Selesai")],
  edges=[("s","pub",None),("pub","poll",None),("poll","pv",None),("pv","e0","Tidak"),
   ("e0","e0x",None) if False else ("pv","host","Ya"),("host","r1","Tidak"),
   ("r1","e1",None),("host","prof","Ya"),("prof","r2","Tidak"),("r2","e2",None),
   ("prof","cam","Ya"),("cam","r3","Tidak"),("r3","e3",None),("cam","sess","Ya"),
   ("sess","r4","Tidak"),("r4","e4",None),("sess","win","Ya"),("win","r5","Tidak"),
   ("r5","e5",None),("win","tpl","Ya"),("tpl","r6","Tidak"),("r6","e6",None),
   ("tpl","ov","Ya"),("ov","e7",None)]),
 dict(id="f13-account", name="F-13 Akun dan audit",
  nodes=[("s","start","Mulai"),("create","task","Admin buat akun: email unik + role"),
   ("act","task","Akun aktif; password awal wajib diganti"),("chg","xg","Ganti password?"),
   ("new","task","Password baru: sesi lama di-revoke semua"),
   ("e","end","Selesai dan audit")],
  edges=[("s","create",None),("create","act",None),("act","chg",None),
   ("chg","new","Ya"),("new","e",None),("chg","e","Tidak")]),
 dict(id="e2e-business", name="Alur end-to-end keseluruhan (06.1)",
  nodes=[("s","start","Mulai"),("a1","task","Master data + import CSV"),("a2","task","Jadwal praktikum"),
   ("a3","task","Enrollment wajah lokal Core API: YuNet + SFace"),
   ("a4","task","Hanya template terenkripsi + model name-version tersimpan; bytes gambar dibuang"),
   ("a5","task","Managed config berversi ditarik device dan AI service"),
   ("b1","task","Guru buka sesi + snapshot roster"),
   ("b2","task","Discovery gallery + cache expiry max 300 dtk"),
   ("b3","xg","Profil deployment"),("b4","task","Pipeline recognition-core lokal di PC lab"),
   ("b5","task","STB kirim burst max 5 JPEG ke AI service"),
   ("b6","task","Decision + kandidat tanpa image dan embedding"),
   ("b7","task","Event idempoten ke Core API"),("b8","xg","Keputusan Core API: otoritas attendance tunggal"),
   ("b9","task","Record present atau late"),("b10","task","NEED_FRONTAL_RETRY: fallback frontal look"),
   ("b11","task","Event audit saja"),("b12","task","Presensi manual bila perlu"),
   ("o1","task","Heartbeat device + camera status"),("o2","task","Cache dan gallery expiry"),
   ("o3","task","Health probe Core ke AI service via ai-readiness"),
   ("c1","task","Auto atau manual close sesi"),("c2","task","Laporan + ekspor"),
   ("c3","task","EWS watchlist"),("c4","task","Tindak lanjut manusia"),
   ("e","end","Selesai")],
  edges=[("s","a1",None),("s","o1",None),("s","a5",None),("a1","a2",None),("a2","a3",None),("a3","a4",None),("a5","a2",None),
   ("a4","b1",None),("b1","b2",None),("b2","b3",None),("b3","b4","AI_EDGE"),
   ("b3","b5","AI_CENTRAL"),("b5","b6",None),("b6","b7",None),("b4","b7",None),
   ("b7","b8",None),("b8","b9","matched valid"),("b8","b10","ambigu"),
   ("b8","b11","duplikat atau kedaluwarsa"),("b10","b4",None),
   ("b9","b12",None),("b11","c1",None),("b12","c1",None),
   ("o1","o2",None),("o2","o3",None),("o3","e",None),("c1","c2",None),("c2","c3",None),
   ("c3","c4",None),("c4","e",None)],
  lanes=[("Persiapan",["a1","a2","a3","a4","a5"]),
         ("Pelaksanaan",["b1","b2","b3","b4","b5","b6","b7","b8","b9","b10","b11","b12"]),
         ("Observabilitas",["o1","o2","o3"]),("Penutupan",["c1","c2","c3","c4","e"])]),
 dict(id="ews-stage1", name="EWS tahap 1 berjalan (09.1)",
  nodes=[("s","start","Mulai"),("panel","task","Buka panel atau API at-risk"),
   ("pol","xg","Policy tersimpan?"),("d0","task","Pakai default: 30 hari + 20 persen + 3x"),
   ("p1","task","Pakai policy revisi terakhir + audit"),
   ("w","task","Override opsional via query tervalidasi"),
   ("g","task","Agregat sesi non-cancelled dalam jendela"),
   ("r","xg","absence_pct >= ambang ATAU late >= ambang?"),
   ("b","task","Tidak masuk daftar"),
   ("f","task","Flag + reasons + ambang efektif + policy_revision"),
   ("e","end","Tindak lanjut manual di luar sistem")],
  edges=[("s","panel",None),("panel","pol",None),("pol","d0","Tidak"),
   ("pol","p1","Ya"),("d0","w",None),("p1","w",None),("w","g",None),
   ("g","r",None),("r","b","Tidak"),("r","f","Ya"),("f","e",None),
   ("b","e",None)]),
 dict(id="ews-stage2", name="EWS tahap 2 usulan (09.2)",
  nodes=[("s","start","Mulai"),("flag","task","Flag at-risk"),
   ("cal","xg","Ambang hasil kalibrasi sekolah? U-01"),("ba","task","Berita acara kalibrasi"),
   ("t","task","Tindak lanjut U-02: pemanggilan-konseling-surat-selesai"),("g1","xg","Guru tangani?"),
   ("cat","task","Catat stage + note beraudit"),("esc","task","Eskalasi U-04: wali kelas lalu BK"),
   ("nt","xg","Kirim notifikasi U-03?"),("ina","task","In-app; kanal luar hanya bila sekolah opt-in"),
   ("e","end","Selesai dicatat")],
  edges=[("s","flag",None),("flag","cal",None),("cal","ba","Belum"),("ba","cal",None),
   ("cal","t","Sudah"),("t","g1",None),("g1","cat","Ya"),("g1","esc","Tidak"),
   ("esc","cat",None),("cat","nt",None),("nt","ina","Ya"),("ina","e",None),
   ("nt","e","Tidak")]),
 dict(id="f14-roles", name="F-14 Ringkasan alur per role (05.14)",
  nodes=[("s","start","Mulai"),("fork","pg","Fork"),
   ("g1","task","Buka sesi miliknya: manual selalu, auto bila mode automatic"),
   ("g2","task","Pantau live"),("g3","task","Manual bila perlu di sesi berjalan"),
   ("g4","task","Ajukan koreksi: pending tanpa putusan"),
   ("g5","task","Laporan dan EWS kelasnya"),
   ("l1","task","Enrollment wajah"),
   ("l2","task","Operasikan device: heartbeat dan monitor"),
   ("l3","task","Preview pra-sesi AI_EDGE tanpa event"),
   ("l4","task","Buka sesi operasional bila perlu"),
   ("a1","task","Master + akun + jadwal + policy sesi"),
   ("a2","task","Device registry + kredensial + kamera + AI config + policy EWS"),
   ("a3","task","Audit semua perubahan kecuali jadwal dan commit import"),
   ("join","pg","Join"),("e","end","Selesai")],
  edges=[("s","fork",None),("fork","g1",None),
   ("g1","g2",None),("g2","g3",None),("g3","g4",None),("g4","g5",None),
   ("g5","join",None),("fork","l1",None),
   ("l1","l2",None),("l2","l3",None),("l3","l4",None),("l4","join",None),
   ("fork","a1",None),("a1","a2",None),("a2","a3",None),("a3","join",None),
   ("join","e",None)]),
 dict(id="prototype-method", name="Metode Prototype (02.1)",
  nodes=[("s","start","Mulai"),("p1","task","1 Dengar kebutuhan dan observasi"),
   ("p2","task","2 Bangun prototipe cepat"),("p3","task","3 Uji coba ke pengguna"),
   ("p4","xg","Uji review: diterima?"),("p5","task","5 Implementasi final dan hardening"),
   ("p6","task","Catat backlog terukur"),("p7","task","Revisi prototipe"),
   ("p8","task","6 Pengujian sistem dan kalibrasi"),("p9","xg","Uji lolos?"),
   ("p10","task","7 Deployment dan serah terima"),("p11","task","8 Evaluasi pasca-pakai"),
   ("p12","xg","Ada kebutuhan baru?"),("done","task","Selesai"),("e","end","Selesai")],
  edges=[("s","p1",None),("p1","p2",None),("p2","p3",None),("p3","p4",None),
   ("p4","p5","Ya, tanpa catatan"),("p4","p6","Ya, dengan catatan kecil"),
   ("p6","p5",None),("p4","p7","Tidak"),("p7","p2",None),
   ("p5","p8",None),("p8","p9",None),("p9","p7","Tidak"),
   ("p9","p10","Ya"),("p10","p11",None),("p11","p12",None),
   ("p12","p1","Ya, misal EWS tahap 2"),("p12","done","Tidak"),
   ("done","e",None)]),
]


def layout(flow):
    nodes = flow["nodes"]
    succ = {}
    for a, b, _ in flow["edges"]:
        succ.setdefault(a, []).append(b)
    depth = {}
    order = []
    instack = set()
    done = set()

    def visit(n, d):
        if n in done:
            depth[n] = max(depth[n], d)
            return
        if n in instack:
            return
        instack.add(n)
        depth[n] = d
        order.append(n)
        for m in succ.get(n, []):
            if m in instack or m in done:
                if m not in depth:
                    depth[m] = d
                continue
            visit(m, d + 1)
        instack.remove(n)
        done.add(n)

    visit(nodes[0][0], 0)
    for nid, _, _ in nodes:
        if nid not in done:
            visit(nid, max(depth.values()) + 1 if depth else 0)
    pos = {nid: (depth[nid], i) for i, nid in enumerate(order)}
    backs = set((a, b) for a, b, _ in flow["edges"]
                if depth.get(b, 0) <= depth.get(a, 0))
    return pos, backs


BSIZE = {"start": (36, 36), "end": (36, 36), "task": (140, 70),
         "xg": (60, 60), "pg": (60, 60)}


def bpmn_xml(flow):
    pos, backs = layout(flow)
    nmap = {n[0]: n for n in flow["nodes"]}
    out_e = {}
    in_e = {}
    for i, (a, b, lab) in enumerate(flow["edges"]):
        fid = "F_%s_%d" % (a, i)
        out_e.setdefault(a, []).append(fid)
        in_e.setdefault(b, []).append(fid)
    L = ['<?xml version="1.0" encoding="UTF-8"?>',
         '<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL" '
         'xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" '
         'xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" '
         'xmlns:di="http://www.omg.org/spec/DD/20100524/DI" '
         'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
         'id="DEF_%s" targetNamespace="http://presensi/school">' % flow["id"]]
    has_lanes = bool(flow.get("lanes"))
    if has_lanes:
        L.append('<process id="P_%s" name="%s" isExecutable="false">' % (
            flow["id"], esc(flow["name"])))
        L.append('<laneSet id="LS_%s">' % flow["id"])
        for li, (lname, members) in enumerate(flow["lanes"]):
            L.append('<lane id="L_%s_%d" name="%s">' % (flow["id"], li, esc(lname)))
            for m in members:
                L.append('<flowNodeRef>%s</flowNodeRef>' % m)
            L.append('</lane>')
        L.append('</laneSet>')
    else:
        L.append('<process id="P_%s" name="%s" isExecutable="false">' % (
            flow["id"], esc(flow["name"])))
    for nid, kind, label in flow["nodes"]:
        if kind == "start":
            L.append('<startEvent id="%s" name="%s">%s</startEvent>' % (
                nid, esc(label),
                "".join("<outgoing>%s</outgoing>" % f for f in out_e.get(nid, []))))
        elif kind == "end":
            L.append('<endEvent id="%s" name="%s">%s</endEvent>' % (
                nid, esc(label),
                "".join("<incoming>%s</incoming>" % f for f in in_e.get(nid, []))))
        elif kind in ("xg", "pg"):
            tag = ("exclusiveGateway" if kind == "xg" else "parallelGateway")
            extra = ' gatewayDirection="Exclusive"' if kind == "xg" else ""
            L.append('<%s id="%s" name="%s"%s>%s%s</%s>' % (
                tag, nid, esc(label), extra,
                "".join("<incoming>%s</incoming>" % f for f in in_e.get(nid, [])),
                "".join("<outgoing>%s</outgoing>" % f for f in out_e.get(nid, [])),
                tag))
        else:
            L.append('<task id="%s" name="%s">%s%s</task>' % (
                nid, esc(label),
                "".join("<incoming>%s</incoming>" % f for f in in_e.get(nid, [])),
                "".join("<outgoing>%s</outgoing>" % f for f in out_e.get(nid, []))))
    for i, (a, b, lab) in enumerate(flow["edges"]):
        fid = "F_%s_%d" % (a, i)
        cond = ('<conditionExpression xsi:type="tFormalExpression">'
                '<![CDATA[%s]]></conditionExpression>' % lab) if lab else ""
        # ensure xsi namespace present when conditions exist
        L.append('<sequenceFlow id="%s" sourceRef="%s" targetRef="%s">%s</sequenceFlow>'
                 % (fid, a, b, cond))
    L.append('</process>')
    # DI — koordinat nyata agar hasil import langsung terbaca
    L.append('<bpmndi:BPMNDiagram id="DG_%s"><bpmndi:BPMNPlane id="PL_%s" '
             'bpmnElement="P_%s">' % (flow["id"], flow["id"], flow["id"]))
    lane_h = {}
    if has_lanes:
        y = 20
        for li, (lname, members) in enumerate(flow["lanes"]):
            rows = [pos[m][1] for m in members if m in pos]
            h = (max(rows) - min(rows) + 1) * 120 + 40 if rows else 160
            lane_h[li] = (y, h)
            y += h + 10
    box = {}
    for nid, kind, label in flow["nodes"]:
        d, r = pos[nid]
        w, h = BSIZE[kind]
        x = 30 + d * 210
        yy = 30 + r * 120
        if has_lanes:
            for li, (lname, members) in enumerate(flow["lanes"]):
                if nid in members:
                    rows = sorted(pos[m][1] for m in members if m in pos)
                    base = rows.index(r)
                    yy = lane_h[li][0] + 30 + base * 120
        box[nid] = (x, yy, w, h)
        L.append('<bpmndi:BPMNShape id="S_%s" bpmnElement="%s">'
                 '<dc:Bounds x="%d" y="%d" width="%d" height="%d" /></bpmndi:BPMNShape>'
                 % (nid, nid, x, yy, w, h))
    for i, (a, b, lab) in enumerate(flow["edges"]):
        fid = "F_%s_%d" % (a, i)
        x1, y1, w1, h1 = box[a]
        x2, y2, w2, h2 = box[b]
        if (a, b) in backs:
            mx = x1 + w1 + 50
            pts = [(x1 + w1, y1 + h1 // 2), (mx, y1 + h1 // 2),
                   (mx, y2 + h2 // 2), (x2 + w2, y2 + h2 // 2)]
        else:
            pts = [(x1 + w1, y1 + h1 // 2), (x2, y2 + h2 // 2)]
        wps = "".join('<di:waypoint xsi:type="dc:Point" x="%d" y="%d" />' % p
                      for p in pts)
        L.append('<bpmndi:BPMNEdge id="E_%s" bpmnElement="%s">%s</bpmndi:BPMNEdge>'
                 % (fid, fid, wps))
    L.append('</bpmndi:BPMNPlane></bpmndi:BPMNDiagram></definitions>')
    return "\n".join(L) + "\n"


DSTYLE = {
 "start": "ellipse;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;fontSize=12;",
 "end": "ellipse;whiteSpace=wrap;html=1;fillColor=#f8cecc;strokeColor=#b85450;fontSize=12;",
 "task": "rounded=1;whiteSpace=wrap;html=1;fontSize=12;",
 "xg": "rhombus;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;fontSize=12;",
 "pg": "rhombus;whiteSpace=wrap;html=1;fillColor=#e1d5e7;strokeColor=#9673a6;fontSize=12;",
}
DSIZE = {"start": (60, 60), "end": (60, 60), "task": (200, 80),
         "xg": (190, 110), "pg": (120, 90)}


def drawio_flow_xml(flow):
    pos, backs = layout(flow)
    nmap = {n[0]: n for n in flow["nodes"]}
    L = ['<mxfile><diagram id="D_%s" name="%s"><mxGraphModel dx="0" dy="0" '
         'grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" '
         'fold="1" page="1" pageScale="1" pageWidth="1600" pageHeight="1200">'
         '<root><mxCell id="0"/><mxCell id="1" parent="0"/>' % (
             flow["id"], esc(flow["name"]))]
    ids = {}
    for i, (nid, kind, label) in enumerate(flow["nodes"]):
        d, r = pos[nid]
        w, h = DSIZE[kind]
        x = 30 + d * 300
        y = 30 + r * 160
        vid = "v%d" % i
        ids[nid] = vid
        val = esc(label).replace("\n", "&#10;")
        L.append('<mxCell id="%s" value="%s" style="%s" vertex="1" parent="1">'
                 '<mxGeometry x="%d" y="%d" width="%d" height="%d" as="geometry"/>'
                 '</mxCell>' % (vid, val, DSTYLE[kind], x, y, w, h))
    for i, (a, b, lab) in enumerate(flow["edges"]):
        val = (' value="%s"' % esc(lab)) if lab else ""
        L.append('<mxCell id="e%d" style="endArrow=block;html=1;fontSize=11;" '
                 'edge="1" parent="1" source="%s" target="%s"%s>'
                 '<mxGeometry relative="1" as="geometry"/></mxCell>'
                 % (i, ids[a], ids[b], val))
    L.append('</root></mxGraphModel></diagram></mxfile>')
    return "\n".join(L) + "\n"


def main():
    for flow in FLOWS:
        # hapus artefak draf edge f12 (tidak dipakai)
        flow["edges"] = [e for e in flow["edges"] if e[1] != "e0x"]
        with open(os.path.join(BPMN_DIR, flow["id"] + ".bpmn"), "w",
                  encoding="utf-8", newline="\n") as fh:
            fh.write(bpmn_xml(flow))
        print("wrote bpmn", flow["id"])
        with open(os.path.join(DRAWIO_DIR, "flow-" + flow["id"] + ".drawio"), "w",
                  encoding="utf-8", newline="\n") as fh:
            fh.write(drawio_flow_xml(flow))
        print("wrote drawio flow", flow["id"])


if __name__ == "__main__":
    main()
