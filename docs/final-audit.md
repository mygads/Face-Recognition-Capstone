# Final architecture and code audit

Audit date: 2026-10-02. Scope: current repository implementation and its
documented development/deployment paths. Synthetic test records were used; no
student images or production biometric data were accessed.

## Results

| Area | Result | Evidence |
| --- | --- | --- |
| Edge/Central business logic | **PASS** | `AI_EDGE` and `AI_CENTRAL` build adapters around `libs/recognition-core`; both use its detector/quality/liveness/embed/match/temporal decision stages. `apps/api/attendance_decision.py` is the single final attendance authority for device/session/roster/idempotency/grace-period checks. The gateway has capture/motion/transport code, not a second identity or attendance policy. See [ADR-001](adr/ADR-001-shared-recognition-core.md). |
| Reusable recognition core | **PASS** | `libs/recognition-core` is an installable Python package with domain objects, protocols, fake stages, and pipeline/temporal implementations. It has no FastAPI dependency; both edge and AI Central import the same package. Core unit tests pass. |
| Raw biometric data boundaries | **PASS** | Enrollment and AI frame inputs are bounded and processed transiently. Stored embeddings are AES-256-GCM ciphertext. Operator DTOs/logs omit images, embeddings, ciphertext, and credentials; decrypted gallery vectors are returned only to authenticated devices for active sessions in their assigned lab. Validation errors omit submitted values. Security/privacy and biometric tests pass. |
| Authentication and RBAC | **PASS** | Human access uses Argon2 password hashes and expiring signed JWTs; current active role assignments are loaded per request. Device credentials are separate high-entropy bearer values stored as hashes and scoped to device/lab/session. Teacher schedule/report/correction handlers check resource ownership. During this audit, global student directories and class-detail rosters were found accessible with the broader `ROSTER_READ` permission; those API routes and the UI page are now ADMIN-only. Regression tests cover teacher/laborant denial while class-catalog and enrollment workflows remain available. |
| Empty-database migrations | **PASS** | PostgreSQL 16 temporary database started empty; all nine Alembic revisions applied, role seed added three roles, and `alembic check` reported `No new upgrade operations detected`. No model/migration drift was found. |
| Automated tests and checks | **PASS** | `scripts/check.py`: Python lint/format/mypy, 224 pytest tests, frontend ESLint/Prettier/type checks, E2E TypeScript check, and 12 Vitest tests pass. Playwright E2E passes 10/10. The documented synthetic school-day regression command passes. |
| UI navigation and Gentelella use | **PASS** | Sidebar links resolve to implemented Vue Router pages and role guards; the denied page is used by the guard and is not a dead menu entry. The app uses Vue components and Gentelella styling/assets without its vanilla DOM-mutating dashboard scripts or a second frontend app. |
| Documentation accuracy | **PASS** | Corrected stale claims in `docs/architecture/overview.md` about template storage, gallery provisioning, session discovery, credential renewal, and unfinished attendance handlers. Master-data and privacy docs now state the ADMIN-only roster boundary and describe the enrollment roster exception. Remaining contract placeholders and manual deployment limits are documented. |
| README development setup | **PASS** | `docker compose config`, the documented `scripts/dev.py test` command, and fresh PostgreSQL migration/seed checks succeeded. Native web production build succeeded. The Compose API and PostgreSQL were started in an isolated temporary project/database, both API health paths responded, migration and seed succeeded, and the temporary project/volume were removed. |

## Defect fixed during audit

Student list/detail and class-detail responses contained student names and
school identifiers, but required only `ROSTER_READ`, granted to TEACHER and
LABORANT. The master-data page/menu also appeared to those roles. The API now
requires `MANAGE_MASTER_DATA` for those global identity/roster responses; the
page, sidebar link, and authenticated route are ADMIN-only. The basic class
catalog remains available for schedule creation and enrollment selection, and
LABORANT receives a selected class roster only through the enrollment endpoint.
Tests assert these boundaries.

The architecture overview also retained statements from before central gallery
discovery, encrypted embedding storage, and automatic credential renewal were
implemented. Those statements have been replaced with the current behavior and
remaining limitations.

## Verification commands

| Command | Result |
| --- | --- |
| `py -3 scripts/check.py` | PASS — Ruff lint/format, mypy, 224 pytest tests, ESLint, Prettier, Vue/Playwright TypeScript checks, and 12 Vitest tests. One non-failing Starlette deprecation warning recommends moving its test client from `httpx` to `httpx2`. |
| `npm --prefix apps/web run test:e2e` | PASS — 10 Playwright scenarios. Tests mock the API; Vite reports an expected refused proxy connection when no API is running. |
| `py -3 scripts/regression.py` | PASS — synthetic school-day regression scenario, including the documented import/enrollment/session/presence/late/roster/idempotency/correction/closed-session/export flow. |
| `py -3 scripts/dev.py test` | PASS — Compose config, web production build, API container tests, and AI-service container tests. |
| `docker compose config --quiet` | PASS. |
| Fresh PostgreSQL 16: `py -3 -m alembic upgrade head`; `py -3 -m presensi_api.db.seed_roles`; `py -3 -m alembic check` (run from `apps/api`) | PASS — nine migrations, three baseline roles, no drift. |
| `COMPOSE_PROJECT_NAME=presensi-final-audit py -3 scripts/dev.py dev-up` (temporary ports), health requests, container migration/seed, `py -3 scripts/dev.py dev-down` | PASS — PostgreSQL healthy; `/health` and `/api/v1/health` returned 200; isolated volume removed afterward. |
| `git diff --check` | PASS. |

## Residual risks and manual work

- **Hardware is not verified here.** Webcam selection/negotiated resolution, Armbian UVC compatibility, temperature, sustained CPU/RAM, network reconnect on target hardware, and the walk-through field protocol remain manual acceptance work.
- **Recognition quality is not calibrated.** Thresholds and false-accept/false-reject tradeoffs need a locally approved synthetic/consenting evaluation set and representative hardware. Do not treat model baseline values as production thresholds.
- **Liveness is disabled in example configuration.** The candidate model still needs deployment-license clearance and local effectiveness testing. Until approved, production needs a supervised/session-control fallback.
- **Offline AI_EDGE fails closed after process restart.** Gallery vectors are memory-only; the event outbox survives restart, but the agent needs Core API connectivity to reload the gallery. Queue events from an ended session remain auditable and cannot create final attendance.
- **Deployment controls remain required.** Production needs HTTPS/private network boundaries, proxy body and rate limits, protected device token files, managed biometric keys with tested recovery, encrypted device storage, and restricted metrics access. Device/enrollment rate limiting is process-local; the security guide requires shared ingress limits for multiple replicas. Login does not have an application-level rate limiter, so the production reverse proxy must enforce one.
- **Correction approval and some account/settings/attendance-list operations are not implemented.** Correction requests remain pending; documented contract placeholders return 501 after authorization. This is an implementation limit, not an unauthenticated data path.
- **School policy remains a prerequisite.** The school must approve purpose, notices/consent or other basis, retention, access, correction/appeal, manual fallback, and incident handling. This audit does not establish legal compliance or biometric accuracy.

These residuals are deployment/operational or explicitly documented workflow gaps;
no additional critical code defect was found in the audited paths.
