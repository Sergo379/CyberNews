import logging
import os

from cybernews_runtime.config import load_settings
from cybernews_runtime.security import secret_setting

settings = load_settings("auth", "auth_db", "auth_svc")


def duration(name: str, default: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        raise ValueError(f"Invalid {name}") from None
    if not 1 <= value <= maximum:
        raise ValueError(f"{name} must be between 1 and {maximum} seconds")
    return value


try:
    jwt_secret = secret_setting("JWT_SECRET")
    internal_key = secret_setting("INTERNAL_AUTH_SECRET")
    if jwt_secret == internal_key:
        raise ValueError("JWT_SECRET and INTERNAL_AUTH_SECRET must be distinct")
    access_ttl = duration("ACCESS_TOKEN_TTL_SECONDS", 900, 1800)
    admin_ttl = duration("ADMIN_SESSION_TTL_SECONDS", 900, 900)
except ValueError as exc:
    logging.getLogger("cybernews.config").error("%s", exc)
    raise SystemExit(1) from None
