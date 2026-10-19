"""Scheduled sync and cleanup: the daemon the CLI never had, inside the one server process."""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from tiqr.core.service import TicketService

logger = logging.getLogger("tiqr.api")


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
        sync_interval: float,
        cleanup_interval: float,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.lock = threading.Lock()
        self._clock = clock
        now = clock()
        candidates = (
            _Job("sync", service.scheduled_sync, sync_interval, now),
            _Job("cleanup", service.scheduled_cleanup, cleanup_interval, now),
        )
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
