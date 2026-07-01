"""Configuration objects — the whole behaviour of the updater is data-driven.

A host constructs an :class:`UpdaterConfig`, passes it to
:class:`~gitplucker.updater.Updater`, and never has to subclass anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .errors import ConfigError
from .models import Channel


class ConflictPolicy(str):
    MARK = "mark"        # write git-style conflict markers, keep going
    LOCAL = "local"      # keep the local version of a conflicted file
    REMOTE = "remote"    # take the remote version of a conflicted file
    ABORT = "abort"      # raise MergeConflictError


class ApplyStrategy(str):
    WHOLE_APP = "whole_app"   # replace the tracked tree, backup + rollback
    SELECTIVE = "selective"   # only paths matching include_globs
    PACKAGE = "package"       # pip-install the downloaded wheel/sdist


@dataclass
class RepoSubscription:
    """One repo the app follows, on one or more branches, via one channel."""

    repo: str                                  # "owner/name"
    branches: list[str] = field(default_factory=lambda: ["main"])
    channel: Channel = Channel.PYTHON_SOURCE
    # RELEASE channel: glob picking which asset to download (falls back to zipball).
    asset_pattern: str = "*.zip"
    # Only these paths (relative, glob) are considered part of the app payload.
    include_globs: list[str] = field(default_factory=lambda: ["**/*"])
    exclude_globs: list[str] = field(
        default_factory=lambda: [
            "**/.git/**", "**/__pycache__/**", "**/*.pyc",
            "**/.gitplucker/**", "**/.venv/**", "**/node_modules/**",
        ]
    )
    # Subfolder inside the repo that maps to install_root ("" == repo root).
    source_subdir: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.channel, str):
            self.channel = Channel(self.channel)
        if self.repo.count("/") != 1:
            raise ConfigError(f"repo must be 'owner/name', got {self.repo!r}")


@dataclass
class UpdaterConfig:
    """Top-level configuration.

    ``allowed_repos`` is the security allowlist: any subscription (or ad-hoc
    request) whose repo is not listed here is rejected before any network call.
    """

    install_root: Path
    subscriptions: list[RepoSubscription] = field(default_factory=list)
    allowed_repos: list[str] = field(default_factory=list)

    token: str | None = None                    # GitHub PAT for private repos / rate limits
    api_base: str = "https://api.github.com"

    apply_strategy: str = ApplyStrategy.WHOLE_APP
    selective_globs: list[str] = field(default_factory=list)  # used by SELECTIVE

    merge: bool = True                          # 3-way merge on python-source
    conflict_policy: str = ConflictPolicy.MARK
    auto_install_deps: bool = True
    requirements_file: str | None = "requirements.txt"  # relative to install_root
    backup: bool = True

    # Where gitplucker keeps its state (base snapshots, version manifest, backups).
    state_dir: Path | None = None

    def __post_init__(self) -> None:
        self.install_root = Path(self.install_root)
        if self.state_dir is None:
            self.state_dir = self.install_root / ".gitplucker"
        self.state_dir = Path(self.state_dir)

        allowed = set(self.allowed_repos)
        # A subscription implicitly requires its repo to be allowlisted.
        for sub in self.subscriptions:
            if sub.repo not in allowed:
                raise ConfigError(
                    f"subscription repo {sub.repo!r} is not in allowed_repos "
                    f"{sorted(allowed)!r}; add it explicitly to permit updates."
                )

    def is_allowed(self, repo: str) -> bool:
        return repo in set(self.allowed_repos)

    def subscription_for(self, repo: str, branch: str | None = None) -> RepoSubscription | None:
        for sub in self.subscriptions:
            if sub.repo == repo and (branch is None or branch in sub.branches):
                return sub
        return None
