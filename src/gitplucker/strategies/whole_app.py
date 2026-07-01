"""WHOLE_APP: apply every planned op (add/modify/merge/delete) transactionally."""

from __future__ import annotations

from ..config import UpdaterConfig
from ..events import EventEmitter
from ..models import ApplyResult, UpdatePlan
from ..state import StateStore
from .base import ApplyStrategy, _execute_ops


class WholeAppStrategy(ApplyStrategy):
    name = "whole_app"

    def apply(self, cfg: UpdaterConfig, plan: UpdatePlan, emitter: EventEmitter,
              state: StateStore) -> ApplyResult:
        return _execute_ops(cfg, plan, plan._ops, emitter, state, allow_delete=True)
