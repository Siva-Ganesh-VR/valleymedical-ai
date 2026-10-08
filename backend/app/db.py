"""Database engine and session factory (SQLite for the POC; Postgres in production)."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


def build_engine(url: str) -> Engine:
    kwargs: dict = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url:
            kwargs["poolclass"] = StaticPool
        else:
            Path(url.replace("sqlite:///", "")).parent.mkdir(parents=True, exist_ok=True)
            # A real model call can take seconds while a request holds a write transaction, so
            # wait for the lock instead of failing at once, and let readers run beside a writer.
            kwargs["connect_args"]["timeout"] = 30
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite") and ":memory:" not in url:
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.close()
    return engine


def build_sessionmaker(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=True)
