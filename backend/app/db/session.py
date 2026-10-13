"""Engine and session factory."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

__all__ = ["make_engine", "make_session_factory", "sqlalchemy_url"]


def sqlalchemy_url(database_url: str) -> str:
    """``postgresql://`` (as in ``.env``) -> ``postgresql+psycopg://`` (psycopg 3 driver)."""
    for prefix in ("postgresql://", "postgres://"):
        if database_url.startswith(prefix):
            return "postgresql+psycopg://" + database_url.removeprefix(prefix)
    return database_url


def make_engine(database_url: str) -> Engine:
    url = sqlalchemy_url(database_url)
    if url.startswith("sqlite"):
        from sqlalchemy.pool import StaticPool

        engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_connection, _record):  # type: ignore[no-untyped-def]
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

        return engine
    return create_engine(url, pool_pre_ping=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)
