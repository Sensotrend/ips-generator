"""Alembic environment: URL from settings (or ``config.attributes['connection']`` in tests)."""

from __future__ import annotations

from alembic import context
from sqlalchemy import Connection

from app.config import get_settings
from app.db.models import Base
from app.db.session import make_engine

target_metadata = Base.metadata


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = context.config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    engine = make_engine(get_settings().database_url)
    with engine.connect() as conn:
        _run(conn)
    engine.dispose()


if context.is_offline_mode():
    raise SystemExit("offline migrations are not supported")
run_migrations_online()
