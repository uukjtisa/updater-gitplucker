from pathlib import Path
from gitplucker import Channel, RepoSubscription, UpdaterConfig
from gitplucker.updater import Updater


def _mk(tmp_path):
    repo, branch = "me/app", "main"
    cfg = UpdaterConfig(install_root=tmp_path / "i", allowed_repos=[repo],
                        subscriptions=[RepoSubscription(repo=repo, channel=Channel.PYTHON_SOURCE)],
                        state_dir=tmp_path / "s")
    (tmp_path / "i").mkdir()
    return Updater(cfg), repo, branch


def test_pending_commits_uses_compare_when_baseline(tmp_path, monkeypatch):
    u, repo, branch = _mk(tmp_path)
    u.state.set_version(repo, branch, "2026-07-01+abc1234")
    calls = {}
    def fake_head(r, b): return "def5678", "2026-07-02T00:00:00Z"
    def fake_compare(r, base, head, limit=50):
        calls["compare"] = (base, head)
        return [{"sha": "def5678", "message": "feat: newer", "date": "", "author": "x"}]
    def fake_list(r, b, limit=20):
        calls["list"] = True
        return []
    monkeypatch.setattr(u.client, "get_branch_head", fake_head)
    monkeypatch.setattr(u.client, "compare_commits", fake_compare)
    monkeypatch.setattr(u.client, "list_commits", fake_list)
    out = u.pending_commits(repo, branch)
    assert calls["compare"] == ("abc1234", "def5678")
    assert "list" not in calls
    assert out and out[0]["message"] == "feat: newer"


def test_pending_commits_falls_back_to_recent(tmp_path, monkeypatch):
    u, repo, branch = _mk(tmp_path)  # no baseline set
    monkeypatch.setattr(u.client, "get_branch_head", lambda r, b: ("h", ""))
    monkeypatch.setattr(u.client, "list_commits",
                        lambda r, b, limit=20: [{"sha": "h", "message": "latest", "date": "", "author": "x"}])
    out = u.pending_commits(repo, branch)
    assert out and out[0]["message"] == "latest"
