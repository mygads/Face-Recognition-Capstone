# Edge Agent (`AI_EDGE`)

Native Python service for one lab PC and its UVC camera. It captures the camera
stream at the configured resolution/FPS, calls `recognition-core` on a sampled
stride, caches the active session gallery in memory, and sends only recognition
event fields to the FastAPI Core API. It also sends device heartbeats and keeps
an SQLite outbox so temporary API outages do not stop camera operation.

## Prerequisites

- Python 3.11 or newer.
- A supported UVC camera and its Windows/Linux device permissions.
- YuNet and SFace model files provisioned locally. Do not fetch weights at
  runtime or add model weights to Git. See [model provenance](../../docs/models.md).
- Locally calibrated recognition thresholds. The example config intentionally
  leaves them empty; there is no default production threshold.

Install from the repository root in the project virtual environment:

```powershell
python -m pip install -e "apps/edge-agent[camera]" -e "libs/recognition-core[opencv]"
```

```bash
python3 -m pip install -e 'apps/edge-agent[camera]' -e 'libs/recognition-core[opencv]'
```

Install `apps/edge-agent[antispoof]` only if an approved, locally provisioned
liveness model is configured. The current `anti-spoof-mn3` candidate has a
deployment license warning in [models.md](../../docs/models.md); do not enable it
for deployment until that use is cleared.

## Configure a lab PC

Copy `config/edge-agent.example.yaml` to `config/edge-agent.yaml`, then set the
device UUID, model paths, API URL, camera settings, and locally calibrated
thresholds. The local file should not be committed. A deployment can point to a
config elsewhere with `--config` or `PRESENSI_EDGE_CONFIG`.

Windows PowerShell:

```powershell
Copy-Item apps/edge-agent/config/edge-agent.example.yaml apps/edge-agent/config/edge-agent.yaml
$env:PRESENSI_EDGE_DEVICE_ID = "<registered-device-uuid>"
$env:PRESENSI_EDGE_API_TOKEN = "<short-lived-operator-token>"
python -m presensi_edge_agent --config apps/edge-agent/config/edge-agent.yaml cameras
python -m presensi_edge_agent --config apps/edge-agent/config/edge-agent.yaml status
python -m presensi_edge_agent --config apps/edge-agent/config/edge-agent.yaml run
```

Linux:

```bash
cp apps/edge-agent/config/edge-agent.example.yaml apps/edge-agent/config/edge-agent.yaml
export PRESENSI_EDGE_DEVICE_ID='<registered-device-uuid>'
export PRESENSI_EDGE_API_TOKEN='<short-lived-operator-token>'
python3 -m presensi_edge_agent --config apps/edge-agent/config/edge-agent.yaml cameras
python3 -m presensi_edge_agent --config apps/edge-agent/config/edge-agent.yaml status
python3 -m presensi_edge_agent --config apps/edge-agent/config/edge-agent.yaml run
```

Use `api.token_file` for a protected token file when the service manager supplies
secrets that way. On Windows, restrict the file ACL to the service account; on
Linux, use owner-only permissions. The API currently expects its short-lived
operator JWT. This package does not add a device credential or token-refresh
endpoint, so the token must be rotated by the deployment and the process
restarted when it expires.

The `cameras` command reports accessible camera indices; set the selected index
in config. `status` checks Core API process health, camera availability, and
whether local run prerequisites are ready. It does not act as an OS process
supervisor. Run this native service directly on the camera PC; webcam
passthrough is intentionally not part of the default Docker development stack.

`camera.width`, `camera.height`, and `camera.fps` request the capture mode (the
camera driver may negotiate a different mode). `recognition.sample_every_n_frames`
controls inference sampling independently from capture FPS. The default example
requests 1920×1080 at 30 FPS and samples every sixth frame; tune it on target
hardware.

## API and template-provider blocker

Heartbeat (`POST /api/v1/devices/{device_id}/heartbeat`) and recognition-event
ingest (`POST /api/v1/attendance/recognition-events`) use the existing Core API.
Events are persisted locally with a UUID idempotency key and retried with
exponential backoff in strict FIFO order. A retrying head event blocks later
events so reconnect never reorders attendance evidence. SQLite persists the
queue across agent restarts. The allowlisted outbox schema contains no image,
embedding, or token fields. Non-retryable event responses are moved to a local
dead-letter state for operator review.

The session gallery remains in memory. Its local validity is capped by both the
provider expiry and `session_ends_at`, plus `api.cache_max_offline_seconds`
(default 300 seconds since the last successful fetch). After that limit, the
agent clears the gallery and stops recognition until a fresh active-session
cache arrives. On reconnect the Core API also rejects attendance for sessions
it has closed; those events can still be stored as recognition audit evidence.
If the process restarts offline, the in-memory gallery is unavailable and local
recognition waits for a fresh provider response; queued events still survive.

The active-session cache uses a provider adapter contract at
`api.cache_path`. The matching Core API endpoint does **not** exist yet and
`GET /api/v1/face-templates` currently returns 501 with metadata only. The
database deliberately stores no embedding payload. Therefore a fresh agent
cannot load a gallery and cannot perform live identity matching until an
approved template-provider/storage design is implemented. This task does not
change that biometric storage policy. A failed cache refresh is logged and
retried while the service remains available for heartbeats and delivery of any
already queued events.

## Liveness and physical controls

Liveness is disabled in the example config. When disabled, deployment must
document and operate physical/session controls such as supervised one-person
entry and a bounded attendance station. When enabled and required, failed or
inconclusive liveness cannot produce an accepted local decision. Review model
license and device performance before enabling it; see [model provenance](../../docs/models.md).

## Tests

From repository root, run `python -m pytest apps/edge-agent/tests -q` and
`python scripts/check.py`. Tests use synthetic payloads and mocked camera/API
adapters; no face images or hardware are used. UVC enumeration, driver mode
negotiation, throughput, and model inference still require validation on each
target lab PC (**MANUAL HARDWARE TEST REQUIRED**).
