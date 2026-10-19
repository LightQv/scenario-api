"""Authenticated release feed and idempotent episode progression."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Response
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_database
from app.models import User
from app.schemas.up_next import CaughtUpRequest, EpisodeWatched, NextFeed, ShowExclusionRequest, ShowProgressState, ProgressActionRequest, ProgressActionState
from app.services.progress_action_service import action_states, submit_action
from app.services.up_next_service import exclude_show, mark_episode, release_feed, restore_show, show_progress, start_tracking, mark_season, mark_show
from app.services.release_catalog_service import refresh_owner_catalogs

router = APIRouter(
    tags=["Up next"],
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Access forbidden"},
    },
)


def mutation_owner(
    expected_owner: Annotated[UUID | None, Header(alias="X-Scenario-Owner")] = None,
    current_user: User = Depends(get_current_user),
) -> User:
    """Reject a stale remembered profile or cookie-owner change before any write.

    Args:
        expected_owner: Identity of the authenticated feed shown by the client.
        current_user: Actual cookie-authenticated account, never a caller ID.

    Returns:
        The authenticated owner after the identity guard matches.
    """
    if expected_owner != current_user.id:
        raise HTTPException(403, "Account changed; reload your next episodes")
    return current_user


@router.get(
    "", response_model=NextFeed, status_code=200,
    summary="Your next episodes and bookmarked releases",
)
def get_feed(
    response: Response,
    language: Literal["en-US", "fr-FR"] = "en-US",
    current_user: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> NextFeed:
    """Return **only the authenticated owner's** progress and release queue.

    Season zero is excluded. Air dates are information, not streaming availability.
    Reading this endpoint never advances progress or writes history.
    """
    response.headers["Cache-Control"] = "private, no-store"
    return release_feed(database_session, current_user.id, language)


@router.post(
    "/refresh", status_code=202, response_model=None,
    summary="Queue a deduplicated background release refresh",
)
def refresh_feed(
    response: Response,
    language: Literal["en-US", "fr-FR"] = "en-US",
    current_user: User = Depends(mutation_owner),
    database_session: Session = Depends(get_database),
) -> None:
    """Queue public catalogue work only; keep the last complete feed readable."""
    response.headers["Cache-Control"] = "private, no-store"
    refresh_owner_catalogs(database_session, current_user.id, language)


@router.put(
    "/shows/{tmdb_id}/episodes", status_code=204,
    summary="Mark a released regular episode watched", response_model=None,
    responses={
        422: {"description": "Special, unknown or unreleased episode"},
        503: {"description": "TMDB verification unavailable"},
    },
)
def put_episode(
    tmdb_id: Annotated[int, Path(gt=0)],
    episode: EpisodeWatched,
    current_user: User = Depends(mutation_owner),
    database_session: Session = Depends(get_database),
) -> None:
    """Idempotently record progress without modifying show history or statistics."""
    mark_episode(database_session, current_user.id, tmdb_id, episode)


@router.get(
    "/shows/{tmdb_id}/progress", response_model=ShowProgressState, status_code=200,
    summary="Read private released episode progress", responses={503: {"description": "TMDB unavailable"}},
)
def get_progress(
    response: Response,
    tmdb_id: Annotated[int, Path(gt=0)],
    current_user: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> ShowProgressState:
    """Read **only your own** progress, including an untracked show's empty state."""
    response.headers["Cache-Control"] = "private, no-store"
    result: ShowProgressState = show_progress(database_session, current_user.id, tmdb_id)
    result.actions = action_states(database_session, current_user.id, tmdb_id)
    result.syncing = result.syncing or any(action.status == "pending" for action in result.actions)
    return result


