from fastapi import APIRouter

from cybernews_runtime.admin_client import AdminClient
from cybernews_runtime.application import create_application

from .api import router as rss_api
from .config import allowed_hosts, article_url, auth_key, auth_url, autostart, import_key, interval, max_bytes, settings
from .fetch import FeedFetcher
from .import_client import ArticleClient
from .scheduler import Scheduler

router = APIRouter()


@router.get("/", tags=["operations"])
def service_info():
    return {"service": settings.service_name, "status": "ok"}


def startup():
    app.state.scheduler.start()


def shutdown():
    app.state.scheduler.stop()
    app.state.article_client.close()
    app.state.admin_client.close()


app = create_application(
    "Collector Service", settings, router, "/api/v1/collector", startup=startup, shutdown=shutdown,
)
app.state.admin_client = AdminClient(auth_url, auth_key)
app.state.article_client = ArticleClient(article_url, import_key)
app.state.scheduler = Scheduler(
    app.state.database, FeedFetcher(allowed_hosts, max_bytes), app.state.article_client, interval, autostart == "true",
)
app.include_router(rss_api)
