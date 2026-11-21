import logging

from cybernews_runtime.admin_client import service_url
from cybernews_runtime.config import load_settings
from cybernews_runtime.security import secret_setting

settings = load_settings("community", "community_db", "community_svc")

try:
    auth_url = service_url("AUTH_SERVICE_URL", "http://auth:8000")
    article_url = service_url("ARTICLE_SERVICE_URL", "http://articles:8000")
    moderation_url = service_url("MODERATION_SERVICE_URL", "http://moderation:8000")
    auth_key = secret_setting("INTERNAL_AUTH_SECRET")
    article_key = secret_setting("ARTICLE_READ_SECRET")
    moderation_key = secret_setting("COMMUNITY_MODERATION_SECRET")
    if len({auth_key, article_key, moderation_key}) != 3:
        raise ValueError("Community service keys must be distinct")
except ValueError as exc:
    logging.getLogger("cybernews.config").error("%s", exc)
    raise SystemExit(1) from None
