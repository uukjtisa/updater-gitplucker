from gitplucker import Channel, RepoSubscription, Updater, UpdaterConfig
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
        backup=True,
    )


def test_apply_then_rollback_restores_previous_state(tmp_path):
    install = tmp_path / "install"; install.mkdir()
    (install / "a.py").write_text("old\n", encoding="utf-8")   # will be modified
    payload = tmp_path / "payload"; payload.mkdir()
    (payload / "a.py").write_text("new\n", encoding="utf-8")
    (payload / "b.py").write_text("added\n", encoding="utf-8")  # will be added

    cfg = _cfg(tmp_path, install)
    state = StateStore(cfg.state_dir)
    plan = UpdatePlan("me/app", "main", Ch.PYTHON_SOURCE, "v0", "v1", has_update=True)
    plan._ops = [FileOp("a.py", "copy", src=payload / "a.py"),
                 FileOp("b.py", "copy", src=payload / "b.py")]

    res = get_strategy("whole_app").apply(cfg, plan, EventEmitter(), state)
    assert res.success
    assert (install / "a.py").read_text() == "new\n"
    assert (install / "b.py").exists()

    # A snapshot + manifest must now exist.
    u = Updater(cfg)
    snaps = u.list_snapshots("me/app", "main")
    assert len(snaps) == 1
    assert snaps[0]["version_before"] == "v0"
    assert snaps[0]["files"] == 2

    rb = u.rollback("me/app", "main")
    assert rb.success, rb.message
    assert (install / "a.py").read_text() == "old\n"      # restored
    assert not (install / "b.py").exists()                 # added file removed
    assert u.state.get_version("me/app", "main") == "v0"   # version rewound
