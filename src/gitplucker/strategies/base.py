"""Apply strategies and the shared transactional file-writer.

The writer stages a backup of every file it's about to touch and rolls the whole
batch back if any single op fails, so an interrupted update can't leave a
half-written app.
"""

from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from pathlib import Path

from .. import events as ev
from ..config import ApplyStrategy as StrategyName
from ..config import UpdaterConfig
from ..errors import ApplyError
from ..events import EventEmitter
from ..models import ApplyResult, UpdatePlan
from ..planner import FileOp
from ..state import StateStore


class ApplyStrategy(ABC):
    name: str = "base"

    @abstractmethod
    def apply(
        self,
        cfg: UpdaterConfig,
        plan: UpdatePlan,
        emitter: EventEmitter,
        state: StateStore,
    ) -> ApplyResult:
        ...


def _execute_ops(
    cfg: UpdaterConfig,
    plan: UpdatePlan,
    ops: list[FileOp],
    emitter: EventEmitter,
    state: StateStore,
    allow_delete: bool = True,
) -> ApplyResult:
    result = ApplyResult(repo=plan.repo, branch=plan.branch)
    root = cfg.install_root

    # Honor a user's file selection (None = apply everything).
    if plan._selected is not None:
        ops = [op for op in ops if op.relpath in plan._selected]
    backup_dir: Path | None = None
    if cfg.backup:
        backup_dir = state.new_backup_dir(plan.repo, plan.branch)
        result.backup_path = backup_dir
        emitter.emit(ev.BACKUP, path=str(backup_dir))

    touched: list[tuple[Path, Path | None]] = []  # (target, backup_copy or None if new)

    def stage_backup(target: Path) -> None:
        if not cfg.backup or backup_dir is None:
            return
        if target.exists():
            rel = target.relative_to(root)
            bpath = backup_dir / rel
            bpath.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, bpath)
            touched.append((target, bpath))
        else:
            touched.append((target, None))  # newly created -> remove on rollback

    try:
        for op in ops:
            target = root / op.relpath
            if op.kind == "delete":
                if not allow_delete:
                    continue
                stage_backup(target)
                if target.exists():
                    target.unlink()
                emitter.emit(ev.APPLY_FILE, path=op.relpath, change="delete")
            elif op.kind == "copy":
                stage_backup(target)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(op.src, target)
                emitter.emit(ev.APPLY_FILE, path=op.relpath, change="copy")
            elif op.kind == "write":
                stage_backup(target)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(op.text or "", encoding="utf-8")
                emitter.emit(ev.APPLY_FILE, path=op.relpath, change="write")
            result.applied_files.append(op.relpath)
    except Exception as e:
        _rollback(root, touched, emitter)
        result.rolled_back = True
        result.success = False
        result.message = f"apply failed, rolled back: {e}"
        emitter.emit(ev.ROLLBACK, path=str(backup_dir) if backup_dir else "")
        raise ApplyError(result.message) from e

    result.conflicts = [c.path for c in plan.conflicts]
    result.success = True
    result.message = f"applied {len(result.applied_files)} file operation(s)"
    return result


def _rollback(root: Path, touched: list[tuple[Path, Path | None]], emitter: EventEmitter) -> None:
    for target, backup in reversed(touched):
        try:
            if backup is None:
                if target.exists():
                    target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup, target)
        except OSError:
            pass


def get_strategy(name: str) -> ApplyStrategy:
    from .package import PackageStrategy
    from .selective import SelectiveStrategy
    from .whole_app import WholeAppStrategy

    mapping = {
        StrategyName.WHOLE_APP: WholeAppStrategy,
        StrategyName.SELECTIVE: SelectiveStrategy,
        StrategyName.PACKAGE: PackageStrategy,
    }
    cls = mapping.get(name)
    if cls is None:
        raise ApplyError(f"unknown apply strategy {name!r}")
    return cls()
