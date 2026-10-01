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

## CSV/XLSX import

`POST /api/v1/students/import/preview` accepts `multipart/form-data` with `upload`, `student_number_column`, `full_name_column`, and `class_code_column`. The mapping values must exactly match distinct header names in the first row; matching ignores letter case. CSV files must be UTF-8 (with or without BOM). XLSX reads the active worksheet and its first row as headers. Other formats are rejected.

The API accepts `.csv` and `.xlsx` only, checks the media type and extension, limits upload size to 5 MiB, expanded XLSX size to 25 MiB, and data rows to 10,000. Preview reports row numbers, canonical student identifiers, class codes, and validation messages. It checks duplicates against all existing students (including inactive records), duplicates in the file, blank/oversized names or identifiers, and missing/inactive class codes. Blank lines are skipped.

`POST /api/v1/students/import/commit` takes the same file and column mapping again, reruns validation against current data, then inserts all students and class memberships in one database transaction. Any invalid row or uniqueness race rolls back the entire import. Preview data is not stored server-side; this avoids a staging table and makes commit revalidation explicit. UI keeps the chosen file locally until commit and disables commit while any row is invalid. The sample template at `docs/templates/students-import-template.csv` contains synthetic example values only; replace the sample identifiers and use a class code that exists in the target database.

## UI

`/app/master-data` provides responsive tabs for students, classes, and laboratories, with text search, paging, create/edit forms, detail panels, active-state updates, and class roster membership controls. Authenticated users with read permission can inspect records; write controls are shown only for ADMIN. API validation details and duplicate conflicts remain visible beside the relevant form or page.
