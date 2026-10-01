# Initial PostgreSQL schema

The Core API owns the domain schema. PostgreSQL changes are applied through Alembic; do not create or modify application tables at process startup. SQLAlchemy 2 typed mappings in `apps/api/src/presensi_api/db/models.py` are the metadata source for reviewed Alembic revisions.

## Data groups

| Area | Tables | Purpose |
| --- | --- | --- |
| Identity and access | `users`, `roles`, `user_roles` | Human accounts and role assignments. Role assignments retain who granted them when available. |
| Roster and timetable | `students`, `classes`, `class_students`, `laboratories`, `devices`, `practicum_schedules` | Current roster, class membership, rooms, edge devices, and recurring schedules. |
| Attendance operation | `attendance_sessions`, `session_students` | A live session and its immutable-at-capture roster snapshot. |
| Recognition evidence | `face_templates`, `recognition_events` | Model-versioned template metadata and raw, idempotent AI outcomes. Ambiguous and no-match outcomes remain evidence only. |
| Final attendance | `attendance_records`, `attendance_corrections` | The API's final attendance decision and a reviewable correction request/decision history. |
| Audit | `audit_logs` | Append-oriented actor/action/entity records with optional before/after JSON state. Do not put face data, passwords, tokens, or secrets in audit state. |

Every standalone/synchronizable entity uses a UUID primary key generated in the application. Join tables use composite primary keys. UUIDs are suitable as stable identifiers when records are replayed or synchronized across edge and central services. The recognition producer also supplies `event_uuid` as its retry/idempotency key.

All event and lifecycle timestamps use `timestamp with time zone` (`DateTime(timezone=True)`). Schedule `start_time`/`end_time` are local wall-clock values; `timezone_name` records the IANA zone used to interpret them. This is deliberate because a recurring weekly schedule is not a single instant.

## Recognition and privacy boundary

`recognition_events` stores the raw result (`matched`, `ambiguous`, `no_match`, or `error`), model name/version, similarity, confidence and margin, quality metadata, event UUID, source device, session, optional recognized student, and the event timestamp. The Core API adds its attendance decision/rejection reason to metadata; raw outcome and final attendance remain separate.

`attendance_records` is the final domain decision. The application validates the active session, `session_students` snapshot, device, timing/grace period, and recognition outcome before inserting a record. A database unique constraint allows at most one final row per `(session_id, student_id)`. One recognition event can be used by at most one final record. Manual/system decisions have no recognition event; face-recognition decisions must reference one.

`face_templates` contains a student association, `model_name`, `model_version`, quality metadata, creation/revocation times, and optional account provenance. The default schema deliberately stores no source image, image/blob, or embedding payload. A future biometric payload store requires a separate documented privacy/security decision and must not be added as ordinary JSON or audit data.

## Constraints and indexes

Named unique constraints enforce account email, role code, exact student number, class code within academic year, laboratory code, recognition event UUID, attendance session/student, and attendance record/recognition event uniqueness. A unique functional index on `lower(students.student_number)` rejects case-only identifier duplicates as well. User-role, class-student, and session-student links use composite primary keys to prevent duplicate membership. `session_students` also holds student name/number snapshots so a later roster edit does not rewrite the session's roster context.

Two partial unique indexes apply only to active rows: one prevents multiple active templates for the same student/model/version while allowing revoked history, and one prevents two active attendance sessions for the same schedule while preserving past sessions. These indexes are declared for PostgreSQL and SQLite so the same key constraints are exercised by fast unit tests.

Foreign keys used for joins have indexes where a composite unique/primary key does not already cover the lookup order. Time-series indexes on `(session_id, occurred_at)` and `(device_id, occurred_at)` support session/device event review; `(recognized_student_id, occurred_at)` supports a student's evidence history. Attendance has an index on student, correction rows on attendance/requester, and audit rows on actor/time and entity/time. These are the initial query paths; additional indexes should follow measured query plans because each index adds write and storage cost.

Check constraints validate grades, weekdays, schedule ordering, session/device/outcome/status vocabularies, confidence/margin bounds, correction state consistency, and event/student consistency. They protect data integrity across API code and synchronization/replay paths.

## Migrations and seed

From the repository root with Docker Compose available:

```sh
docker compose run --rm api alembic upgrade head
docker compose run --rm api python -m presensi_api.db.seed_roles
```

The role seed is repeatable and assigns deterministic UUIDs to `ADMIN`, `TEACHER`, and `LABORANT`. The role normalization revision renames the earlier lowercase roles and retains old student assignments under `LEGACY_STUDENT`, which receives no application permissions. To create a future revision, run `alembic revision --autogenerate -m "short description"` from `apps/api` with a reachable PostgreSQL database configured. Review the generated operations before committing; autogenerate is a candidate generator, not a schema correctness check. CI applies the migrations to PostgreSQL and runs `alembic check` to detect model/revision drift.
