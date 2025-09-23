from typing import Generator, Optional
from fastapi import Depends, HTTPException, status, Cookie
from sqlalchemy.orm import Session

from app.database.session import get_database_session
from app.core.security import verify_token
from app.models import User


def get_database() -> Generator[Session, None, None]:
    """
    Database session dependency for FastAPI endpoints.

    Provides a database session that is automatically closed after use.

    Yields:
        Session: SQLAlchemy database session
    """
    yield from get_database_session()


def get_current_user(
    access_token: Optional[str] = Cookie(None, alias="access_token"),
    database_session: Session = Depends(get_database),
) -> User:
    """
    Dependency to get the currently authenticated user from cookie.

    Retrieves and validates the JWT token from the access_token cookie,
    then fetches the corresponding user from the database.

    Args:
        access_token: JWT token from the HTTP-only cookie
        database_session: Database session dependency

    Returns:
        User: The authenticated user object

    Raises:
        HTTPException: 403 if token is missing or invalid, or if user doesn't exist
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="Could not validate credentials"
    )

    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access token not found"
        )

    user_id = verify_token(access_token)
    if user_id is None:
        raise credentials_exception

    user = database_session.query(User).filter(User.id == user_id).first()
    if user is None:
        raise credentials_exception

    return user


def get_current_user_id(current_user: User = Depends(get_current_user)) -> str:
    """
    Dependency to get only the ID of the currently authenticated user.

    Convenience dependency that extracts just the user ID from the
    authenticated user object.

    Args:
        current_user: The authenticated user from get_current_user dependency

    Returns:
        str: The user ID as a string
    """
    return str(current_user.id)
