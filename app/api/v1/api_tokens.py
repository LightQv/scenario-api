"""Long-term API token management endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_database
from app.models import User
from app.schemas import (
    ApiTokenCreate,
    ApiTokenCreateResponse,
    ApiTokenDetail,
    ApiTokenGenerateResponse,
    ApiTokenListItem,
)
from app.services.api_token_service import (
    create_api_token,
    generate_api_token,
    get_api_token_detail,
    list_api_tokens,
    revoke_api_token,
)

router = APIRouter(
    tags=["API tokens"],
    responses={403: {"description": "Access forbidden"}},
)


@router.get(
    "",
    response_model=list[ApiTokenListItem],
    status_code=status.HTTP_200_OK,
    summary="List long-term API tokens",
)
def list_tokens(
    user: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> list[ApiTokenListItem]:
    """List non-revoked long-term API tokens for the current user."""
    return list_api_tokens(database_session, user)


@router.post(
    "/generate",
    response_model=ApiTokenGenerateResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate a long-term API token value",
)
def generate_token(user: User = Depends(get_current_user)) -> ApiTokenGenerateResponse:
    """Generate a token value for the authenticated user to save in a token form."""
    return ApiTokenGenerateResponse(token=generate_api_token())


@router.get(
    "/{token_id}",
    response_model=ApiTokenDetail,
    status_code=status.HTTP_200_OK,
    summary="Get long-term API token detail",
)
def token_detail(
    token_id: UUID,
    user: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> ApiTokenDetail:
    """Return one token with decrypted value for its authenticated owner."""
    return get_api_token_detail(database_session, user, token_id)


@router.post(
    "",
    response_model=ApiTokenCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create long-term API token",
)
def create_token(
    payload: ApiTokenCreate,
    user: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> ApiTokenCreateResponse:
    """Create a long-term API token for the current cookie-authenticated user."""
    return create_api_token(database_session, user, payload)


@router.delete(
    "/{token_id}",
    response_model=dict[str, bool],
    status_code=status.HTTP_200_OK,
    summary="Revoke long-term API token",
)
def revoke_token(
    token_id: UUID,
    user: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> dict[str, bool]:
    """Revoke one current-user long-term API token."""
    return revoke_api_token(database_session, user, token_id)
