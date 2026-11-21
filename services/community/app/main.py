from fastapi import APIRouter

from cybernews_runtime.application import create_application
from cybernews_runtime.service_client import ArticleReader, CommentAccess, IdentityClient

from .api import router as community_router
from .config import article_key, article_url, auth_key, auth_url, moderation_url, settings
from .moderation_api import internal

router = APIRouter()


@router.get("/", tags=["operations"])
def service_info():
    return {"service": settings.service_name, "status": "ok"}


def close():
    app.state.identity_client.close()
    app.state.article_reader.close()
    app.state.comment_access.close()


app = create_application("Community Service", settings, router, "/api/v1/community", shutdown=close)
app.state.identity_client = IdentityClient(auth_url, auth_key)
app.state.article_reader = ArticleReader(article_url, article_key)
app.state.comment_access = CommentAccess(moderation_url, auth_key)
app.include_router(community_router)
app.include_router(internal)
