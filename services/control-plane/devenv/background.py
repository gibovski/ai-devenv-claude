"""Periodic maintenance: lease expiry, done checks, worker supervision, MCP config refresh."""

import logging
import threading
import time
from collections.abc import Callable

log = logging.getLogger("devenv.background")


class Loop:
    def __init__(self, interval: float = 15.0):
        self.interval = interval
        self.jobs: list[tuple[str, Callable[[], None], float]] = []
        self._last: dict[str, float] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def add(self, name: str, fn: Callable[[], None], every: float | None = None) -> None:
        self.jobs.append((name, fn, every or self.interval))

    def tick(self) -> None:
        now = time.monotonic()
        for name, fn, every in self.jobs:
            if now - self._last.get(name, -1e9) < every:
                continue
            self._last[name] = now
            try:
                fn()
            except Exception:  # noqa: BLE001
                log.exception("background job %s failed", name)

    def start(self) -> None:
        def run():
            while not self._stop.wait(1.0):
                self.tick()

        self._thread = threading.Thread(target=run, name="devenv-background", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
