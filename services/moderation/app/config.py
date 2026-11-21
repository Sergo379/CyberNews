import logging
import os
from urllib.parse import urlsplit

from cybernews_runtime.admin_client import service_url
from cybernews_runtime.config import load_settings
from cybernews_runtime.security import secret_setting

settings = load_settings("moderation", "moderation_db", "moderation_svc")

try:
    internal_key = secret_setting("INTERNAL_AUTH_SECRET")
    article_read_key = secret_setting("ARTICLE_READ_SECRET")
    community_key = secret_setting("COMMUNITY_MODERATION_SECRET")
    article_url = service_url("ARTICLE_SERVICE_URL", "http://articles:8000")
    community_url = service_url("COMMUNITY_SERVICE_URL", "http://community:8000")
    if len({internal_key, article_read_key, community_key}) != 3:
        raise ValueError
    auth_service_url = os.getenv("AUTH_SERVICE_URL", "http://auth:8000")
    address = urlsplit(auth_service_url)
    if (address.scheme not in {"http", "https"} or not address.hostname or
            address.username or address.password or address.path not in {"", "/"} or address.query or address.fragment):
        raise ValueError
except ValueError:
    logging.getLogger("cybernews.config").error("Invalid Moderation service addresses or credentials")
    raise SystemExit(1) from None
