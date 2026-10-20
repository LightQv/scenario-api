"""Exercise notification migration/outbox on an owned disposable PostgreSQL only.

No configured settings/database or real push endpoints are used. Requires the
already installed postgres:16-alpine Docker image; never pulls another image.
"""
import importlib.util
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "contract_tests")]
from test_notifications import service
from app.database.base import Base
from app.models import EpisodeProgress, ShowExclusion, ShowProgress, User, View
from app.models.notification import NotificationDelivery, NotificationPreference, PushSubscription
from app.models.release_catalog import ReleaseCatalog
from app.schemas.notification import NotificationSettingsInput


def run() -> None:
    """Verify DDL preservation, owner isolation, concurrency, retries and local dates."""
    name = f"scenario-notifications-test-{uuid4().hex[:12]}"
    subprocess.run(["docker", "run", "--detach", "--rm", "--pull", "never", "--name", name,
                    "--label", "scenario.test=notifications", "--tmpfs", "/var/lib/postgresql/data",
                    "--publish", "127.0.0.1::5432", "--env", "POSTGRES_HOST_AUTH_METHOD=trust",
                    "--env", "POSTGRES_DB=notification_test", "postgres:16-alpine"], check=True, capture_output=True)
    engine = None
    try:
        port = json.loads(subprocess.check_output(["docker", "inspect", name]))[0]["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostPort"]
        engine = create_engine(f"postgresql+psycopg2://postgres@127.0.0.1:{port}/notification_test")
        for attempt in range(60):
            try:
                with engine.connect() as db:
                    db.execute(text("SELECT 1"))
                break
            except OperationalError:
                if attempt == 59:
                    raise
                time.sleep(1)
        notification_names = {"notification_preference", "push_subscription", "notification_delivery"}
        with engine.begin() as db:
            Base.metadata.create_all(db, tables=[table for table in Base.metadata.sorted_tables if table.name not in notification_names])
        owner, other = uuid4(), uuid4()
        with Session(engine) as db:
            for identity in (owner, other):
                db.add(User(id=identity, username=f"fixture-{identity}", email=f"{identity}@example.test", hashed_password="fixture"))
            db.commit()
            before = db.execute(select(User.__table__).order_by(User.id)).all()
        spec = importlib.util.spec_from_file_location("notification_migration", ROOT / "app/database/migrations/versions/202610192100_0021_notifications.py")
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        with engine.begin() as db, patch.object(migration, "op", Operations(MigrationContext.configure(db))):
            migration.upgrade()
            # A real pre-0022 preference proves existing opt-ins/schedules survive.
            db.execute(text("INSERT INTO notification_preference (user_id, enabled, timezone, delivery_time, language, created_at, updated_at) VALUES (:owner, false, 'Europe/Paris', '09:00', 'en-US', now(), now())"), {"owner": owner})
            legacy_preference = db.execute(text("SELECT user_id, enabled, timezone, delivery_time, language, created_at, updated_at FROM notification_preference")).all()
            legacy_device = uuid4()
            db.execute(text("INSERT INTO push_subscription (id, user_id, endpoint_hash, encrypted_subscription, created_at, updated_at) VALUES (:id, :owner, :hash, 'fixture-encrypted', now(), now())"), {"id": legacy_device, "owner": owner, "hash": "b" * 64})
            db.execute(text("INSERT INTO notification_delivery (id, subscription_id, local_date, attempts, status, next_attempt_at, created_at, updated_at) VALUES (:id, :device, '2026-10-19', 1, 'sent', now(), now(), now())"), {"id": uuid4(), "device": legacy_device})
            legacy_devices = db.execute(text("SELECT * FROM push_subscription")).all()
            legacy_receipts = db.execute(text("SELECT * FROM notification_delivery")).all()
        details_spec = importlib.util.spec_from_file_location("notification_details_migration", ROOT / "app/database/migrations/versions/202610201500_0022_notification_details.py")
        details_migration = importlib.util.module_from_spec(details_spec)
        details_spec.loader.exec_module(details_migration)
        with engine.begin() as db, patch.object(details_migration, "op", Operations(MigrationContext.configure(db))):
            details_migration.upgrade()
            assert db.execute(text("SELECT user_id, enabled, timezone, delivery_time, language, created_at, updated_at FROM notification_preference")).all() == legacy_preference
            assert db.execute(text("SELECT show_details FROM notification_preference")).scalar_one() is False
            assert db.execute(text("SELECT * FROM push_subscription")).all() == legacy_devices
            assert db.execute(text("SELECT * FROM notification_delivery")).all() == legacy_receipts
            # Remove only our preservation fixtures before the independent scheduling scenario.
            db.execute(text("DELETE FROM push_subscription WHERE id = :id"), {"id": legacy_device})
        now = datetime(2026, 10, 25, 8, 0, tzinfo=timezone.utc)  # Paris fall-back day, 09:00 local.
        day = now.date()
        with Session(engine) as db:
            assert db.execute(select(User.__table__).order_by(User.id)).all() == before
            assert service.preference_state(db, owner).enabled is False
            assert service.preference_state(db, owner).show_details is False
            pref = db.get(NotificationPreference, owner)
            pref.enabled = True
            pref.language = "fr-FR"
            db.add(PushSubscription(user_id=owner, endpoint_hash="a" * 64, encrypted_subscription="fixture-encrypted"))
            db.add(ShowProgress(user_id=owner, tmdb_id=42, caught_up_through=date(2026, 10, 24)))
            db.add(ReleaseCatalog(media_type="tv", tmdb_id=42, language="fr-FR", next_refresh_at=now, payload={
                "id": 42, "name": "Une série privée", "seasons": [{"season_number": 1}], "season/1": {"episodes": [{"episode_number": 1, "air_date": day.isoformat()}]},
            }))
            db.commit()
            assert service.releases_today(db, owner, "fr-FR", day)
            assert not service.releases_today(db, other, "fr-FR", day)
            assert not service.releases_today(db, owner, "fr-FR", day + timedelta(days=1))
            db.add(ShowExclusion(user_id=owner, tmdb_id=42, title="Fixture", poster_path=""))
            db.commit()
            assert not service.releases_today(db, owner, "fr-FR", day)
            db.delete(db.get(ShowExclusion, (owner, 42)))
            db.add(EpisodeProgress(user_id=owner, tmdb_id=42, season_number=1, episode_number=1, watched=True))
            db.commit()
            assert not service.releases_today(db, owner, "fr-FR", day)
            db.get(EpisodeProgress, (owner, 42, 1, 1)).watched = False
            db.commit()
            assert service.releases_today(db, owner, "fr-FR", day)
            db.rollback()
        def tick(at: datetime) -> None:
            """Run a real independent worker session."""
            with Session(engine) as db:
                service.process_notifications(db, at)
        with patch.object(service, "available", return_value=True), patch.object(service, "IntegrationSecretCipher") as cipher, patch.object(service, "send_push", return_value=201) as push:
            cipher.return_value.decrypt.return_value = "fixture"
            tick(now - timedelta(minutes=1))
            assert push.call_count == 0
            with ThreadPoolExecutor(max_workers=3) as workers:
                list(workers.map(tick, [now] * 3))
            assert push.call_count == 1
            assert push.call_args.kwargs["releases"] is None
            tick(now + timedelta(hours=1))
            assert push.call_count == 1
            tick(now + timedelta(days=1))
            assert push.call_count == 1, "No qualifying releases means no daily push"
            with Session(engine) as db:
                jobs = db.scalars(select(NotificationDelivery)).all()
                assert len(jobs) == 1 and jobs[0].status == "sent"
                # Reset only our fixture receipt to exercise transport failures.
                jobs[0].status = "pending"
                db.commit()
            push.return_value = 503
            tick(now)
            with Session(engine) as db:
                job = db.scalar(select(NotificationDelivery))
                assert job.attempts == 2 and job.status == "pending" and job.next_attempt_at == now + timedelta(minutes=10)
            tick(now + timedelta(minutes=10))
            tick(now + timedelta(minutes=25))
            with Session(engine) as db:
                job = db.scalar(select(NotificationDelivery))
                assert job.attempts == 4 and job.status == "failed"
                job.status = "pending"
                db.commit()
            before_midnight_expiry = push.call_count
            # An earlier bounded provider request can span local midnight. A
            # sender must recheck wall time, not reuse its cycle-start date.
            with patch.object(service, "monotonic", side_effect=[0, 86400, 86400]):
                tick(now)
            assert push.call_count == before_midnight_expiry
            with Session(engine) as db:
                assert db.scalar(select(NotificationDelivery)).status == "cancelled"
                job = db.scalar(select(NotificationDelivery))
                job.status = "pending"
                job.next_attempt_at = now
                db.commit()
                # Opt-out deletes any pending outbox entry, without affecting history.
                service.save_preferences(db, owner, NotificationSettingsInput(enabled=False, timezone="Europe/Paris", delivery_time="09:00", language="fr-FR"))
                assert db.scalar(select(func.count()).select_from(NotificationDelivery)) == 0
                assert db.scalar(select(func.count()).select_from(View)) == 0
                assert db.execute(select(User.__table__).order_by(User.id)).all() == before
                service.remove_subscription(db, other, "https://web.push.apple.com/foreign")
                assert db.scalar(select(func.count()).select_from(PushSubscription)) == 1
                db.get(NotificationPreference, owner).enabled = True
                db.commit()
            # Send-time consent controls already queued jobs, never a stored title snapshot.
            push.return_value = 201
            with Session(engine) as db:
                service.save_preferences(db, owner, NotificationSettingsInput(enabled=True, show_details=True, timezone="Europe/Paris", delivery_time="09:00", language="fr-FR"))
                # Old clients omit the new field: they must not silently reset consent.
                service.save_preferences(db, owner, NotificationSettingsInput(enabled=True, timezone="Europe/Paris", delivery_time="09:00", language="fr-FR"))
                assert service.preference_state(db, owner).show_details is True
            tick(now)
            assert push.call_args.kwargs["releases"] == [{"title": "Une série privée", "episode": "S01 E01"}]
            with Session(engine) as db:
                job = db.scalar(select(NotificationDelivery))
                job.status = "pending"
                job.next_attempt_at = now
                db.commit()
                service.save_preferences(db, owner, NotificationSettingsInput(enabled=True, show_details=False, timezone="Europe/Paris", delivery_time="09:00", language="fr-FR"))
            tick(now)
            assert push.call_args.kwargs["releases"] is None
            with Session(engine) as db:
                job = db.scalar(select(NotificationDelivery))
                job.status = "pending"
                job.next_attempt_at = now
                db.add(ShowExclusion(user_id=owner, tmdb_id=42, title="Fixture", poster_path=""))
                db.commit()
            before_cancel = push.call_count
            tick(now)
            assert push.call_count == before_cancel, "A queued job must recheck real release eligibility before sending"
            with Session(engine) as db:
                assert db.scalar(select(NotificationDelivery)).status == "cancelled"
                db.delete(db.get(ShowExclusion, (owner, 42)))
                job = db.scalar(select(NotificationDelivery))
                job.status = "pending"
                job.next_attempt_at = now
                db.commit()
            push.return_value = 410
            tick(now)
            with Session(engine) as db:
                assert db.scalar(select(func.count()).select_from(PushSubscription)) == 0
                assert db.scalar(select(func.count()).select_from(NotificationDelivery)) == 0
        with engine.begin() as db, patch.object(details_migration, "op", Operations(MigrationContext.configure(db))):
            details_migration.downgrade()
            details_migration.upgrade()
            assert db.execute(text("SELECT show_details FROM notification_preference")).scalar_one() is False
        with engine.begin() as db, patch.object(details_migration, "op", Operations(MigrationContext.configure(db))):
            details_migration.downgrade()
        with engine.begin() as db, patch.object(migration, "op", Operations(MigrationContext.configure(db))):
            migration.downgrade()
            migration.upgrade()
        with engine.begin() as db, patch.object(details_migration, "op", Operations(MigrationContext.configure(db))):
            details_migration.upgrade()
        print("Notification PostgreSQL rehearsal passed: additive DDL/default-off details consent, preserved preferences/users/history, owner isolation, DST-local schedule, concurrent daily deduplication, silent no-release days, send-time details consent/revocation, watched/excluded filtering, bounded retries, midnight expiry, opt-out, expired endpoint cleanup and downgrade/re-upgrade.")
    finally:
        if engine:
            engine.dispose()
        subprocess.run(["docker", "stop", name], check=True, capture_output=True)


if __name__ == "__main__":
    run()
