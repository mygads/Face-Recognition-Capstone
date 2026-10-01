# Initial PostgreSQL schema

The Core API owns the domain schema. PostgreSQL changes are applied through Alembic; do not create or modify application tables at process startup. SQLAlchemy 2 typed mappings in `apps/api/src/presensi_api/db/models.py` are the metadata source for reviewed Alembic revisions.

## Data groups

| Area | Tables | Purpose |
| --- | --- | --- |
| Identity and access | `users`, `roles`, `user_roles` | Human accounts and role assignments. Role assignments retain who granted them when available. |
| Roster and timetable | `students`, `classes`, `class_students`, `laboratories`, `devices`, `practicum_schedules` | Current roster, class membership, rooms, registered devices with deployment/app/model/camera health metadata, and recurring schedules. |
| Attendance operation | `attendance_sessions`, `session_students` | A live session and its immutable-at-capture roster snapshot. |
| Recognition evidence | `face_templates`, `recognition_events` | Model-versioned template metadata and raw, idempotent AI outcomes. Ambiguous and no-match outcomes remain evidence only. |
| Final attendance | `attendance_records`, `attendance_corrections` | The API's final attendance decision and a reviewable correction request/decision history. |
| Audit | `audit_logs` | Append-oriented actor/action/entity records with optional before/after JSON state. Do not put face data, passwords, tokens, or secrets in audit state. |

Every standalone/synchronizable entity uses a UUID primary key generated in the application. Join tables use composite primary keys. UUIDs are suitable as stable identifiers when records are replayed or synchronized across edge and central services. The recognition producer also supplies `event_uuid` as its retry/idempotency key.

All event and lifecycle timestamps use `timestamp with time zone` (`DateTime(timezone=True)`). Schedule `start_time`/`end_time` are local wall-clock values; `timezone_name` records the IANA zone used to interpret them. This is deliberate because a recurring weekly schedule is not a single instant.

## Recognition and privacy boundary

`recognition_events` stores the raw result (`matched`, `ambiguous`, `no_match`, or `error`), model name/version, similarity, confidence and margin, quality metadata, event UUID, source device, session, optional recognized student, and the event timestamp. The Core API adds its attendance decision/rejection reason to metadata; raw outcome and final attendance remain separate.

`attendance_records` is the final domain decision. The application validates the active session, `session_students` snapshot, device, timing/grace period, and recognition outcome before inserting a record. A database unique constraint allows at most one final row per `(session_id, student_id)`. One recognition event can be used by at most one final record. Manual/system decisions have no recognition event; face-recognition decisions must reference one.

`face_templates` contains a student association, enrollment batch, `model_name`, `model_version`, quality metadata, creation/revocation times, and optional account provenance. Recognition vectors are stored as AES-256-GCM ciphertext in `embedding_ciphertext`; they are never written as ordinary JSON, audit state, or plaintext columns. Each ciphertext uses a random nonce and authenticated additional data bound to the template/student/model identifiers. The active key ring is supplied outside the repository through `PRESENSI_FACE_TEMPLATE_KEYS` and `PRESENSI_FACE_TEMPLATE_ACTIVE_KEY_ID`; database rows retain only a non-secret key ID. Rotate by adding a new key alongside existing keys, setting it active, and running `python -m presensi_api.biometric_key_rotation`; verify the command's count before removing old keys. Revocation clears the ciphertext while retaining audit metadata. Keep backups of key material under the institution's secret-management policy; losing every key makes the vectors unrecoverable.

Raw captures are decoded and processed in memory and are not persisted by default. The enrollment endpoint returns only status, counts, and possible duplicate-lookalike warnings. A device-authenticated runtime endpoint decrypts only the active session roster's matching model/version templates for edge inference; AI Central receives that gallery through its device-authenticated provider and keeps it in bounded memory. Operator metadata responses and audit logs never include vectors or ciphertext. Existing metadata-only rows are revoked by the migration because they cannot participate in recognition.

## Constraints and indexes

Named unique constraints enforce account email, role code, exact student number, class code within academic year, laboratory code, recognition event UUID, attendance session/student, and attendance record/recognition event uniqueness. A unique functional index on `lower(students.student_number)` rejects case-only identifier duplicates as well. User-role, class-student, and session-student links use composite primary keys to prevent duplicate membership. `session_students` also holds student name/number snapshots so a later roster edit does not rewrite the session's roster context.

The active template lookup index on `(model_name, model_version, student_id)` supports session gallery retrieval and duplicate-lookalike comparisons. A student row lock plus transaction-level active-template check ensures an enrollment batch does not race another active batch; multiple templates within the accepted batch are intentional. The partial unique index on active attendance sessions prevents two active sessions for one schedule while preserving past sessions. These indexes are declared for PostgreSQL and SQLite where applicable.

Foreign keys used for joins have indexes where a composite unique/primary key does not already cover the lookup order. Time-series indexes on `(session_id, occurred_at)` and `(device_id, occurred_at)` support session/device event review; `(recognized_student_id, occurred_at)` supports a student's evidence history. Attendance has an index on student, correction rows on attendance/requester, and audit rows on actor/time and entity/time. These are the initial query paths; additional indexes should follow measured query plans because each index adds write and storage cost.

The device `last_seen_at` index supports stale-heartbeat filtering. `deployment_profile` is constrained to `AI_EDGE` or `STB_GATEWAY` and must match the registered device type. Version fields are bounded strings; camera status is a small enum. Optional latency summary stores only aggregate p50/p95 milliseconds, never frame-level data. Device online/offline status is derived at read time and is not duplicated in storage.

Check constraints validate grades, weekdays, schedule ordering, session/device/outcome/status vocabularies, confidence/margin bounds, correction state consistency, and event/student consistency. They protect data integrity across API code and synchronization/replay paths.

## Migrations and seed

From the repository root with Docker Compose available:

```sh
docker compose run --rm api alembic upgrade head
docker compose run --rm api python -m presensi_api.db.seed_roles
```

The role seed is repeatable and assigns deterministic UUIDs to `ADMIN`, `TEACHER`, and `LABORANT`. The role normalization revision renames the earlier lowercase roles and retains old student assignments under `LEGACY_STUDENT`, which receives no application permissions. To create a future revision, run `alembic revision --autogenerate -m "short description"` from `apps/api` with a reachable PostgreSQL database configured. Review the generated operations before committing; autogenerate is a candidate generator, not a schema correctness check. CI applies the migrations to PostgreSQL and runs `alembic check` to detect model/revision drift.
