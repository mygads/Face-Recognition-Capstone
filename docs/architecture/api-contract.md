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
| Enrollment/templates | POST /api/v1/enrollments; GET /api/v1/face-templates |
| Attendance | GET /api/v1/attendance; POST /api/v1/attendance/corrections |
| Reports | GET /api/v1/reports/attendance |

Login and token validation are implemented. Protected resource operations other than `/auth/me` remain contract placeholders and return HTTP 501 after authorization succeeds; they do not return data. Their schemas define the proposed request/success shapes only. Template request/response schemas contain metadata only and have no image, blob, or embedding fields. `/health` remains a hidden-from-OpenAPI process-health alias for existing Docker health checks; `/api/v1/health` is the versioned health operation.

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

FastAPI's OpenAPI document is the only source for frontend API response and request types. Do not hand-write duplicate API response interfaces across Vue components. Generate a shared client type surface, then use it through one frontend API module.

For example, after adding openapi-typescript as a web development dependency and starting the API:

~~~sh
npx openapi-typescript http://127.0.0.1:8000/openapi.json -o apps/web/src/api/generated/schema.d.ts
~~~

The frontend should import paths/components from that generated file, or generate an Orval client from the same OpenAPI URL. Generated files are tool output and must not be edited manually. Keep endpoint calls and common error parsing in a small apps/web/src/api client layer; Vue components should consume that client instead of defining transport types. A later frontend tooling task can pin the generator version and add an api:generate package script/CI drift check.

Additive, backward-compatible contract changes can stay in v1. Removing/renaming fields, changing field types, or changing resource semantics requires a new /api/v2 contract with an explicit migration/deprecation plan.
