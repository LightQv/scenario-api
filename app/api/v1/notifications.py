"""Cookie-authenticated, owner-guarded notification settings and current-device actions."""
from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_database
from app.api.v1.up_next import mutation_owner
from app.models import User
from app.schemas.notification import EndpointInput, NotificationSettingsInput, NotificationSettingsState, SubscriptionInput
from app.services import notification_service as service

router = APIRouter(responses={401: {"description": "Sign in required"}, 403: {"description": "Owner changed"}})


@router.get("", response_model=NotificationSettingsState, status_code=200, summary="Private daily release notification settings")
def get_settings(response: Response, user: User = Depends(get_current_user), db: Session = Depends(get_database)) -> NotificationSettingsState:
    response.headers["Cache-Control"] = "private, no-store"
    return service.preference_state(db, user.id)


@router.put("", response_model=NotificationSettingsState, status_code=200, summary="Opt in/out of daily release summaries")
def put_settings(payload: NotificationSettingsInput, response: Response, user: User = Depends(mutation_owner), db: Session = Depends(get_database)) -> NotificationSettingsState:
    response.headers["Cache-Control"] = "private, no-store"
    return service.save_preferences(db, user.id, payload)


@router.put("/device", status_code=204, response_model=None, summary="Register this browser's encrypted push subscription")
def put_device(payload: SubscriptionInput, user: User = Depends(mutation_owner), db: Session = Depends(get_database)) -> None:
    service.save_subscription(db, user.id, payload)


@router.delete("/device", status_code=204, response_model=None, summary="Remove only your current browser subscription")
def delete_device(payload: EndpointInput, user: User = Depends(mutation_owner), db: Session = Depends(get_database)) -> None:
    service.remove_subscription(db, user.id, payload.endpoint)


@router.post("/test", status_code=202, response_model=None, summary="Send a rate-limited test to your own device")
def post_test(payload: EndpointInput, user: User = Depends(mutation_owner), db: Session = Depends(get_database)) -> None:
    service.test_subscription(db, user.id, payload.endpoint)
