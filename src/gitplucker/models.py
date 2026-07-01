"""Plain data structures passed between gitplucker components and the host app.

These are intentionally dumb dataclasses/enums so a UI (PyQt, Compose bridge,
CLI) can inspect an :class:`UpdatePlan` and render it without importing any of
the machinery.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Channel(str, Enum):
    """How a subscription is updated."""

    RELEASE = "release"                # GitHub Releases + assets (versioned)
    SOURCE = "source"                  # raw source at a branch/tag (zipball)
    PYTHON_SOURCE = "python-source"    # source + 3-way merge + dependency detection


class ChangeType(str, Enum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    MERGED = "merged"        # remote + local changes reconciled cleanly
    CONFLICT = "conflict"    # remote + local touched the same lines
    UNCHANGED = "unchanged"


@dataclass
class FileChange:
    """One file's delta between the installed tree and the incoming payload."""

    path: str                      # relative to install_root, POSIX-style
    change: ChangeType
    remote_hash: str | None = None
    local_hash: str | None = None
    locally_modified: bool = False  # differs from the last applied base
    conflict_lines: int = 0
    note: str = ""


@dataclass
class DependencyChange:
    """A Python dependency the incoming version needs that isn't satisfied yet."""

    module: str                 # top-level import name seen in the code
    package: str                # pip package name to install
    spec: str = ""              # optional version spec, e.g. "==2.1.0"
    is_new: bool = True         # newly referenced vs. previous version
    reason: str = ""            # e.g. "imported in systema/core/net.py"

    @property
    def requirement(self) -> str:
        return f"{self.package}{self.spec}"


@dataclass
class UpdatePlan:
    """The full, inspectable result of a :meth:`Updater.check`.

    Nothing has been written yet — this is a dry run the host can show to a user
    (or an AI) before calling :meth:`Updater.apply`.
    """

    repo: str
    branch: str
    channel: Channel
    current_version: str | None
    target_version: str | None
    has_update: bool = False
    file_changes: list[FileChange] = field(default_factory=list)
    dependency_changes: list[DependencyChange] = field(default_factory=list)
    release_notes: str = ""
    warnings: list[str] = field(default_factory=list)
    # Internal handles the matching apply() uses; opaque to callers.
    _payload_root: Path | None = None
    _base_root: Path | None = None
    _ops: list = field(default_factory=list)          # list[planner.FileOp]
    _package_path: Path | None = None                 # RELEASE wheel/sdist, if any
    _is_package: bool = False
    _workdir: Path | None = None                      # temp dir to clean after apply
    _subscription: object | None = None               # RepoSubscription used

    @property
    def conflicts(self) -> list[FileChange]:
        return [f for f in self.file_changes if f.change is ChangeType.CONFLICT]

    @property
    def new_dependencies(self) -> list[DependencyChange]:
        return [d for d in self.dependency_changes if d.is_new]

    def summary(self) -> str:
        added = sum(1 for f in self.file_changes if f.change is ChangeType.ADDED)
        mod = sum(1 for f in self.file_changes if f.change in
                  (ChangeType.MODIFIED, ChangeType.MERGED))
        return (
            f"{self.repo}@{self.branch} [{self.channel.value}] "
            f"{self.current_version or '—'} -> {self.target_version or '—'}: "
            f"+{added} ~{mod} files, {len(self.conflicts)} conflicts, "
            f"{len(self.new_dependencies)} new deps"
        )


@dataclass
class ApplyResult:
    repo: str
    branch: str
    success: bool = False
    applied_files: list[str] = field(default_factory=list)
    installed_deps: list[str] = field(default_factory=list)
    backup_path: Path | None = None
    rolled_back: bool = False
    conflicts: list[str] = field(default_factory=list)
    message: str = ""
