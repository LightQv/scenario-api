"""Owner-private Web Push subscriptions and durable release-day summaries."""

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import requests
from fastapi import HTTPException
from pywebpush import WebPushException, webpush
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.settings import settings
from app.models import EpisodeProgress, Media, ShowExclusion, ShowProgress, User, View, Watchlist
from app.models.notification import NotificationDelivery, NotificationPreference, PushSubscription
from app.models.progress_action import ProgressAction
from app.models.release_catalog import ReleaseCatalog
from app.schemas.notification import NotificationSettingsInput, NotificationSettingsState, SubscriptionInput, checked_endpoint
from app.services.encryption_service import IntegrationSecretCipher
from app.services.up_next_service import parsed_date


def available() -> bool:
    """Require explicit runtime enablement and all server-only key material."""
    return bool(settings.WEB_PUSH_ENABLED and settings.WEB_PUSH_PRIVATE_KEY and
                settings.WEB_PUSH_PUBLIC_KEY and settings.WEB_PUSH_SUBJECT and
                settings.INTEGRATION_SETTINGS_ENCRYPTION_KEY)


def endpoint_hash(endpoint: str) -> str:
    """Use a non-reversible identity in lookups, never log endpoint credentials."""
    return hashlib.sha256(endpoint.encode()).hexdigest()


def preference_state(db: Session, owner: UUID) -> NotificationSettingsState:
    """Read defaults without opting in or creating a device."""
    row: NotificationPreference | None = db.get(NotificationPreference, owner)
    return NotificationSettingsState(
        user_id=owner, enabled=row.enabled if row else False,
        timezone=row.timezone if row else "Europe/Paris",
        delivery_time=row.delivery_time if row else "09:00",
        language=row.language if row else "en-US",
        available=available(), public_key=settings.WEB_PUSH_PUBLIC_KEY if available() else "",
        device_hashes=list(db.scalars(select(PushSubscription.endpoint_hash).where(PushSubscription.user_id == owner))),
    )


def save_preferences(db: Session, owner: UUID, payload: NotificationSettingsInput) -> NotificationSettingsState:
    """Serialize changes per owner and cancel pending sends on opt-out."""
    if payload.enabled and not available():
        raise HTTPException(503, "Release notifications are not configured")
    # Use the parent row as the owner mutex, including a previously absent preference.
    db.execute(select(User.id).where(User.id == owner).with_for_update())
    row: NotificationPreference | None = db.get(NotificationPreference, owner)
    if row is None:
        row = NotificationPreference(user_id=owner)
        db.add(row)
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    if not payload.enabled:
        devices = select(PushSubscription.id).where(PushSubscription.user_id == owner)
        db.execute(delete(NotificationDelivery).where(
            NotificationDelivery.subscription_id.in_(devices), NotificationDelivery.status == "pending",
        ))
    db.commit()
    return preference_state(db, owner)


def save_subscription(db: Session, owner: UUID, payload: SubscriptionInput) -> None:
    """Encrypt browser credentials; never transfer another owner's endpoint."""
    if not available():
        raise HTTPException(503, "Release notifications are not configured")
    db.execute(select(User.id).where(User.id == owner).with_for_update())
    pref: NotificationPreference | None = db.get(NotificationPreference, owner)
    if pref is None or not pref.enabled:
        raise HTTPException(409, "Enable release notifications first")
    hashed: str = endpoint_hash(payload.endpoint)
    row: PushSubscription | None = db.scalar(select(PushSubscription).where(PushSubscription.endpoint_hash == hashed).with_for_update())
    if row is not None and row.user_id != owner:
        raise HTTPException(409, "Remove this browser's old subscription before subscribing")
    encrypted: str = IntegrationSecretCipher().encrypt(payload.model_dump_json(exclude_none=True))
    if row is None:
        count: int = db.scalar(select(func.count()).select_from(PushSubscription).where(PushSubscription.user_id == owner)) or 0
        if count >= 10:
            raise HTTPException(429, "Device limit reached")
        db.add(PushSubscription(user_id=owner, endpoint_hash=hashed, encrypted_subscription=encrypted))
    else:
        row.encrypted_subscription = encrypted
    db.commit()


def remove_subscription(db: Session, owner: UUID, endpoint: str) -> None:
    """Idempotently remove only a cookie owner's exact device."""
    db.execute(select(User.id).where(User.id == owner).with_for_update())
    db.execute(delete(PushSubscription).where(PushSubscription.user_id == owner, PushSubscription.endpoint_hash == endpoint_hash(endpoint)))
    db.commit()


class PushSession(requests.Session):
    """Do not let a push provider redirect credential-bearing requests elsewhere."""

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        """Revalidate the destination and disable redirects and ambient proxies."""
        checked_endpoint(url)
        kwargs["allow_redirects"] = False
        return super().request(method, url, **kwargs)


