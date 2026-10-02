# AI_CENTRAL service contract

`apps/ai-service` is a central inference host, not a second business API. A
trusted STB/edge agent sends a chronological burst over the private lab LAN. The
service verifies the device UUID and bearer credential, applies request/rate
limits, decodes supported media in bounded memory, and invokes the shared
`libs/recognition-core` pipeline. It returns a track decision and limited
candidate metadata. The edge agent submits a recognition event to `apps/api`,
which validates session, device, roster, idempotency, and attendance policy.

```mermaid
sequenceDiagram
  participant Edge as Trusted edge device
  participant AI as Central AI service
  participant Core as recognition-core
  participant API as Core API
  Edge->>AI: Bearer token + device UUID + frame burst
  AI->>AI: Size/rate/auth checks; safe in-memory decode
  AI->>Core: Frames + cached active-session gallery
  Core-->>AI: Track decision and candidate metadata
  AI-->>Edge: Decision only; no frame or embedding
  Edge->>API: Idempotent recognition event
  API->>API: Session, roster, device, duplicate and grace checks
```

## Request and data controls

- The service forwards the per-device bearer token plus `X-Device-ID` to Core
  API. Core API verifies the registered credential before supplying a gallery.
  The AI service retains a hash of the validated token in memory for that
  session's bounded gallery lifetime, never the raw token in logs.
- Body bytes, frame bytes/count, decoded dimensions, and per-device request rate
  have configurable limits. Only JPEG, PNG, and WebP still images are accepted.
- Images are verified and decoded in memory. The service has no image disk path
  or raw-frame logging.
- Responses contain track state/outcome, accepted candidate UUID and confidence
  metadata, reason code, observation count, model version, and optional liveness
  score. Embeddings and image content are excluded.
- `/health` is a process health check. `/metrics` exposes a bounded in-memory
  request count and p50/p95 burst latency summary.

## Session cache lifecycle

`SessionGalleryCache` is memory-only and keyed by `(device_id, session_id)`. It
accepts only active snapshots with timezone-aware generated, expiry, and session
end times; expiry is capped by configured maximum age. It verifies model name,
version, and normalized vector metadata. Each device can invalidate its own
session snapshot when the session closes; expiration and process restart also
remove snapshots. Invalidation clears the corresponding temporal track state.

`CoreApiGalleryProvider` obtains the active gallery from the authenticated Core
API device runtime endpoint. Core API decrypts templates only for the selected
device/laboratory/session/model scope. A successful device/session validation
allows AI Central to continue using its already-loaded memory cache during a
Core API outage until the server expiry, session end, or configured maximum age.
The device token and gallery are not persisted; a process restart requires Core
API connectivity again. There is no public gallery upload route.

## Configuration and deployment

Model files are local provisioned YuNet/SFace assets; service startup never
downloads weights. The local setup command can explicitly download the pinned
files. If paths are configured but thresholds are blank, the service starts in
degraded mode without a recognition runner. Recognition thresholds must be
explicitly set from local evaluation before inference is enabled. The AI Compose
profile installs the inference dependencies and the shared recognition-core
package. For LAN access, bind the service to the central
server's lab-network interface and place it behind TLS or an equivalent trusted
transport boundary. Development Compose binds to loopback by default.

Liveness stays disabled by default. Enabling it requires an explicitly configured
local model and cutoff. Refer to [`models.md`](../models.md) for the current
licensing warning and ensure there is a supervised/session control when no
operationally cleared liveness model is deployed.
