# Attendance reports

`GET /api/v1/reports/attendance` returns aggregate counts and
`GET /api/v1/reports/attendance/records` returns the paginated rows. Both accept
`starts_on`, `ends_on`, and optional `student_id` or exact `student_number`,
`class_id`, `laboratory_id`, `session_id`, and `status` filters. The UI asks for
NIS/NISN directly and uses class/lab options derived from visible schedules, so
it does not fetch an unrestricted school-wide student directory for teachers.
Date bounds are inclusive local calendar dates
in `timezone_name` (default `Asia/Jakarta`); the API converts them to a UTC,
half-open timestamp range over `attendance_sessions.opened_at`.

## Row semantics

The report starts from `session_students`, so it uses the roster snapshot taken
when a session opened. Student number and display name are the snapshot values;
class and lab are taken from the schedule attached to that session. Cancelled
sessions are excluded. A roster row with an attendance record uses that record's
status. A row with no record is `not_recorded` while its session is active and
`absent` after the session is closed. This keeps an in-progress student from
being reported absent early. The response calls the aggregate `total_rows`
because one student attending two sessions counts twice.

## Access policy

`ADMIN` can report across all schedules. `TEACHER` has `REPORTS_READ`, but the
query is additionally constrained to schedules whose `teacher_user_id` matches
the authenticated user's ID. The same scope is applied to summaries, pages, and
exports. Other roles do not have report permission. Filtering by a student,
class, laboratory, session, date, or status never widens the teacher's scope.

## Query, pagination, and export

Rows use one SQL query joining roster snapshots to sessions, schedules, class,
laboratory, and teacher, with an outer join to final attendance records. Filter
and teacher predicates are applied in SQL before ordering, count, offset, and
limit. The default page is 25 rows and the API maximum is 100. `attendance_sessions`
has a B-tree index on `opened_at` for the date range; existing primary/composite
keys on `session_students`, its session foreign key, schedule class/lab indexes,
and the attendance unique key support the joins and filters.

`GET /api/v1/reports/attendance/export?format=csv|xlsx` exports the same filtered
rows, capped at 50,000 per request. XLSX uses a write-only workbook. CSV is UTF-8
with BOM for spreadsheet compatibility. Text values beginning with spreadsheet
formula markers are prefixed with an apostrophe to prevent formula execution.
Exports contain attendance and timetable identifiers and labels only: no
recognition scores, embeddings, images, or device credentials.

The Vue reports view offers the same filters and downloads both formats. The
frontend consumes generated OpenAPI request/response types; the binary download
uses the shared bearer token and error handling without logging it.
