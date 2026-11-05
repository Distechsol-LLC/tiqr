"""Scheduled sync and cleanup: the daemon the CLI never had, inside the one server process."""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from tiqr.core.service import TicketService

logger = logging.getLogger("tiqr.api")

SYNC_INTERVAL = 15
CLEANUP_INTERVAL = 3600


@dataclass(slots=True)
class _Job:
    name: str
    run: Callable[[], int]
    interval: float
    due: float


class Maintenance:
    """Runs due jobs on one background thread, starting with both due at startup.

    `lock` also serializes the on-demand sync and cleanup endpoints, so runs never overlap and
    a slower run cannot save an older event cursor over a newer one.
    """

    def __init__(
        self,
        service: TicketService,
        *,
        sync_interval: float = SYNC_INTERVAL,
        cleanup_interval: float = CLEANUP_INTERVAL,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.lock = threading.Lock()
        self._clock = clock
        now = clock()
        candidates = (
            _Job("sync", service.scheduled_sync, sync_interval, now),
            _Job("cleanup", service.scheduled_cleanup, cleanup_interval, now),
        )
        self._service = service
        self._jobs = [job for job in candidates if job.interval > 0]
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def run_due(self) -> float | None:
        """Run every job that is due; return seconds until the next one, or None if none run."""
        for job in self._jobs:
            if self._clock() < job.due:
                continue
            with self.lock:
                try:
                    count = job.run()
                except Exception:  # The next run retries; the server keeps going.
                    logger.exception("Scheduled %s failed", job.name)
                else:
                    if count:
                        logger.info("Scheduled %s processed %d", job.name, count)
            job.due = self._clock() + job.interval
        if not self._jobs:
            return None
        return max(0.0, min(job.due for job in self._jobs) - self._clock())

    def sync_soon(self, *delays: float) -> None:
        """Run a sync after each delay in seconds, on top of the scheduled ones.

        BioStar announces a scan a few seconds before it is searchable, so callers pass delays.
        """
        for delay in delays:
            timer = threading.Timer(delay, self._sync_now)
            timer.daemon = True
            timer.start()

    def _sync_now(self) -> None:
        if self._stop.is_set():
            return
        with self.lock:
            try:
                count = self._service.scheduled_sync()
            except Exception:  # The scheduled run retries.
                logger.exception("Live sync failed")
            else:
                if count:
                    logger.info("Live sync processed %d", count)

    def _loop(self) -> None:
        # The startup run happens even if stop() came first, so it is never silently skipped.
        while (delay := self.run_due()) is not None and not self._stop.wait(delay):
            pass

    @property
    def running(self) -> bool:
        """Whether the thread runs; with no jobs configured, there is nothing to run."""
        return not self._jobs or (self._thread is not None and self._thread.is_alive())

    def start(self) -> None:
        if self._jobs:
            self._thread = threading.Thread(target=self._loop, name="tiqr-maintenance", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """Ask the thread to stop, and wait for a run in progress to finish."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
