# Attendance decision service

Human operator clients may submit recognition evidence to
`POST /api/v1/attendance/recognition-events`; device agents use the device-scoped
`POST /api/v1/devices/{device_id}/recognition-events` endpoint with a dedicated
device credential.
The request contains an event UUID, device/session/candidate identifiers, the AI outcome,
similarity and/or confidence, optional liveness result, capture timestamp, and model
name/version. It never accepts or stores an image or embedding.

The endpoint stores each validly referenced event before deciding final attendance. An
event with `ambiguous`, `no_match`, or `error` outcome remains audit evidence and cannot
produce a final record. A `matched` event creates a record only when:

1. the device is active and assigned to the laboratory in the session's schedule;
2. the session is active when the API processes the event;
3. the candidate exists and belongs to the `session_students` roster snapshot;
4. the AI outcome is `matched` and any supplied liveness result passes; and
5. no attendance record already exists for that student and session.

The API does not select a face similarity threshold. Recognition service configuration
must produce a `matched` outcome using the calibrated policy. A reported failed liveness
check rejects attendance; an omitted liveness result remains optional until deployment
policy makes liveness mandatory.

The grace cutoff is `attendance_sessions.opened_at + grace_period_minutes`. A capture at
or before the cutoff is `present`; a later capture is `late`. The event's capture time is
used, rather than API receipt time, to handle network delay.

`event_id` is the idempotency key. Replaying the same payload returns the original
decision and record. Reusing the key with different content returns HTTP 409. A new event
for an already recorded student is itself retained, with reason
`attendance_already_recorded`; the unique database constraint remains the final guard
against duplicate attendance. Two concurrent deliveries can both pass the
pre-check, so the record insert runs inside a savepoint: a `UNIQUE` violation is
caught, the audit event still commits, and the response reports the clean
duplicate reason instead of a 500.

## Presensi manual guru (rencana, keputusan tim 2026-10-21)

Hasil recognition yang gagal (wajah tidak terdeteksi, retry berulang, perangkat
bermasalah) harus bisa ditutup guru secara manual. Kondisi saat ini: guru hanya
bisa mengajukan *correction request* berstatus pending (belum ada workflow
approval), dan tidak ada endpoint "tandai hadir langsung". Rencana (backlog
P1-11): endpoint `POST /attendance/sessions/{id}/manual-marks` dengan
`SESSION_OPERATE` + kepemilikan jadwal guru, body `{student_id, status
(present|late|absent|excused), note?}`; menulis `AttendanceRecord`
`source='manual'`, `recognition_event_id=NULL`, `device_id=NULL`,
`marked_by=<guru>`; memvalidasi sesi berjalan (`active`/`manual_override`),
roster snapshot, dan duplikat student+session; mengembalikan record + audit
`attendance.manual_marked`. UI guru menampilkan tombol tandai manual per siswa
yang belum tercatat, dengan status validasi/error yang jelas. Rekonsiliasi:
record manual tidak menimpa record face_recognition yang sudah ada; perubahan
atas record manual memakai alur koreksi yang sama.

The operator endpoint requires a bearer token with `SESSION_OPERATE`. Teacher
tokens are limited to sessions for their own schedules; ADMIN and LABORANT can
operate all sessions. The device endpoint authenticates the registered device
and checks that its laboratory matches the session's schedule before applying
the same attendance decision service.
