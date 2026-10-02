# System guide and developer onboarding

This guide is the entry point for a developer joining the repository. It
explains the system boundary, shared components, request flow, deployment
profiles, data protections, and what still needs real-world validation. Feature
contracts and operations remain in the linked architecture/runbook documents.

## Product scope

The application manages practical-class attendance. Operators maintain students,
classes, laboratories, schedules, devices, and enrollment templates. A teacher
opens a runtime attendance session; the API snapshots that class roster. A
camera agent collects a short frame sequence and asks the recognition pipeline
to identify a student from that active session gallery. The Core API alone
decides whether an event creates PRESENT or LATE attendance.

The system supports two recognition profiles:

1. **AI_EDGE:** inference runs beside the camera on a lab PC. Ubuntu is the
   documented deployment target; Windows is for local development or supervised
   demos.
2. **STB_GATEWAY + AI_CENTRAL:** an ARM64 gateway sends short frame bursts to a
   central inference service.

Running all components on one computer is a development/demo topology using
either profile. It does not define a third recognition profile.

## Main components

| Component | Technology | Ownership |
| --- | --- | --- |
| Web app | Vue 3, Vite, TypeScript, Pinia, Vue Router, SCSS | Authenticated school UI; types and request contract come from FastAPI OpenAPI. |
| Core API | FastAPI, Pydantic, SQLAlchemy 2, Alembic | Human/device authentication, resource authorization, schedules/sessions, template registry, attendance decisions, reports, audit. |
| Database | PostgreSQL 16 | System of record for school master data, encrypted templates, events, attendance, and audit. |
| Recognition core | Installable Python package; protocols, domain objects, pipeline and temporal decision | Model-independent stages shared by edge and central inference. It has no FastAPI dependency. |
| Edge agent | Native Python process | UVC capture, sampling, local inference or gateway burst transport, heartbeat, session cache, durable event outbox. |
| Central AI service | FastAPI inference process | Device-authenticated frame burst handling, image decode limits, inference, in-memory active-session gallery, aggregate latency metrics. |
| Reverse proxy | Nginx in deployment guides | TLS termination/static Vue hosting, routes to Core API and optionally AI service, body/time limits, ingress restrictions. |

The root Docker Compose file is a **development** stack: PostgreSQL and Core
API by default; AI service is the central profile; web container is an optional
HMR profile. Production Compose files are under infra/deployment and are
separate. The edge agent and camera are native by default to avoid relying on
OS-specific USB/video-device passthrough.

## Recognition profiles and deployment shapes

The same logical architecture can run in three physical topologies:

| Shape | Recognition profile | Components on server | Components at the camera |
| --- | --- | --- | --- |
| VPS + lab edge PCs | AI_EDGE | PostgreSQL, Core API, Vue static build/reverse proxy | Native AI_EDGE edge-agent and YuNet/SFace on each Ubuntu PC |
| Central server + STB | AI_CENTRAL | PostgreSQL, Core API, Vue static build/reverse proxy, central AI service | Native STB_GATEWAY agent on each ARM64 camera gateway; no identity model on STB |
| Single PC | Usually AI_EDGE for the first demo; AI_CENTRAL can be tested when configured | The same local Compose server stack and web | Native edge-agent opens the same computer's UVC camera |

For a single-PC development run, Docker hosts Postgres and Core API; native Vite
provides hot reload; native edge-agent owns the webcam. The optional central
AI service can be added to Compose, but requires its model and calibrated
threshold configuration. The browser enrollment page also opens the webcam;
close that stream before starting the edge-agent if the camera driver grants
exclusive access.

~~~mermaid
flowchart LR
  Operator[ADMIN / TEACHER / LABORANT] --> Web[Vue SPA]
  Web --> API[FastAPI Core API]
  API --> DB[(PostgreSQL)]
  API -->|active session gallery for authorized device| Edge
  Camera[UVC camera] --> Edge[AI_EDGE agent]
  Edge --> RC[recognition-core]
  RC -->|candidate event with idempotency UUID| API
  Camera2[UVC camera] --> STB[STB_GATEWAY]
  STB -->|bounded JPEG burst on trusted path| AI[AI_CENTRAL service]
  AI --> RC
  AI -->|device/session scoped gallery| API
  STB -->|decision event| API
