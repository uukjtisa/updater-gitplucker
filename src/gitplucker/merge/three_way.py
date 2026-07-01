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


# Origin tags produced by annotate_three_way / annotate_three_way_text.
# same, update_add, update_del, local_add, local_del,
# conflict_marker, conflict_local, conflict_base, conflict_remote
def annotate_three_way(base: list[str], local: list[str], remote: list[str]):
    """Tag every line of a 3-way merge by where the change came from.

    Returns a list of ``(tag, line)`` pairs so a viewer can colour each origin:
    lines the update added/removed (relative to the common ancestor) vs lines the
    user changed locally, plus conflict regions where both sides touched the same
    lines. This is a *review* projection over the base, not the merged file.
    """
    la = _index_map(base, local)
    lb = _index_map(base, remote)
    sync = sorted(i for i in la if i in lb)

    out: list[tuple[str, str]] = []
    a = b = c = 0

    def region(base_reg, local_reg, remote_reg):
        local_changed = local_reg != base_reg
        remote_changed = remote_reg != base_reg
        if not local_changed and not remote_changed:
            out.extend(("same", ln) for ln in base_reg)
        elif local_changed and not remote_changed:
            out.extend(("local_del", ln) for ln in base_reg)
            out.extend(("local_add", ln) for ln in local_reg)
        elif remote_changed and not local_changed:
            out.extend(("update_del", ln) for ln in base_reg)
            out.extend(("update_add", ln) for ln in remote_reg)
        elif local_reg == remote_reg:
            # both made the identical change -> show as the update's result
            out.extend(("update_del", ln) for ln in base_reg)
            out.extend(("update_add", ln) for ln in local_reg)
        else:
            out.append(("conflict_marker", "<<<<<<< local\n"))
            out.extend(("conflict_local", ln) for ln in local_reg)
            out.append(("conflict_marker", "||||||| base\n"))
            out.extend(("conflict_base", ln) for ln in base_reg)
            out.append(("conflict_marker", "=======\n"))
            out.extend(("conflict_remote", ln) for ln in remote_reg)
            out.append(("conflict_marker", ">>>>>>> update\n"))

    for bi in sync:
        li, ri = la[bi], lb[bi]
        region(base[a:bi], local[b:li], remote[c:ri])
        out.append(("same", base[bi]))
        a, b, c = bi + 1, li + 1, ri + 1
    region(base[a:], local[b:], remote[c:])
    return out


def annotate_three_way_text(base_text: str, local_text: str, remote_text: str):
    return annotate_three_way(
        base_text.splitlines(keepends=True),
        local_text.splitlines(keepends=True),
        remote_text.splitlines(keepends=True),
    )
