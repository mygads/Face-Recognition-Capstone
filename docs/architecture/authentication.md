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
| `TEACHER` | Read roster/laboratories/schedules, manage schedules and sessions, read attendance, request attendance corrections. |
| `LABORANT` | Read roster/laboratories, operate devices/sessions, manage enrollment, read relevant attendance. |

Attendance report access is ADMIN-only until a narrower reporting scope is defined.

Reusable `require_permissions(...)` dependencies enforce route-level policy. User roles are stored in `roles` and `user_roles`; a role not in the baseline enum gives no implicit permission. Settings permission is defined for future settings handlers; there is not yet a settings endpoint.

Current business routers are still placeholders. Guard checks prove that a role may reach the route, after which the placeholder returns 501. Before any list/detail or mutation handler returns or changes data, it must also enforce resource scope: teachers may access or manage only their assigned classes/schedules, and laborants only their relevant laboratory/devices/sessions/attendance. Teacher correction policy (including any approval workflow) remains a domain rule to specify before implementing corrections. Route permission alone is not a substitute for row-level authorization.

Enrollment/template metadata routes require `ADMIN` or `LABORANT`, including while they return 501. The API contract accepts no image, blob, or embedding. See the [biometric data boundary](database-schema.md#recognition-and-privacy-boundary).

## Creating the first account

After migration and role seed, create an account with a hidden interactive password prompt:

```sh
docker compose run --rm api python -m presensi_api.auth.create_user \
  --email admin@example.edu --full-name "School Administrator" --role ADMIN
```

The password is not a command-line argument and is never printed. The provisioner enforces a minimum of 12 characters and stores only the Argon2 hash. Creating an account also writes a minimal `account.created` audit event.

## Error behavior

Unauthenticated or expired tokens receive `401` with `WWW-Authenticate: Bearer`; valid users lacking a permission receive `403`. Both use the API's standard `ErrorEnvelope`. The signing secret is loaded only when an auth-protected operation executes, so process health checks do not depend on auth configuration.
