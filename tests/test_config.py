import pytest

from gitplucker import RepoSubscription, UpdaterConfig
from gitplucker.errors import ConfigError


def test_subscription_must_be_allowlisted(tmp_path):
    with pytest.raises(ConfigError):
        UpdaterConfig(
            install_root=tmp_path,
            allowed_repos=["me/allowed"],
            subscriptions=[RepoSubscription(repo="me/not-allowed")],
        )


def test_allowlist_query(tmp_path):
    cfg = UpdaterConfig(
        install_root=tmp_path,
        allowed_repos=["me/allowed"],
        subscriptions=[RepoSubscription(repo="me/allowed")],
    )
    assert cfg.is_allowed("me/allowed")
    assert not cfg.is_allowed("me/other")
    assert cfg.state_dir == tmp_path / ".gitplucker"


def test_bad_repo_shape(tmp_path):
    with pytest.raises(ConfigError):
        RepoSubscription(repo="no-slash")
