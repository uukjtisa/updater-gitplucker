"""Tiny self-contained semantic-version helper (no external deps).

Only the subset gitplucker needs: parse ``[v]MAJOR.MINOR.PATCH[-pre][+build]``
and compare. Non-semver tags fall back to a string/date comparison so that
source channels keyed on commit shas or dates still order sensibly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SEMVER = re.compile(
    r"^v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?:-(?P<pre>[0-9A-Za-z.-]+))?(?:\+(?P<build>[0-9A-Za-z.-]+))?$"
)


@dataclass(frozen=True, order=False)
class Version:
    major: int
    minor: int
    patch: int
    pre: tuple[object, ...] = ()
    raw: str = ""

    @classmethod
    def parse(cls, text: str) -> "Version | None":
        m = _SEMVER.match(text.strip())
        if not m:
            return None
        pre = _split_pre(m.group("pre"))
        return cls(
            int(m.group("major")),
            int(m.group("minor")),
            int(m.group("patch")),
            pre,
            text.strip(),
        )

    def _key(self) -> tuple:
        # A release (empty pre) outranks any pre-release of the same core.
        return (self.major, self.minor, self.patch, 0 if not self.pre else -1, self.pre)

    def __lt__(self, other: "Version") -> bool:
        return self._key() < other._key()

    def __le__(self, other: "Version") -> bool:
        return self._key() <= other._key()

    def __gt__(self, other: "Version") -> bool:
        return self._key() > other._key()

    def __str__(self) -> str:
        return self.raw or f"{self.major}.{self.minor}.{self.patch}"


def _split_pre(pre: str | None) -> tuple[object, ...]:
    if not pre:
        return ()
    parts: list[object] = []
    for token in pre.split("."):
        parts.append(int(token) if token.isdigit() else token)
    return tuple(parts)


def is_newer(candidate: str, current: str | None) -> bool:
    """Return True if ``candidate`` should be considered an update over ``current``.

    Falls back to a plain string comparison when either side is not semver
    (e.g. commit shas or ``YYYY.MM.DD`` source stamps). Unknown ``current``
    (never installed) is always treated as older.
    """
    if not current:
        return True
    cv = Version.parse(candidate)
    cur = Version.parse(current)
    if cv and cur:
        return cv > cur
    return str(candidate) != str(current)
