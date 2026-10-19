"""Bounded background worker for durable public release catalogue jobs."""

import asyncio
from time import monotonic

from app.core.logger import log
from app.database.session import SessionLocal
from app.services.release_catalog_service import claim_catalog, fetch_catalog, publish_catalog, seed_catalogs
from app.services.progress_action_service import drain_ready_actions


class ReleaseCatalogScheduler:
    """Use isolated sessions and database leases, not request threads or private caches."""

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._stop: asyncio.Event = asyncio.Event()
        self._seed_after: float = 0
        self._seed_lock: asyncio.Lock = asyncio.Lock()

    def start(self) -> None:
        """Start one bounded worker loop; database leases coordinate multiple processes."""
        if self._task is None or self._task.done():
            self._stop = asyncio.Event()
            self._seed_lock = asyncio.Lock()
            self._task = asyncio.create_task(self._workers(), name="release-catalog-worker")

    async def stop(self) -> None:
        """Let the current bounded fetch finish before shutting down its worker."""
        self._stop.set()
        if self._task is not None:
            await self._task
            self._task = None

    def _tick(self) -> bool:
        """Seed hourly, lease one job, fetch without holding a database connection."""
        with SessionLocal() as db:
            drain_ready_actions(db)
            identity = claim_catalog(db)
        if identity is None:
            return False
        payload = None
        try:
            payload = fetch_catalog(*identity[:3])
        except Exception:  # Keep the worker alive; no private data or tokens in logs.
            log.warning("Release catalogue refresh failed; last good snapshot retained")
        with SessionLocal() as db:
            publish_catalog(db, identity, payload)
            drain_ready_actions(db)
        return True

    def _seed(self) -> None:
        """Discover public jobs independently from the bounded network consumers."""
        with SessionLocal() as db:
            seed_catalogs(db)

    async def _workers(self) -> None:
        """Run three bounded consumers, sharing database leases across processes."""
        await asyncio.gather(*(self._run() for _ in range(3)))

    async def _run(self) -> None:
        """Keep work off the event loop; prioritize interactive misses over scheduled work."""
        while not self._stop.is_set():
            worked: bool = False
            try:
                async with self._seed_lock:
                    if monotonic() >= self._seed_after:
                        await asyncio.to_thread(self._seed)
                        self._seed_after = monotonic() + 3600
                worked = await asyncio.to_thread(self._tick)
            except Exception:
                log.warning("Release catalogue worker unavailable; retrying")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=0.5 if worked else 5)
            except TimeoutError:
                pass


release_catalog_scheduler: ReleaseCatalogScheduler = ReleaseCatalogScheduler()
