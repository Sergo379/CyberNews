import logging
import os
from urllib.parse import urlsplit

from cybernews_runtime.config import load_settings
from cybernews_runtime.security import secret_setting

settings = load_settings("moderation", "moderation_db", "moderation_svc")

try:
    internal_key = secret_setting("INTERNAL_AUTH_SECRET")
    auth_service_url = os.getenv("AUTH_SERVICE_URL", "http://auth:8000")
    address = urlsplit(auth_service_url)
    if (address.scheme not in {"http", "https"} or not address.hostname or
            address.username or address.password or address.path not in {"", "/"} or address.query or address.fragment):
        raise ValueError
except ValueError:
    logging.getLogger("cybernews.config").error("Invalid INTERNAL_AUTH_SECRET or AUTH_SERVICE_URL")
    raise SystemExit(1) from None
