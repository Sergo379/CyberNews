import logging
import os

from cybernews_runtime.admin_client import service_url
from cybernews_runtime.config import load_settings
from cybernews_runtime.security import secret_setting

settings = load_settings("collector", "collector_db", "collector_svc")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

DEFAULT_HOSTS = "feeds.feedburner.com,www.bleepingcomputer.com,bleepingcomputer.com,krebsonsecurity.com,www.krebsonsecurity.com"


def positive_int(name: str, default: int, lowest: int, highest: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        raise ValueError(f"Invalid {name}") from None
    if not lowest <= value <= highest:
        raise ValueError(f"Invalid {name}")
    return value


try:
    auth_url = service_url("AUTH_SERVICE_URL", "http://auth:8000")
    article_url = service_url("ARTICLE_SERVICE_URL", "http://articles:8000")
    auth_key = secret_setting("INTERNAL_AUTH_SECRET")
    import_key = secret_setting("ARTICLE_IMPORT_SECRET")
    if auth_key == import_key:
        raise ValueError("The import key must be distinct from the Auth service key")
    interval = positive_int("RSS_SYNC_INTERVAL_SECONDS", 1800, 60, 86400)
    max_bytes = positive_int("RSS_MAX_BYTES", 2_097_152, 1024, 8_388_608)
    allowed_hosts = frozenset(
        host.strip().rstrip(".").lower().encode("idna").decode("ascii")
        for host in os.getenv("RSS_ALLOWED_HOSTS", DEFAULT_HOSTS).split(",") if host.strip()
    )
    if not allowed_hosts:
        raise ValueError("RSS_ALLOWED_HOSTS is empty")
    autostart = os.getenv("RSS_AUTO_SYNC", "true").lower()
    if autostart not in {"true", "false"}:
        raise ValueError("RSS_AUTO_SYNC must be true or false")
except UnicodeError:
    logging.getLogger("cybernews.config").error("Invalid RSS_ALLOWED_HOSTS")
    raise SystemExit(1) from None
except ValueError as exc:
    logging.getLogger("cybernews.config").error("%s", exc)
    raise SystemExit(1) from None
