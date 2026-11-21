import logging
import os
import re
from dataclasses import dataclass, field

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError


@dataclass(frozen=True)
class Settings:
    service_name: str
    log_level: str
    database_url: URL = field(repr=False)

    @classmethod
    def from_env(cls, default_name: str, default_db: str, default_user: str) -> "Settings":
        service_name = os.getenv("SERVICE_NAME", default_name)
        log_level = os.getenv("LOG_LEVEL", "INFO").upper()
        if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", service_name):
            raise ValueError("Invalid SERVICE_NAME")
        if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("Invalid LOG_LEVEL")

        database_url = os.getenv("DATABASE_URL")
        if database_url:
            try:
                url = make_url(database_url)
            except (ArgumentError, ValueError):
                raise ValueError("Invalid DATABASE_URL") from None
            if url.drivername != "postgresql+psycopg":
                raise ValueError("DATABASE_URL must use postgresql+psycopg")
        else:
            password = os.getenv("DB_PASSWORD")
            if not password:
                raise ValueError("DB_PASSWORD or DATABASE_URL is required")
            try:
                port = int(os.getenv("DB_PORT", "5432"))
            except ValueError:
                raise ValueError("Invalid DB_PORT") from None
            if not 1 <= port <= 65535:
                raise ValueError("Invalid DB_PORT")
            url = URL.create(
                "postgresql+psycopg",
                username=os.getenv("DB_USER", default_user),
                password=password,
                host=os.getenv("DB_HOST", "postgres"),
                port=port,
                database=os.getenv("DB_NAME", default_db),
            )

        if not all((url.username, url.password, url.host, url.database)):
            raise ValueError("Database host, name, username and password are required")
        return cls(service_name, log_level, url)


def load_settings(default_name: str, default_db: str, default_user: str) -> Settings:
    from .logs import configure_logging

    configure_logging(default_name, "INFO")
    try:
        settings = Settings.from_env(default_name, default_db, default_user)
    except ValueError as exc:
        logging.getLogger("cybernews.config").error("%s", exc)
        raise SystemExit(1) from None

    configure_logging(settings.service_name, settings.log_level)
    return settings
