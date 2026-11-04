"""P2-2 live UAT: real Postgres + real API over HTTP, synthetic data only.

Reproducible end-to-end check (no mocks): bootstrap login, password change,
teacher account, lab/class/students/memberships, schedule, session open,
device registration + credential, heartbeat, recognition event ->
attendance_recorded, idempotency, dashboard snapshot, GZip on the wire,
session close.

Usage (with the live stack up, see docs/pengujian.md P2-2):
  API_BASE=http://127.0.0.1:8017 python3 scripts/live-uat.py

Env (defaults work with the documented live-UAT stack):
  API_BASE, ADMIN_EMAIL, BOOTSTRAP_PASSWORD, ADMIN_PASSWORD,
  TEACHER_PASSWORD, TZ_NAME
"""

import os
import socket
import sys
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

API = os.environ.get("API_BASE", "http://127.0.0.1:8017")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@local.test")
JKT = ZoneInfo(os.environ.get("TZ_NAME", "Asia/Jakarta"))
now_jkt = datetime.now(JKT)
today = now_jkt.date().isoformat()
SUFFIX = now_jkt.strftime("%H%M%S")
weekday = now_jkt.weekday()  # Mon=0..Sun=6, sama dgn session_can_open_today

passed: list[str] = []


def check(name: str, cond: bool, extra: object = "") -> None:
    print(("PASS " if cond else "FAIL ") + name, extra)
    if not cond:
        sys.exit(1)
    passed.append(name)


c = httpx.Client(base_url=API, timeout=15)

# 1. bootstrap login + change password
r = c.post(
    "/api/v1/auth/login",
    data={
        "username": ADMIN_EMAIL,
        "password": os.environ.get("BOOTSTRAP_PASSWORD", "1234abcd"),
    },
)
if r.status_code == 200:
    tok0 = r.json()["access_token"]
    check("login bootstrap", True)
else:  # rerun: sandi sudah diganti pada UAT sebelumnya
    r = c.post(
        "/api/v1/auth/login",
        data={
            "username": ADMIN_EMAIL,
            "password": os.environ.get("ADMIN_PASSWORD", "UatLive2026!x"),
        },
    )
    check("login admin baru (rerun)", r.status_code == 200, r.text[:120])
    ADMIN = r.json()["access_token"]
    A = {"Authorization": f"Bearer {ADMIN}"}
    tok0 = None
if tok0 is not None:
    r = c.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {tok0}"},
        json={
            "current_password": os.environ.get("BOOTSTRAP_PASSWORD", "1234abcd"),
            "new_password": os.environ.get("ADMIN_PASSWORD", "UatLive2026!x"),
        },
    )
    check("change password", r.status_code in (200, 201), r.text[:160])
    r = c.post(
        "/api/v1/auth/login",
        data={
            "username": ADMIN_EMAIL,
            "password": os.environ.get("ADMIN_PASSWORD", "UatLive2026!x"),
        },
    )
    check("login admin baru", r.status_code == 200, r.text[:120])
    ADMIN = r.json()["access_token"]
    A = {"Authorization": f"Bearer {ADMIN}"}
check("admin bersih change-flag", r.json().get("password_change_required") is False)
A = {"Authorization": f"Bearer {ADMIN}"}

# 2. teacher account
r = c.post(
    "/api/v1/accounts",
    headers=A,
    json={
        "full_name": "Guru UAT",
        "email": "guru.uat." + SUFFIX + "@local.test",
        "role": "TEACHER",
    },
)
check("buat akun guru", r.status_code in (200, 201), r.text[:200])
teacher = r.json()
r = c.post(
    "/api/v1/auth/login",
    data={
        "username": "guru.uat." + SUFFIX + "@local.test",
        "password": teacher["temporary_password"],
    },
)
check("login guru", r.status_code == 200, r.text[:120])
tok_g = r.json()["access_token"]
r = c.post(
    "/api/v1/auth/change-password",
    headers={"Authorization": f"Bearer {tok_g}"},
    json={
        "current_password": teacher["temporary_password"],
        "new_password": os.environ.get("TEACHER_PASSWORD", "GuruUat2026!x"),
    },
)
check("ganti sandi guru", r.status_code in (200, 201), r.text[:160])
r = c.post(
    "/api/v1/auth/login",
    data={
        "username": "guru.uat." + SUFFIX + "@local.test",
        "password": os.environ.get("TEACHER_PASSWORD", "GuruUat2026!x"),
    },
)
check("login guru bersih", r.status_code == 200, r.text[:120])
TEACHER = r.json()["access_token"]
T = {"Authorization": f"Bearer {TEACHER}"}

