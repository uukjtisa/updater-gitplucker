"""SOURCE / PYTHON_SOURCE channel: fetch raw source at a branch tip.

Downloads the branch zipball (no formal release needed) and stamps a version
from the commit date + short sha, e.g. ``2026-07-01+1a2b3c4``, which
:mod:`gitplucker.version` orders chronologically.
"""

from __future__ import annotations

from pathlib import Path

from ..backend.github_api import GitHubClient
from ..config import RepoSubscription
from .base import FetchResult, UpdateSource, apply_subdir, extract_zip


class SourceZipSource(UpdateSource):
    def fetch(self, client, sub: RepoSubscription, branch, workdir, progress=None) -> FetchResult:
        sha, date = client.get_branch_head(sub.repo, branch)
        stamp = f"{date[:10]}+{sha[:7]}" if date else (sha[:7] or branch)
        url = client.zipball_url(sub.repo, branch)
        zpath = workdir / "source.zip"
        client.download(sub.repo, url, zpath, progress)
        root = extract_zip(zpath, workdir / "extracted")
        return FetchResult(
            version=stamp,
            files_root=apply_subdir(root, sub.source_subdir),
            ref=sha,
            release_notes=f"source @ {branch} ({stamp})",
        )
