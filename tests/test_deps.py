from gitplucker.deps import (resolve_dependencies, scan_imports,
                             diff_requirements, parse_requirements)


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _reqs(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


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


# ── requirements.txt diff engine ─────────────────────────────────────────────
def test_parse_requirements_ignores_noise(tmp_path):
    p = _reqs(tmp_path, "r.txt",
              "# a comment\n"
              "\n"
              "requests>=2.0  # inline note\n"
              "PyYAML==6.0\n"
              "flask[async]>=3\n"
              "typing-extensions; python_version < '3.11'\n"
              "-r other.txt\n"
              "-e .\n"
              "git+https://example.com/x.git\n")
    parsed = parse_requirements(p)
    assert set(parsed) == {"requests", "pyyaml", "flask", "typing-extensions"}
    assert parsed["requests"]["spec"] == ">=2.0"
    assert parsed["flask"]["spec"] == ">=3"          # extras stripped
    assert parsed["typing-extensions"]["spec"] == ""  # marker stripped, unpinned


def test_diff_added_removed_changed(tmp_path):
    old = _reqs(tmp_path, "old.txt", "requests>=2.0\nrich==13.0\nnumpy\n")
    new = _reqs(tmp_path, "new.txt", "requests>=2.0\nrich==13.7\nhttpx>=0.27\n")
    changes = {d.package.lower(): d for d in diff_requirements(old, new)}
    assert set(changes) == {"rich", "httpx", "numpy"}         # requests unchanged -> omitted
    assert changes["httpx"].change_kind == "added" and changes["httpx"].should_install
    assert changes["httpx"].new_spec == ">=0.27"
    assert changes["rich"].change_kind == "changed" and changes["rich"].should_install
    assert changes["rich"].old_spec == "==13.0" and changes["rich"].new_spec == "==13.7"
    assert changes["numpy"].change_kind == "removed" and not changes["numpy"].should_install
    assert changes["numpy"].old_spec == ""


def test_diff_whitespace_and_case_insensitive(tmp_path):
    old = _reqs(tmp_path, "old.txt", "Requests >= 2.0\n")
    new = _reqs(tmp_path, "new.txt", "requests>=2.0\n")
    assert diff_requirements(old, new) == []          # same name/spec despite case+spaces


def test_diff_missing_old_file_all_added(tmp_path):
    new = _reqs(tmp_path, "new.txt", "requests>=2.0\nrich==13.7\n")
    changes = diff_requirements(tmp_path / "does_not_exist.txt", new)
    assert {d.package.lower() for d in changes} == {"requests", "rich"}
    assert all(d.change_kind == "added" and d.should_install for d in changes)


def test_diff_include_unchanged(tmp_path):
    old = _reqs(tmp_path, "old.txt", "requests>=2.0\n")
    new = _reqs(tmp_path, "new.txt", "requests>=2.0\n")
    changes = diff_requirements(old, new, include_unchanged=True)
    assert len(changes) == 1 and changes[0].change_kind == "unchanged"
    assert not changes[0].should_install


def test_diff_requirement_string_for_install(tmp_path):
    old = _reqs(tmp_path, "old.txt", "")
    new = _reqs(tmp_path, "new.txt", "httpx>=0.27\nnumpy\n")
    to_install = {d.requirement for d in diff_requirements(old, new) if d.should_install}
    assert to_install == {"httpx>=0.27", "numpy"}
