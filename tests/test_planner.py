from pathlib import Path

from gitplucker import Channel, RepoSubscription, UpdaterConfig
from gitplucker.models import ChangeType
from gitplucker.planner import build_file_plan
from gitplucker.state import StateStore


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _by_path(changes):
    return {c.path: c for c in changes}


def test_merge_added_modified_flow(tmp_path):
    install = tmp_path / "install"
    payload = tmp_path / "payload"
    base = tmp_path / "base_src"
    install.mkdir()
    payload.mkdir()
    base.mkdir()

    repo, branch = "me/app", "main"
    cfg = UpdaterConfig(
        install_root=install,
        allowed_repos=[repo],
        subscriptions=[RepoSubscription(repo=repo, channel=Channel.PYTHON_SOURCE)],
        state_dir=tmp_path / "state",
    )
    sub = cfg.subscriptions[0]
    state = StateStore(cfg.state_dir)

    # Establish a base snapshot (what was last pulled from the repo).
    _write(base, "app.py", "import os\nvalue = 0\nprint(value)\n")
    state.snapshot_base(repo, branch, base, ["app.py"])

    # Local user appended a comment (a non-overlapping edit).
    _write(install, "app.py", "import os\nvalue = 0\nprint(value)\n# my local note\n")

    # Upstream changed the first line and added a new file (also non-overlapping).
    _write(payload, "app.py", "import sys\nvalue = 0\nprint(value)\n")
    _write(payload, "new.py", "x = 1\n")

    changes, ops, warnings = build_file_plan(cfg, sub, branch, payload, state)
    by = _by_path(changes)

    assert by["new.py"].change is ChangeType.ADDED
    assert by["app.py"].change is ChangeType.MERGED
    # The merged write op should contain both edits.
    merged_op = next(o for o in ops if o.relpath == "app.py")
    assert merged_op.kind == "write"
    assert "import sys" in merged_op.text and "my local note" in merged_op.text
    assert not warnings


def test_line_ending_only_diff_is_not_a_change(tmp_path):
    install = tmp_path / "install"
    payload = tmp_path / "payload"
    install.mkdir()
    payload.mkdir()

    repo, branch = "me/app", "main"
    cfg = UpdaterConfig(
        install_root=install,
        allowed_repos=[repo],
        subscriptions=[RepoSubscription(repo=repo, channel=Channel.PYTHON_SOURCE)],
        state_dir=tmp_path / "state",
    )
    sub = cfg.subscriptions[0]
    state = StateStore(cfg.state_dir)

    # Same text, different line endings (CRLF local vs LF upstream): bytes differ
    # (so it would hash as "modified") but there is no real textual change.
    (install / "NOTICE").write_bytes(b"line one\r\nline two\r\n")
    (payload / "NOTICE").write_bytes(b"line one\nline two\n")

    changes, ops, _ = build_file_plan(cfg, sub, branch, payload, state)
    by = _by_path(changes)
    assert by["NOTICE"].change is ChangeType.UNCHANGED
    assert not any(o.relpath == "NOTICE" for o in ops)


def test_conflict_marks(tmp_path):
    install = tmp_path / "install"
    payload = tmp_path / "payload"
    base = tmp_path / "base_src"
    for d in (install, payload, base):
        d.mkdir()

    repo, branch = "me/app", "main"
    cfg = UpdaterConfig(
        install_root=install,
        allowed_repos=[repo],
        subscriptions=[RepoSubscription(repo=repo, channel=Channel.PYTHON_SOURCE)],
        state_dir=tmp_path / "state",
    )
    sub = cfg.subscriptions[0]
    state = StateStore(cfg.state_dir)

    _write(base, "app.py", "value = 0\n")
    state.snapshot_base(repo, branch, base, ["app.py"])
    _write(install, "app.py", "value = 999\n")   # local changed the line
    _write(payload, "app.py", "value = 1\n")      # upstream changed the same line

    changes, ops, _ = build_file_plan(cfg, sub, branch, payload, state)
    app = _by_path(changes)["app.py"]
    assert app.change is ChangeType.CONFLICT
    op = next(o for o in ops if o.relpath == "app.py")
    assert "<<<<<<<" in op.text  # default MARK policy writes markers
