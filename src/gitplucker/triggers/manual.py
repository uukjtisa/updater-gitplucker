"""Manual trigger: check now, optionally auto-apply clean updates."""

from __future__ import annotations

from typing import Callable

from ..models import ApplyResult, UpdatePlan


class ManualTrigger:
    def __init__(self, updater) -> None:
        self.updater = updater

    def run(
        self,
        auto_apply: bool = False,
        should_apply: Callable[[UpdatePlan], bool] | None = None,
    ) -> list[tuple[UpdatePlan, ApplyResult | None]]:
        """Check every subscription; apply those the predicate approves.

        ``should_apply`` defaults to "apply when there's an update and no
        conflicts". Return pairs of ``(plan, result-or-None)``.
        """
        if should_apply is None:
            should_apply = lambda p: p.has_update and not p.conflicts
        out: list[tuple[UpdatePlan, ApplyResult | None]] = []
        for plan in self.updater.check():
            result = None
            if auto_apply and should_apply(plan):
                result = self.updater.apply(plan)
            else:
                self.updater.discard(plan)
            out.append((plan, result))
        return out
