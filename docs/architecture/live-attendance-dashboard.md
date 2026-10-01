# Live attendance dashboard

The teacher dashboard loads active attendance sessions from the Core API and fetches
an initial summary with `GET /api/v1/sessions/{session_id}/dashboard`. It then opens
`WS /api/v1/sessions/{session_id}/updates`. The Vue view applies each `snapshot`
message to the current page state, so counts, recent activity, and device status update
without a page reload. The browser reconnects after a dropped connection and fetches
a fresh snapshot when a session is selected or manually refreshed.

## WebSocket protocol

The browser connects without credentials in the URL, then sends its access token as
the first JSON frame:

```json
{"type":"authenticate","access_token":"<short-lived access token>"}
```

After authentication, the server periodically sends:

```json
{"type":"snapshot","data":{"session_id":"...","summary":{},"devices":[],"recent_activity":[]}}
```

The first frame must arrive within five seconds. Invalid or missing authentication
closes with code `4401`; insufficient permission closes with `4403`; an inaccessible
session closes with `4404`. Session access follows the same scope as session
operations: teachers may view their own sessions, while ADMIN and LABORANT use their
existing global operational scope. The server rechecks account/session access while
streaming and closes the connection when the access token expires.

The initial implementation refreshes the database snapshot every two seconds per
connected dashboard. `SESSION_DASHBOARD_POLL_SECONDS` configures the interval and is
clamped to 0.25–30 seconds. `DEVICE_ONLINE_THRESHOLD_SECONDS` configures the online
window and is clamped to 5–3,600 seconds (default 60 seconds). These environment
variables tune freshness and database load; this baseline does not require a message
broker.

## Snapshot and device status

The summary reports roster size, `present`, `late`, and `not_present`. The latter is
the roster count minus present and late final records. Recent activity is limited to
ten recognition or attendance items, with student names from the session-time roster
snapshot. Device entries come from the laboratory assigned to the session schedule.
A device is online only when it is active and its `last_seen_at` is inside the online
window. A protected `POST /api/v1/devices/{device_id}/heartbeat` updates this time;
accepted recognition events also refresh it.

## Data protection

WebSocket messages contain dashboard display fields only: counts, device labels and
connectivity timestamps, and small recognition/attendance summaries. They never
include face images, image blobs, embeddings, or face-template metadata. Tokens are
sent only in the first WebSocket frame, never in query parameters or application
logs. The frontend does not log the token or event payloads.
