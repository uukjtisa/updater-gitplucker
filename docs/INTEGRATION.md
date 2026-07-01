# Integration guide (for developers and AI assistants)

This document is written so that an AI assistant (or a human) can wire
`gitplucker` into one of the owner's apps **without re-reading the source**.
Follow it top to bottom.

## 0. What this library does, in one paragraph

`gitplucker` updates a locally-installed app from a GitHub repo. You give it an
allowlist of permitted repos, one or more *subscriptions* (repo + branches +
channel), and where the app lives on disk. Calling `updater.check()` performs a
**dry run** and returns inspectable `UpdatePlan` objects; calling
`updater.apply(plan)` performs the update (backup → write/merge files → install
new Python deps → snapshot a new merge base). It never acts on its own.

## 1. Install

```bash
pip install updater-gitplucker
```

## 2. Minimal wiring

```python
from pathlib import Path
from gitplucker import Updater, UpdaterConfig, RepoSubscription, Channel

def build_updater(app_root: Path, token: str | None = None) -> Updater:
    repo = "OWNER/REPO"                       # <-- set this
    config = UpdaterConfig(
        install_root=app_root,                # folder the app runs from
        allowed_repos=[repo],                 # security allowlist (required)
        subscriptions=[
            RepoSubscription(
                repo=repo,
                branches=["main"],            # configurable list, e.g. ["main","stable"]
                channel=Channel.PYTHON_SOURCE # source + merge + dependency detection
            ),
        ],
        token=token,                          # None for public repos
        auto_install_deps=True,
        # apply_strategy defaults to WHOLE_APP; conflict_policy defaults to "mark"
    )
    return Updater(config)
```

> **Pick the channel per app type**
> - Python app glued by scripts → `Channel.PYTHON_SOURCE` (merge + deps).
> - Non-Python / mixed asset tree → `Channel.SOURCE` (files only, no dep scan).
> - Ships a wheel or a Releases zip → `Channel.RELEASE` (optionally with
>   `apply_strategy=ApplyStrategy.PACKAGE` to pip-install the wheel).

## 3. Choose a trigger

**Manual (button / menu item):**
```python
updater = build_updater(app_root)
plans = updater.check()
for plan in plans:
    if plan.has_update and not plan.conflicts:
        result = updater.apply(plan)
    else:
        updater.discard(plan)      # IMPORTANT: discard plans you don't apply
```

**At startup (prompt the user):**
```python
from gitplucker import StartupTrigger
StartupTrigger(updater).run(on_update=lambda plan: ask_user(plan.summary()))
# on_update returns True to apply, False to skip
```

**Background (periodic):**
```python
from gitplucker import BackgroundTrigger
bg = BackgroundTrigger(updater, interval_seconds=3600)
bg.start(on_update=lambda plan: True, auto_apply=False)  # ... bg.stop() on exit
```

## 4. Show progress / drive a UI

```python
def on_event(name, payload):
    if name == "download.progress":
        pct = payload["received"] / max(payload["total"], 1)
        set_progress(pct)
    elif name == "apply.file":
        log(f"{payload['change']} {payload['path']}")
updater.events.on(on_event)
```

Rendering a plan before applying:
```python
lines = [plan.summary()]
for fc in plan.file_changes:
    if fc.change.value != "unchanged":
        lines.append(f"{fc.change.value:9} {fc.path}  {fc.note}")
for dep in plan.dependency_changes:
    lines.append(f"install    {dep.requirement}  ({dep.reason})")
show("\n".join(lines))
```

## 5. Handling conflicts

`plan.conflicts` is non-empty only on `PYTHON_SOURCE` when both you and upstream
edited the **same lines**. With the default `conflict_policy="mark"`, applying
writes git-style `<<<<<<< / ======= / >>>>>>>` markers into the file for you to
resolve. To avoid surprises, gate auto-apply on `not plan.conflicts` and prompt
the user otherwise. Alternatives: set `conflict_policy` to `"local"` (keep
yours), `"remote"` (take upstream), or `"abort"` (raise `MergeConflictError`).

## 6. Rollback

Every apply (when `backup=True`, the default) copies touched files to
`install_root/.gitplucker/backups/<repo>/<branch>-<timestamp>/` first, and a
failure mid-apply auto-restores that batch. To undo a *successful* update, copy
the latest backup folder back over `install_root`.

## 7. First-run behavior & the merge base

On the very first `apply`, there is no stored base, so files are taken from
upstream directly (local edits to a first-time file are reported in
`plan.warnings` as "no merge available"). From then on, each successful apply
snapshots the pulled files as the new base, enabling true 3-way merges next
time. If you want existing local edits protected from day one, run one `apply`
against the exact version the app currently matches before users start editing.

## 8. Cheap polling

`updater.has_update_available(repo, branch)` does a version-only API probe (no
download) — use it for frequent background checks, then do a full `check_repo`
only when it returns True. (`BackgroundTrigger` already does this.)

## 9. Gotchas / rules

- **Always `discard(plan)` for plans you don't apply** — it deletes the temp
  download. `apply()` discards for you.
- `include_globs` / `exclude_globs` on a subscription define what counts as the
  app payload. Defaults exclude `.git`, `__pycache__`, `.venv`, `.gitplucker`,
  `node_modules`. Add app-specific data dirs to `exclude_globs` so user data is
  never overwritten or deleted.
- Deletions only happen under `WHOLE_APP`, only for files that were previously
  pulled from the repo and are unmodified locally.
- `requirements_file` (default `requirements.txt`, relative to `install_root`)
  is read only to pick up version pins for detected deps; it is not required.
- The library is synchronous. For a GUI, run `check`/`apply` on a worker thread
  and marshal events back to the UI thread.

## 10. Config quick reference

| Field | Default | Meaning |
|---|---|---|
| `install_root` | — | Where the app lives (required) |
| `allowed_repos` | `[]` | Allowlist; every subscription repo must be in it |
| `subscriptions` | `[]` | `RepoSubscription(repo, branches, channel, …)` |
| `token` | `None` | GitHub PAT (private repos / higher rate limit) |
| `apply_strategy` | `"whole_app"` | `whole_app` / `selective` / `package` |
| `selective_globs` | `[]` | Paths applied under `selective` |
| `merge` | `True` | Enable 3-way merge on `python-source` |
| `conflict_policy` | `"mark"` | `mark` / `local` / `remote` / `abort` |
| `auto_install_deps` | `True` | pip-install detected deps on apply |
| `requirements_file` | `"requirements.txt"` | For version pins (relative) |
| `backup` | `True` | Snapshot before apply; enables rollback |
| `state_dir` | `install_root/.gitplucker` | Where state/backups live |

`RepoSubscription`: `repo` (`"owner/name"`), `branches` (`["main"]`), `channel`,
`asset_pattern` (`"*.zip"`, RELEASE), `include_globs`, `exclude_globs`,
`source_subdir` (map a repo subfolder onto `install_root`).
