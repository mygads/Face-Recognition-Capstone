# Edge Agent (`AI_EDGE` and `STB_GATEWAY`)

Select the runtime with the root YAML key `mode`. `AI_EDGE` runs
`recognition-core` locally. `STB_GATEWAY` is the low-resource ARM64 Armbian
profile: it loads no local face recognition model, samples the camera at low
resolution, and sends short JPEG bursts to the authenticated central AI service.
See `config/stb-gateway.example.yaml` for its separate starting configuration.

## STB_GATEWAY on Armbian

The gateway example requests 640×360 at 10 FPS and runtime validation caps the
mode at 1280×720/15 FPS. It downsamples frames to 160×90 for frame-difference
motion, brightness, and a small Laplacian sharpness check. Motion triggers are
limited by a cooldown; periodic bursts provide a fallback when a person is
stationary. At most five quality-passing JPEGs are encoded in memory per burst.
No continuous video, raw frame, or image is written to disk. Only central AI's
decision metadata can enter the SQLite event outbox.
The camera open path checks the negotiated mode and also rejects a returned
frame larger than the configured size, so a driver that ignores the low-
resolution request is not silently passed through to central AI.

The example motion, brightness, and sharpness values are starting values, not
calibrated operating limits. Tune them against the actual camera position and
room lighting, then record the measurements for the selected board.

### Install and register the systemd service

