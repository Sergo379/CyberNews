from fastapi import APIRouter

from cybernews_runtime.application import create_application

from .api import admin, internal, public
from .config import settings

router = APIRouter()


@router.get("/", tags=["operations"])
def service_info():
    return {"service": settings.service_name, "status": "ok"}


app = create_application("Auth Service", settings, router, "/api/v1/auth")
app.include_router(public)
app.include_router(admin)
app.include_router(internal)
