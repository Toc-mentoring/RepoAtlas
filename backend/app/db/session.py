"""Create database engines without connecting during module import."""

import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url


def make_engine(database_url: str | None = None) -> Engine:
    url = database_url or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL must point to the RepoAtlas PostgreSQL database")
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    if make_url(url).drivername != "postgresql+psycopg":
        raise ValueError("DATABASE_URL must use postgresql+psycopg")
    return create_engine(url, pool_pre_ping=True)
