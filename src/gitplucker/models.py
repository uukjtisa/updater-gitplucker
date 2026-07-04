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
    is_text: bool = True            # False for binary files (no reviewable text diff)


@dataclass
class DependencyChange:
    """A change to a project's Python dependencies between the installed version
    and the incoming one.

    The primary source is a requirements.txt DIFF (added / removed / changed):
    ``change_kind`` says which, and ``old_spec`` / ``new_spec`` give the version
    specifiers on each side. The legacy import-scan path (``resolve_dependencies``)
    fills the same object with ``change_kind='added'`` and a ``module`` name.
    """

    module: str                 # top-level import name (import-scan path); "" for a diff
    package: str                # pip package / requirement name
    spec: str = ""              # version spec to INSTALL, e.g. ">=2.1.0" ("" = unpinned)
    is_new: bool = True         # convenience: True for an added dependency
    reason: str = ""            # human explanation, e.g. "0.5.0 -> 0.6.0"
    source_file: str = ""       # payload-relative file the change came from
    change_kind: str = "added"  # added | removed | changed | unchanged
    old_spec: str = ""          # previous version spec ("" when added)
    new_spec: str = ""          # incoming version spec ("" when removed)

    @property
    def requirement(self) -> str:
        """The pip requirement string to install (package + install spec)."""
        return f"{self.package}{self.spec}"

    @property
    def should_install(self) -> bool:
        """Added and changed deps get installed; removed/unchanged never do."""
        return self.change_kind in ("added", "changed")

    def describe(self) -> str:
        """One-line, human summary for a UI row."""
        if self.change_kind == "added":
            return f"+ {self.package}{self.new_spec}  (new)"
        if self.change_kind == "removed":
            return f"- {self.package}{self.old_spec}  (removed upstream)"
        if self.change_kind == "changed":
            return (f"~ {self.package}: {self.old_spec or 'unpinned'} "
                    f"-> {self.new_spec or 'unpinned'}")
        return f"  {self.package}{self.new_spec}"


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
    _selected: set | None = None                      # None = all; else only these relpaths
    _package_path: Path | None = None                 # RELEASE wheel/sdist, if any
    _is_package: bool = False
    _workdir: Path | None = None                      # temp dir to clean after apply
    _subscription: object | None = None               # RepoSubscription used

    @property
    def conflicts(self) -> list[FileChange]:
        return [f for f in self.file_changes if f.change is ChangeType.CONFLICT]

    @property
    def new_dependencies(self) -> list[DependencyChange]:
        """Newly added dependencies (change_kind == 'added')."""
        return [d for d in self.dependency_changes if d.change_kind == "added"]

    @property
    def changed_dependencies(self) -> list[DependencyChange]:
        return [d for d in self.dependency_changes if d.change_kind == "changed"]

    @property
    def removed_dependencies(self) -> list[DependencyChange]:
        """Dependencies dropped upstream — reported only, never auto-uninstalled."""
        return [d for d in self.dependency_changes if d.change_kind == "removed"]

    @property
    def deps_to_install(self) -> list[DependencyChange]:
        """The added + changed deps an apply would pip-install."""
        return [d for d in self.dependency_changes if d.should_install]

    def dependency_summary(self) -> str:
        """Compact one-liner, e.g. 'New: 2  -  Changed: 1  -  Removed: 0', or ''."""
        n, c, r = (len(self.new_dependencies), len(self.changed_dependencies),
                   len(self.removed_dependencies))
        if not (n or c or r):
            return ""
        return f"New: {n}  -  Changed: {c}  -  Removed: {r}"

    @property
    def changed_paths(self) -> list[str]:
        """Relative paths that an apply would actually write/delete (selectable)."""
        return [op.relpath for op in self._ops]

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
