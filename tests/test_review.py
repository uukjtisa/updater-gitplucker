from pathlib import Path
from types import SimpleNamespace

from gitplucker import Channel, RepoSubscription, UpdaterConfig
from gitplucker.updater import Updater
from gitplucker.planner import build_file_plan
from gitplucker.state import StateStore


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _fake_plan(sub, branch, payload, ops):
    return SimpleNamespace(
        _ops=ops, _subscription=sub, _payload_root=payload, branch=branch)


def _mk(tmp_path):
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
    return cfg, cfg.subscriptions[0], StateStore(cfg.state_dir), install, payload, base, repo, branch


def test_review_three_way_separates_origins(tmp_path):
    cfg, sub, state, install, payload, base, repo, branch = _mk(tmp_path)

    _write(base, "app.py", "import os\nvalue = 0\nprint(value)\n")
    state.snapshot_base(repo, branch, base, ["app.py"])
    _write(install, "app.py", "import os\nvalue = 0\nprint(value)\n# my local note\n")
    _write(payload, "app.py", "import sys\nvalue = 0\nprint(value)\n")

    changes, ops, _ = build_file_plan(cfg, sub, branch, payload, state)
    u = Updater(cfg)
    tagged = u.review_change(_fake_plan(sub, branch, payload, ops), "app.py")
    tags = [t for t, _ in tagged]

    # The update changed the import line; the user added a local note.
    assert "update_add" in tags and "update_del" in tags
    assert "local_add" in tags
    assert ("update_add", "import sys\n") in tagged
    assert ("local_add", "# my local note\n") in tagged


def test_review_two_way_fallback_without_base(tmp_path):
    cfg, sub, state, install, payload, base, repo, branch = _mk(tmp_path)

    # No base snapshot -> a plain added file, two-way tagging as update-origin.
    _write(payload, "new.py", "x = 1\ny = 2\n")
    changes, ops, _ = build_file_plan(cfg, sub, branch, payload, state)
    u = Updater(cfg)
    tagged = u.review_change(_fake_plan(sub, branch, payload, ops), "new.py")
    tags = [t for t, _ in tagged]
    assert "update_add" in tags
    assert "local_add" not in tags


def test_seed_baseline_enables_three_way(tmp_path, monkeypatch):
    """After seeding a baseline from upstream, a later local-only edit shows as
    local_add/local_del rather than update-origin."""
    cfg, sub, state, install, payload, base, repo, branch = _mk(tmp_path)

    # Pristine upstream the user "installed".
    _write(install, "app.py", "import os\nvalue = 0\n")

    # Seed the baseline by pointing the source fetch at a payload dir that mirrors
    # the pristine upstream. We stub _source_for to avoid any network.
    _write(payload, "app.py", "import os\nvalue = 0\n")

    class _Fetched:
        is_package = False
        version = "2026.07.02+abcdef0"
        files_root = payload
        release_notes = None
        package_path = None

    class _Src:
        def fetch(self, client, sub, branch, workdir, progress):
            return _Fetched()

    u = Updater(cfg)
    monkeypatch.setattr(u, "_source_for", lambda sub: _Src())

    res = u.seed_baseline(repo, branch)
    assert res["seeded"] is True
    assert u.has_baseline(repo, branch)

    # Now the user edits their local file (diverges from the seeded baseline),
    # and upstream is unchanged -> review must attribute it to the user.
    _write(install, "app.py", "import os\nvalue = 42\n")
    from gitplucker.planner import build_file_plan
    changes, ops, _ = build_file_plan(cfg, sub, branch, payload, state)
    tagged = u.review_change(_fake_plan(sub, branch, payload, ops), "app.py")
    tags = [t for t, _ in tagged]
    assert "local_add" in tags or "local_del" in tags


def test_seed_baseline_idempotent(tmp_path, monkeypatch):
    cfg, sub, state, install, payload, base, repo, branch = _mk(tmp_path)
    _write(payload, "app.py", "x = 1\n")

    class _Fetched:
        is_package = False
        version = "v1"
        files_root = payload
        release_notes = None
        package_path = None

    class _Src:
        def fetch(self, *a):
            return _Fetched()

    u = Updater(cfg)
    monkeypatch.setattr(u, "_source_for", lambda sub: _Src())
    assert u.seed_baseline(repo, branch)["seeded"] is True
    second = u.seed_baseline(repo, branch)
    assert second["seeded"] is False and second["version"] == "v1"
