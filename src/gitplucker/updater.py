"""The Updater orchestrator — the one object a host app talks to.

Typical use::

    updater = Updater(config)
    for plan in updater.check():          # dry run, safe to show a user
        if plan.has_update and not plan.conflicts:
            result = updater.apply(plan)   # backup + write + install deps
        else:
            updater.discard(plan)          # drop the temp download

Everything else (sources, merge, strategies, triggers) is wired from ``config``.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from . import events as ev
from .backend.github_api import GitHubClient
from .config import RepoSubscription, UpdaterConfig
from .deps import install_requirements, resolve_dependencies, scan_imports
from .errors import RepoNotAllowedError
from .events import EventEmitter
from .fsutil import is_text_file, list_files
from .models import Channel, ChangeType, UpdatePlan, ApplyResult
from .planner import build_file_plan
from .sources import ReleaseSource, SourceZipSource
from .state import StateStore
from .strategies import get_strategy
from .version import is_newer


class Updater:
    def __init__(self, config: UpdaterConfig) -> None:
        self.config = config
        self.events = EventEmitter()
        self.client = GitHubClient(
            allowed_repos=config.allowed_repos,
            token=config.token,
            api_base=config.api_base,
        )
        self.state = StateStore(config.state_dir)
        config.state_dir.mkdir(parents=True, exist_ok=True)
        (config.state_dir / "work").mkdir(parents=True, exist_ok=True)

    # -- public: checking -------------------------------------------------
    def check(self) -> list[UpdatePlan]:
        """Dry-run every subscription × branch. Returns one plan per pair."""
        plans: list[UpdatePlan] = []
        for sub in self.config.subscriptions:
            for branch in sub.branches:
                plans.append(self.check_one(sub, branch))
        return plans

    def check_repo(self, repo: str, branch: str | None = None) -> UpdatePlan:
        if not self.config.is_allowed(repo):
            raise RepoNotAllowedError(f"repo {repo!r} is not allowlisted")
        sub = self.config.subscription_for(repo, branch)
        if sub is None:
            sub = RepoSubscription(repo=repo, branches=[branch or "main"])
        return self.check_one(sub, branch or sub.branches[0])

    def check_one(self, sub: RepoSubscription, branch: str) -> UpdatePlan:
        self.events.emit(ev.CHECK_START, repo=sub.repo, branch=branch)
        current = self.state.get_version(sub.repo, branch)
        workdir = Path(tempfile.mkdtemp(prefix="gp-", dir=self.config.state_dir / "work"))
        source = self._source_for(sub)

        def _progress(recv: int, total: int) -> None:
            self.events.emit(ev.DOWNLOAD_PROGRESS, repo=sub.repo, received=recv, total=total)

        fetched = source.fetch(self.client, sub, branch, workdir, _progress)

        plan = UpdatePlan(
            repo=sub.repo, branch=branch, channel=sub.channel,
            current_version=current, target_version=fetched.version,
            release_notes=fetched.release_notes,
        )
        plan._workdir = workdir
        plan._subscription = sub
        plan._payload_root = fetched.files_root
        plan._base_root = self.state.base_dir(sub.repo, branch)

        version_bump = is_newer(fetched.version, current)

        if fetched.is_package:
            plan._is_package = True
            plan._package_path = fetched.package_path
            plan.has_update = version_bump
        else:
            changes, ops, warnings = build_file_plan(
                self.config, sub, branch, fetched.files_root, self.state
            )
            plan.file_changes = changes
            plan._ops = ops
            plan.warnings.extend(warnings)

            if sub.channel is Channel.PYTHON_SOURCE:
                req_path = None
                if self.config.requirements_file:
                    req_path = self.config.install_root / self.config.requirements_file
                deps = resolve_dependencies(
                    fetched.files_root, req_path,
                    known_modules=self.state.get_known_modules(sub.repo, branch),
                )
                plan.dependency_changes = deps
                for d in deps:
                    self.events.emit(ev.DEP_DETECTED, requirement=d.requirement)

            has_file_work = any(op.kind for op in ops)
            plan.has_update = bool(version_bump or has_file_work or plan.dependency_changes)

        self.events.emit(ev.CHECK_DONE, repo=sub.repo, branch=branch, has_update=plan.has_update)
        return plan

    def has_update_available(self, repo: str, branch: str = "main") -> bool:
        """Cheap version-only probe (no download) for background polling."""
        if not self.config.is_allowed(repo):
            return False
        sub = self.config.subscription_for(repo, branch) or RepoSubscription(repo, [branch])
        current = self.state.get_version(repo, branch)
        try:
            if sub.channel is Channel.RELEASE:
                rel = self.client.get_latest_release(repo)
                target = rel.tag if rel else None
            else:
                sha, date = self.client.get_branch_head(repo, branch)
                target = f"{date[:10]}+{sha[:7]}" if date else sha[:7]
        except Exception:
            return False
        return bool(target) and is_newer(target, current)

    # -- public: applying -------------------------------------------------
    def apply(self, plan: UpdatePlan, only=None) -> ApplyResult:
        """Apply a checked plan.

        ``only`` — optional iterable of relative paths (a subset of
        ``plan.changed_paths``) to restrict the update to just those files. When
        given, unselected file changes are skipped, deletions of unselected
        files are skipped, and dependencies are only installed if the file that
        introduced them was selected. ``None`` applies everything.
        """
        if not plan.has_update:
            self.discard(plan)
            return ApplyResult(plan.repo, plan.branch, success=True,
                               message="already up to date")

        plan._selected = set(only) if only is not None else None
        partial = plan._selected is not None

        sub: RepoSubscription = plan._subscription  # type: ignore[assignment]
        strategy = get_strategy(self.config.apply_strategy)
        result = strategy.apply(self.config, plan, self.events, self.state)

        # Install dependencies (python-source only), after files are in place.
        # On a partial apply, only install deps whose introducing file was chosen.
        if (result.success and sub.channel is Channel.PYTHON_SOURCE
                and self.config.auto_install_deps and plan.dependency_changes):
            deps = plan.dependency_changes
            if partial:
                deps = [d for d in deps
                        if not d.source_file or d.source_file in plan._selected]
            reqs = [d.requirement for d in deps]
            if reqs:
                ok, out = install_requirements(reqs)
                for r in reqs:
                    self.events.emit(ev.DEP_INSTALL, requirement=r, ok=ok)
                result.installed_deps.extend(reqs)
                if not ok:
                    result.message += f"\n[deps] pip reported errors:\n{out[-1000:]}"

        # Record the new baseline so the next merge has a common ancestor.
        # A partial apply must NOT overwrite the whole baseline (unselected files
        # weren't updated), so the version/base snapshot is only advanced on a
        # full apply. Partial applies stay on the previous baseline version.
        if result.success and not partial and not plan._is_package and plan._payload_root:
            payload_files = list_files(plan._payload_root, sub.include_globs, sub.exclude_globs)
            self.state.snapshot_base(sub.repo, plan.branch, plan._payload_root, payload_files)
            self.state.set_known_modules(
                sub.repo, plan.branch, set(scan_imports(plan._payload_root).keys())
            )
        if result.success and not partial and plan.target_version:
            self.state.set_version(sub.repo, plan.branch, plan.target_version)
        if partial:
            result.message += "  (partial update — version marker unchanged)"

        self.events.emit(ev.APPLY_DONE, repo=plan.repo, branch=plan.branch, success=result.success)
        self.discard(plan)
        return result

    def install_dependencies(self, plan: UpdatePlan) -> tuple[bool, str]:
        """Install a plan's detected dependencies without touching files."""
        reqs = [d.requirement for d in plan.dependency_changes]
        return install_requirements(reqs)

    def preview_change(self, plan: UpdatePlan, relpath: str, context: int = 3) -> str:
        """Return a unified diff of what applying ``relpath`` would do.

        Lets a host show the exact change for review before selecting a file.
        Returns a human-readable note for binary files or when there's nothing
        to preview.
        """
        import difflib

        op = next((o for o in plan._ops if o.relpath == relpath), None)
        if op is None:
            return f"(no change for {relpath})"

        install_path = self.config.install_root / relpath

        def _read(path: Path) -> str | None:
            if not path.exists():
                return ""
            if not is_text_file(path):
                return None
            return path.read_text(encoding="utf-8", errors="replace")

        old = _read(install_path)
        if op.kind == "delete":
            new = ""
        elif op.kind == "write":
            new = op.text or ""
        else:  # copy
            src = op.src
            if src is None or (src.exists() and not is_text_file(src)):
                new = None
            else:
                new = src.read_text(encoding="utf-8", errors="replace") if src.exists() else ""

        if old is None or new is None:
            return f"(binary file — {op.kind}; no text diff for {relpath})"

        diff = difflib.unified_diff(
            old.splitlines(keepends=True), new.splitlines(keepends=True),
            fromfile=f"current/{relpath}", tofile=f"updated/{relpath}", n=context,
        )
        text = "".join(diff)
        return text or f"(no textual difference for {relpath})"

    # -- rollback / snapshots ---------------------------------------------
    def list_snapshots(self, repo: str, branch: str) -> list[dict]:
        """Rollback points for repo/branch, newest first (full traceback history)."""
        if not self.config.is_allowed(repo):
            return []
        out: list[dict] = []
        for d in self.state.list_backups(repo, branch):
            m = self.state.read_manifest(d)
            if not m:
                continue
            out.append({
                "path": d,
                "created": m.get("created"),
                "version_before": m.get("version_before"),
                "version_after": m.get("version_after"),
                "partial": m.get("partial", False),
                "files": len(m.get("entries", [])),
            })
        return out

    def rollback(self, repo: str, branch: str, snapshot=None) -> ApplyResult:
        """Revert the latest (or a given) applied update from its snapshot.

        Restores overwritten/deleted files from the backup and removes files the
        update newly added, then rewinds the stored version marker. The snapshot
        itself is kept (history is never pruned) so you can still trace back.
        """
        if not self.config.is_allowed(repo):
            raise RepoNotAllowedError(f"repo {repo!r} is not allowlisted")
        snaps = self.state.list_backups(repo, branch)
        if not snaps:
            return ApplyResult(repo, branch, success=False, message="no snapshot to revert")
        backup_dir = Path(snapshot) if snapshot else snaps[0]
        manifest = self.state.read_manifest(backup_dir)
        if not manifest:
            return ApplyResult(repo, branch, success=False,
                               message=f"snapshot manifest missing in {backup_dir}")

        root = self.config.install_root
        files_root = backup_dir / "files"
        restored: list[str] = []
        errors: list[str] = []
        for entry in manifest.get("entries", []):
            rel = entry["relpath"]
            target = root / rel
            try:
                if entry.get("existed_before"):
                    src = files_root / rel
                    if src.exists():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, target)
                        restored.append(rel)
                else:
                    if target.exists():           # update added it -> remove it
                        target.unlink()
                        restored.append(rel)
            except OSError as e:
                errors.append(f"{rel}: {e}")

        version_before = manifest.get("version_before")
        self.state.set_version(repo, branch, version_before)
        # The merge base now reflects a version we just rewound past; drop it so
        # the next check re-establishes a clean baseline instead of mis-merging.
        try:
            base = self.state.base_dir(repo, branch)
            if base.exists():
                shutil.rmtree(base, ignore_errors=True)
        except OSError:
            pass

        self.events.emit(ev.ROLLBACK, path=str(backup_dir))
        result = ApplyResult(
            repo, branch, success=not errors, backup_path=backup_dir,
            message=f"reverted {len(restored)} file(s) to "
                    f"{version_before or 'the pre-update state'}",
        )
        if errors:
            result.message += f"; {len(errors)} error(s): " + "; ".join(errors[:5])
        return result

    # -- housekeeping -----------------------------------------------------
    def discard(self, plan: UpdatePlan) -> None:
        """Delete the temp download backing a plan. Safe to call twice."""
        if plan._workdir and Path(plan._workdir).exists():
            shutil.rmtree(plan._workdir, ignore_errors=True)
        plan._workdir = None

    def _source_for(self, sub: RepoSubscription):
        if sub.channel is Channel.RELEASE:
            return ReleaseSource()
        return SourceZipSource()
