"""Background trigger: poll on a timer thread, notify via callback.

Uses the cheap ``has_update_available`` version probe on each tick and only does
a full ``check`` (download + diff) when the probe says something changed, to
keep idle polling light. Call :meth:`start` / :meth:`stop`.
"""

from __future__ import annotations

import threading
from typing import Callable

from ..models import ApplyResult, UpdatePlan


class BackgroundTrigger:
    def __init__(self, updater, interval_seconds: float = 3600.0) -> None:
        self.updater = updater
        self.interval = interval_seconds
        self._timer: threading.Timer | None = None
        self._stop = threading.Event()

    def start(
        self,
        on_update: Callable[[UpdatePlan], bool] | None = None,
        auto_apply: bool = False,
    ) -> None:
        self._stop.clear()
        self._schedule(on_update, auto_apply)

    def stop(self) -> None:
        self._stop.set()
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _schedule(self, on_update, auto_apply) -> None:
        if self._stop.is_set():
            return
        self._timer = threading.Timer(self.interval, self._tick, args=(on_update, auto_apply))
        self._timer.daemon = True
        self._timer.start()

    def _tick(self, on_update, auto_apply) -> None:
        try:
            for sub in self.updater.config.subscriptions:
                for branch in sub.branches:
                    if not self.updater.has_update_available(sub.repo, branch):
                        continue
                    plan = self.updater.check_repo(sub.repo, branch)
                    if not plan.has_update:
                        self.updater.discard(plan)
                        continue
                    approved = auto_apply
                    if on_update is not None:
                        approved = bool(on_update(plan))
                    if approved:
                        self.updater.apply(plan)
                    else:
                        self.updater.discard(plan)
        except Exception:
            pass  # never let a poll crash the host
        finally:
            self._schedule(on_update, auto_apply)
