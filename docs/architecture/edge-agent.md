# AI_EDGE agent

## Runtime responsibilities

`apps/edge-agent` is a native Python process on the lab PC. It enumerates UVC
camera indices, opens the selected camera using requested resolution/FPS, and
passes frames to `libs/recognition-core`. The core's configurable frame stride
keeps capture cadence separate from detector/recognition sampling. Frames stay
in process memory and are not written to disk.

The agent loads YuNet/SFace model files from configured local paths. It does not
download models. Top-1 and Top-1-vs-Top-2 margin thresholds are required runtime
settings and must come from local calibration. The stream currently uses a
single camera track and rejects frames containing zero or multiple faces; lab
framing should keep one participant in view until multi-person tracking is
designed.

## Data and retry boundaries

The agent's SQLite outbox stores only the allowlisted recognition-event
contract, including its idempotency UUID. It rejects any extra payload field,
so image, face crop, embedding, and credentials cannot enter that queue. A
separate sync worker handles device heartbeat, cache refresh, and event delivery
so API outages do not block camera capture. Retryable network/5xx/rate-limit
responses use exponential backoff; non-retryable event delivery is retained in
a dead-letter state. Log records are structured and exclude secrets and
biometric material.

The API supports device heartbeat and
`POST /api/v1/attendance/recognition-events`. Its attendance service remains the
only place that creates final attendance after validating device, lab, active
session, roster, liveness policy, and duplicate rules.

## Gallery provider and current blocker

The service depends on a cache-provider adapter contract and accepts a
device-scoped active-session bundle in memory. A bundle is checked for matching
device, active session, expiry, and recognition model/version before it becomes
the matching gallery. Its effective expiry is the earliest of the provider
expiry, scheduled session end, and the configured local freshness ceiling
(`api.cache_max_offline_seconds`, default 300 seconds after the last successful
fetch). An expired bundle is cleared and the agent stops recognition until a
fresh active-session bundle arrives. The gallery is not persisted locally.
If the process restarts while disconnected, it cannot restore biometric vectors
from disk; it fails closed until the provider is reachable, while the event
outbox remains durable across that restart.

The event outbox uses a durable monotonically ordered SQLite sequence. Events
are sent FIFO with the original `event_id`; retrying a head event blocks later
events until it is acknowledged or dead-lettered. If an event is accepted by
the API but its response is lost, the same idempotency key is retried. The API
returns the saved result instead of creating a second record. On reconnect, the
API still checks that the session is active; queued events from a session that
has ended remain auditable but cannot create attendance.

Core API currently has no active-session roster/template cache endpoint.
`GET /api/v1/face-templates` is a metadata-only 501 placeholder, enrollment is
also a 501 placeholder, and the default `face_templates` schema has no vector
column or biometric object store. Consequently, the agent currently cannot
load embeddings for matching and must not be represented as end-to-end
operational. **This is a blocker until the team approves a biometric storage
policy and implements an authenticated provider.** This task preserves the
existing no-image/no-embedding database policy. Replace the configured provider
adapter when that approved API contract exists; do not put vectors in generic
JSON or this agent's disk cache. The future provider must return an authoritative
`expires_at` no later than `session_ends_at`; the edge independently caps that
expiry by the configured offline freshness ceiling.

The API currently authenticates requests with short-lived operator JWTs. The
agent reads the token from an environment variable or protected token file. A
deployment must rotate the token and restart the process after expiry; a
device-specific credential/refresh flow is not implemented here.

## Configuration and operations

Use `apps/edge-agent/config/edge-agent.example.yaml` as a template. Keep the
machine-specific copy and credentials out of Git. See
[`apps/edge-agent/README.md`](../../apps/edge-agent/README.md) for PowerShell and
Linux commands, camera enumeration, status diagnostics, model paths, and
calibration requirements. Camera access is native and intentionally excluded
from default Docker Compose.

Liveness is disabled in the sample config. That mode requires documented
physical/session controls at the lab station. The available anti-spoof model
candidate still has a deployment-license warning; do not enable it in a
deployment until the license/use has been cleared and its threshold calibrated.

Hardware validation is pending: camera enumeration, negotiated 1080p mode,
reconnect behavior, and end-to-end inference need to be checked on the target
Windows/Linux lab PCs (**MANUAL HARDWARE TEST REQUIRED**).
