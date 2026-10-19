"""Lifespan-managed single bounded notification worker; database locks coordinate replicas."""
import asyncio
from datetime import datetime, timezone

from app.core.logger import log
from app.database.session import SessionLocal
from app.services.notification_service import process_notifications


class NotificationScheduler:
    """Poll the durable outbox without unbounded tasks or external cron."""

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._stop: asyncio.Event = asyncio.Event()

    def start(self) -> None:
        """Start one consumer for this API process."""
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="release-notifications")

    async def stop(self) -> None:
        """Wait for in-flight bounded provider work before releasing the database."""
        self._stop.set()
        if self._task:
            await self._task
            self._task = None

    @staticmethod
    def tick() -> None:
        """Give this worker its own transaction/session, never a request session."""
        with SessionLocal() as db:
            process_notifications(db, datetime.now(timezone.utc))

    async def _run(self) -> None:
        """Check schedules once a minute; never log private endpoint/error contents."""
        while not self._stop.is_set():
            try:
                await asyncio.to_thread(self.tick)
            except Exception:
                log.warning("Release notification worker cycle failed; retrying next minute")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=60)
            except asyncio.TimeoutError:
                pass


notification_scheduler = NotificationScheduler()
