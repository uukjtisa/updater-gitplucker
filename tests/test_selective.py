from gitplucker import (Channel, RepoSubscription, Updater, UpdaterConfig)
from gitplucker.events import EventEmitter
from gitplucker.models import Channel as Ch
from gitplucker.models import UpdatePlan
from gitplucker.planner import FileOp
from gitplucker.state import StateStore
from gitplucker.strategies import get_strategy


def _cfg(tmp_path, install):
    return UpdaterConfig(
        install_root=install,
        allowed_repos=["me/app"],
        subscriptions=[RepoSubscription("me/app", channel=Channel.PYTHON_SOURCE)],
        state_dir=tmp_path / "state",
        backup=False,
    )


def test_selected_ops_only_apply_chosen_files(tmp_path):
    install = tmp_path / "install"; install.mkdir()
    payload = tmp_path / "payload"; payload.mkdir()
    (payload / "a.py").write_text("A\n", encoding="utf-8")
    (payload / "b.py").write_text("B\n", encoding="utf-8")

    cfg = _cfg(tmp_path, install)
    state = StateStore(cfg.state_dir)
    plan = UpdatePlan("me/app", "main", Ch.PYTHON_SOURCE, None, "v1", has_update=True)
    plan._ops = [FileOp("a.py", "copy", src=payload / "a.py"),
                 FileOp("b.py", "copy", src=payload / "b.py")]
    plan._selected = {"a.py"}          # only update a.py

    result = get_strategy("whole_app").apply(cfg, plan, EventEmitter(), state)
    assert result.success
    assert (install / "a.py").exists()
    assert not (install / "b.py").exists()      # deselected file untouched
    assert result.applied_files == ["a.py"]


def test_preview_change_returns_unified_diff(tmp_path):
    install = tmp_path / "install"; install.mkdir()
    (install / "a.py").write_text("line1\nline2\n", encoding="utf-8")
    payload = tmp_path / "payload"; payload.mkdir()
    (payload / "a.py").write_text("line1\nCHANGED\n", encoding="utf-8")

    cfg = _cfg(tmp_path, install)
    u = Updater(cfg)
    plan = UpdatePlan("me/app", "main", Ch.PYTHON_SOURCE, None, "v1", has_update=True)
    plan._ops = [FileOp("a.py", "copy", src=payload / "a.py")]

    diff = u.preview_change(plan, "a.py")
    assert "CHANGED" in diff
    assert "-line2" in diff and "+CHANGED" in diff
    assert u.preview_change(plan, "missing.py").startswith("(no change")
