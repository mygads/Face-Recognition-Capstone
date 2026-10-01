# API v1 contract and frontend client generation

The HTTP contract lives under /api/v1 and is described by FastAPI OpenAPI at /openapi.json. Pydantic v2 request and response models are the source of truth. Endpoint code must map domain/service results into response models; SQLAlchemy ORM objects are not returned directly.

## Route groups

| Router | Initial paths |
| --- | --- |
| Health | GET /api/v1/health |
| Auth | POST /api/v1/auth/login, GET /api/v1/auth/me |
| Students/classes | GET, POST /api/v1/students; GET, POST /api/v1/classes |
| Laboratories/devices | GET, POST /api/v1/laboratories; GET, POST, PATCH /api/v1/devices; device provision/rotate/renew, heartbeat, active-session discovery, and session gallery endpoints under /api/v1/devices/{device_id} |
| Schedules | GET, POST /api/v1/schedules |
| Sessions | GET, POST /api/v1/sessions; GET /api/v1/sessions/{session_id}/dashboard; POST /api/v1/sessions/{session_id}/close; WS /api/v1/sessions/{session_id}/updates |
| Enrollment/templates | GET /api/v1/enrollments/class-status; POST /api/v1/enrollments/captures; POST /api/v1/enrollments; GET /api/v1/face-templates |
| Attendance | GET /api/v1/attendance; POST /api/v1/attendance/corrections |
| Reports | GET /api/v1/reports/attendance, /attendance/records, /attendance/export |

Device registry supports create/list/update, assignment to an active laboratory, and heartbeat metadata updates. List responses compute `health_status` using the configured heartbeat timeout and the latest camera status. Heartbeats may report deployment profile (must match the registered profile), app/model versions, camera status, and aggregate p50/p95 latency; they cannot change laboratory assignment. A laboratory reassignment writes an audit log with the previous and new laboratory IDs. Device-specific credentials are provisioned/rotated by administrators and renewed by the authenticated device; the token is returned once and only its hash is stored. Active session discovery and session gallery retrieval are scoped to the device's laboratory. The multi-capture enrollment route processes and encrypts templates; operator template responses expose metadata only. Raw captures and embedding vectors are not returned to operator clients. Attendance report summary, paginated rows, and CSV/XLSX downloads are implemented with teacher schedule scoping; see [attendance reports](attendance-reports.md). Other protected resource operations remain contract placeholders and return HTTP 501 after authorization succeeds; they do not return data. Their schemas define the proposed request/success shapes only. `/health` remains a hidden-from-OpenAPI process-health alias for existing Docker health checks; `/api/v1/health` is the versioned health operation.

## Error body

Errors use one envelope regardless of whether they come from request validation, an HTTP exception, a contract placeholder, or an unexpected server error:

~~~json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed.",
    "details": [
      {
        "field": "body.student_number",
        "message": "String should have at least 1 character",
        "code": "string_too_short"
      }
    ]
  }
}
~~~

The details property is omitted when there are no field errors. Unexpected 500 responses contain only a generic public message; internal exception details are not part of the contract. OpenAPI declares the same ErrorEnvelope schema for each placeholder's standard error statuses.

## TypeScript client

FastAPI's OpenAPI document is the only source for frontend API request/response types. `apps/web` pins `openapi-typescript` for declarations and `openapi-fetch` for the typed fetch client. From `apps/web`, start the Core API and run:

~~~sh
npm run api:generate
~~~

This writes `src/api/generated/schema.d.ts` from `http://127.0.0.1:8000/openapi.json`. Generated files are tool output and must not be edited manually. Calls, bearer injection, and standard error parsing live in `src/api/client.ts`; Vue pages and stores consume that shared client rather than duplicating response interfaces. Regenerate after changing API schemas and commit the generated diff with the contract change.

Additive, backward-compatible contract changes can stay in v1. Removing/renaming fields, changing field types, or changing resource semantics requires a new /api/v2 contract with an explicit migration/deprecation plan.
