"""Update-source abstraction and shared zip-extraction helpers.

An :class:`UpdateSource` turns a subscription + branch into a
:class:`FetchResult`: a folder on disk containing the incoming version of the
app, plus a version label and release notes. Everything downstream (diffing,
merging, applying) is source-agnostic.
"""

from __future__ import annotations

import zipfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from ..backend.github_api import GitHubClient
from ..config import RepoSubscription
from ..errors import SourceError


@dataclass
class FetchResult:
    version: str
    files_root: Path            # directory whose contents map onto install_root
    ref: str = ""               # sha/tag actually fetched
    release_notes: str = ""
    is_package: bool = False    # True when files_root holds a wheel/sdist, not a tree
    package_path: Path | None = None


class UpdateSource(ABC):
    @abstractmethod
    def fetch(
        self,
        client: GitHubClient,
        sub: RepoSubscription,
        branch: str,
        workdir: Path,
        progress=None,
    ) -> FetchResult:
        ...


def extract_zip(zip_path: Path, dest: Path) -> Path:
    """Extract ``zip_path`` into ``dest`` and return the effective root.

    GitHub zipballs wrap everything in a single ``owner-repo-<sha>/`` folder; we
    transparently descend into it so callers always get the repo root.
    """
    dest.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(dest)
    except zipfile.BadZipFile as e:
        raise SourceError(f"downloaded file is not a valid zip: {zip_path}") from e

    entries = [p for p in dest.iterdir() if p.name not in (".", "..")]
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return dest


def apply_subdir(root: Path, subdir: str) -> Path:
    if not subdir:
        return root
    target = root / subdir
    if not target.is_dir():
        raise SourceError(f"source_subdir {subdir!r} not found in payload")
    return target
