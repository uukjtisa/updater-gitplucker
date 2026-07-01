"""Exception hierarchy for gitplucker.

Every error raised by the library derives from :class:`GitpluckerError`, so a
host application can catch the whole surface with a single ``except``.
"""

from __future__ import annotations


class GitpluckerError(Exception):
    """Base class for all gitplucker errors."""


class ConfigError(GitpluckerError):
    """The :class:`~gitplucker.config.UpdaterConfig` is invalid or inconsistent."""


class RepoNotAllowedError(GitpluckerError):
    """A repository was requested that is not in ``allowed_repos``.

    This is a hard security boundary: gitplucker will never fetch, download, or
    apply anything from a repo the host did not explicitly permit.
    """


class SourceError(GitpluckerError):
    """An update source failed to produce a usable payload."""


class GitHubAPIError(SourceError):
    """The GitHub REST API returned an error or unexpected response."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class MergeConflictError(GitpluckerError):
    """A merge produced conflicts and the policy was to abort."""


class ApplyError(GitpluckerError):
    """Applying an update failed; a rollback may have been attempted."""