On the Armbian ARM64 device, install V4L2/OpenCV support and basic diagnostics:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip python3-opencv python3-numpy v4l-utils sysstat
```

Place a checkout/release of this repository at `/opt/presensi-edge-agent`, then
install the Python package in a venv that can use Debian's OpenCV packages:

```bash
sudo python3 -m venv --system-site-packages /opt/presensi-edge-agent/.venv
sudo /opt/presensi-edge-agent/.venv/bin/pip install -e /opt/presensi-edge-agent/apps/edge-agent
sudo useradd --system --no-create-home --home-dir /var/lib/presensi-edge-agent --shell /usr/sbin/nologin presensi-edge
sudo usermod -aG video presensi-edge
sudo install -d -o root -g presensi-edge -m 0750 /etc/presensi-edge-agent
sudo install -d -o root -g root -m 0755 /var/lib/presensi-edge-agent
sudo cp /opt/presensi-edge-agent/apps/edge-agent/config/stb-gateway.example.yaml /etc/presensi-edge-agent/stb-gateway.yaml
sudo chown root:presensi-edge /etc/presensi-edge-agent/stb-gateway.yaml
sudo chmod 0640 /etc/presensi-edge-agent/stb-gateway.yaml
```

Edit the copied YAML with the Core API and AI service URLs, and keep the
resolution/FPS within the documented gateway cap. Create protected token files
for Core API and central AI at the paths named by `api.token_file` and
`central_ai.token_file`. The files should be owned by `root:presensi-edge` and
mode `0440`; provision credentials through the site's secret handling process.
Do not commit credentials. Core API currently uses expiring operator JWTs and
does not provide automatic device credential refresh. Since the agent rereads
token files for each request, an operator can rotate the protected file without
restarting the process; unattended operation still needs an approved renewable
device credential or managed rotation process before JWT expiry.

Provide device and active-session window values in
`/etc/presensi-edge-agent/agent.env`:

```ini
PRESENSI_EDGE_DEVICE_ID=<registered-device-uuid>
PRESENSI_EDGE_SESSION_ID=<active-attendance-session-uuid>
PRESENSI_EDGE_SESSION_STARTS_AT=2026-10-01T08:00:00+07:00
PRESENSI_EDGE_SESSION_ENDS_AT=2026-10-01T10:00:00+07:00
```

Set the real schedule times for the lab; the gateway refuses to start with an
expired/not-yet-active configured window and stops sending frames at the end
time. The Core API still verifies the session is active for every final event.
Because a session discovery endpoint does not exist yet, update these values
before each practicum session. Protect the env file (`root:root`, mode `0600`)
and the token files (`root:presensi-edge`, mode `0440`).

**Central inference is not end-to-end operational yet:** the AI service currently
has no production provider for the session template gallery, and Core API has
no approved gallery endpoint/storage policy. Until that provider is implemented,
the AI service returns `session_gallery_unavailable`; this gateway can capture,
authenticate, retry, and forward decisions, but it cannot identify enrolled
students against production templates.

Install the checked-in unit and enable/start it:

```bash
sudo install -o root -g root -m 0644 /opt/presensi-edge-agent/apps/edge-agent/deploy/presensi-edge-agent.service /etc/systemd/system/presensi-edge-agent.service
sudo systemctl daemon-reload
sudo systemctl enable --now presensi-edge-agent.service
sudo systemctl status --no-pager presensi-edge-agent.service
sudo journalctl -u presensi-edge-agent.service -f
```

The service runs as an unprivileged `presensi-edge` user with `video` group
access. If the camera is not accessible, inspect `ls -l /dev/video*`, verify the
device uses the `video` group, and re-login/restart after group membership
changes. `v4l2-ctl --list-devices` and `v4l2-ctl --device=/dev/video0 --all` can
show the camera's actual supported modes. Check camera enumeration before
enabling the unit:

```bash
sudo -u presensi-edge /opt/presensi-edge-agent/.venv/bin/presensi-edge-agent --config /etc/presensi-edge-agent/stb-gateway.yaml cameras
```

The `status` subcommand is useful from a shell where the same device/session
environment variables are set; the running unit's health and errors are
available through `systemctl status` and `journalctl` above.

The checked-in service unit is at
[`deploy/presensi-edge-agent.service`](deploy/presensi-edge-agent.service).

### Benchmark CPU, memory, and temperature

Measure on the actual STB, with the intended camera mode and a representative
session. First collect a five-minute idle baseline, then collect at least
30 minutes while the gateway is sampling and the central service is reachable.
Record the board model, Armbian/kernel/OpenCV versions, camera mode, and ambient
conditions with the output. For process CPU and resident memory, get the systemd
PID and sample once per second (install `sysstat` above):

```bash
PID=$(systemctl show --property=MainPID --value presensi-edge-agent.service)
pidstat -u -r -p "$PID" 1 1800 | tee stb-gateway-pidstat.txt
```

Read current memory and available thermal sensors in a second terminal:

```bash
watch -n 2 'systemctl show presensi-edge-agent.service -p MemoryCurrent; for sensor in /sys/class/thermal/thermal_zone*/temp; do [ -r "$sensor" ] || continue; printf "%s " "$sensor"; awk "{printf \"%.1f C\\n\", \$1/1000}" "$sensor"; done'
```

Thermal sysfs values are commonly millidegrees Celsius; sensor availability and
units depend on the board/kernel. Compare idle and active CPU averages, peak
RSS/cgroup memory, and peak reported temperature. Also record central AI p50/p95
latency from its `/metrics` endpoint. No benchmark results are asserted by this
repository; establish acceptable limits for the selected board and camera, and
check for thermal throttling during the full run.

Native Python service for one lab PC and its UVC camera. It captures the camera
stream at the configured resolution/FPS, calls `recognition-core` on a sampled
stride, caches the active session gallery in memory, and sends only recognition
event fields to the FastAPI Core API. It also sends device heartbeats and keeps
an SQLite outbox so temporary API outages do not stop camera operation.

## AI_EDGE prerequisites

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
endpoint, so a protected token file needs manual rotation before expiry. The
agent rereads that file on each request; a value supplied only through an
environment variable requires a process restart to change.

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
The heartbeat reports deployment profile, edge-agent version, configured model
version when present, and current camera connectivity; central-inference gateway
model version is refreshed from recognition events. Registry health and timeout
semantics are described in [device registry architecture](../../docs/architecture/device-registry.md).
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
