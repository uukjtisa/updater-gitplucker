# updater-gitplucker

A **modular, pluggable GitHub updater library** for Python-glued projects. Drop
it into any of your apps to keep them up to date from GitHub — with a safety
allowlist, a 3-way merge that preserves your local edits, and automatic Python
dependency detection/installation.

- **Import name:** `gitplucker`  ·  **Package:** `updater-gitplucker`
- **Zero required dependencies** — the core runs on the Python standard library.
- **Passive by design** — it hands you an inspectable *plan*; you decide when to
  apply. Trigger it manually, at startup, or from a background thread.

```python
from gitplucker import Updater, UpdaterConfig, RepoSubscription, Channel
from pathlib import Path

config = UpdaterConfig(
    install_root=Path("/path/to/your/app"),         # where the app lives on disk
    allowed_repos=["your-org/your-app"],            # nothing outside this is ever fetched
    subscriptions=[
        RepoSubscription("your-org/your-app", branches=["main"],
                         channel=Channel.PYTHON_SOURCE),
    ],
    token="ghp_...",                                # optional (private repos / rate limits)
)

updater = Updater(config)
for plan in updater.check():                        # dry run — nothing written yet
    print(plan.summary())
    if plan.has_update and not plan.conflicts:
        updater.apply(plan)                         # backup → write → install deps
    else:
        updater.discard(plan)
```

## Install

```bash
pip install updater-gitplucker
```

Or the latest from source:

```bash
pip install "git+https://github.com/uukjtisa/updater-gitplucker.git"
```

## Concepts

### Allowlist (security boundary)
`allowed_repos` is enforced at the network layer: any repo not listed is
rejected **before** any request. Every subscription's repo must be allowlisted.

### Channels — *how* a repo is updated
| Channel | Source | Best for |
|---|---|---|
| `Channel.RELEASE` | Latest GitHub Release + assets (`.zip`, `.whl`, …) | Versioned/shipped builds |
| `Channel.SOURCE` | Raw source at a branch tip (zipball) | Repos without formal releases |
| `Channel.PYTHON_SOURCE` | `SOURCE` **+ 3-way merge + dependency auto-detect** | Python apps held together by scripts (the main use case) |

### Apply strategies — *what* an update replaces (`config.apply_strategy`)
| Strategy | Effect |
|---|---|
| `ApplyStrategy.WHOLE_APP` (default) | Add/modify/merge/delete the tracked tree, with backup + rollback |
| `ApplyStrategy.SELECTIVE` | Only paths matching `selective_globs`; never deletes |
| `ApplyStrategy.PACKAGE` | `pip install` the downloaded wheel/sdist (RELEASE channel) |

### Triggers — *when* it runs
- **Manual** — just call `updater.check()` / `updater.apply()` (or `ManualTrigger`).
- **Startup** — `StartupTrigger(updater).run(on_update=prompt_fn)`.
- **Background** — `BackgroundTrigger(updater, interval_seconds=3600).start(...)`.

All three are optional wrappers; the library never acts on its own.

### 3-way merge (PYTHON_SOURCE)
After each apply, gitplucker snapshots the exact files it pulled (the *base*).
On the next update it merges `base → your local edits` with `base → upstream`.
Non-overlapping changes merge cleanly; only edits to the **same lines** produce a
conflict. `config.conflict_policy` decides what happens then: `mark` (git-style
markers, default), `local`, `remote`, or `abort`.

### Dependency auto-detection (PYTHON_SOURCE)
Every incoming `.py` is scanned for imports; standard-library and the app's own
packages are filtered out; anything left that isn't installed is surfaced in
`plan.dependency_changes` and (if `auto_install_deps=True`) `pip install`-ed on
apply. Version pins in your `requirements.txt` are honored. Newly-added modules
are flagged `is_new`.

## Inspecting a plan

```python
plan.summary()            # one-line human summary
plan.has_update           # bool
plan.file_changes         # list[FileChange]  (added/modified/merged/conflict/deleted)
plan.conflicts            # list[FileChange]  (subset needing attention)
plan.dependency_changes   # list[DependencyChange]
plan.new_dependencies     # subset that are newly referenced
plan.warnings             # e.g. "local changes overwritten (no merge available)"
plan.release_notes        # release body / source stamp
```

## Events

```python
updater.events.on(lambda name, payload: print(name, payload))
```
Emitted: `check.start/done`, `download.progress`, `dep.detected/install`,
`apply.file`, `backup`, `rollback`, `apply.done`. A throwing listener can never
break an update.

## State & rollback
Everything lives in `install_root/.gitplucker/` (override via `state_dir`):
`manifest.json` (installed version + known modules per repo/branch), `base/`
(merge snapshots), `backups/` (timestamped pre-apply copies for manual
rollback). A failed apply auto-rolls-back the current batch.

See [`docs/INTEGRATION.md`](docs/INTEGRATION.md) for a step-by-step wiring guide
and [`examples/basic.py`](examples/basic.py) for a runnable script.