def send_push(subscription: str, language: str, tag: str, ttl: int = 3600) -> int:
    """Send a generic encrypted message; disclose no titles/account on lock screens.

    Returns:
        Provider HTTP status, including expired subscriptions. Transport errors
        propagate to the bounded outbox retry policy, without logging credentials.
    """
    payload: SubscriptionInput = SubscriptionInput.model_validate_json(subscription)
    french: bool = language == "fr-FR"
    data: dict[str, str] = {
        "title": "Scenario",
        "body": ("Votre résumé des sorties du jour est prêt." if french else "Your release-day summary is ready.") if tag != "test" else
                ("Les notifications sont activées sur cet appareil." if french else "Notifications are working on this device."),
        "tag": f"scenario-release-{tag}",
    }
    with PushSession() as session:
        session.trust_env = False
        try:
            response: requests.Response | str = webpush(
                subscription_info=payload.model_dump(exclude_none=True), data=json.dumps(data),
                vapid_private_key=settings.WEB_PUSH_PRIVATE_KEY,
                vapid_claims={"sub": settings.WEB_PUSH_SUBJECT}, timeout=10, ttl=ttl,
                requests_session=session,
            )
            return response.status_code if isinstance(response, requests.Response) else 500
        except WebPushException as error:
            if error.response is not None:
                return error.response.status_code
            raise


def test_subscription(db: Session, owner: UUID, endpoint: str) -> None:
    """Send only to an owned saved device, with a durable one-minute cooldown."""
    if not available():
        raise HTTPException(503, "Release notifications are not configured")
    db.execute(select(User.id).where(User.id == owner).with_for_update())
    row: PushSubscription | None = db.scalar(select(PushSubscription).where(
        PushSubscription.user_id == owner, PushSubscription.endpoint_hash == endpoint_hash(endpoint),
    ).with_for_update())
    if row is None:
        raise HTTPException(404, "Device not subscribed")
    pref: NotificationPreference | None = db.get(NotificationPreference, owner)
    if pref is None or not pref.enabled:
        raise HTTPException(409, "Release notifications are off")
    now: datetime = datetime.now(timezone.utc)
    if row.last_test_at and now - row.last_test_at < timedelta(minutes=1):
        raise HTTPException(429, "Wait a minute before sending another test")
    row.last_test_at = now
    secret: str = row.encrypted_subscription
    language: str = pref.language
    db.commit()
    try:
        code: int = send_push(IntegrationSecretCipher().decrypt(secret) or "", language, "test", 60)
    except Exception:
        raise HTTPException(503, "Push delivery could not be confirmed") from None
    if code in (404, 410):
        remove_subscription(db, owner, endpoint)
        raise HTTPException(410, "Device subscription expired; enable this device again")
    if not 200 <= code < 300:
        raise HTTPException(503, "Push provider did not accept the test")


def episode_releases_today(payload: dict[str, Any], day: date, cutoff: date, overrides: dict[tuple[int, int], bool]) -> bool:
    """Select today's unwatched regular episodes, including explicit false overrides."""
    for season in payload.get("seasons", []):
        number: int = season.get("season_number", 0)
        if not isinstance(number, int) or number <= 0:
            continue
        for episode in payload.get(f"season/{number}", {}).get("episodes", []):
            ep: int = episode.get("episode_number", 0)
            if not isinstance(ep, int) or ep <= 0 or parsed_date(episode.get("air_date")) != day:
                continue
            if not overrides.get((number, ep), day <= cutoff):
                return True
    return False


def releases_today(db: Session, owner: UUID, language: str, day: date) -> bool:
    """Read catalogues only; never call TMDB, change progress or notify backlog."""
    progress = {row.tmdb_id: row.caught_up_through for row in db.scalars(select(ShowProgress).where(ShowProgress.user_id == owner))}
    excluded = set(db.scalars(select(ShowExclusion.tmdb_id).where(ShowExclusion.user_id == owner)))
    pending = set(db.scalars(select(ProgressAction.tmdb_id).where(ProgressAction.user_id == owner, ProgressAction.status == "pending")))
    overrides: dict[int, dict[tuple[int, int], bool]] = {}
    for row in db.scalars(select(EpisodeProgress).where(EpisodeProgress.user_id == owner)):
        overrides.setdefault(row.tmdb_id, {})[(row.season_number, row.episode_number)] = row.watched
    movies = set(db.scalars(select(Media.tmdb_id).join(Watchlist, Media.watchlist_id == Watchlist.id).where(
        Watchlist.author_id == owner, Watchlist.type == "SYSTEM", Media.type == "PENDING", Media.media_type == "movie",
    )))
    movies -= set(db.scalars(select(View.tmdb_id).where(View.viewer_id == owner, View.media_type == "movie")))
    # Compact stored catalogues are shared public data; all private selectors above are owner-bound.
    for catalog in db.scalars(select(ReleaseCatalog).where(ReleaseCatalog.language == language, ReleaseCatalog.payload.is_not(None))):
        payload: dict[str, Any] = catalog.payload or {}
        if catalog.media_type == "movie" and catalog.tmdb_id in movies and parsed_date(payload.get("release_date")) == day:
            return True
        if catalog.media_type == "tv" and catalog.tmdb_id in progress and catalog.tmdb_id not in excluded | pending:
            if episode_releases_today(payload, day, progress[catalog.tmdb_id], overrides.get(catalog.tmdb_id, {})):
                return True
    return False


