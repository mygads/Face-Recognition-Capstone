# Authentication and authorization

## Authentication flow

The Core API uses FastAPI's OAuth2 password form (`application/x-www-form-urlencoded`) at `POST /api/v1/auth/login`. The `username` form field is the account email. Browser login includes the `X-Presensi-Session: browser` header to request an HttpOnly session cookie; non-browser OAuth bearer clients can omit it and receive no cookie session. Passwords are hashed with Argon2 through `pwdlib`; plaintext values are never persisted. Unknown accounts use a process-local dummy Argon2 hash so a login attempt still performs a password verification.

A successful login returns a signed HS256 bearer access token with `sub`, `iat`, `exp`, `jti`, `iss`, and `token_use=access` claims. Its default lifetime remains 15 minutes (configurable from 5–60 minutes). The same response sets an opaque-to-JavaScript, HttpOnly `presensi_session` cookie with a signed session identifier. The session has an absolute 24-hour lifetime by default, is stored server-side in `auth_sessions`, and is revoked on logout or password change. The access token is renewed through `POST /api/v1/auth/refresh`; the cookie is not returned in JSON. `GET /api/v1/auth/me` returns a Pydantic DTO for the authenticated user. Active account and roles are loaded from the database on each request, so deactivation and role changes take effect without waiting for token expiry.

The Vue client keeps the short-lived bearer token in Pinia memory only; it does not write tokens to local storage, session storage, URLs, or logs. On a reload, it silently exchanges the HttpOnly session cookie for a new access token, so navigation and refresh do not prompt for a password during the 24-hour session. The session cookie is `SameSite=Lax`, host-only, scoped to `/api/v1/auth`, and `Secure` outside development/test. Refresh and logout require a custom browser header, and configured CORS origins are exact and credentialed. The shared OpenAPI client adds the bearer header to authenticated requests, converts API/network failures into a safe error type, and clears local access state on an authenticated `401`. Route guards improve navigation UX but do not replace backend permission checks.

`JWT_SECRET` must be at least 32 bytes. It is excluded from Git. `JWT_ACCESS_TOKEN_TTL_MINUTES` defaults to 15 (5–60); `JWT_SESSION_TTL_HOURS` defaults to 24 (1–168); and `JWT_SESSION_COOKIE_SECURE` defaults to false only in development/test and true elsewhere. `scripts/dev.py` generates a random local key in the ignored `.env` file when blank; production/shared environments must supply a private secret through their secret manager. `.env.example` intentionally contains empty `JWT_SECRET` and `POSTGRES_PASSWORD` values; the task runner generates both before starting Compose.

Successful and failed password logins write `auth.login.succeeded` or `auth.login.failed` audit actions. Audit state records only authentication method/result; it excludes the submitted email, password, token, signing key, IP address, and biometric data. Invalid email/password, inactive account, and accounts without a supported role share the same outward login error.

## Baseline roles

| Role | Route permissions |
| --- | --- |
| `ADMIN` | All listed permissions: master data, accounts, settings, roster/laboratory/device, schedules/sessions, enrollment, attendance read/correction, reports. |
| `TEACHER` | Read class/laboratory catalogs and roster snapshots for operated sessions, manage schedules and sessions, read attendance and reports for owned schedules, request attendance corrections. No global student directory. |
| `LABORANT` | Read class/laboratory catalogs, operate devices/sessions, manage enrollment using the selected-class roster, read relevant attendance. No global student directory. |

Attendance report list, summary, and export endpoints constrain a teacher to schedules assigned to their account; `ADMIN` can read all schedules. Other roles cannot access reports.

Reusable `require_permissions(...)` dependencies enforce route-level policy. User roles are stored in `roles` and `user_roles`; a role not in the baseline enum gives no implicit permission. Runtime configuration endpoints under `/api/v1/admin/settings` require `MANAGE_SETTINGS`, which only `ADMIN` receives. They publish validated enrollment, AI Central, or device-profile configuration revisions and write a `runtime_configuration.published` audit event. Device runtime pull/status routes require that device's own credential and cannot be called with a human JWT.

Several unrelated protected operations remain placeholders and return 501 after route authorization. Implemented handlers enforce resource scope: teachers may access or manage only their assigned classes/schedules and laborants only their relevant laboratory/devices/sessions/attendance. A teacher correction request is stored with `pending` status and an `attendance.correction.requested` audit event; it does not change the final attendance record. The school still needs to define who can approve or reject a request and what evidence is required before an approval workflow is implemented. Route permission alone is not a substitute for row-level authorization.

Enrollment and operator template metadata routes require `ADMIN` or `LABORANT`. Raw captures are processed in memory; embeddings are encrypted at rest and only returned in an active session gallery to the matching device credential. Operator routes never expose vectors or ciphertext. See the [biometric data boundary](database-schema.md#recognition-and-privacy-boundary). Device runtime routes authenticate a registered device credential separately from human JWTs.

## Local development bootstrap

Local development startup applies migrations, seeds roles, and creates
admin@local.test on an empty database. Its local-only initial password is
`123456789abcd`; the account must change it before normal API access. This
fixed development credential is intentionally limited to `APP_ENV=development`
and is not called by production deployment. Do not expose a development stack
before changing it.

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

After the first production administrator is provisioned, that administrator
can create TEACHER and LABORANT accounts from the **Kelola akun staf** page. The
API generates a random temporary password and returns it only in the successful
create response to an administrator. It is not logged or saved as plaintext;
the new user must change it before accessing normal application routes.

## Changing a password

Authenticated users can change their password at POST
/api/v1/auth/change-password or from the Profil page. The current password is
verified, the new password must contain at least 12 characters, and successful
changes invalidate all existing access tokens and revoke all browser sessions.
The audit event excludes password values. A bootstrap-only token remains
restricted after password change, so the user must sign in again to obtain a
normal access token.

## Error behavior

Unauthenticated or expired tokens receive `401` with `WWW-Authenticate: Bearer`; valid users lacking a permission receive `403`. Both use the API's standard `ErrorEnvelope`. The signing secret is loaded only when an auth-protected operation executes, so process health checks do not depend on auth configuration.
