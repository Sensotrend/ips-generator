"""Alembic migrations create exactly the schema of the SQLAlchemy models."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext

from app.db.models import Base
from app.db.session import make_engine, sqlalchemy_url

BACKEND = Path(__file__).resolve().parents[2]


def test_migrations_match_models() -> None:
    engine = make_engine("sqlite://")
    config = Config(str(BACKEND / "alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert diff == []


def test_postgres_url_uses_psycopg3() -> None:
    assert sqlalchemy_url("postgresql://u:p@h:5433/db") == "postgresql+psycopg://u:p@h:5433/db"
    assert sqlalchemy_url("sqlite://") == "sqlite://"
