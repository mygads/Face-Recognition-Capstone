# API v1 contract and frontend client generation

The HTTP contract lives under /api/v1 and is described by FastAPI OpenAPI at /openapi.json. Pydantic v2 request and response models are the source of truth. Endpoint code must map domain/service results into response models; SQLAlchemy ORM objects are not returned directly.

## Route groups

| Router | Initial paths |
| --- | --- |
| Health | GET /api/v1/health |
| Auth | POST /api/v1/auth/login, GET /api/v1/auth/me |
| Students/classes | GET, POST /api/v1/students; GET, POST /api/v1/classes |
| Laboratories/devices | GET, POST /api/v1/laboratories; GET, POST /api/v1/devices |
| Schedules | GET, POST /api/v1/schedules |
| Sessions | GET, POST /api/v1/sessions; POST /api/v1/sessions/{session_id}/close |
| Enrollment/templates | GET /api/v1/enrollments/class-status; POST /api/v1/enrollments/captures; POST /api/v1/enrollments; GET /api/v1/face-templates |
| Attendance | GET /api/v1/attendance; POST /api/v1/attendance/corrections |
| Reports | GET /api/v1/reports/attendance |

Login and token validation are implemented. Enrollment roster status reads current template metadata. The multi-capture enrollment upload contract remains a HTTP 501 placeholder until biometric embedding persistence is approved and implemented. Other protected resource operations remain contract placeholders and return HTTP 501 after authorization succeeds; they do not return data. Their schemas define the proposed request/success shapes only. Template request/response schemas contain metadata only and have no image, blob, or embedding fields. `/health` remains a hidden-from-OpenAPI process-health alias for existing Docker health checks; `/api/v1/health` is the versioned health operation.

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
