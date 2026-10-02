from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def create_mysql_engine(database_url: str) -> AsyncEngine:
    """Create the small, long-lived MySQL connection pool used by one process."""
    return create_async_engine(
        database_url,
        hide_parameters=True,
        pool_size=5,
        max_overflow=5,
        pool_timeout=30,
        pool_recycle=1800,
        pool_pre_ping=True,
    )
