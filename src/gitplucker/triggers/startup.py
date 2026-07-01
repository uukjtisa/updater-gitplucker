"""Startup trigger: run once at app launch, prompting via a callback.

Wire ``on_update`` to your UI. Return True to apply, False to skip. If you omit
it, updates are only reported (never auto-applied) unless ``auto_apply`` is set.
"""

from __future__ import annotations

from typing import Callable

from ..models import ApplyResult, UpdatePlan


class StartupTrigger:
    def __init__(self, updater) -> None:
        self.updater = updater

    def run(
        self,
        on_update: Callable[[UpdatePlan], bool] | None = None,
        auto_apply: bool = False,
    ) -> list[tuple[UpdatePlan, ApplyResult | None]]:
        out: list[tuple[UpdatePlan, ApplyResult | None]] = []
        for plan in self.updater.check():
            if not plan.has_update:
                self.updater.discard(plan)
                out.append((plan, None))
                continue
            approved = auto_apply
            if on_update is not None:
                approved = bool(on_update(plan))
            if approved:
                out.append((plan, self.updater.apply(plan)))
            else:
                self.updater.discard(plan)
                out.append((plan, None))
        return out