@router.put(
    "/shows/{tmdb_id}/actions", status_code=202, response_model=ProgressActionState,
    summary="Accept an ordered watched intent, even while the catalogue is preparing",
    responses={409: {"description": "Operation identity reused"}, 422: {"description": "Invalid target or future cutoff"}, 429: {"description": "Inbox limit reached"}},
)
def put_progress_action(
    response: Response,
    tmdb_id: Annotated[int, Path(gt=0)],
    body: ProgressActionRequest,
    current_user: User = Depends(mutation_owner),
    database_session: Session = Depends(get_database),
) -> ProgressActionState:
    """Accept owner-private desired state; validation never trusts client release metadata."""
    response.headers["Cache-Control"] = "private, no-store"
    return submit_action(database_session, current_user.id, tmdb_id, body)


@router.put(
    "/shows/{tmdb_id}/tracking", status_code=204, response_model=None,
    summary="Start tracking without marking any episodes watched",
    responses={503: {"description": "TMDB unavailable"}},
)
def put_tracking(
    tmdb_id: Annotated[int, Path(gt=0)],
    current_user: User = Depends(mutation_owner),
    database_session: Session = Depends(get_database),
) -> None:
    """Idempotently follow a show without adding viewing history."""
    start_tracking(database_session, current_user.id, tmdb_id)


@router.put(
    "/shows/{tmdb_id}/seasons/{season_number}", status_code=204, response_model=None,
    summary="Mark a season's released regular episodes watched",
    responses={422: {"description": "No released episodes or future cutoff"}, 503: {"description": "TMDB unavailable"}},
)
def put_season(
    tmdb_id: Annotated[int, Path(gt=0)],
    season_number: Annotated[int, Path(gt=0, le=10000)],
    body: CaughtUpRequest,
    current_user: User = Depends(mutation_owner),
    database_session: Session = Depends(get_database),
) -> None:
    """Start tracking and record only this season; history/statistics stay unchanged."""
    mark_season(database_session, current_user.id, tmdb_id, season_number, body.through, body.watched)


@router.put(
    "/shows/{tmdb_id}/watched", status_code=204, response_model=None,
    summary="Set watched state of all released regular episodes",
    responses={422: {"description": "No released episodes or future cutoff"}, 503: {"description": "Catalogue not ready"}},
)
def put_show_watched(
    tmdb_id: Annotated[int, Path(gt=0)],
    body: CaughtUpRequest,
    current_user: User = Depends(mutation_owner),
    database_session: Session = Depends(get_database),
) -> None:
    """Atomically set released children and preserve explicit whole-show viewing history."""
    mark_show(database_session, current_user.id, tmdb_id, body.through, body.watched, record_history=True)


@router.put(
    "/shows/{tmdb_id}/caught-up", status_code=204, response_model=None,
    summary="Mark released regular episodes watched",
    responses={
        422: {"description": "Future cutoff"},
        503: {"description": "Catalogue not ready"},
    },
)
def put_caught_up(
    tmdb_id: Annotated[int, Path(gt=0)],
    body: CaughtUpRequest,
    current_user: User = Depends(mutation_owner),
    database_session: Session = Depends(get_database),
) -> None:
    """Set released children through the displayed date without rewriting history."""
    mark_show(database_session, current_user.id, tmdb_id, body.through, body.watched)


@router.put(
    "/shows/{tmdb_id}/exclusion", status_code=204, response_model=None,
    summary="Exclude a show from both Next sections",
)
def put_exclusion(
    tmdb_id: Annotated[int, Path(gt=0)],
    body: ShowExclusionRequest,
    current_user: User = Depends(mutation_owner),
    database_session: Session = Depends(get_database),
) -> None:
    """Save an idempotent exclusion; history, bookmarks and progress stay unchanged."""
    exclude_show(database_session, current_user.id, tmdb_id, body)


@router.delete(
    "/shows/{tmdb_id}/exclusion", status_code=204, response_model=None,
    summary="Restore an excluded show",
)
def delete_exclusion(
    tmdb_id: Annotated[int, Path(gt=0)],
    current_user: User = Depends(mutation_owner),
    database_session: Session = Depends(get_database),
) -> None:
    """Clear only the authenticated owner's preference, preserving saved progress."""
    restore_show(database_session, current_user.id, tmdb_id)
