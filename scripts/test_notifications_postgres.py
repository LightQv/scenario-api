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
        now = datetime(2026, 10, 25, 8, 0, tzinfo=timezone.utc)  # Paris fall-back day, 09:00 local.
        day = now.date()
        with Session(engine) as db:
            assert db.execute(select(User.__table__).order_by(User.id)).all() == before
            assert service.preference_state(db, owner).enabled is False
            db.add(NotificationPreference(user_id=owner, enabled=True, timezone="Europe/Paris", delivery_time="09:00", language="fr-FR"))
            db.add(PushSubscription(user_id=owner, endpoint_hash="a" * 64, encrypted_subscription="fixture-encrypted"))
            db.add(ShowProgress(user_id=owner, tmdb_id=42, caught_up_through=date(2026, 10, 24)))
            db.add(ReleaseCatalog(media_type="tv", tmdb_id=42, language="fr-FR", next_refresh_at=now, payload={
                "id": 42, "seasons": [{"season_number": 1}], "season/1": {"episodes": [{"episode_number": 1, "air_date": day.isoformat()}]},
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
            tick(now + timedelta(hours=1))
            assert push.call_count == 1
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
            tick(now + timedelta(days=1))
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
            push.return_value = 410
            tick(now)
            with Session(engine) as db:
                assert db.scalar(select(func.count()).select_from(PushSubscription)) == 0
                assert db.scalar(select(func.count()).select_from(NotificationDelivery)) == 0
        with engine.begin() as db, patch.object(migration, "op", Operations(MigrationContext.configure(db))):
            migration.downgrade()
            migration.upgrade()
        print("Notification PostgreSQL rehearsal passed: additive DDL, preserved users/history, owner isolation, DST-local schedule, concurrent daily deduplication, watched/excluded filtering, bounded retries, midnight expiry, opt-out, expired endpoint cleanup and downgrade/re-upgrade.")
    finally:
        if engine:
            engine.dispose()
        subprocess.run(["docker", "stop", name], check=True, capture_output=True)


if __name__ == "__main__":
    run()
