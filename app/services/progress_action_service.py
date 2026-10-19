"""Ordered progress intents survive catalogue preparation and uncertain HTTP responses."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import ProgressAction, ReleaseCatalog, User
from app.schemas.up_next import EpisodeWatched, ProgressActionRequest, ProgressActionState
from app.services.release_catalog_service import request_catalog
from app.services.up_next_service import mark_episode, mark_season, mark_show, utc_today


def action_states(db: Session, user_id: UUID, tmdb_id: int) -> list[ProgressActionState]:
    """Return bounded receipts in acceptance order; never expose another owner's intents."""
    rows: list[ProgressAction] = list(db.scalars(select(ProgressAction).where(
        ProgressAction.user_id == user_id, ProgressAction.tmdb_id == tmdb_id,
    ).order_by(ProgressAction.sequence.desc()).limit(200)).all())
    return [ProgressActionState.model_validate(row) for row in reversed(rows)]


def apply_actions(db: Session, user_id: UUID, tmdb_id: int) -> None:
    """Apply the ordered inbox under an owner lock; the caller commits receipts and data.

    Args:
        db: Isolated transaction with a public snapshot already present.
        user_id: Owner serialized by the caller using the user row.
        tmdb_id: Show whose pending actions must be drained together.
    """
    row: ReleaseCatalog | None = db.get(ReleaseCatalog, ("tv", tmdb_id, "en-US"))
    if row is None or row.payload is None:
        return
    actions: list[ProgressAction] = list(db.scalars(select(ProgressAction).where(
        ProgressAction.user_id == user_id, ProgressAction.tmdb_id == tmdb_id,
        ProgressAction.status == "pending",
    ).order_by(ProgressAction.sequence)).all())
    for action in actions:
        try:
            # Validation failures roll back only this intent, not earlier/later choices.
            with db.begin_nested():
                if action.season_number is not None and not isinstance(row.payload.get(f"season/{action.season_number}"), dict):
                    raise HTTPException(422, "Regular season not found")
                if action.episode_number is not None:
                    mark_episode(db, user_id, tmdb_id, EpisodeWatched(
                        season_number=action.season_number, episode_number=action.episode_number,
                        watched=action.watched,
                    ), commit=False, through=action.through)
                elif action.season_number is not None:
                    mark_season(db, user_id, tmdb_id, action.season_number, action.through, action.watched, commit=False)
                else:
                    mark_show(db, user_id, tmdb_id, action.through, action.watched, record_history=action.record_history, commit=False)
            action.status = "applied"
        except HTTPException as error:
            if error.status_code != 422:
                raise
            action.status = "failed"


def submit_action(db: Session, user_id: UUID, tmdb_id: int, body: ProgressActionRequest) -> ProgressActionState:
    """Durably accept a desired state once; prioritize cold preparation and apply warm data.

    Args:
        db: Owner-authenticated request transaction.
        user_id: Verified cookie owner; never trusted from the request body.
        tmdb_id: Show identity awaiting server-side catalogue validation.
        body: Immutable operation identity, target, cutoff and desired boolean.

    Returns:
        An owner-private receipt, including deferred validation failures.
    """
    if body.through > utc_today():
        raise HTTPException(422, "Cannot mark future episodes")
    # All submissions and worker drains for this owner serialize, including overlaps.
    db.scalar(select(User.id).where(User.id == user_id).with_for_update())
    existing: ProgressAction | None = db.get(ProgressAction, body.id)
    if existing is not None:
        if existing.user_id != user_id or existing.tmdb_id != tmdb_id or any(
            getattr(existing, name) != value for name, value in body.model_dump().items() if name != "id"
        ):
            raise HTTPException(409, "Action identity already used")
        return ProgressActionState.model_validate(existing)
    count: int = db.scalar(select(func.count()).select_from(ProgressAction).where(
        ProgressAction.user_id == user_id, ProgressAction.status == "pending",
    )) or 0
    if count >= 150:
        raise HTTPException(429, "Too many pending progress actions; try again later")
    request_catalog(db, "tv", tmdb_id, "en-US", priority=10)
    action: ProgressAction = ProgressAction(user_id=user_id, tmdb_id=tmdb_id, status="pending", **body.model_dump())
    db.add(action)
    db.flush()
    apply_actions(db, user_id, tmdb_id)
    db.commit()
    return ProgressActionState.model_validate(action)


def drain_ready_actions(db: Session) -> None:
    """Process a bounded ready inbox and expire old final receipts, never pending intents."""
    identities: list[tuple[UUID, int]] = list(db.execute(select(
        ProgressAction.user_id, ProgressAction.tmdb_id,
    ).join(ReleaseCatalog, (ReleaseCatalog.tmdb_id == ProgressAction.tmdb_id)
        & (ReleaseCatalog.media_type == "tv") & (ReleaseCatalog.language == "en-US")
    ).where(ProgressAction.status == "pending", ReleaseCatalog.payload.is_not(None)).distinct().limit(20)).all())
    for owner, tmdb_id in identities:
        # Never wait on interactive work in another process.
        if db.scalar(select(User.id).where(User.id == owner).with_for_update(skip_locked=True)) is not None:
            apply_actions(db, owner, tmdb_id)
        db.commit()
    db.execute(delete(ProgressAction).where(
        ProgressAction.status != "pending",
        ProgressAction.updated_at < datetime.now(timezone.utc) - timedelta(days=7),
    ))
    db.commit()