~~~

## Data flows

### Enrollment

1. ADMIN or LABORANT selects a class and existing student in the Vue enrollment
   page. The UI requests browser camera permission and captures multiple frames.
2. Frames travel to the enrollment endpoint in a bounded request. Core API runs
   the configured YuNet/SFace processor, rejects invalid, multiple-face, or
   poor-quality frames, and chooses the best accepted embeddings.
3. Raw captures are discarded after request processing. Embeddings are encrypted
   with AES-256-GCM before database storage; ordinary operator responses expose
   status/quality metadata, not image or vector data.
4. The API compares the new embedding with other active templates of the same
   model/version and may return a duplicate-lookalike warning. It does not merge
   people or enrollments.
5. Template revocation is audited and clears encrypted vector material. Old
   metadata-only rows are revoked by the encryption migration because they have
   no usable embedding; their students need enrollment again.

### Session and attendance

1. A teacher opens an eligible schedule. Core API makes an ACTIVE session and
   snapshots active class students into session_students in the same transaction.
2. A device fetches only its active session gallery after device credential,
   laboratory, session, and model/version checks. The edge gallery lives in
   memory and expires at the earliest of session end, grant expiry, or the
   configured offline freshness ceiling.
3. The selected profile runs multi-frame recognition and temporal agreement.
   Ambiguous identity or insufficient evidence produces NEED_FRONTAL_RETRY;
   it does not auto-accept.
4. Edge/STB sends allowlisted decision metadata with an event UUID. Images,
   embeddings, and credentials are excluded from the event queue and ordinary
   logs.
5. Core API stores recognition event evidence, validates that device/lab/session
   match and the candidate exists in the snapshot, applies grace-period and
   duplicate rules, then optionally creates one final attendance record.
   Recognition event data and final attendance are separate records.

~~~mermaid
sequenceDiagram
  participant Teacher
  participant Web as Vue
  participant API as Core API
  participant DB as PostgreSQL
  participant Device as Edge / STB
  participant AI as recognition-core / AI service
  Teacher->>Web: Open a scheduled session
  Web->>API: Open session
  API->>DB: Create session + roster snapshot
  Device->>API: Authenticated cache/discovery request
  API->>DB: Check device, lab, session, roster, active templates
  API-->>Device: Scoped gallery and session expiry
  Device->>AI: Sample frames or bounded burst
  AI-->>Device: Decision/candidate metadata only
  Device->>API: Recognition event with event_id
  API->>DB: Store evidence, validate, create final attendance if valid
  API-->>Web: WebSocket/dashboard update
~~~

## Domain and security boundary

- User roles start with ADMIN, TEACHER, and LABORANT. Human API routes check
  permission and applicable resource scope; UI route guards are not a substitute
  for API authorization.
- Device credentials are distinct from user JWTs. They identify one registered
  device and are stored as verifier hashes. Keep token files protected by OS ACLs.
- Face frames are transient by default. Encrypted embeddings are sensitive
  biometric data and need a school-approved key recovery/retention process.
- A decrypted active gallery is an explicit device-service response, not an
  operator API response. It is scoped to that device's assigned lab and active
  model/session.
- PostgreSQL and raw service ports must remain private. In deployment publish
  only the reverse-proxy entry points that are intentionally required.
- This engineering design does not certify legal compliance, recognition
  accuracy, fairness, or liveness effectiveness.

Read [security and privacy](../security-and-privacy.md),
[authentication/RBAC](authentication.md), and
[ADR-001](../adr/ADR-001-shared-recognition-core.md) before changing these
boundaries.

## Current model recommendation

The repository's initial integrated candidate is OpenCV Zoo **YuNet
2023mar + SFace 2021dec**, on the OpenCV 4 runtime currently used by the project.
It is a practical baseline to benchmark locally because the detector,
landmark alignment, normalized embedding, cosine matcher, and tests are already
integrated. This is not an accuracy claim or final production approval.

