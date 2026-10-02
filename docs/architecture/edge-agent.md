# Edge agent profiles

`apps/edge-agent` has two runtime modes selected by `mode` in YAML. `AI_EDGE`
keeps the local inference behavior described below. `STB_GATEWAY` is a separate
low-resource path for ARM64 Armbian and does not import or instantiate the
recognition pipeline/model adapters.

## STB_GATEWAY on ARM64 Armbian

The gateway opens one UVC device with the configured V4L2 capture mode. The
sample requests 640×360 at 10 FPS; runtime validation rejects capture settings
above 1280×720 or 15 FPS. A downsampled 160×90 grayscale frame-difference,
brightness, and Laplacian-variance check is used as a cheap candidate/quality
gate. Periodic sampling remains enabled as a fallback so a stationary person
is not excluded indefinitely. A cooldown bounds burst frequency. The gateway
encodes at most five quality-passing JPEG frames in memory and posts them to
the authenticated AI Central burst endpoint. It never writes a frame to disk,
and the service response contains no image or embedding.
The camera adapter also checks negotiated resolution and rejects any returned
frame larger than the configured camera size if a driver ignores the request.

The gateway forwards AI decisions to Core API as allowlisted recognition-event
fields. Only that result payload enters the existing ordered SQLite outbox;
frames are discarded after the central request. Core API validates device,
laboratory, active session, roster, liveness policy, idempotency, and attendance
rules. Heartbeat and event delivery run on a separate retrying worker. Central
AI upload failures are logged with status/retryability and the next camera
sampling continues without persisting the failed burst.

The gateway discovers active sessions for the registered device's laboratory
through Core API, so an operator does not have to change a session UUID every
class. It refuses ambiguous discovery when more than one active session is
found. Each successful discovery refreshes a local offline deadline capped by
`api.cache_max_offline_seconds` and the scheduled session end. Core API remains
the final authority when queued events are delivered.

Devices authenticate to Core API and AI Central with a high-entropy
device-specific bearer credential, provisioned once by an administrator. The
API renews it before expiry when the agent is configured with a protected
`api.token_file`; the old credential has a short overlap for crash-safe file
replacement. Linux token files are atomically replaced with owner-only
permissions. Windows service deployments must protect the file with an ACL for
the service account.

AI Central obtains the production gallery from Core API, checks it against the
active session and device laboratory, and holds it in memory only. Session
discovery and active template retrieval are implemented; galleries are bounded
by the scheduled end and configured cache age. When Core API becomes
unreachable, a previously validated device/session may continue using its
cached gallery until that deadline. A restarted AI service has no gallery and
fails closed until Core API is reachable again. Events already produced remain
durable in the gateway outbox and are retried with their original idempotency
key.

The STB profile is native and uses systemd on Armbian. Installation, service
unit setup, and CPU/RAM/temperature measurements are in
[`apps/edge-agent/README.md`](../../apps/edge-agent/README.md#stb_gateway-on-armbian).

## AI_EDGE agent

## Runtime responsibilities

`apps/edge-agent` is a native Python process on the lab PC. It enumerates UVC
camera indices, opens the selected camera using requested resolution/FPS, and
passes frames to `libs/recognition-core`. The core's configurable frame stride
keeps capture cadence separate from detector/recognition sampling. Frames stay
in process memory and are not written to disk.

The agent loads YuNet/SFace model files from configured local paths. The
commissioning installer downloads the pinned files and checks their checksums;
the running agent never downloads weights. An administrator publishes quality,
sampling, temporal-agreement, and calibrated Top-1/Top-1-vs-Top-2 margin values
from **AI & kamera**. The agent polls Core API with its device credential,
applies a validated revision, reports its state, and caches the non-biometric
configuration for restart during a temporary outage. Model files/version,
liveness model, network endpoint, token file, and camera remain host-level
configuration. Thresholds must come from local calibration. The stream currently
uses a single camera track and rejects frames containing
zero or multiple faces; lab framing should keep one participant in view until
multi-person tracking is designed.

## Data and retry boundaries

The agent's SQLite outbox stores only the allowlisted recognition-event
contract, including its idempotency UUID. It rejects any extra payload field,
so image, face crop, embedding, and credentials cannot enter that queue. A
separate sync worker handles device heartbeat, cache refresh, and event delivery
so API outages do not block camera capture. Retryable network/5xx/rate-limit
responses use exponential backoff; non-retryable event delivery is retained in
a dead-letter state. Log records are structured and exclude secrets and
biometric material.

The API supports device heartbeat and the device-authenticated
`POST /api/v1/devices/{device_id}/recognition-events`. Its attendance service remains the
only place that creates final attendance after validating device, lab, active
session, roster, liveness policy, and duplicate rules.

## Gallery and cache lifecycle

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

Core API encrypts vectors at rest with AES-256-GCM and releases only the
requested active-session/model gallery to that device's authenticated runtime
request. Keep the key ring in the institution's secret manager and configure
the same versioned model on capture and inference devices. Metadata routes,
operator screens, logs, and the SQLite outbox do not include embeddings.

## Configuration and operations

Use `apps/edge-agent/config/edge-agent.example.yaml` as a template. Keep the
machine-specific copy and credentials out of Git. See
[`apps/edge-agent/README.md`](../../apps/edge-agent/README.md) for PowerShell and
Linux commands, camera enumeration, status diagnostics, model paths, and
calibration requirements. The installer offers camera index, resolution, and
requested FPS choices and persists them to device YAML. Quality and threshold
policy is managed from the admin dashboard; camera selection, capture mode,
model files, endpoint, and credentials stay local to the host. Camera access is
native and intentionally excluded from default Docker Compose.

For `AI_EDGE`, the agent also exposes a temporary loopback-only preview endpoint
on `127.0.0.1:8765`. The same camera frame is downscaled in memory and displayed
by the dashboard only when the operator browser is on that AI_EDGE host and the
operator is ADMIN/LABORANT. The preview uses a short-lived local token after
validating the operator bearer token with Core API; it does not forward preview
frames to Core API or persist them. No preview listener starts for
`STB_GATEWAY`. The dashboard must use a localhost origin listed in
`preview.allowed_origins`.

While an operator preview session is open, the agent samples YuNet detection
and the shared quality assessor at most once every 750 ms. It overlays an oval
around detected faces: green means
the current frame passes the configured face-size, sharpness, and brightness
checks; amber asks the operator to adjust framing or lighting. Green does not
mean an identity match or an attendance record. This observation contains only
normalized face boxes and quality signals, never a name, embedding, or image.
The full-screen student display hides diagnostics and tentative candidate names.
It shows the roster name and attendance result only after Core API confirms a
final attendance record, and only when that returned student belongs to the
active session's cached roster. Candidate matches and frame-quality checks
never reveal a name on the student display.
Missing calibrated identity thresholds continue to pause AI_EDGE recognition;
the preview does not loosen enrollment or attendance quality rules.

Liveness is disabled in the sample config. That mode requires documented
physical/session controls at the lab station. The available anti-spoof model
candidate still has a deployment-license warning; do not enable it in a
deployment until the license/use has been cleared and its threshold calibrated.

Hardware validation is pending: camera enumeration, negotiated 1080p mode,
reconnect behavior, and end-to-end inference need to be checked on the target
Windows/Linux lab PCs (**MANUAL HARDWARE TEST REQUIRED**).

For `STB_GATEWAY`, negotiated V4L2 mode, central burst latency, sustained CPU,
RSS, and thermal behavior still need measurement on each target Armbian board;
the benchmark procedure is in the edge-agent README (**MANUAL HARDWARE TEST REQUIRED**).
