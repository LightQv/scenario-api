"""Business logic for user-owned long-term API tokens."""

from datetime import datetime
from hashlib import sha256
from secrets import token_urlsafe
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import User, UserApiToken
from app.schemas import (
    ALLOWED_API_TOKEN_SCOPES,
    ApiTokenCreate,
    ApiTokenCreateResponse,
    ApiTokenDetail,
    ApiTokenListItem,
)
from app.services.encryption_service import IntegrationSecretCipher


def generate_api_token() -> str:
    """Generate a long-term API token value."""
    return f"scn_{token_urlsafe(48)}"


def hash_api_token(token: str) -> str:
    """Return the stable lookup hash for an API token."""
    return sha256(token.encode("utf-8")).hexdigest()


def list_api_tokens(database_session: Session, user: User) -> list[ApiTokenListItem]:
    """List non-revoked API tokens for one user."""
    rows = (
        database_session.query(UserApiToken)
        .filter(
            UserApiToken.user_id == user.id,
            UserApiToken.revoked_at.is_(None),
        )
        .order_by(UserApiToken.created_at.desc())
        .all()
    )
    return [ApiTokenListItem.model_validate(row) for row in rows]


def get_api_token_detail(
    database_session: Session,
    user: User,
    token_id: UUID,
) -> ApiTokenDetail:
    """Return one owner-readable API token detail."""
    row = _get_owned_active_token(database_session, user.id, token_id)
    token = IntegrationSecretCipher().decrypt(row.encrypted_token)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stored API token cannot be decrypted",
        )
    return ApiTokenDetail(
        id=row.id,
        name=row.name,
        scopes=list(row.scopes or []),
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        token=token,
    )


def create_api_token(
    database_session: Session,
    user: User,
    payload: ApiTokenCreate,
) -> ApiTokenCreateResponse:
    """Create a long-term API token for one user."""
    scopes = _validate_scopes(payload.scopes)
    token = payload.token.strip() if payload.token else generate_api_token()
    if not token:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Token is required")

    row = UserApiToken(
        user_id=user.id,
        name=payload.name.strip(),
        token_hash=hash_api_token(token),
        encrypted_token=IntegrationSecretCipher().encrypt(token),
        scopes=scopes,
    )
    database_session.add(row)
    try:
        database_session.commit()
    except Exception as error:
        database_session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="API token already exists",
        ) from error
    database_session.refresh(row)
    return ApiTokenCreateResponse(
        id=row.id,
        name=row.name,
        scopes=list(row.scopes or []),
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        token=token,
    )


def revoke_api_token(database_session: Session, user: User, token_id: UUID) -> dict[str, bool]:
    """Revoke one user-owned API token."""
    row = _get_owned_active_token(database_session, user.id, token_id)
    row.revoked_at = datetime.utcnow()
    database_session.commit()
    return {"revoked": True}


def resolve_bearer_api_token(
    database_session: Session,
    token: str,
) -> tuple[User, UserApiToken] | None:
    """Resolve a bearer token to its owning user and token row."""
    if not token:
        return None
    token_hash = hash_api_token(token)
    row = (
        database_session.query(UserApiToken)
        .filter(
            UserApiToken.token_hash == token_hash,
            UserApiToken.revoked_at.is_(None),
        )
        .first()
    )
    if row is None or row.user is None:
        return None
    row.last_used_at = datetime.utcnow()
    database_session.commit()
    database_session.refresh(row)
    return row.user, row


def _validate_scopes(scopes: list[str]) -> list[str]:
    """Validate requested API token scopes."""
    unique_scopes = sorted(set(scopes))
    invalid_scopes = [scope for scope in unique_scopes if scope not in ALLOWED_API_TOKEN_SCOPES]
    if invalid_scopes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid API token scopes: {', '.join(invalid_scopes)}",
        )
    return unique_scopes


def _get_owned_active_token(
    database_session: Session,
    user_id: UUID,
    token_id: UUID,
) -> UserApiToken:
    """Return an active token owned by one user or raise 404."""
    row = (
        database_session.query(UserApiToken)
        .filter(
            UserApiToken.id == token_id,
            UserApiToken.user_id == user_id,
            UserApiToken.revoked_at.is_(None),
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API token not found")
    return row
