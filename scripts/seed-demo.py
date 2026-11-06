"""Seed data demo sintetis untuk ujicoba/dosen (BUKAN data siswa nyata).

Idempoten: aman dijalankan ulang (get-or-create + lewati event/mark yang
sudah tercatat). Alur: bootstrap admin -> ganti sandi -> akun guru/laboran
-> lab/kelas/siswa -> jadwal demo (window ikut jam jalan) -> device +
kredensial -> sesi RPL AKTIF (campuran present/manual/late/excused/absent +
1 unrecorded) -> sesi TKJ DITUTUP (ada absen otomatis) -> heartbeat Online.

Jalankan dengan stack dev menyala:
  python3 scripts/seed-demo.py
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

API = os.environ.get("API_BASE", "http://127.0.0.1:8000")
JKT = ZoneInfo("Asia/Jakarta")
now_jkt = datetime.now(JKT)
today = now_jkt.date().isoformat()
weekday = now_jkt.weekday()

ADMIN_EMAIL = "admin@local.test"
ADMIN_PASSWORD = os.environ.get("DEMO_ADMIN_PASSWORD", "DemoAdmin2026!x")
GURU_PASSWORD = os.environ.get("DEMO_GURU_PASSWORD", "GuruDemo2026!x")
LAB_PASSWORD = os.environ.get("DEMO_LAB_PASSWORD", "LabDemo2026!x")

passed: list[str] = []


def check(name: str, cond: bool, extra: object = "") -> None:
    print(("PASS " if cond else "FAIL ") + name, extra)
    if not cond:
        sys.exit(1)
    passed.append(name)


c = httpx.Client(base_url=API, timeout=20)

# 1. bootstrap + ganti sandi
r = c.post("/api/v1/auth/login", data={"username": ADMIN_EMAIL, "password": "1234abcd"})
if r.status_code == 200:
    tok0 = r.json()["access_token"]
    r = c.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {tok0}"},
        json={"current_password": "1234abcd", "new_password": ADMIN_PASSWORD},
    )
    check("ganti sandi admin", r.status_code in (200, 201), r.text[:120])
else:
    print("INFO bootstrap sudah dipakai, lanjut dengan sandi demo:", r.status_code)
r = c.post(
    "/api/v1/auth/login", data={"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
)
check("login admin demo", r.status_code == 200)
ADMIN = r.json()["access_token"]
A = {"Authorization": f"Bearer {ADMIN}"}


# 2. akun guru + laboran
def buat_akun(nama: str, email: str, role: str, pw: str) -> tuple[str, str]:
    r = c.post(
        "/api/v1/accounts",
        headers=A,
        json={"full_name": nama, "email": email, "role": role},
    )
    if r.status_code in (200, 201):
        temp = r.json()["temporary_password"]
        uid = r.json()["id"]
    else:  # rerun: akun sudah ada
        print("INFO akun ada:", email, r.status_code)
        r2 = c.post("/api/v1/auth/login", data={"username": email, "password": pw})
        assert r2.status_code == 200, r2.text[:200]
        me = c.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {r2.json()['access_token']}"},
        )
        uid = me.json()["id"]
        temp = None
    if temp:
        t0 = c.post(
            "/api/v1/auth/login", data={"username": email, "password": temp}
        ).json()["access_token"]
        rc = c.post(
            "/api/v1/auth/change-password",
            headers={"Authorization": f"Bearer {t0}"},
            json={"current_password": temp, "new_password": pw},
        )
        assert rc.status_code in (200, 201), rc.text[:200]
    rt = c.post("/api/v1/auth/login", data={"username": email, "password": pw})
    assert rt.status_code == 200, rt.text[:200]
    check(f"akun {role} {email}", True)
    return uid, rt.json()["access_token"]


dewi_id, DEWI = buat_akun(
    "Dewi Lestari", "dewi.guru@sekolah.test", "TEACHER", GURU_PASSWORD
)
agus_id, AGUS = buat_akun(
    "Agus Santoso", "agus.guru@sekolah.test", "TEACHER", GURU_PASSWORD
)
budi_id, BUDI = buat_akun(
    "Budi Hartono", "budi.laboran@sekolah.test", "LABORANT", LAB_PASSWORD
)
T_DEWI = {"Authorization": f"Bearer {DEWI}"}
T_AGUS = {"Authorization": f"Bearer {AGUS}"}


def cari(coll: str, key: str, val: str) -> dict[str, Any] | None:
    """Cari satu item di koleksi list (paginasi besar, filter klien)."""
    r = c.get(f"/api/v1/{coll}", headers=A, params={"limit": 100})
    if r.status_code != 200:
        return None
    rows: list[dict[str, Any]] = r.json().get("items", [])
    for it in rows:
        if str(it.get(key)) == str(val):
            return it
    return None


# 3. lab
def buat_lab(code: str, name: str) -> dict[str, Any]:
    ada = cari("laboratories", "code", code)
    if ada:
        print("INFO lab ada:", code)
        check(f"lab {code}", True)
        return ada
    r = c.post("/api/v1/laboratories", headers=A, json={"code": code, "name": name})
    assert r.status_code in (200, 201), r.text[:200]
    check(f"lab {code}", True)
    payload: dict[str, Any] = r.json()
    return payload


lab_rpl = buat_lab("LAB-RPL1", "Lab Komputer 1")
lab_fis = buat_lab("LAB-FIS", "Lab Fisika")


# 4. kelas + siswa
def buat_kelas_siswa(
    code: str, name: str, siswa: list[tuple[str, str]]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cls = cari("classes", "code", code)
    if not cls:
        r = c.post(
            "/api/v1/classes",
            headers=A,
            json={
                "code": code,
                "name": name,
                "grade": 12,
                "academic_year": "2026-2027",
            },
        )
        assert r.status_code in (200, 201), r.text[:200]
        cls = r.json()
    else:
        print("INFO kelas ada:", code)
    out = []
    for nis, nm in siswa:
        st = cari("students", "student_number", nis)
        if not st:
            rs = c.post(
                "/api/v1/students",
                headers=A,
                json={"student_number": nis, "full_name": nm},
            )
            assert rs.status_code in (200, 201), rs.text[:200]
            st = rs.json()
        rm = c.post(
            f"/api/v1/classes/{cls['id']}/students",
            headers=A,
            json={"student_id": st["id"]},
        )
        assert rm.status_code in (200, 201, 409), rm.text[:200]
        out.append(st)
    check(f"kelas {code} + {len(out)} siswa", True)
    return cls, out


rpl_names = [
    "Ahmad Fauzi",
    "Rizky Ramadhan",
    "Dimas Prayoga",
    "Fajar Nugroho",
    "Yoga Saputra",
    "Ilham Maulana",
    "Reza Fahlevi",
    "Bagas Prasetyo",
    "Dinda Puspita",
    "Sinta Maharani",
]
cls_rpl, sis_rpl = buat_kelas_siswa(
    "XII-RPL-1",
    "Kelas XII RPL 1",
    [(f"202601{i + 1:02d}", n) for i, n in enumerate(rpl_names)],
)
tkj_names = [
    "Putri Ayu",
    "Nadia Safitri",
    "Eko Wijaya",
    "Hendra Gunawan",
    "Tono Prasetyo",
    "Wulan Sari",
    "Galih Permana",
    "Ratna Dewi",
]
cls_tkj, sis_tkj = buat_kelas_siswa(
    "XII-TKJ-1",
    "Kelas XII TKJ 1",
    [(f"202602{i + 1:02d}", n) for i, n in enumerate(tkj_names)],
)


# 5. jadwal demo: window mengikuti jam jalan (sesi lama auto-tutup di akhir jadwal,
#    jadi window statis hanya hidup beberapa jam). Idempoten: cocokkan jadwal by
#    (kelas, mapel, weekday); bila window kedaluwarsa, geser via PUT.
def demo_window() -> tuple[str, str]:
    from datetime import timedelta

    mulai = (now_jkt - timedelta(minutes=30)).replace(second=0, microsecond=0)
    selesai = (now_jkt + timedelta(hours=2)).replace(second=0, microsecond=0)
    # Lewat tengah malam -> kunci di 23:59 hari yang sama.
    if selesai.time() <= mulai.time():
        selesai = now_jkt.replace(hour=23, minute=59, second=0, microsecond=0)
    if mulai >= selesai:
        mulai = (selesai - timedelta(hours=2)).replace(second=0, microsecond=0)
    return mulai.strftime("%H:%M:%S"), selesai.strftime("%H:%M:%S")


WIN_START, WIN_END = demo_window()


def window_covers_now(it: dict[str, Any]) -> bool:
    sekarang = now_jkt.strftime("%H:%M:%S")
    mulai = str(it.get("start_time", ""))
    selesai = str(it.get("end_time", ""))
    return bool(mulai <= sekarang <= selesai)


def buat_jadwal(
    cls: dict[str, Any],
    lab: dict[str, Any],
    teacher_id: str,
    subject: str,
) -> dict[str, Any]:
    start, end = WIN_START, WIN_END
    r = c.get("/api/v1/schedules", headers=A, params={"limit": 100})
    cocok: list[dict[str, Any]] = []
    if r.status_code == 200:
        sched_rows: list[dict[str, Any]] = r.json().get("items", [])
        cocok = [
            it
            for it in sched_rows
            if (
                it.get("school_class_id") == cls["id"]
                or it.get("class_id") == cls["id"]
            )
            and it.get("weekday") == weekday
            and it.get("subject") == subject
        ]
        for it in cocok:  # pass 1: pakai yang window-nya menutupi jam jalan
            if window_covers_now(it):
                print("INFO jadwal ada:", subject)
                check(f"jadwal {subject}", True)
                return it
        for it in cocok:  # pass 2: geser window yang kedaluwarsa
            if True:
                u = c.patch(
                    f"/api/v1/schedules/{it['id']}",
                    headers=A,
                    json={
                        "start_time": start,
                        "end_time": end,
                        "effective_from": today,
                    },
                )
                assert u.status_code == 200, u.text[:300]
                print("INFO jadwal digeser ke jam jalan:", subject, start, "-", end)
                check(f"jadwal {subject}", True)
                return dict(u.json())
    r = c.post(
        "/api/v1/schedules",
        headers=A,
        json={
            "class_id": cls["id"],
            "laboratory_id": lab["id"],
            "teacher_user_id": teacher_id,
            "subject": subject,
            "weekday": weekday,
            "start_time": start,
            "end_time": end,
            "timezone_name": "Asia/Jakarta",
            "effective_from": today,
        },
    )
    if r.status_code == 409:  # bentrok dgn jadwal seed lama -> pakai yang ada
        print("INFO jadwal bentrok, pakai daftar:", r.text[:120])
        r2 = c.get("/api/v1/schedules", headers=A, params={"limit": 100})
        rows2: list[dict[str, Any]] = r2.json().get("items", [])
        for it in rows2:
            if it.get("subject") == subject:
                check(f"jadwal {subject}", True)
                return it
    assert r.status_code in (200, 201), r.text[:300]
    check(f"jadwal {subject}", True)
    payload: dict[str, Any] = r.json()
    return payload


sched_rpl = buat_jadwal(cls_rpl, lab_rpl, dewi_id, "Praktikum Pemrograman Web")
sched_tkj = buat_jadwal(cls_tkj, lab_fis, agus_id, "Praktikum Jaringan Komputer")


# 6. device + kredensial
def buat_device(
    lab: dict[str, Any], name: str, dtype: str, profile: str
) -> tuple[str, dict[str, str]]:
    dev = cari("devices", "name", name)
    if not dev:
        r = c.post(
            "/api/v1/devices",
            headers=A,
            json={
                "laboratory_id": lab["id"],
                "name": name,
                "device_type": dtype,
                "deployment_profile": profile,
            },
        )
        assert r.status_code in (200, 201), r.text[:200]
        dev = r.json()
    else:
        print("INFO device ada:", name)
    did_raw: object = dev.get("id", dev.get("device_id"))
    assert did_raw is not None
    did: str = str(did_raw)
    rk = c.post(f"/api/v1/devices/{did}/credentials", headers=A)
    if rk.status_code == 409:  # kredensial sudah ada -> rotate
        rk = c.post(
            f"/api/v1/devices/{did}/credentials/rotate",
            headers=A,
            json={"reason": "rotasi kredensial seed demo"},
        )
    assert rk.status_code in (200, 201), rk.text[:200]
    check(f"device {name}", True)
    return did, {"Authorization": f"Bearer {rk.json()['token']}", "X-Device-ID": did}


dev_rpl, D_RPL = buat_device(lab_rpl, "edge-pc-rpl-01", "edge_pc", "AI_EDGE")
dev_fis, D_FIS = buat_device(lab_fis, "stb-fis-01", "camera_gateway", "STB_GATEWAY")


def heartbeat(D: dict[str, str], did: str) -> None:
    r = c.post(
        f"/api/v1/devices/{did}/device-heartbeat",
        headers=D,
        json={
            "camera_status": "online",
            "queue_status": {"pending_events": 0, "dead_letter_events": 0},
        },
    )
    assert r.status_code in (200, 201), r.text[:200]


heartbeat(D_RPL, dev_rpl)
heartbeat(D_FIS, dev_fis)
check("heartbeat Online x2", True)


def kirim_event(
    D: dict[str, str], did: str, sess_id: str, student_id: str, outcome: str = "matched"
) -> httpx.Response:
    ev = {
        "event_id": str(uuid.uuid4()),
        "device_id": did,
        "session_id": sess_id,
        "student_id": student_id,
        "outcome": outcome,
        "similarity": 0.81,
        "confidence": 0.93,
        "margin": 0.21,
        "liveness_passed": None,
        "liveness_score": None,
        "occurred_at": datetime.now(JKT).isoformat(),
        "model_name": "opencv-zoo-sface",
        "model_version": "demo-seed-1",
    }
    r = c.post(f"/api/v1/devices/{did}/recognition-events", headers=D, json=ev)
    return r


def manual(
    T: dict[str, str],
    sess_id: str,
    student_id: str,
    status: str,
    note: str | None = None,
) -> httpx.Response:
    body = {"student_id": student_id, "status": status}
    if note:
        body["note"] = note
    r = c.post(
        f"/api/v1/attendance/sessions/{sess_id}/manual-marks", headers=T, json=body
    )
    return r


def roster_tercatat(sess_id: str) -> set[str]:
    r = c.get(f"/api/v1/sessions/{sess_id}/roster", headers=A)
    assert r.status_code == 200, r.text[:200]
    return {e["student_id"] for e in r.json() if e.get("record_status")}


def sesi_untuk_sched(sched_id: str, statuses: tuple[str, ...]) -> dict[str, Any] | None:
    r = c.get("/api/v1/sessions", headers=A, params={"limit": 100})
    assert r.status_code == 200, r.text[:200]
    srows: list[dict[str, Any]] = r.json().get("items", [])
    for it in srows:
        sid = it.get("practicum_schedule_id", it.get("schedule_id"))
        if sid == sched_id and it.get("status") in statuses:
            return it
    return None


def buka_sesi(T: dict[str, str], sched_id: str) -> dict[str, Any]:
    ada = sesi_untuk_sched(sched_id, ("active", "manual_override"))
    if ada:
        print("INFO sesi aktif dipakai ulang:", ada["id"])
        return ada
    r = c.post("/api/v1/sessions", headers=T, json={"practicum_schedule_id": sched_id})
    assert r.status_code in (200, 201), r.text[:300]
    payload: dict[str, Any] = r.json()
    return payload


# 7. sesi RPL AKTIF: 5 event + 1 ambiguous + manual p/l/e/a + 1 unrecorded
sess_a = buka_sesi(T_DEWI, sched_rpl["id"])
check("sesi RPL aktif", sess_a.get("status") in ("active", "manual_override"))
tercatat = roster_tercatat(sess_a["id"])
baru = 0
for st in sis_rpl[:5]:
    if st["id"] in tercatat:
        continue
    re_ = kirim_event(D_RPL, dev_rpl, sess_a["id"], st["id"])
    assert (
        re_.status_code == 200 and re_.json().get("decision") == "attendance_recorded"
    ), re_.text[:200]
    baru += 1
check(f"event matched -> recorded ({baru} baru, sisanya sudah ada)", True)
if sis_rpl[8]["id"] not in tercatat:
    ra = kirim_event(
        D_RPL, dev_rpl, sess_a["id"], sis_rpl[8]["id"], outcome="ambiguous"
    )
    assert ra.status_code == 200, ra.text[:200]
    tercatat = roster_tercatat(sess_a["id"])
check("1 event ambiguous (evidence)", True)
for sid, status, note in [
    (sis_rpl[5]["id"], "present", "Datang dengan surat tugas OSIS"),
    (sis_rpl[6]["id"], "late", "Terlambat 10 menit - hujan deras"),
    (sis_rpl[7]["id"], "excused", "Sakit - surat dari TU"),
    (sis_rpl[8]["id"], "absent", "Tanpa keterangan"),
]:
    if sid in tercatat:
        continue
    assert manual(T_DEWI, sess_a["id"], sid, status, note).status_code in (200, 201)
check("manual-mark + catatan (sisanya sudah ada)", True)
# sis_rpl[9] Sinta Maharani = belum tercatat (demo tombol manual guru)

# 8. sesi TKJ: 4 event + 1 late + 1 excused, lalu TUTUP -> 2 absen otomatis
sess_b = sesi_untuk_sched(sched_tkj["id"], ("closed",))
if sess_b:
    print("INFO sesi TKJ sudah ditutup:", sess_b["id"])
    check("sesi TKJ ditutup (2 absen otomatis)", True)
else:
    sess_b = buka_sesi(T_AGUS, sched_tkj["id"])
    check("sesi TKJ aktif", sess_b.get("status") in ("active", "manual_override"))
    tercatat_b = roster_tercatat(sess_b["id"])
    for st in sis_tkj[:4]:
        if st["id"] in tercatat_b:
            continue
        re_ = kirim_event(D_FIS, dev_fis, sess_b["id"], st["id"])
        assert (
            re_.status_code == 200
            and re_.json().get("decision") == "attendance_recorded"
        ), re_.text[:200]
    if sis_tkj[4]["id"] not in tercatat_b:
        assert manual(
            T_AGUS, sess_b["id"], sis_tkj[4]["id"], "late", "Terlambat 5 menit"
        ).status_code in (200, 201)
    if sis_tkj[5]["id"] not in tercatat_b:
        assert manual(
            T_AGUS, sess_b["id"], sis_tkj[5]["id"], "excused", "Izin - acara keluarga"
        ).status_code in (200, 201)
    r = c.post(f"/api/v1/sessions/{sess_b['id']}/close", headers=T_AGUS)
    assert r.status_code in (200, 201), r.text[:200]
    check("sesi TKJ ditutup (2 absen otomatis)", True)


# 9. Fitur baru: display PIN, penugasan laboran, hak opsional, mode guru, EWS, koreksi
def _patch(path: str, headers: dict[str, str], body: dict[str, str]) -> None:
    rr = c.patch(path, headers=headers, json=body)
    assert rr.status_code in (200, 201), rr.text[:300]


# display PIN per lab
for lab in [lab_rpl, lab_fis]:
    rp = c.post(
        f"/api/v1/laboratories/{lab['id']}/display-pin", headers=A, json={"pin": "1234"}
    )
    assert rp.status_code in (200, 201), rp.text[:200]
check("display PIN lab diatur", True)
# laboran assignment Budi -> kedua lab
for lab in [lab_rpl, lab_fis]:
    ra = c.post(
        f"/api/v1/accounts/{budi_id}/laborant-assignments",
        headers=A,
        json={"laboratory_id": lab["id"]},
    )
    assert ra.status_code in (200, 201), ra.text[:200]
check("laboran ditugaskan ke 2 lab", True)
# hak opsional laboran: beri session_operate + reports_read untuk demo
for perm in ["session_operate", "reports_read", "schedule_read"]:
    rg = c.post(
        f"/api/v1/accounts/{budi_id}/permission-grants",
        headers=A,
        json={"permission": perm},
    )
    assert rg.status_code in (200, 201), rg.text[:200]
check("hak opsional laboran diberikan (3)", True)
# mode guru: Dewi otomatis, Agus manual
_patch(f"/api/v1/accounts/{dewi_id}", A, {"opening_mode": "automatic"})
_patch(f"/api/v1/accounts/{agus_id}", A, {"opening_mode": "manual"})
check("mode pembukaan guru diatur (otomatis/manual)", True)
# EWS follow-up untuk siswa pertama RPL
r = c.post(
    f"/api/v1/reports/attendance/at-risk/{sis_rpl[0]['id']}/follow-ups",
    headers=A,
    json={"note": "Panggil orang tua, bimbingan wali kelas."},
)
assert r.status_code in (200, 201), r.text[:200]
check("EWS tindak lanjut dibuat", True)
# Koreksi: ajukan untuk record pertama sesi RPL (jika ada), lalu setujui sebagian
try:
    rr = c.get(
        "/api/v1/attendance", headers=A, params={"session_id": sess_a["id"], "limit": 1}
    )
    if rr.status_code == 200 and rr.json().get("items"):
        rec = rr.json()["items"][0]
        rk = c.post(
            "/api/v1/attendance/corrections",
            headers=T_DEWI,
            json={
                "attendance_record_id": rec["id"],
                "corrected_status": "late",
                "reason": "Seed: koreksi contoh - seharusnya terlambat",
            },
        )
        if rk.status_code in (200, 201):
            cid = rk.json()["id"]
            rd = c.post(
                f"/api/v1/attendance/corrections/{cid}/decision",
                headers=A,
                json={
                    "decision": "approved",
                    "decision_note": "Seed: disetujui contoh",
                },
            )
            assert rd.status_code in (200, 201), rd.text[:200]
            check("koreksi diajukan + disetujui (contoh)", True)
        else:
            print("INFO koreksi seed dilewati:", rk.status_code, rk.text[:150])
    else:
        print("INFO tidak ada record untuk koreksi seed")
except Exception as e:
    print("INFO koreksi seed dilewati:", e)

print(f"\nSEED DEMO LULUS: {len(passed)} checks")
print(
    "Akun: admin@local.test / DemoAdmin2026!x | dewi.guru@sekolah.test / GuruDemo2026!x"
)
print("      agus.guru@sekolah.test / GuruDemo2026!x")
print("      budi.laboran@sekolah.test / LabDemo2026!x")
