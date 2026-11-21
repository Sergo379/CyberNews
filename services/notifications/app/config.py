import logging

from cybernews_runtime.admin_client import service_url
from cybernews_runtime.broker import Broker
from cybernews_runtime.config import load_settings
from cybernews_runtime.security import secret_setting

settings = load_settings("notifications", "notification_db", "notification_svc")

try:
    auth_url = service_url("AUTH_SERVICE_URL", "http://auth:8000")
    article_url = service_url("ARTICLE_SERVICE_URL", "http://articles:8000")
    auth_key = secret_setting("INTERNAL_AUTH_SECRET")
    article_key = secret_setting("ARTICLE_READ_SECRET")
    if auth_key == article_key:
        raise ValueError("Auth and article read keys must be distinct")
    broker = Broker.from_env()
except ValueError as exc:
    logging.getLogger("cybernews.config").error("%s", exc)
    raise SystemExit(1) from None