# 3. lab, kelas, siswa, membership
r = c.post(
    "/api/v1/laboratories",
    headers=A,
    json={"code": "LAB-UAT-" + SUFFIX, "name": "Lab UAT"},
)
check("buat lab", r.status_code in (200, 201), r.text[:160])
lab = r.json()
r = c.post(
    "/api/v1/classes",
    headers=A,
    json={
        "code": "KLS-UAT-" + SUFFIX,
        "name": "Kelas UAT",
        "grade": 10,
        "academic_year": "2026-2027",
    },
)
check("buat kelas", r.status_code in (200, 201), r.text[:160])
cls = r.json()
students = []
for nis, nm in [
    ("UAT-" + SUFFIX + "-1", "Siswa UAT Satu"),
    ("UAT-" + SUFFIX + "-2", "Siswa UAT Dua"),
]:
    r = c.post(
        "/api/v1/students", headers=A, json={"student_number": nis, "full_name": nm}
    )
    check(f"buat siswa {nis}", r.status_code in (200, 201), r.text[:160])
    students.append(r.json())
    r = c.post(
        f"/api/v1/classes/{cls['id']}/students",
        headers=A,
        json={"student_id": students[-1]["id"]},
    )
    check(f"anggota kelas {nis}", r.status_code in (200, 201), r.text[:120])

# 4. jadwal hari ini + buka sesi
r = c.post(
    "/api/v1/schedules",
    headers=A,
    json={
        "class_id": cls["id"],
        "laboratory_id": lab["id"],
        "teacher_user_id": teacher["id"],
        "subject": "Praktikum UAT",
        "weekday": weekday,
        "start_time": "00:00:00",
        "end_time": "23:59:00",
        "timezone_name": "Asia/Jakarta",
        "effective_from": today,
    },
)
check("buat jadwal", r.status_code in (200, 201), r.text[:200])
sched = r.json()
r = c.post("/api/v1/sessions", headers=T, json={"practicum_schedule_id": sched["id"]})
check("buka sesi", r.status_code in (200, 201), r.text[:200])
sess = r.json()
check(
    "sesi running",
    sess.get("status") in ("active", "manual_override"),
    sess.get("status"),
)

# 5. device + kredensial
r = c.post(
    "/api/v1/devices",
    headers=A,
    json={
        "laboratory_id": lab["id"],
        "name": "Edge UAT",
        "device_type": "edge_pc",
        "deployment_profile": "AI_EDGE",
    },
)
check("registrasi device", r.status_code in (200, 201), r.text[:160])
dev = r.json()
DEV_ID = dev.get("id", dev.get("device_id"))
r = c.post(f"/api/v1/devices/{DEV_ID}/credentials", headers=A)
check("provisi kredensial", r.status_code in (200, 201), r.text[:120])
D = {"Authorization": f"Bearer {r.json()['token']}", "X-Device-ID": DEV_ID}

# 6. heartbeat + event matched
r = c.post(
    f"/api/v1/devices/{DEV_ID}/device-heartbeat",
    headers=D,
    json={
        "camera_status": "online",
        "queue_status": {"pending_events": 0, "dead_letter_events": 0},
    },
)
check("heartbeat", r.status_code in (200, 201), r.text[:120])
eid = str(uuid.uuid4())
event = {
    "event_id": eid,
    "device_id": DEV_ID,
    "session_id": sess["id"],
    "student_id": students[0]["id"],
    "outcome": "matched",
    "similarity": 0.81,
    "confidence": 0.93,
    "margin": 0.21,
    "liveness_passed": None,
    "liveness_score": None,
    "occurred_at": datetime.now(JKT).isoformat(),
    "model_name": "opencv-zoo-sface",
    "model_version": "uat-live-1",
}
r = c.post(f"/api/v1/devices/{DEV_ID}/recognition-events", headers=D, json=event)
check("event matched", r.status_code == 200, r.text[:160])
check(
    "attendance_recorded",
    r.json().get("decision") == "attendance_recorded",
    r.text[:120],
)

# 7. idempoten: kirim ulang event_id sama
r2 = c.post(f"/api/v1/devices/{DEV_ID}/recognition-events", headers=D, json=event)
check(
    "idempoten event ganda",
    r2.status_code == 200 and r2.json().get("decision") == "attendance_recorded",
    r2.text[:120],
)

# 8. dashboard guru
r = c.get(f"/api/v1/sessions/{sess['id']}/dashboard", headers=T)
check("dashboard snapshot", r.status_code == 200, r.text[:120])
summ = r.json()["summary"]
check("hadir tercatat 1", summ.get("present") == 1, str(summ))

# 9. GZip live (minimum_size=1024: snapshot kecil 724B wajar tak dikompres;
#    buktikan pada daftar sesi >1KB via raw socket agar httpx tak decode diam-diam)
raw_path = "/api/v1/sessions?limit=100&offset=0"
raw_req = (
    f"GET {raw_path} HTTP/1.1\r\nHost: 127.0.0.1\r\n"
    f"Authorization: Bearer {ADMIN}\r\n"
    "Accept-Encoding: gzip\r\nConnection: close\r\n\r\n"
)
s = socket.create_connection(("127.0.0.1", 8017), timeout=10)
s.sendall(raw_req.encode())
wire = b""
while True:
    chunk = s.recv(65536)
    if not chunk:
        break
    wire += chunk
s.close()
head, _, body = wire.partition(b"\r\n\r\n")
check(
    "gzip aktif di wire",
    b"content-encoding: gzip" in head.lower(),
    head.split(b"\r\n")[0].decode(),
)

# 10. tutup sesi
r = c.post(f"/api/v1/sessions/{sess['id']}/close", headers=T)
check("tutup sesi", r.status_code in (200, 201), r.text[:120])

print(f"\nUAT LIVE LULUS: {len(passed)} checks")
