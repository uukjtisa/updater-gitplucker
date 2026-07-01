"""Line-level 3-way merge (diff3-style), pure stdlib.

Purpose: when the ``python-source`` channel pulls a new version of a file the
user has also edited locally, we don't want to clobber their edits. Given the
common ancestor (the last version gitplucker applied = ``base``), the user's
current file (``local``), and the incoming file (``remote``), we produce a
merged file that keeps both sides' changes and only marks a conflict where both
touched the *same* lines.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass
class MergeResult:
    text: str
    conflicts: int          # number of conflicting hunks
    conflict_lines: int     # total lines inside conflict markers
    clean: bool             # True if remote and local reconciled with no conflict


def _index_map(base: list[str], other: list[str]) -> dict[int, int]:
    """Map base-line-index -> other-line-index for lines that match, monotonic."""
    sm = SequenceMatcher(a=base, b=other, autojunk=False)
    out: dict[int, int] = {}
    for i, j, n in sm.get_matching_blocks():
        for k in range(n):
            out[i + k] = j + k
    return out


def merge_lines(
    base: list[str],
    local: list[str],
    remote: list[str],
    local_label: str = "LOCAL",
    remote_label: str = "REMOTE",
) -> MergeResult:
    la = _index_map(base, local)
    lb = _index_map(base, remote)
    sync = sorted(i for i in la if i in lb)

    out: list[str] = []
    conflicts = 0
    conflict_lines = 0
    a = b = c = 0  # cursors into base, local, remote

    def resolve(base_reg: list[str], local_reg: list[str], remote_reg: list[str]) -> None:
        nonlocal conflicts, conflict_lines
        if local_reg == base_reg:
            out.extend(remote_reg)          # only remote changed here
        elif remote_reg == base_reg:
            out.extend(local_reg)           # only local changed here
        elif local_reg == remote_reg:
            out.extend(local_reg)           # both made the identical change
        else:
            conflicts += 1
            block = (
                [f"<<<<<<< {local_label}\n"]
                + local_reg
                + ["||||||| BASE\n"]
                + base_reg
                + ["=======\n"]
                + remote_reg
                + [f">>>>>>> {remote_label}\n"]
            )
            conflict_lines += len(local_reg) + len(remote_reg)
            out.extend(block)

    for bi in sync:
        li, ri = la[bi], lb[bi]
        resolve(base[a:bi], local[b:li], remote[c:ri])
        out.append(base[bi])   # the synchronized (identical) line
        a, b, c = bi + 1, li + 1, ri + 1

    resolve(base[a:], local[b:], remote[c:])

    return MergeResult(
        text="".join(out),
        conflicts=conflicts,
        conflict_lines=conflict_lines,
        clean=conflicts == 0,
    )


def merge_text(
    base_text: str,
    local_text: str,
    remote_text: str,
    local_label: str = "LOCAL",
    remote_label: str = "REMOTE",
) -> MergeResult:
    return merge_lines(
        base_text.splitlines(keepends=True),
        local_text.splitlines(keepends=True),
        remote_text.splitlines(keepends=True),
        local_label,
        remote_label,
    )
