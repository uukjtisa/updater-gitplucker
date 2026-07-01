"""Python dependency auto-detection and installation.

Flow for the ``python-source`` channel:

1. Parse every ``.py`` file in the incoming payload with :mod:`ast`.
2. Collect top-level imported module names.
3. Drop the standard library and the app's own local packages.
4. Whatever's left that isn't importable / installed is surfaced as a
   :class:`~gitplucker.models.DependencyChange` — shown in the update plan and,
   if ``auto_install_deps`` is on, ``pip install``-ed on apply.
"""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

from ..models import DependencyChange

try:
    from importlib import metadata as _im
except ImportError:  # pragma: no cover
    import importlib_metadata as _im  # type: ignore

# Import name -> pip package name, for the common mismatches.
PACKAGE_ALIASES: dict[str, str] = {
    "cv2": "opencv-python",
    "PIL": "Pillow",
    "yaml": "PyYAML",
    "bs4": "beautifulsoup4",
    "serial": "pyserial",
    "dotenv": "python-dotenv",
    "sklearn": "scikit-learn",
    "skimage": "scikit-image",
    "google": "google-api-python-client",
    "OpenGL": "PyOpenGL",
    "win32api": "pywin32",
    "win32con": "pywin32",
    "win32gui": "pywin32",
    "wx": "wxPython",
    "Crypto": "pycryptodome",
    "usb": "pyusb",
    "zmq": "pyzmq",
}

_STDLIB = set(getattr(sys, "stdlib_module_names", set())) | {"__future__"}

# Source-layout / directory-convention names that show up as dangling imports
# (e.g. code meant to run from a parent dir with ``src/`` on sys.path) but must
# NEVER be auto-installed — real PyPI packages by these names are never intended.
_NON_PACKAGE_NAMES = {
    "src", "test", "tests", "docs", "doc", "examples", "example",
    "scripts", "build", "dist",
}


def _iter_py_files(root: Path) -> list[Path]:
    skip = {".git", "__pycache__", ".gitplucker", ".venv", "venv", "node_modules"}
    files: list[Path] = []
    for p in root.rglob("*.py"):
        if any(part in skip for part in p.parts):
            continue
        files.append(p)
    return files


def _local_top_levels(root: Path) -> set[str]:
    """Names that resolve to something *inside* the app, so must never be
    mistaken for a PyPI dependency.

    Import scanning is inherently noisy (dangling/dev-only imports, code that
    imports a sibling package by name), and the dangerous failure mode is
    auto-``pip install``-ing a garbage package that happens to share the name.
    So this is deliberately permissive: a name is treated as local if anywhere
    in the payload there is a directory or a ``<name>.py`` with that name — not
    only at the repo root.
    """
    local: set[str] = set()
    skip = {".git", "__pycache__", ".gitplucker", ".venv", "venv", "node_modules"}
    for p in root.rglob("*"):
        if any(part in skip for part in p.relative_to(root).parts):
            continue
        if p.is_dir():
            local.add(p.name)          # any dir name (package or namespace dir)
        elif p.suffix == ".py":
            local.add(p.stem)          # any module file, at any depth
    return local


def scan_imports(root: Path) -> dict[str, str]:
    """Return ``{top_level_module: first_file_relpath}`` for all imports found."""
    found: dict[str, str] = {}
    root = Path(root)
    for py in _iter_py_files(root):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"), filename=str(py))
        except SyntaxError:
            continue
        rel = py.relative_to(root).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    found.setdefault(top, rel)
            elif isinstance(node, ast.ImportFrom):
                if node.level and node.level > 0:
                    continue  # relative import -> local, never a dependency
                if node.module:
                    top = node.module.split(".")[0]
                    found.setdefault(top, rel)
    return found


def _installed_packages() -> set[str]:
    names: set[str] = set()
    try:
        for dist in _im.distributions():
            name = (dist.metadata["Name"] or "").lower()
            if name:
                names.add(name)
    except Exception:
        pass
    return names


def _is_satisfied(module: str, package: str, installed: set[str]) -> bool:
    if package.lower() in installed:
        return True
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError, ModuleNotFoundError):
        return False


def _parse_requirements(path: Path) -> dict[str, str]:
    """Map lowercased package name -> full requirement spec from a requirements file."""
    specs: dict[str, str] = {}
    if not path.exists():
        return specs
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        name = line
        for sep in ("==", ">=", "<=", "~=", ">", "<", "!=", "[", ";", " "):
            idx = line.find(sep)
            if idx > 0:
                name = line[:idx]
                break
        specs[name.strip().lower()] = line
    return specs


def resolve_dependencies(
    payload_root: Path,
    requirements_path: Path | None = None,
    known_modules: set[str] | None = None,
) -> list[DependencyChange]:
    """Compute the dependencies the incoming payload needs but the env lacks.

    ``known_modules`` is the set seen in the *previous* applied version; anything
    outside it is flagged ``is_new`` (a genuinely newly-added module).
    """
    payload_root = Path(payload_root)
    imports = scan_imports(payload_root)
    local = _local_top_levels(payload_root)
    installed = _installed_packages()
    req_specs = _parse_requirements(requirements_path) if requirements_path else {}
    known = known_modules or set()

    changes: list[DependencyChange] = []
    for module, first_file in sorted(imports.items()):
        if module in _STDLIB or module in local or module in _NON_PACKAGE_NAMES:
            continue
        package = PACKAGE_ALIASES.get(module, module)
        if _is_satisfied(module, package, installed):
            continue
        spec = ""
        req = req_specs.get(package.lower())
        if req and any(op in req for op in ("==", ">=", "<=", "~=", ">", "<", "!=")):
            # Preserve pinned version from requirements.txt.
            spec = req[len(package):].split(";")[0].strip()
        changes.append(
            DependencyChange(
                module=module,
                package=package,
                spec=spec,
                is_new=module not in known,
                reason=f"imported in {first_file}",
            )
        )
    return changes


def install_requirements(
    requirements: list[str],
    python: str | None = None,
    extra_pip_args: list[str] | None = None,
) -> tuple[bool, str]:
    """``pip install`` the given requirement strings. Returns ``(ok, output)``."""
    if not requirements:
        return True, "nothing to install"
    cmd = [python or sys.executable, "-m", "pip", "install", *(extra_pip_args or []), *requirements]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except Exception as e:  # pragma: no cover
        return False, f"failed to launch pip: {e}"
    return proc.returncode == 0, (proc.stdout + proc.stderr)
