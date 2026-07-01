"""Trigger helpers — thin wrappers over an :class:`~gitplucker.updater.Updater`.

The library itself is passive: you can ignore these entirely and just call
``updater.check()`` / ``updater.apply()`` yourself (that *is* the manual
trigger). ``StartupTrigger`` and ``BackgroundTrigger`` are conveniences for the
two other requested modes.
"""

from .manual import ManualTrigger
from .startup import StartupTrigger
from .background import BackgroundTrigger

__all__ = ["ManualTrigger", "StartupTrigger", "BackgroundTrigger"]
