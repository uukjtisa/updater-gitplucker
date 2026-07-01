from gitplucker.deps import resolve_dependencies, scan_imports


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_scan_imports_finds_top_level(tmp_path):
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/mod.py",
           "import os\nimport json\nfrom pkg import mod\nimport totally_missing_dep_xyz\n")
    found = scan_imports(tmp_path)
    assert "os" in found and "json" in found
    assert "totally_missing_dep_xyz" in found


def test_resolve_skips_stdlib_and_local(tmp_path):
    _write(tmp_path, "myapp/__init__.py", "")
    _write(tmp_path, "myapp/core.py",
           "import os\nimport sys\nfrom myapp import core\nimport totally_missing_dep_xyz\n")
    deps = resolve_dependencies(tmp_path)
    names = {d.module for d in deps}
    assert "os" not in names          # stdlib filtered
    assert "myapp" not in names       # local package filtered
    assert "totally_missing_dep_xyz" in names
    assert all(d.is_new for d in deps)  # nothing known yet
