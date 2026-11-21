from fastapi import APIRouter

from cybernews_runtime.application import create_application
from cybernews_runtime.service_client import ArticleReader, ServiceClient

from .api import admin, internal, reports, restrictions
from .auth_client import AuthClient
from .comment_commands import CommandWorker, router as comment_moderation
from .config import article_read_key, article_url, community_key, community_url, settings

router = APIRouter()


@router.get("/", tags=["operations"])
def service_info():
    return {"service": settings.service_name, "status": "ok"}


client = AuthClient()


def start():
    app.state.command_worker.start()


def close():
    app.state.command_worker.stop()
    app.state.community.close()
    app.state.article_reader.close()
    client.close()


app = create_application(
    "Moderation Service", settings, router, "/api/v1/moderation",
    dependency_check=client.ready, startup=start, shutdown=close,
)
app.state.auth_client = client
app.state.community = ServiceClient(community_url, community_key, timeout=9)
app.state.article_reader = ArticleReader(article_url, article_read_key)
app.state.command_worker = CommandWorker(app.state.database, app.state.community)
app.include_router(restrictions)
app.include_router(reports)
app.include_router(admin)
app.include_router(internal)
app.include_router(comment_moderation)
