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
import re
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


# ── requirements.txt diff engine (the primary dependency source) ─────────────
_REQ_NAME_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")


def _split_requirement(line: str) -> tuple[str | None, str]:
    """Split one requirements line into ``(canonical_name, version_spec)``.

    Strips inline comments, environment markers (``; python_version < '3.11'``)
    and extras (``[security]``). Returns ``(None, "")`` for blanks, comments,
    option lines (``-r``, ``-e``, ``--hash``) and URL / VCS / local-path
    requirements — anything that isn't a simple ``name<spec>`` we deliberately
    leave to pip rather than trying to diff. ``version_spec`` is the raw suffix,
    e.g. ``">=2.1.0"`` or ``"==1.0,<2"`` or ``""`` when unpinned.
    """
    raw = (line or "").strip()
    if not raw or raw.startswith("#") or raw.startswith("-"):
        return None, ""
    raw = raw.split(" #", 1)[0].split("\t#", 1)[0].strip()   # inline comment
    raw = raw.split(";", 1)[0].strip()                        # env marker
    if not raw or "://" in raw or raw.startswith((".", "/", "~")):
        return None, ""
    m = _REQ_NAME_RE.match(raw)
    if not m:
        return None, ""
    name = m.group(1)
    rest = raw[len(name):].lstrip()
    if rest.startswith("["):                                  # extras: requests[security]
        close = rest.find("]")
        rest = rest[close + 1:] if close != -1 else rest
    return name, rest.strip()


def parse_requirements(path: Path | None) -> dict[str, dict]:
    """Parse a requirements file into ``{name_lower: {name, spec, raw}}``.

    Only simple named requirements are captured (see :func:`_split_requirement`);
    the last occurrence of a duplicated name wins. Missing file -> ``{}``. Never
    raises.
    """
    out: dict[str, dict] = {}
    if not path:
        return out
    path = Path(path)
    if not path.exists():
        return out
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        name, spec = _split_requirement(line)
        if not name:
            continue
        out[name.lower()] = {"name": name, "spec": spec, "raw": line.strip()}
    return out


def _norm_spec(spec: str) -> str:
    """Whitespace-insensitive spec key so ``>= 2.0`` == ``>=2.0``."""
    return "".join((spec or "").split())


def diff_requirements(
    old_path: Path | None,
    new_path: Path | None,
    *,
    include_unchanged: bool = False,
) -> list[DependencyChange]:
    """Diff two requirements files by package name -> list[DependencyChange].

    - in NEW but not OLD             -> ``added``   (installed on apply)
    - in OLD but not NEW             -> ``removed`` (report only; never uninstalled)
    - in both, version spec differs  -> ``changed`` (new spec installed on apply)
    - in both, identical             -> ``unchanged`` (only if ``include_unchanged``)

    Package names are compared case-insensitively; comments, markers, extras and
    option/URL lines are ignored. Deterministic (sorted) and never raises — this
    is the engine that replaced import-scanning as the auto-install driver.
    """
    old = parse_requirements(old_path)
    new = parse_requirements(new_path)
    req_rel = Path(new_path).name if new_path else "requirements.txt"
    changes: list[DependencyChange] = []

    for key in sorted(new):
        entry = new[key]
        name, spec = entry["name"], entry["spec"]
        if key not in old:
            changes.append(DependencyChange(
                module="", package=name, spec=spec, is_new=True,
                change_kind="added", old_spec="", new_spec=spec,
                reason="added in requirements", source_file=req_rel))
        elif _norm_spec(old[key]["spec"]) != _norm_spec(spec):
            changes.append(DependencyChange(
                module="", package=name, spec=spec, is_new=False,
                change_kind="changed", old_spec=old[key]["spec"], new_spec=spec,
                reason=f"{old[key]['spec'] or 'unpinned'} -> {spec or 'unpinned'}",
                source_file=req_rel))
        elif include_unchanged:
            changes.append(DependencyChange(
                module="", package=name, spec=spec, is_new=False,
                change_kind="unchanged", old_spec=old[key]["spec"], new_spec=spec,
                reason="unchanged", source_file=req_rel))

    for key in sorted(old):
        if key not in new:
            entry = old[key]
            changes.append(DependencyChange(
                module="", package=entry["name"], spec="", is_new=False,
                change_kind="removed", old_spec=entry["spec"], new_spec="",
                reason="removed from requirements", source_file=req_rel))
    return changes


def resolve_dependencies(
    payload_root: Path,
    requirements_path: Path | None = None,
    known_modules: set[str] | None = None,
) -> list[DependencyChange]:
    """LEGACY import-scan path (kept for back-compat / explicit opt-in).

    The updater no longer drives auto-installs from this — it uses
    :func:`diff_requirements` on the old vs new requirements.txt instead. This
    still scans imports and surfaces modules the environment can't satisfy, for
    callers that specifically want import-based detection.

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
                source_file=first_file,
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
