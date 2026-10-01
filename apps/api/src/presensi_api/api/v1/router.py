from fastapi import APIRouter

from presensi_api.api.v1.routers import (
    attendance,
    auth,
    enrollment_templates,
    health,
    laboratories_devices,
    reports,
    schedules,
    sessions,
    students_classes,
)

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(health.router)
api_v1_router.include_router(auth.router)
api_v1_router.include_router(students_classes.router)
api_v1_router.include_router(laboratories_devices.router)
api_v1_router.include_router(schedules.router)
api_v1_router.include_router(sessions.router)
api_v1_router.include_router(enrollment_templates.router)
api_v1_router.include_router(attendance.router)
api_v1_router.include_router(reports.router)
