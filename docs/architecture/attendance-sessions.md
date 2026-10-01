# Attendance sessions

An attendance session is a dated runtime instance of a weekly practicum schedule.
Only an active schedule for the current weekday and effective date can be opened.
Teachers can open sessions for their own schedules; ADMIN and LABORANT operators can
open eligible schedules for operations. Session routes require the shared
SESSION_OPERATE permission.

Opening a session creates the attendance_sessions row and copies the schedule class's
active students into session_students in the same transaction. The copied student
number and name are immutable session-time labels; later roster changes do not alter
the session snapshot. Grace period defaults to 15 minutes and can be set from 0 to
1,440 minutes when opening.

Only one active session can exist per schedule, enforced by the existing partial unique
index as well as an API conflict response. A teacher sees and can operate only sessions
for their own schedules. The current schema has no laboratory-to-laborant assignment
table, so LABORANT scope is currently global across sessions.

Sessions may be closed manually. A Core API lifespan worker checks every 30 seconds
and closes overdue sessions at the schedule's local end time, storing that exact
instant as closed_at. Session list and status reads also run the same expiry check.
Automatic closure is audited. The API process remains healthy if the database or
migrations are unavailable during worker startup; the worker retries.

attendance_records has a composite foreign key to (session_id, student_id) in
session_students. This prevents any final attendance record for a student who was
not in the session-time roster, even if a future write path misses an application
check. The migration backfills a snapshot row for any pre-existing attendance
record before adding that constraint.
Recognition-to-attendance rules and the event-ingest contract are described in
[attendance-decisions.md](attendance-decisions.md).

The teacher's live attendance summary, session-scoped WebSocket contract, device
heartbeat, and privacy limits are described in
[live-attendance-dashboard.md](live-attendance-dashboard.md).

The Vue /app/sessions page lists schedules openable today, supports the configurable
grace period, and shows current/recent session status, roster count, scheduled end,
manual close action, and the status detail returned by the Core API.
