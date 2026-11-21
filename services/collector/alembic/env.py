from alembic import context

from app.config import settings
from app.models import Base
from cybernews_runtime.migration import run_migrations

if context.is_offline_mode():
    context.configure(url="postgresql+psycopg://", target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    run_migrations(settings, Base.metadata)
