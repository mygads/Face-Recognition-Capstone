# Authentication and authorization

## Authentication flow

The Core API uses FastAPI's OAuth2 password form (`application/x-www-form-urlencoded`) at `POST /api/v1/auth/login`. The `username` form field is the account email. Passwords are hashed with Argon2 through `pwdlib`; plaintext values are never persisted. Unknown accounts use a process-local dummy Argon2 hash so a login attempt still performs a password verification.

A successful login returns a signed HS256 bearer access token with `sub`, `iat`, `exp`, `jti`, `iss`, and `token_use=access` claims. The default lifetime is 15 minutes and the configured range is 5–60 minutes. There is no refresh token; the client must log in again after expiry. `GET /api/v1/auth/me` returns a Pydantic DTO for the authenticated user. Active account and roles are loaded from the database on each request, so deactivation and role changes take effect without waiting for token expiry.

The Vue client keeps the bearer token in Pinia memory only; it does not write tokens to local storage, session storage, URLs, or logs. Reloading the tab requires a new login. The shared OpenAPI client adds the bearer header to authenticated requests, converts API/network failures into a safe error type, and clears the session on an authenticated `401`. Route guards improve navigation UX but do not replace backend permission checks.

`JWT_SECRET` must be at least 32 bytes. It is excluded from Git. `scripts/dev.py` generates a random local key in the ignored `.env` file when blank; production/shared environments must supply a private secret through their secret manager. `.env.example` intentionally contains empty `JWT_SECRET` and `POSTGRES_PASSWORD` values; the task runner generates both before starting Compose.

Successful and failed password logins write `auth.login.succeeded` or `auth.login.failed` audit actions. Audit state records only authentication method/result; it excludes the submitted email, password, token, signing key, IP address, and biometric data. Invalid email/password, inactive account, and accounts without a supported role share the same outward login error.

## Baseline roles

| Role | Route permissions |
| --- | --- |
| `ADMIN` | All listed permissions: master data, accounts, settings, roster/laboratory/device, schedules/sessions, enrollment, attendance read/correction, reports. |
| `TEACHER` | Read class/laboratory catalogs and roster snapshots for operated sessions, manage schedules and sessions, read attendance and reports for owned schedules, request attendance corrections. No global student directory. |
| `LABORANT` | Read class/laboratory catalogs, operate devices/sessions, manage enrollment using the selected-class roster, read relevant attendance. No global student directory. |

Attendance report list, summary, and export endpoints constrain a teacher to schedules assigned to their account; `ADMIN` can read all schedules. Other roles cannot access reports.

Reusable `require_permissions(...)` dependencies enforce route-level policy. User roles are stored in `roles` and `user_roles`; a role not in the baseline enum gives no implicit permission. Settings permission is defined for future settings handlers; there is not yet a settings endpoint.

Several unrelated protected operations remain placeholders and return 501 after route authorization. Implemented handlers enforce resource scope: teachers may access or manage only their assigned classes/schedules and laborants only their relevant laboratory/devices/sessions/attendance. A teacher correction request is stored with `pending` status and an `attendance.correction.requested` audit event; it does not change the final attendance record. The school still needs to define who can approve or reject a request and what evidence is required before an approval workflow is implemented. Route permission alone is not a substitute for row-level authorization.

Enrollment and operator template metadata routes require `ADMIN` or `LABORANT`. Raw captures are processed in memory; embeddings are encrypted at rest and only returned in an active session gallery to the matching device credential. Operator routes never expose vectors or ciphertext. See the [biometric data boundary](database-schema.md#recognition-and-privacy-boundary). Device runtime routes authenticate a registered device credential separately from human JWTs.

## Local development bootstrap

Local development startup applies migrations, seeds roles, and creates
admin@local.test on an empty database. It generates a random one-time password
and forces password change before normal API access. The bootstrap command is
guarded by APP_ENV=development and is not called by production deployment.

The temporary access token is restricted to the password-change endpoint; the
REST API and attendance websocket deny access until the user signs in again.
This prevents the bootstrap credential from being used as an ordinary admin
password.

## Creating a first production account

After migration and role seed, create an account with a hidden interactive password prompt:

```sh
docker compose run --rm api python -m presensi_api.auth.create_user \
  --email admin@example.edu --full-name "School Administrator" --role ADMIN
```

The password is not a command-line argument and is never printed by this
production provisioner. It enforces a minimum of 12 characters and stores only
the Argon2 hash. Creating an account also writes a minimal account.created audit
event.

## Changing a password

Authenticated users can change their password at POST
/api/v1/auth/change-password or from the Profil page. The current password is
verified, the new password must contain at least 12 characters, and successful
changes invalidate all existing access tokens. The audit event excludes
password values. A bootstrap-only token remains restricted after password
change, so the user must sign in again to obtain a normal access token.

## Error behavior

Unauthenticated or expired tokens receive `401` with `WWW-Authenticate: Bearer`; valid users lacking a permission receive `403`. Both use the API's standard `ErrorEnvelope`. The signing secret is loaded only when an auth-protected operation executes, so process health checks do not depend on auth configuration.
