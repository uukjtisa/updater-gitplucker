"""Minimal synchronous event bus so hosts can hook into progress/prompts.

The library never blocks on user input directly; instead it emits events and
(optionally) asks a decision callback. This keeps it usable from a Qt GUI, a
CLI, or a headless service alike.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


# Well-known event names (documented for integrators). Emitting arbitrary names
# is fine too; these are just the ones the built-in flow raises.
CHECK_START = "check.start"
CHECK_DONE = "check.done"
DOWNLOAD_PROGRESS = "download.progress"   # payload: {repo, received, total}
MERGE_FILE = "merge.file"                 # payload: {path, conflict}
CONFLICT = "conflict"                     # payload: {path, lines}
DEP_DETECTED = "dep.detected"             # payload: {requirement}
DEP_INSTALL = "dep.install"               # payload: {requirement, ok}
APPLY_FILE = "apply.file"                 # payload: {path, change}
BACKUP = "backup"                         # payload: {path}
ROLLBACK = "rollback"                     # payload: {path}
APPLY_DONE = "apply.done"                 # payload: {success}


Listener = Callable[[str, dict], None]


@dataclass
class EventEmitter:
    _listeners: list[Listener] = field(default_factory=list)

    def on(self, listener: Listener) -> Listener:
        """Register a ``listener(event_name, payload)``. Returns it for easy removal."""
        self._listeners.append(listener)
        return listener

    def off(self, listener: Listener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def emit(self, event: str, **payload: Any) -> None:
        for listener in list(self._listeners):
            try:
                listener(event, payload)
            except Exception:
                # A misbehaving listener must never break an update.
                pass
