"""Small filesystem helpers: globbing the payload, hashing, text detection."""

from __future__ import annotations

import hashlib
import re
from functools import lru_cache
from pathlib import Path

_TEXT_EXT = {
    ".py", ".pyi", ".txt", ".md", ".rst", ".json", ".toml", ".ini", ".cfg",
    ".yaml", ".yml", ".xml", ".html", ".htm", ".css", ".js", ".ts", ".kt",
    ".java", ".c", ".h", ".cpp", ".hpp", ".sh", ".bat", ".ps1", ".env",
    ".gitignore", ".gradle", ".properties", ".qss", ".ui",
}


@lru_cache(maxsize=512)
def _compile_glob(pattern: str) -> re.Pattern:
    """Compile a glob into a regex with proper ``**`` (recursive) semantics.

    ``fnmatch`` treats ``*`` as matching across ``/``, so ``**/*`` never matches
    a top-level file. This handles ``**`` explicitly:
    ``**/`` => any (incl. zero) leading dirs, ``**`` => anything, ``*`` => one
    path segment, ``?`` => one non-separator char.
    """
    i, n = 0, len(pattern)
    out = ""
    while i < n:
        c = pattern[i]
        i += 1
        if c == "*":
            if i < n and pattern[i] == "*":
                i += 1
                if i < n and pattern[i] == "/":
                    i += 1
                    out += "(?:.*/)?"
                else:
                    out += ".*"
            else:
                out += "[^/]*"
        elif c == "?":
            out += "[^/]"
        else:
            out += re.escape(c)
    return re.compile("^" + out + "$")


def glob_match(rel: str, patterns: list[str]) -> bool:
    return any(_compile_glob(p).match(rel) for p in patterns)


def list_files(root: Path, include: list[str], exclude: list[str]) -> list[str]:
    """Return POSIX-relative paths under ``root`` matching include, minus exclude."""
    root = Path(root)
    out: list[str] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if not glob_match(rel, include):
            continue
        if glob_match(rel, exclude):
            continue
        out.append(rel)
    return sorted(out)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def is_text_file(path: Path) -> bool:
    if path.suffix.lower() in _TEXT_EXT:
        return True
    try:
        with open(path, "rb") as fh:
            chunk = fh.read(4096)
        if b"\x00" in chunk:
            return False
        chunk.decode("utf-8")
        return True
    except (OSError, UnicodeDecodeError):
        return False
