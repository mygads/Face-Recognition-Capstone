# Security and privacy controls

This document describes implemented controls and deployment requirements for a
school attendance system that processes student biometric data. It is an
engineering control record, not a claim of legal compliance. The school must
approve the purpose, notices, consent/other lawful basis, access policy, retention
period, student/guardian rights, and incident process before using real student
data.

## Data boundaries

| Data | Storage and transfer |
| --- | --- |
| Enrollment captures and AI frames | Processed in memory. The Core API bounds the request body, configures multipart spooling above that bound to avoid temporary-file rollover, and discards captures after processing. AI Central decodes frames in bounded memory. No endpoint writes raw frames to disk. |
| Face embeddings | AES-256-GCM ciphertext in `face_templates`; key material comes from `PRESENSI_FACE_TEMPLATE_KEYS` and the active key ID from `PRESENSI_FACE_TEMPLATE_ACTIVE_KEY_ID`. Revocation and student deactivation erase ciphertext and key metadata. |
| Ordinary operator response | Pydantic DTOs contain status, model metadata, quality metadata, and duplicate warning; they never contain vectors or ciphertext. Recognition response and logs likewise omit embeddings and frame bytes. |
| Device gallery response | Decrypted normalized vectors are returned only to an active, credential-authenticated device assigned to the session laboratory. This is a service boundary, not an operator endpoint. Use TLS between the device, AI service, and Core API in deployed networks. |
| Offline edge queue | Stores idempotent recognition event metadata, not camera frames or embeddings. Device-local storage must be access-controlled and encrypted by the operating system/disk policy. |
| Debug artifacts | No debug-image/artifact writer or debug-image mode is implemented. Do not add one enabled by default. The ignored `debug-artifacts/` path is reserved for future, explicitly development-only artifacts; any future writer must enforce a configurable TTL and deletion job before use. |

All model and event metadata is treated as sensitive student-linked data. No real
student or minor face data belongs in Git, tests, CI, screenshots, or benchmark
fixtures.

## Access control and audit

- `ADMIN` and `LABORANT` may use enrollment and view template metadata. `TEACHER`
  and other roles are denied. Teacher UI never receives template values.
- Device runtime endpoints require a registered device UUID and high-entropy
  bearer credential. Credential verifiers are stored as SHA-256 hashes; a secret
  is returned once on provisioning/rotation, has an expiry, and renewal is
  audited. A human JWT cannot act as a device credential.
- Gallery retrieval is scoped to active sessions in that device's assigned
  laboratory and to the requested model/version. Recognition event submission
  reuses the Core API attendance validation and idempotency rules.
- Enrollment, template revocation, student deactivation, and class membership
  removal write audit events. Student deactivation also revokes active templates
  and clears their encrypted vectors. Audit event state stores counts/IDs needed
  for accountability, never images, vectors, tokens, or secrets.
- Key rotation is performed with
  `python -m presensi_api.biometric_key_rotation`; keep old keys available until
  all active rows have been rotated and verified. Store production keys in a
  managed secret store and restrict access to the API workload.

## Request protections

- `PRESENSI_API_MAX_REQUEST_BYTES` defaults to 16 MiB and is bounded by API
  configuration. Multipart parser spooling is configured to that same ceiling,
  so accepted request files stay in memory rather than rolling over to temporary
  disk files. Per-capture and aggregate enrollment limits remain in force.
- `PRESENSI_DEVICE_API_REQUESTS_PER_MINUTE` defaults to 120 per authenticated
  device. `PRESENSI_ENROLLMENT_REQUESTS_PER_MINUTE` defaults to 10 per authorized
  operator. AI Central also has per-device burst limiting. Core API limits are
  process-local; deployments with multiple API replicas must enforce a shared
  rate limit at the trusted ingress/reverse proxy as well.
- The API does not enable wildcard CORS. `PRESENSI_CORS_ALLOWED_ORIGINS` accepts
  exact origins only; remote origins must use HTTPS. Leave it empty when the web
  app uses the same-origin Vite proxy. Credentials/cookies are not enabled for
  CORS.
- Secrets are supplied through environment variables for local development and
  a secret manager for production. `.env` is ignored by Git; `.env.example`
  contains no actual secrets. Do not pass secrets as command-line arguments or
  include them in support logs.

## Retention and deletion

`PRESENSI_RECOGNITION_EVENT_RETENTION_DAYS` defaults to 90 days and accepts 1 to
3,650 days. Schedule this command to run daily, after database migrations:

```sh
docker compose run --rm api python -m presensi_api.retention
```

Expired recognition events without a final attendance record are deleted.
Expired events referenced by an attendance record are redacted instead: the
student candidate, confidence, similarity, margin, liveness/quality metadata,
and idempotency fingerprint are removed; the event becomes `redacted`. The event
UUID and minimum session/device/time/model linkage remain so the final attendance
record's foreign key and audit trail remain valid. Attendance records and audit
logs have separate school-defined retention requirements and are not deleted by
this job. Record the approved period in the school's retention schedule and
adjust the environment setting accordingly.

There are currently no debug image artifacts to expire. If that changes, do not
store them for production use; require an explicit development-only switch, a
configured short retention window, automatic cleanup, and a test proving cleanup
before enabling the feature.

The retention sweep writes an audit record containing only the configured age
and deleted/redacted counts. It does not log individual student IDs or event
payloads.

## HTTPS and reverse proxy deployment

Docker Compose is for development and binds the API to loopback. In production:

1. Terminate HTTPS at a maintained reverse proxy or ingress; use modern TLS
   settings and enable HSTS there. Do not publish the API or AI service directly
   to the public Internet.
2. Use TLS for edge-to-AI and AI-to-Core API traffic, including the device bearer
   credential and gallery vectors. Prefer mutual TLS or a private authenticated
   network in addition to application credentials.
3. Allow only the proxy/ingress to reach the application ports. Configure its
   host allowlist, body-size cap, request-rate limits, and trusted forwarded
   headers. Do not trust `X-Forwarded-*` headers from arbitrary clients.
4. Configure the exact HTTPS web origins in `PRESENSI_CORS_ALLOWED_ORIGINS`.
   CORS is a browser policy, not an authentication or network firewall.
5. Disable request-body/header logging at the proxy, API gateway, and observability
   stack. Redact `Authorization`, cookies, upload bodies, base64 image data, and
   query/header values that may contain credentials. Keep application logs at
   metadata level only.
   Restrict the AI service `/metrics` route to the trusted operations network;
   it reports aggregate host/process utilization. Keep
   `PRESENSI_AI_BENCHMARK_TIMING_ENABLED=false` except during a controlled
   benchmark, then disable it and restart the service.
6. Keep PostgreSQL private, encrypted at rest, backed up under the same access
   policy, and test encrypted-template key recovery before production.

## School policy and operational review

Before a live pilot, the school must document and approve who may enroll/revoke,
how identity is confirmed, notice and consent or another valid basis for minors,
manual attendance fallback, correction/appeal handling, retention for attendance
and audit records, access reviews, and incident response. A revoked/deactivated
template may remain in an already-issued device or AI in-memory cache until that
cache expires; the current gallery/session cache is capped by its configured
maximum age and session end. Production operators should configure a short
maximum age appropriate to the session and treat device/cache revocation as a
separate operational control.

This repository's tests use synthetic records and do not establish biometric
accuracy, liveness effectiveness, security certification, or legal compliance.
