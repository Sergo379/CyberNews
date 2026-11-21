from fastapi import APIRouter

from cybernews_runtime.application import create_application

from .config import settings

router = APIRouter()


@router.get("/", tags=["operations"])
def service_info():
    return {"service": settings.service_name, "status": "ok"}


app = create_application("Notification Service", settings, router, "/api/v1/notifications")
