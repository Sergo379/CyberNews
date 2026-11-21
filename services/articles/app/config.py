import logging

from cybernews_runtime.admin_client import service_url
from cybernews_runtime.config import load_settings
from cybernews_runtime.security import secret_setting

settings = load_settings("articles", "article_db", "article_svc")

try:
    auth_url = service_url("AUTH_SERVICE_URL", "http://auth:8000")
    auth_key = secret_setting("INTERNAL_AUTH_SECRET")
    import_key = secret_setting("ARTICLE_IMPORT_SECRET")
    if auth_key == import_key:
        raise ValueError("The import key must be distinct from the Auth service key")
except ValueError as exc:
    logging.getLogger("cybernews.config").error("%s", exc)
    raise SystemExit(1) from None
