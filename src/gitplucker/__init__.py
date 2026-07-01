"""gitplucker — modular, pluggable GitHub updater for Python-glued projects.

Public API (stable):

    from gitplucker import (
        Updater, UpdaterConfig, RepoSubscription,
        Channel, ApplyStrategy, ConflictPolicy,
        ManualTrigger, StartupTrigger, BackgroundTrigger,
    )

See ``docs/INTEGRATION.md`` for a step-by-step wiring guide (written so an AI
assistant can drop this into an app unattended).
"""

from __future__ import annotations

from .config import ApplyStrategy, ConflictPolicy, RepoSubscription, UpdaterConfig
from .errors import (
    ApplyError,
    ConfigError,
    GitHubAPIError,
    GitpluckerError,
    MergeConflictError,
    RepoNotAllowedError,
    SourceError,
)
from .merge import (
    MergeResult,
    annotate_three_way,
    annotate_three_way_text,
    merge_text,
)
from .models import (
    ApplyResult,
    Channel,
    ChangeType,
    DependencyChange,
    FileChange,
    UpdatePlan,
)
from .triggers import BackgroundTrigger, ManualTrigger, StartupTrigger
from .updater import Updater

__version__ = "0.6.0"

__all__ = [
    "Updater",
    "UpdaterConfig",
    "RepoSubscription",
    "Channel",
    "ApplyStrategy",
    "ConflictPolicy",
    "ChangeType",
    "UpdatePlan",
    "FileChange",
    "DependencyChange",
    "ApplyResult",
    "ManualTrigger",
    "StartupTrigger",
    "BackgroundTrigger",
    "merge_text",
    "MergeResult",
    "annotate_three_way",
    "annotate_three_way_text",
    "GitpluckerError",
    "ConfigError",
    "RepoNotAllowedError",
    "SourceError",
    "GitHubAPIError",
    "MergeConflictError",
    "ApplyError",
    "__version__",
]
