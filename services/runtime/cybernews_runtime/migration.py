import logging

from alembic import command, context
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .database import Database


def run_migrations(settings, metadata):
    engine = Database(settings.database_url).engine
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=metadata)
            with context.begin_transaction():
                connection.execute(text("SELECT pg_advisory_xact_lock(23062403)"))
                context.run_migrations()
    finally:
        engine.dispose()


def upgrade_schema():
    try:
        command.upgrade(Config("alembic.ini"), "head")
    except SQLAlchemyError as exc:
        logging.getLogger("cybernews.migration").error(
            "Database migration failed", extra={"error_type": type(exc).__name__},
        )
        raise SystemExit(1) from None
