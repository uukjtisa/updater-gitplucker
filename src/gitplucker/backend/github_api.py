"""Zero-dependency GitHub REST client.

Uses only the stdlib (``urllib``) so the core library installs with no third
party packages. Every method enforces the repository allowlist: a repo that
was not explicitly permitted can never be contacted.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..errors import GitHubAPIError, RepoNotAllowedError

ProgressCb = Callable[[int, int], None]


@dataclass
class ReleaseInfo:
    tag: str
    name: str
    body: str
    prerelease: bool
    assets: list[dict] = field(default_factory=list)  # each: {name, browser_download_url, url, size}
    zipball_url: str = ""


class GitHubClient:
    def __init__(
        self,
        allowed_repos: set[str] | list[str],
        token: str | None = None,
        api_base: str = "https://api.github.com",
    ) -> None:
        self._allowed = set(allowed_repos)
        self._token = token
        self._api = api_base.rstrip("/")

    # -- allowlist gate ---------------------------------------------------
    def _guard(self, repo: str) -> None:
        if repo not in self._allowed:
            raise RepoNotAllowedError(
                f"repo {repo!r} is not allowlisted; refusing to contact GitHub."
            )

    def _headers(self, accept: str = "application/vnd.github+json") -> dict[str, str]:
        h = {
            "Accept": accept,
            "User-Agent": "gitplucker/0.1",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    def _get_json(self, url: str) -> dict | list:
        req = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise GitHubAPIError(f"GET {url} failed: {e.reason}", status=e.code) from e
        except urllib.error.URLError as e:
            raise GitHubAPIError(f"GET {url} failed: {e.reason}") from e

    # -- API surface ------------------------------------------------------
    def get_latest_release(self, repo: str, include_prerelease: bool = False) -> ReleaseInfo | None:
        self._guard(repo)
        if include_prerelease:
            data = self._get_json(f"{self._api}/repos/{repo}/releases")
            if not data:
                return None
            rel = data[0]  # releases come newest-first
        else:
            try:
                rel = self._get_json(f"{self._api}/repos/{repo}/releases/latest")
            except GitHubAPIError as e:
                if e.status == 404:
                    return None
                raise
        return ReleaseInfo(
            tag=rel.get("tag_name", ""),
            name=rel.get("name") or rel.get("tag_name", ""),
            body=rel.get("body", "") or "",
            prerelease=bool(rel.get("prerelease")),
            assets=rel.get("assets", []) or [],
            zipball_url=rel.get("zipball_url", ""),
        )

    def get_branch_head(self, repo: str, branch: str) -> tuple[str, str]:
        """Return ``(sha, iso_date)`` of the branch tip."""
        self._guard(repo)
        data = self._get_json(f"{self._api}/repos/{repo}/branches/{branch}")
        commit = data.get("commit", {})
        sha = commit.get("sha", "")
        date = (
            commit.get("commit", {}).get("committer", {}).get("date", "")
            or commit.get("commit", {}).get("author", {}).get("date", "")
        )
        return sha, date

    def list_commits(self, repo: str, branch: str, limit: int = 20) -> list[dict]:
        """Recent commits on ``branch``, newest first.

        Each item: ``{sha, message, date, author}``. Best-effort — returns []
        on any API error so callers can degrade gracefully.
        """
        self._guard(repo)
        try:
            data = self._get_json(
                f"{self._api}/repos/{repo}/commits?sha={branch}&per_page={int(limit)}")
        except GitHubAPIError:
            return []
        return [self._commit_row(c) for c in (data if isinstance(data, list) else [])]

    def compare_commits(self, repo: str, base: str, head: str, limit: int = 50) -> list[dict]:
        """Commits in ``base..head`` (what an update would bring), newest first.

        This is the "stacked commits" list — everything between the installed
        revision and the branch tip. Best-effort; returns [] on error.
        """
        self._guard(repo)
        try:
            data = self._get_json(f"{self._api}/repos/{repo}/compare/{base}...{head}")
        except GitHubAPIError:
            return []
        commits = data.get("commits", []) if isinstance(data, dict) else []
        rows = [self._commit_row(c) for c in commits]
        return list(reversed(rows))[:int(limit)]   # API returns oldest-first

    @staticmethod
    def _commit_row(c: dict) -> dict:
        commit = c.get("commit", {}) or {}
        author = commit.get("author", {}) or {}
        committer = commit.get("committer", {}) or {}
        return {
            "sha": c.get("sha", ""),
            "message": (commit.get("message", "") or "").strip(),
            "date": committer.get("date", "") or author.get("date", ""),
            "author": author.get("name", "") or (c.get("author", {}) or {}).get("login", ""),
        }

    def download(self, repo: str, url: str, dest: Path, progress: ProgressCb | None = None) -> Path:
        """Download a URL (asset or zipball) to ``dest``, enforcing the allowlist."""
        self._guard(repo)
        # Asset API URLs need the octet-stream Accept header to get the binary.
        accept = "application/octet-stream" if "/releases/assets/" in url else "*/*"
        req = urllib.request.Request(url, headers=self._headers(accept))
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with urllib.request.urlopen(req) as resp, open(dest, "wb") as fh:
                total = int(resp.headers.get("Content-Length") or 0)
                received = 0
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    fh.write(chunk)
                    received += len(chunk)
                    if progress:
                        progress(received, total)
        except urllib.error.HTTPError as e:
            raise GitHubAPIError(f"download {url} failed: {e.reason}", status=e.code) from e
        except urllib.error.URLError as e:
            raise GitHubAPIError(f"download {url} failed: {e.reason}") from e
        return dest

    def zipball_url(self, repo: str, ref: str) -> str:
        self._guard(repo)
        return f"{self._api}/repos/{repo}/zipball/{ref}"
