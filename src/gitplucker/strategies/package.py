"""PACKAGE: pip-install the downloaded wheel/sdist into the current interpreter.

Used with the RELEASE channel when the app ships as a built distribution rather
than a source tree. No file ops are applied; pip owns the install.
"""

from __future__ import annotations

from ..config import UpdaterConfig
from ..deps import install_requirements
from ..errors import ApplyError
from ..events import EventEmitter
from ..models import ApplyResult, UpdatePlan
from ..state import StateStore
from .base import ApplyStrategy


class PackageStrategy(ApplyStrategy):
    name = "package"

    def apply(self, cfg: UpdaterConfig, plan: UpdatePlan, emitter: EventEmitter,
              state: StateStore) -> ApplyResult:
        result = ApplyResult(repo=plan.repo, branch=plan.branch)
        if not plan._is_package or not plan._package_path:
            raise ApplyError(
                "PACKAGE strategy requires a RELEASE channel with a .whl/.tar.gz asset"
            )
        ok, out = install_requirements([str(plan._package_path)], extra_pip_args=["--upgrade"])
        result.success = ok
        result.installed_deps = [plan._package_path.name]
        result.message = out.strip()[-2000:]
        if not ok:
            raise ApplyError(f"pip install of {plan._package_path.name} failed:\n{out}")
        return result
