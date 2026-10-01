# Device registry and health

The Core API owns the device registry. `device_id` is the device UUID (`devices.id`)
used by agent configuration and recognition events. Each device is assigned to one
active laboratory and registered as either `AI_EDGE` (`edge_pc`) or `STB_GATEWAY`
(`camera_gateway`). The STB gateway uses central inference; this field records the
camera deployment profile, while the model version reported by the gateway may be
empty when inference versioning is owned by the AI service.

## Heartbeat contract

`POST /api/v1/devices/{device_id}/heartbeat` refreshes `last_seen_at` using the API
clock. The optional body reports the deployment profile, agent/app version, model
version, camera state (`unknown`, `online`, `offline`, or `error`), and aggregate
`p50_ms`/`p95_ms` latency. It contains no image, embedding, credential, or
frame-level data. A reported deployment profile must match the registry; heartbeat
cannot modify the device's laboratory assignment.

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
device or reassign its laboratory. Initial assignment and every actual reassignment
write `device.laboratory_assigned` to `audit_logs`, with the actor and assigned
laboratory UUIDs; reassignment records both previous and new IDs. Reassigning to the
current lab does not add a duplicate audit row.
