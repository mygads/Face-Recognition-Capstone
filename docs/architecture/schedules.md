# Practicum schedules

`practicum_schedules` stores a recurring weekly schedule: weekday (Monday=0 through
Sunday=6), local wall-clock start/end time, IANA timezone, and an inclusive effective
date range. This matches the current academic timetable and lets the attendance-session
flow create a dated runtime instance later. It is not a single dated meeting record.

Admins can assign any active user with the `TEACHER` role. Teachers can view and manage
only their own schedules and cannot assign a schedule to another account. The API
returns explicit DTO fields for the class, laboratory, and teacher names so the Vue
table does not need to join master data on the client. Active classes, laboratories,
and teacher accounts are required.

Before creating or updating an active schedule, the API looks for another active
schedule that overlaps on all three dimensions: weekday, inclusive effective-date
range, and wall-clock interval. Two schedules conflict when they share the same class,
laboratory, or teacher. A slot starting exactly when another ends is allowed. Inactive
schedules do not block an active schedule. API errors use `409 schedule_conflict`; bad
references, invalid time order, and unknown timezones use the standard validation
envelope.

The frontend provides search, weekday/status filters, pagination, create/edit forms,
and a small detail panel. It uses the existing Gentelella-derived shell, tokens, form,
table, and status components. The list and form are intentionally kept simple; no
calendar or drag-and-drop dependency is added.

Conflict detection currently runs in the API transaction before the write. PostgreSQL
does not enforce cross-row timetable overlap as a declarative constraint here, so
concurrent schedule writes would need transaction-level serialization or a database
exclusion strategy before this endpoint is relied on for high-contention writes.
