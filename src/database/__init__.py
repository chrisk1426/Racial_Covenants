"""
Database engine and session factory.

Usage:
    from src.database import get_session, engine
    from src.database.models import Base

    # Create tables (run once)
    Base.metadata.create_all(engine)

    # Use a session
    with get_session() as session:
        books = session.query(Book).all()
"""

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.config import config

engine = create_engine(
    config.DATABASE_URL,
    # Keep connections alive between requests (important for FastAPI)
    pool_pre_ping=True,
    # Tune pool size based on expected concurrency (small team → small pool)
    pool_size=5,
    max_overflow=10,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Context manager that provides a database session and handles rollback on error."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Create all tables. Safe to call multiple times (CREATE TABLE IF NOT EXISTS)."""
    from src.database.models import Base  # noqa: F401 — import triggers model registration
    Base.metadata.create_all(engine)
