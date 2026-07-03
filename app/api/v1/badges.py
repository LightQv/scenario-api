"""Badge endpoints."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_database
from app.models import User
from app.schemas import BadgeListResponse
from app.services.badge_service import get_user_badges

router = APIRouter(tags=["Badges"])


@router.get(
    "",
    response_model=BadgeListResponse,
    status_code=status.HTTP_200_OK,
    summary="List profile badges",
    description="Return current badge progress and permanently unlocked badges for the authenticated user.",
)
def list_badges(
    user: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> BadgeListResponse:
    """
    Return profile badges for the current user.

    The endpoint calculates progress from existing Scenario data and persists any
    newly unlocked badges so unlocks do not disappear when source data changes.
    """
    return get_user_badges(database_session, user.id)
