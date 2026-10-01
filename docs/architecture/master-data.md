# Master data API and UI

The Core API owns writes to students, classes, laboratory rooms, and class rosters. Vue calls the typed `openapi-fetch` client generated from `/openapi.json`; regenerate it with `npm run api:generate` from `apps/web` whenever this contract changes.

## API surface

All routes are under `/api/v1` and return the shared `ErrorEnvelope` on errors.

| Resource | Read | Write |
| --- | --- | --- |
| Students | `GET /students`, `GET /students/{student_id}` | `POST /students`, `PATCH /students/{student_id}` |
| Classes | `GET /classes`, `GET /classes/{class_id}` | `POST /classes`, `PATCH /classes/{class_id}` |
| Class roster | Included in class details; student details list linked classes | `POST /classes/{class_id}/students`, `DELETE /classes/{class_id}/students/{student_id}` |
| Laboratories | `GET /laboratories`, `GET /laboratories/{laboratory_id}` | `POST /laboratories`, `PATCH /laboratories/{laboratory_id}` |

List endpoints accept `limit` (1–100), `offset`, case-insensitive `search`, and `is_active`. Read access uses roster/laboratory permissions. Writes and roster membership changes require `MANAGE_MASTER_DATA` (currently ADMIN only).

## Integrity and lifecycle

- Student identifiers are trimmed and canonicalized to uppercase at the API boundary. PostgreSQL also enforces a unique functional index on `lower(student_number)`, so concurrent or direct writes cannot create case-only duplicates. A conflicting value returns HTTP 409 with `duplicate_student_number`.
- Existing attendance references restrict student deletion. The API does not expose student deletion; `PATCH` with `is_active: false` provides deactivation while preserving attendance, templates, and history.
- Classes and laboratories use the same explicit active flag. Their `PATCH` endpoints update fields and can deactivate a row; no master-data endpoint hard-deletes records.
- Membership uses the existing `(class_id, student_id)` primary key. Only active students can be enrolled in an active class. Duplicate enrollment returns HTTP 409. Removing a membership removes only the current class link; session roster snapshots are separate records and stay intact.
- Detail and list responses use explicit Pydantic schemas, not ORM serialization. Timestamps remain timezone-aware. Student face images and embeddings are not part of these APIs.

The case-insensitive student constraint is revision `c621cc9d1ea9_student_identifier_case_insensitive_unique.py`. If an existing database contains identifiers differing only by case, reconcile those duplicate records before applying that revision; Alembic will refuse to create the unique index while duplicates remain.

## UI

`/app/master-data` provides responsive tabs for students, classes, and laboratories, with text search, paging, create/edit forms, detail panels, active-state updates, and class roster membership controls. Authenticated users with read permission can inspect records; write controls are shown only for ADMIN. API validation details and duplicate conflicts remain visible beside the relevant form or page.
