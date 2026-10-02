# Device registry and health

The Core API owns the device registry. `device_id` is the device UUID (`devices.id`)
used by agent configuration and recognition events. Each device is assigned to one
active laboratory and registered as either `AI_EDGE` (`edge_pc`) or `STB_GATEWAY`
(`camera_gateway`). The STB gateway uses central inference; this field records the
camera deployment profile, while the model version reported by the gateway may be
empty when inference versioning is owned by the AI service.

## Heartbeat contract

`POST /api/v1/devices/{device_id}/device-heartbeat` refreshes `last_seen_at` using
the API clock and requires a registered device credential. The optional body
reports the deployment profile, agent/app version, model version, camera state
(`unknown`, `online`, `offline`, or `error`), and aggregate `p50_ms`/`p95_ms`
latency. It contains no image, embedding, or frame-level data. A reported
deployment profile must match the registry; heartbeat cannot modify the device's
laboratory assignment. The human-admin route
`POST /api/v1/devices/{device_id}/heartbeat` remains available for authorized
manual health updates.

An administrator provisions or rotates a high-entropy device credential. The
API returns the raw secret once and stores only its SHA-256 verifier. Device
heartbeat renews an expiring credential when the edge agent uses a protected
token file; the previous verifier overlaps for 24 hours to allow safe file
replacement. The device can discover active sessions in its assigned lab and
fetch only that session's active roster/templates using the same credential.

`PRESENSI_DEVICE_HEARTBEAT_TIMEOUT_SECONDS` controls freshness, defaults to 60
seconds, and is clamped to 5–3,600 seconds. The same timeout is used for the registry
and live session dashboard. `DEVICE_ONLINE_THRESHOLD_SECONDS` remains a compatibility
fallback when the new variable is unset.

The API computes health at read time:

| Status | Rule |
| --- | --- |
| Offline | Device is inactive, has never checked in, or last heartbeat is older than the configured timeout. |
| Warning | Heartbeat is recent and device is active, but camera status is not `online`. |
| Online | Device is active, heartbeat is recent, and camera status is `online`. |

The registry page refreshes every 15 seconds and reads the active server profile
from the AI-readiness endpoint. The device form only offers the profile supported
by that server. In the single-PC AI_EDGE setup the page permits one active camera
device; AI_CENTRAL permits registering the STB gateways used by the labs. An
administrator can reassign a device, provision or rotate its credential, or
remove it from active use after a confirmation dialog.
The raw credential is shown only in the immediate one-time result panel, with
copy and download actions; closing the panel clears it from the page, and there
is no endpoint or UI to retrieve an existing raw token. The panel can also
download a one-time setup bundle containing the device UUID, deployment profile,
Core API origin, optional Central AI origin, model version, and raw credential.
That file is a secret: transfer it through a trusted channel, install it on only
that device, and delete it after setup. The installer uses the registry profile
to configure `AI_EDGE` local inference or `STB_GATEWAY` forwarding; it does not
decide or invent recognition thresholds. The dashboard command expects the
bundle in that host user's Downloads folder with the device-specific filename
shown in the UI. A remote host can be bootstrapped without a manual repository
clone after securely transferring the file. Installer prompts for camera index,
requested resolution, and FPS, checks the driver-returned mode, and writes the
selection to local YAML. It does not change advanced recognition or quality
policy. Rotations require an audit reason and retain the previous verifier for
the documented overlap window.
Initial assignment and every actual reassignment write `device.laboratory_assigned`
to `audit_logs`, with the actor and assigned laboratory UUIDs; reassignment records
both previous and new IDs. Reassigning to the current lab does not add a duplicate
audit row.

Removing a device is a soft deactivation, not a database cascade. It immediately
revokes current and previous device credentials, marks the camera offline, and
writes `device.deactivated` to `audit_logs`. Recognition and attendance history
remain linked to that device. The registry hides inactive devices by default;
the **Tampilkan perangkat nonaktif** filter exposes them for review or reactivation.
When reactivated, an administrator must provision a new device credential.

Installer defaults are auto-filled for local development: Core API
`http://127.0.0.1:8000`, and AI Central `http://127.0.0.1:8001` when the browser is
on localhost. For a remote host, the Core API defaults to the current web origin;
the administrator must provide the reachable AI Central HTTPS origin because it
cannot be inferred reliably from the web domain. The connection-mode selector is
shown for AI_CENTRAL/STB setup; AI_EDGE infers same-host versus private HTTPS from
the Core API URL. The enrollment model version is read-only and comes from Core
API configuration; a new model version is not selectable until it is provisioned
and approved across enrollment and inference.