Do not set attendance thresholds from published numbers or total accuracy.
Collect a school-approved evaluation set under the target camera conditions;
report false match/accept and false non-match/reject over many Top-1 and margin
thresholds. Break down issues by lighting, pose, height/camera angle, glasses,
and other relevant conditions. Prioritize a low false-accept operating point
with a frontal/manual fallback. NIST documents that image quality and demographic
groups can affect false-positive/negative rates; see the cited model decision in
[model provenance and recommendation](../models.md).

## Implementation status and remaining work

| Area | Implemented | Still required |
| --- | --- | --- |
| Master data, class roster, schedule, session, imports, attendance decisions, device registry, reports | API/UI workflows and synthetic regression coverage exist. | Verify school-specific policy and perform field acceptance on the target environment. |
| Enrollment | Multi-frame flow, quality rejection, encrypted template storage, duplicate-lookalike warning, revoke/re-enroll. | Locally provision matching model assets and encryption keys; use authorized capture subjects. |
| AI_EDGE and AI_CENTRAL | Both consume recognition-core and feed the same Core API attendance authority. | Model/threshold calibration, camera/system performance, and reconnect acceptance on real devices. |
| Liveness | Optional recognition-core stage and service config paths exist. | A deployment-suitable asset/license and operational effectiveness have not been approved; sample config stays off. |
| Historic templates | Migration adds encrypted-template fields and revokes active rows without ciphertext. | Apply Alembic upgrade per existing database and re-enroll affected students. |
| Attendance corrections | Teacher requests are audited and remain pending. | Approval/rejection and evidence policy are not implemented. |
| Operations | Production Compose, deployment instructions, migration/backup/restore patterns exist. | School-managed domain/keys, reverse proxy/rate controls, backup drill, monitoring and field tests. |

Other protected endpoints may be contract placeholders that return 501. Check
[API contract status](api-contract.md) and [the final audit](../final-audit.md)
before planning an integration around one.

## Developer startup

1. Read this guide, [overview](overview.md), and the relevant ADR.
2. Install Docker, Python, Node/npm and Git for the host OS. Start the local
   stack with `py -3 scripts/start-local.py` on Windows or
   `python3 scripts/start-local.py` on Ubuntu. This command applies Alembic
   migrations, seeds roles, bootstraps the local administrator if needed,
   installs web dependencies, and starts Vite.
3. Sign in with `admin@local.test` / `123456789abcd`, then change the password
   at first sign-in. Add school records and staff accounts from the UI.
4. Run scripts/check.py and the synthetic scenario scripts/regression.py. These
   checks do not use face images or a webcam.
5. For manual camera work, provision models only for evaluation, register the
   device in **Perangkat**, download its one-time setup bundle, and use the
   matching installer in [edge-agent setup](../../apps/edge-agent/README.md).
   See the camera-calibration section and use only non-sensitive legal
   fixtures/adult volunteers with consent.

Host OS prerequisites are installed once. The local startup command does not
download model weights, choose a threshold, or publish ports/domains. Device
credentials are issued in the admin UI and transferred in a secret setup
bundle; production service setup and public networking stay in the deployment
runbooks.

## Repository map

| Path | What belongs there |
| --- | --- |
| apps/web | Vue UI, client generated from OpenAPI, route/store/layout |
| apps/api | HTTP schemas/routers, permissions, SQLAlchemy services and migration config |
| apps/edge-agent | Native UVC capture, AI_EDGE and STB_GATEWAY config and runtime |
| apps/ai-service | Central frame inference service |
| libs/recognition-core | Domain protocols, pipeline and model adapters |
| infra/deployment | Production Compose files and database bootstrap |
| infra/docker | Development/production service images |
| scripts | Local development, checks, regression workflow |
| docs/architecture | System contracts and feature decisions |
| docs/deployment | Environment and operator runbooks |
| docs/test-plans | Manual acceptance protocols |
| tests | CI, API/UI, synthetic regression, AI/deployment benchmarks |

## Further reading

- [Database schema](database-schema.md)
- [API contract and generated client](api-contract.md)
- [Enrollment](enrollment.md) and [attendance decisions](attendance-decisions.md)
- [Sessions](attendance-sessions.md), [devices](device-registry.md), [AI service](ai-service.md)
- [Deployment guides](../deployment/README.md)
- [Field test plan](../test-plans/walkthrough-field-test.md)
