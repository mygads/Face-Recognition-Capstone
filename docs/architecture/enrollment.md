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
interface. `POST /api/v1/enrollments/captures` accepts 3–10 bounded image
captures, rejects unsupported formats, decode failures, multiple/no-face
frames, and poor quality, then stores the best 3–5 normalized embeddings for
the configured YuNet/SFace model. Embeddings are encrypted at rest using the
AES-256-GCM key ring described in
[database-schema.md](database-schema.md); raw frames are discarded after
processing. Do not reuse enrollment templates across model versions.

The API compares new vectors against other students' active vectors for the
same model/version. Similarity above the configurable warning threshold adds a
duplicate-lookalike warning for the operator; it never merges students or
enrollments. The operator must verify identity before proceeding. To re-enroll,
select the active student, revoke the current enrollment batch, and capture a
new set. Revocation is audited and does not delete historical rows. Operators
must provision the encryption key ring before accepting enrollments; a missing
or mismatched key fails closed.

The E2E flow uses a synthetic canvas-backed media stream and mocked API
responses. It exercises class/status selection, countdown/capture progress,
operator identity confirmation, revocation/re-enrollment controls, and
automatic selection of the next eligible student without using student
imagery. It does not validate biometric accuracy; local model assets and a
locally calibrated duplicate-warning threshold remain deployment inputs.
