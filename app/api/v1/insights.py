from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session
from app.api.dependencies import get_current_user, get_database
from app.models import User
from app.schemas.insights import ViewInsights
from app.services.insights_service import InsightsService

router: APIRouter = APIRouter()


def get_insights_service(
    database_session: Session = Depends(get_database),
) -> InsightsService:
    """Provide the read-only insights service for this request."""
    return InsightsService(database_session)


@router.get(
    "/views",
    response_model=ViewInsights,
    status_code=status.HTTP_200_OK,
    summary="Read your private viewing story snapshot",
    responses={403: {"description": "Authenticated cookie required"}},
)
def get_view_insights(
    response: Response,
    current_user: User = Depends(get_current_user),
    service: InsightsService = Depends(get_insights_service),
) -> ViewInsights:
    """Return **only your current marked-watched records**.

    `recorded_at` is the offset-aware instant a record was added, not playback
    or completion time. Legacy/imported dates stay null. Unmarking removes a
    record; re-marking creates a new date. This is not an immutable event log.
    Existing public history responses do not expose recording dates.
    """
    response.headers["Cache-Control"] = "private, no-store"
    return service.views(current_user.id)
