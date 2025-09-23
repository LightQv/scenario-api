"""
Database session management and configuration.

This module handles SQLAlchemy database engine creation, session management,
and provides dependency injection for FastAPI endpoints. It ensures proper
connection pooling and session lifecycle management.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator

from app.core.settings import settings

# Configure SQLAlchemy engine with connection pooling
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,  # Verify connections before use
    pool_size=10,  # Number of connections to maintain in pool
    max_overflow=20,  # Additional connections beyond pool_size
    echo=settings.DEBUG,  # Log SQL queries in debug mode
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_database_session() -> Generator[Session, None, None]:
    """
    Database session dependency for FastAPI endpoints.

    This function creates a database session and ensures it's properly closed
    after use. It uses Python's generator pattern to guarantee cleanup even
    if exceptions occur during request processing.

    The session is configured with autocommit=False and autoflush=False for
    explicit transaction control, which is recommended for web applications.

    Yields:
        Session: SQLAlchemy database session

    Example:
        >>> from fastapi import Depends
        >>> def my_endpoint(db: Session = Depends(get_database_session)):
        ...     user = db.query(User).first()
        ...     return user

    Note:
        This function is typically used as a FastAPI dependency injection
        and should not be called directly in application code.
    """
    database_session = SessionLocal()
    try:
        yield database_session
    finally:
        database_session.close()
