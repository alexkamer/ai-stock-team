"""SQLAlchemy engine/session setup.

DATABASE_URL is a plain os.environ.get with a sane local default - see
core/env.py for where it can come from (.env file or real shell env var).
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

import core.env  # noqa: F401 - loads .env before the os.environ.get() below

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./data/app.db")

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create tables that don't yet exist. Alembic owns real migrations;
    this is only a convenience for local/dev/test bootstrapping."""
    if DATABASE_URL.startswith("sqlite:///"):
        path = DATABASE_URL.removeprefix("sqlite:///")
        if path not in (":memory:", ""):
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    Base.metadata.create_all(bind=engine)
