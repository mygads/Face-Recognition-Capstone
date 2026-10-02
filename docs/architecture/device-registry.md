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

The registry page refreshes every 15 seconds and lets an administrator register a
device, reassign its laboratory, and provision or rotate its agent credential.
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
