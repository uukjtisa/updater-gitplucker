"""RELEASE channel: fetch the latest GitHub Release.

Picks the first asset matching ``asset_pattern`` (default ``*.zip``); if the
release has no matching asset it falls back to the auto-generated source
zipball. A ``.whl``/``.tar.gz`` asset is passed through as a package payload so
the PACKAGE apply strategy can pip-install it directly.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path

from ..backend.github_api import GitHubClient
from ..config import RepoSubscription
from ..errors import SourceError
from .base import FetchResult, UpdateSource, apply_subdir, extract_zip

_PACKAGE_SUFFIXES = (".whl", ".tar.gz")


class ReleaseSource(UpdateSource):
    def __init__(self, include_prerelease: bool = False) -> None:
        self.include_prerelease = include_prerelease

    def fetch(self, client, sub: RepoSubscription, branch, workdir, progress=None) -> FetchResult:
        rel = client.get_latest_release(sub.repo, self.include_prerelease)
        if rel is None:
            raise SourceError(f"{sub.repo} has no releases")

        asset = self._match_asset(rel.assets, sub.asset_pattern)
        if asset:
            name = asset["name"]
            dest = workdir / name
            url = asset.get("url") or asset.get("browser_download_url")
            client.download(sub.repo, url, dest, progress)
            if name.endswith(_PACKAGE_SUFFIXES):
                return FetchResult(
                    version=rel.tag, files_root=workdir, ref=rel.tag,
                    release_notes=rel.body, is_package=True, package_path=dest,
                )
            root = extract_zip(dest, workdir / "extracted")
            return FetchResult(rel.tag, apply_subdir(root, sub.source_subdir),
                               rel.tag, rel.body)

        # Fallback: source zipball of the tagged release.
        if not rel.zipball_url:
            raise SourceError(f"{sub.repo} release {rel.tag} has no usable asset or zipball")
        zpath = workdir / "release.zip"
        client.download(sub.repo, rel.zipball_url, zpath, progress)
        root = extract_zip(zpath, workdir / "extracted")
        return FetchResult(rel.tag, apply_subdir(root, sub.source_subdir), rel.tag, rel.body)

    @staticmethod
    def _match_asset(assets: list[dict], pattern: str) -> dict | None:
        for a in assets:
            if fnmatch.fnmatch(a.get("name", ""), pattern):
                return a
        return None
