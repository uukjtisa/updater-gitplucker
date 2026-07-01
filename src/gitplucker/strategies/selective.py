"""SELECTIVE: only apply ops whose path matches ``selective_globs``; never delete.

Good for updating just plugins/assets/scripts while leaving the rest of a
checkout (and any user data) untouched.
"""

from __future__ import annotations

from ..config import UpdaterConfig
from ..events import EventEmitter
from ..fsutil import glob_match
from ..models import ApplyResult, UpdatePlan
from ..state import StateStore
from .base import ApplyStrategy, _execute_ops


class SelectiveStrategy(ApplyStrategy):
    name = "selective"

    def apply(self, cfg: UpdaterConfig, plan: UpdatePlan, emitter: EventEmitter,
              state: StateStore) -> ApplyResult:
        globs = cfg.selective_globs or ["**/*"]
        ops = [op for op in plan._ops
               if op.kind != "delete" and glob_match(op.relpath, globs)]
        return _execute_ops(cfg, plan, ops, emitter, state, allow_delete=False)
