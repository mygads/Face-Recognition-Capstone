# Enrollment workflow

The operator screen is available to `ADMIN` and `LABORANT`. An operator selects
an active class, reviews each student's template status, opens the camera, and
captures four short frames after a three-second countdown. The operator confirms
the displayed student identity before the interface selects the next student.
The camera stream stops when the operator leaves or changes the class, cancels a
capture, or confirms an identity.

The class roster status endpoint returns `not_enrolled`, `enrolled`, or
`needs_reenrollment`. It derives these states from template metadata: an active
template means enrolled; only revoked templates means re-enrollment is needed;
no template history means not enrolled. This endpoint does not return an image,
embedding, model information, or quality score.

Raw captures stay in browser memory until submitted and are not saved by this
interface. The API contract for multiple image captures is
`POST /api/v1/enrollments/captures`. Processing and template persistence are
currently unavailable: the database policy in
[database-schema.md](database-schema.md) excludes embedding payloads, so this
route remains an explicit `501` placeholder until the biometric storage policy
is resolved. Do not treat the UI's mocked end-to-end submission as proof that
server enrollment is operational.

The E2E flow uses a synthetic canvas-backed media stream and mocked API
responses. It exercises class/status selection, countdown/capture progress,
operator identity confirmation, and automatic selection of the next eligible
student without using student imagery.
