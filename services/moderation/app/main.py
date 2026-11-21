from fastapi import APIRouter

from cybernews_runtime.application import create_application

from .api import admin, internal, reports, restrictions
from .auth_client import AuthClient
from .config import settings

router = APIRouter()


@router.get("/", tags=["operations"])
def service_info():
    return {"service": settings.service_name, "status": "ok"}


client = AuthClient()
app = create_application(
    "Moderation Service", settings, router, "/api/v1/moderation",
    dependency_check=client.ready, shutdown=client.close,
)
app.state.auth_client = client
app.include_router(restrictions)
app.include_router(reports)
app.include_router(admin)
app.include_router(internal)
