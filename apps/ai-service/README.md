# Central AI Service

FastAPI inference process for profile `AI_CENTRAL`. It receives short frame
bursts from authenticated edge devices, decodes images in memory, runs the shared
`libs/recognition-core` pipeline, and returns recognition decision metadata. The
Core API remains the authority for session/device/roster rules and final
attendance.

## Development setup

From the repository root:

```bash
python -m pip install -r requirements-dev.txt
python -m uvicorn presensi_ai_service.main:app --reload --port 8001
```

Or start it with the central profile in Compose:

```bash
python scripts/dev.py dev-up --central
```

The Compose binding defaults to loopback. For an authorized LAN test, set
`AI_SERVICE_BIND_ADDRESS` to the central host's lab-network address and configure
the matching firewall rule. Use TLS or a trusted TLS-terminating proxy in a
shared environment; the local Compose profile is for development.

## Device authentication and request limits

Recognition requires both `X-Device-ID` and an `Authorization: Bearer <token>`
header. `PRESENSI_AI_DEVICE_TOKENS` is a JSON object mapping device UUIDs to
random URL-safe tokens of at least 32 characters. Keep it in the ignored local
`.env` or a deployment secret store. Tokens are compared in constant time and
are never logged. Unknown devices and invalid tokens receive the same 401 error.

`POST /api/v1/recognition/sessions/{session_id}/bursts` accepts 1–5 chronological
frames with JPEG, PNG, or WebP media type. Request and per-frame encoded sizes,
decoded pixel dimensions, and device request rate are bounded. Pillow verifies
the image stream and size before decoding; frames are held only in memory and
never written to disk. Animated images and mismatched/corrupt media are rejected.
Errors use an `{ "error": { "code", "message" } }` envelope. Validation errors
do not echo the rejected image payload.

Responses contain the track decision, an accepted candidate UUID plus confidence
and margin when available, reason code, observation count, model version, and
optional liveness score. They never contain raw frames or embeddings. The service
does not create attendance records; the edge device forwards an event to
`apps/api` for final policy validation.

## Model configuration

Install the shared package and inference dependencies (already included by
`requirements-dev.txt` and the central Compose profile):

```bash
python -m pip install -e "libs/recognition-core[opencv]"
python -m pip install -e "apps/ai-service[inference]"
```

Provision YuNet and SFace weights locally and set:

```text
PRESENSI_AI_YUNET_MODEL_PATH=/models/face_detection_yunet_2023mar.onnx
PRESENSI_AI_SFACE_MODEL_PATH=/models/face_recognition_sface_2021dec.onnx
PRESENSI_AI_MODEL_VERSION=school-provisioned-version
PRESENSI_AI_MIN_TOP1_SIMILARITY=<locally calibrated value>
PRESENSI_AI_MIN_TOP1_TOP2_MARGIN=<locally calibrated value>
```

The service does not download pretrained models at startup. Both model files,
model version, and calibrated thresholds are required before it builds the
recognizer. Thresholds have no preset acceptance values. Model provenance and
deployment license notes are in [`docs/models.md`](../../docs/models.md).
Compose mounts the ignored local `models/weights` folder read-only at `/models`;
for a native run, set model paths to files on the host instead.

Liveness is disabled unless explicitly configured. Enabling it requires a local
model path, version, and calibrated score. The `anti-spoof-mn3` candidate noted
in `docs/models.md` is not cleared for operational attendance until its dataset
and weight licensing are reviewed; do not use it as an automatic production
default. Apply supervised session/physical controls while no cleared liveness
model is configured.

## Session gallery cache

The service keeps active session roster templates in `SessionGalleryCache`, in
memory only. Snapshots are scoped by device and session, must match the running
model version, and expire at the earliest of server expiry, session end, or the
configured maximum cache age. `DELETE /api/v1/recognition/sessions/{session_id}/cache`
lets the authenticated device invalidate its local snapshot and temporal track
state when a session closes. Expiry also removes cached data; process restart
clears all cache entries.

The production `CoreApiGalleryProvider` validates the device credential, fetches
the active device-scoped session gallery, and adapts its normalized vectors into
the shared recognition-core domain. Core API encrypts vectors at rest and
releases them only for the active session/model version. AI Central does not
write raw frames or persist templates; the cache is memory-only and expires at
the server-provided age/session deadline. A validated device/session credential
can continue against the already-loaded gallery during a Core API outage until
that same bounded deadline. A restart clears both gallery and validation state,
so the service fails closed until Core API becomes reachable.

Do not add a public gallery-upload route. Provision the device credential
through the Core API and configure its protected token file on the edge agent.

## Health and metrics

- `GET /health` reports process health.
- `GET /metrics` returns in-memory recognition request/error/timeout counters and
  p50/p95 end-to-end burst latency in milliseconds. The sample window is bounded
  and contains no device, student, image, or embedding labels.

Metrics reset when the process restarts. They are operational indicators, not a
substitute for the offline evaluation harness or a hardware throughput test.

## Verification

```bash
python -m pytest apps/ai-service/tests -q
python -m ruff check apps/ai-service libs/recognition-core apps/edge-agent
python -m mypy
```

The request tests use a generated synthetic image and fake recognition-core
stages. Hardware/model and trusted-LAN integration still require local testing.
