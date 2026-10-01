# Attendance decision service

Edge/AI clients submit recognition evidence to `POST /api/v1/attendance/recognition-events`.
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
against duplicate attendance.

The endpoint currently requires a bearer token with `SESSION_OPERATE`. Teacher tokens
are limited to sessions for their own schedules; ADMIN and LABORANT can operate all
sessions. Dedicated device/service credentials are not modeled yet, so edge deployments
must use an authorized operator token until that identity mechanism is added.
