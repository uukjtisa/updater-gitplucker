"""Minimal end-to-end example: check + apply for one repo.

Run:  python examples/basic.py
(Point install_root/allowed_repos at something real first.)
"""

from __future__ import annotations

import os
from pathlib import Path

from gitplucker import Channel, RepoSubscription, Updater, UpdaterConfig


def main() -> None:
    config = UpdaterConfig(
        install_root=Path("/path/to/your/app"),             # where the app lives on disk
        allowed_repos=["your-org/your-app"],                # security allowlist
        subscriptions=[
            RepoSubscription(
                repo="your-org/your-app",
                branches=["main"],
                channel=Channel.PYTHON_SOURCE,              # source + merge + deps
            ),
        ],
        token=os.environ.get("GITHUB_TOKEN"),               # optional, for private repos
        auto_install_deps=True,
    )

    updater = Updater(config)

    # Log every event to the console.
    updater.events.on(lambda name, payload: print(f"[{name}] {payload}"))

    for plan in updater.check():
        print(plan.summary())
        for fc in plan.file_changes:
            if fc.change.value != "unchanged":
                print(f"   {fc.change.value:9} {fc.path} {fc.note}")
        for dep in plan.dependency_changes:
            print(f"   dep      {dep.requirement}  ({dep.reason})")

        if plan.has_update and not plan.conflicts:
            result = updater.apply(plan)
            print("APPLIED:", result.message, "| deps:", result.installed_deps)
        else:
            if plan.conflicts:
                print("Conflicts present — review before applying.")
            updater.discard(plan)


if __name__ == "__main__":
    main()