def process_notifications(db: Session, now: datetime) -> None:
    """Queue/send one generic daily summary per device, under PostgreSQL locks.

    A bounded sender holds a row lock through each provider request. A crash after
    provider acceptance may redeliver; a stable browser tag coalesces that case.
    Failed jobs retry at most four times and expire at local midnight.
    """
    if not available():
        return
    owners = db.scalars(select(NotificationPreference.user_id).where(NotificationPreference.enabled.is_(True))).all()
    db.commit()
    for owner in owners:
        pref: NotificationPreference | None = db.scalar(select(NotificationPreference).join(User, User.id == NotificationPreference.user_id).where(
            NotificationPreference.user_id == owner, NotificationPreference.enabled.is_(True),
        ).with_for_update(of=User, skip_locked=True))
        if pref is None:
            db.rollback()
            continue
        local: datetime = now.astimezone(ZoneInfo(pref.timezone))
        if local.strftime("%H:%M") < pref.delivery_time:
            db.rollback()
            continue
        devices = db.scalars(select(PushSubscription).where(PushSubscription.user_id == owner)).all()
        if devices and releases_today(db, owner, pref.language, local.date()):
            for device in devices:
                db.execute(insert(NotificationDelivery).values(
                    subscription_id=device.id, local_date=local.date(), attempts=0,
                    status="pending", next_attempt_at=now,
                ).on_conflict_do_nothing(constraint="uq_notification_device_day"))
        db.commit()
    # Process a bounded batch; separate transactions isolate device failures.
    for _ in range(20):
        candidate = db.execute(select(NotificationDelivery.id, PushSubscription.user_id).join(
            PushSubscription, PushSubscription.id == NotificationDelivery.subscription_id,
        ).where(
            NotificationDelivery.status == "pending", NotificationDelivery.next_attempt_at <= now,
        ).order_by(NotificationDelivery.next_attempt_at).limit(1)).first()
        if candidate is None:
            db.rollback()
            break
        # Every mutation uses the same owner mutex before touching devices/jobs.
        # Skip busy owners instead of deadlocking opt-out against a sender.
        locked = db.scalar(select(User.id).where(User.id == candidate.user_id).with_for_update(skip_locked=True))
        if locked is None:
            db.rollback()
            continue
        job: NotificationDelivery | None = db.scalar(select(NotificationDelivery).where(
            NotificationDelivery.id == candidate.id, NotificationDelivery.status == "pending",
            NotificationDelivery.next_attempt_at <= now,
        ).with_for_update(skip_locked=True).execution_options(populate_existing=True))
        if job is None:
            db.rollback()
            continue
        device: PushSubscription | None = db.get(PushSubscription, job.subscription_id)
        pref = db.scalar(select(NotificationPreference).where(
            NotificationPreference.user_id == device.user_id,
        )) if device else None
        if pref is None or not pref.enabled or now.astimezone(ZoneInfo(pref.timezone)).date() != job.local_date:
            job.status = "cancelled"
        elif not releases_today(db, device.user_id, pref.language, job.local_date):
            job.status = "cancelled"
        else:
            job.attempts += 1
            local = now.astimezone(ZoneInfo(pref.timezone))
            midnight: datetime = datetime.combine(local.date() + timedelta(days=1), datetime.min.time(), ZoneInfo(pref.timezone))
            ttl: int = max(1, min(86400, int((midnight - now).total_seconds())))
            try:
                code: int = send_push(IntegrationSecretCipher().decrypt(device.encrypted_subscription) or "", pref.language, job.local_date.isoformat(), ttl)
            except Exception:
                code = 503
            if code in (404, 410):
                db.delete(device)
            elif 200 <= code < 300:
                job.status = "sent"
            elif job.attempts >= 4 or 300 <= code < 500 and code != 429:
                job.status = "failed"
            else:
                job.next_attempt_at = now + timedelta(minutes=5 * job.attempts)
        db.commit()
    db.execute(delete(NotificationDelivery).where(NotificationDelivery.local_date < now.date() - timedelta(days=30)))
    db.commit()
