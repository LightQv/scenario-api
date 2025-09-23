from datetime import datetime, timedelta
from typing import Any, Union, Optional
import jwt
import bcrypt
import uuid

from app.core.exceptions.custom_exception import CustomExceptionError
from app.core.settings import settings
from app.services.constant.response_constant import (
    EXPIRED_TOKEN_ERROR,
    INVALID_TOKEN_ERROR,
)


def create_access_token(
    subject: Union[str, Any], expires_delta: Optional[timedelta] = None
) -> str:
    """
    Create a JWT access token for user authentication.

    Generates a JSON Web Token (JWT) with the specified subject (usually user ID)
    and expiration time. The token is signed with the application's secret key.

    Args:
        subject: The subject of the token (typically user ID)
        expires_delta: Optional custom expiration time delta

    Returns:
        str: Encoded JWT access token

    Example:
        >>> token = create_access_token(subject=user.id)
        >>> # Returns: "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."
    """
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            minutes=settings.JWT_ACCESS_TOKEN_EXPIRES_IN
        )

    to_encode = {"exp": expire, "sub": str(subject)}
    encoded_jwt = jwt.encode(
        to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )
    return encoded_jwt


def verify_token(token: str) -> Optional[str]:
    """
    Verify and decode a JWT access token.

    Validates the JWT token signature and expiration, then extracts
    the subject (user ID) from the token payload.

    Args:
        token: The JWT token string to verify

    Returns:
        Optional[str]: User ID if token is valid, None if invalid

    Raises:
        CustomExceptionError: If token is expired or invalid

    Example:
        >>> user_id = verify_token("eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...")
        >>> # Returns: "123e4567-e89b-12d3-a456-426614174000"
    """
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        user_id: str = payload.get("sub")
        if user_id is None:
            return None
        return user_id
    except jwt.ExpiredSignatureError as error:
        raise CustomExceptionError(EXPIRED_TOKEN_ERROR) from error
    except jwt.InvalidTokenError as error:
        raise CustomExceptionError(INVALID_TOKEN_ERROR) from error
    except Exception as error:
        raise error


def hash_password(password: str) -> str:
    """
    Hash a password using bcrypt with salt.

    Securely hashes a plain text password using the bcrypt algorithm
    with a randomly generated salt. This is the standard approach for
    storing user passwords securely.

    Args:
        password: Plain text password to hash

    Returns:
        str: Bcrypt hashed password as a string

    Example:
        >>> hashed = hash_password("mySecurePassword123!")
        >>> # Returns: "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewdBPj/RVSg2/CPK"
    """
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a password against its bcrypt hash.

    Compares a plain text password with a stored bcrypt hash to determine
    if they match. Used during user authentication to verify credentials.

    Args:
        plain_password: Plain text password to verify
        hashed_password: Stored bcrypt hash to compare against

    Returns:
        bool: True if password matches the hash, False otherwise

    Example:
        >>> is_valid = verify_password("myPassword123", stored_hash)
        >>> # Returns: True or False
    """
    return bcrypt.checkpw(
        plain_password.encode("utf-8"), hashed_password.encode("utf-8")
    )


def generate_password_reset_token() -> str:
    """
    Generate a unique token for password reset functionality.

    Creates a cryptographically secure random UUID4 token that can be
    used for password reset links sent via email. The token should be
    stored in the database and have a reasonable expiration time.

    Returns:
        str: UUID4 token as a string

    Example:
        >>> reset_token = generate_password_reset_token()
        >>> # Returns: "123e4567-e89b-12d3-a456-426614174000"
    """
    return str(uuid.uuid4())
