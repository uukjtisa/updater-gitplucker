from gitplucker.merge import merge_text


def test_non_overlapping_changes_merge_clean():
    base = "a\nb\nc\nd\n"
    local = "a\nb-local\nc\nd\n"      # user changed line 2
    remote = "a\nb\nc\nd-remote\n"    # upstream changed line 4
    res = merge_text(base, local, remote)
    assert res.clean
    assert "b-local" in res.text
    assert "d-remote" in res.text
    assert "<<<<<<<" not in res.text


def test_overlapping_changes_conflict():
    base = "a\nb\nc\n"
    local = "a\nLOCAL\nc\n"
    remote = "a\nREMOTE\nc\n"
    res = merge_text(base, local, remote)
    assert not res.clean
    assert res.conflicts == 1
    assert "<<<<<<<" in res.text and ">>>>>>>" in res.text


def test_identical_change_no_conflict():
    base = "a\nb\nc\n"
    local = "a\nX\nc\n"
    remote = "a\nX\nc\n"
    res = merge_text(base, local, remote)
    assert res.clean
    assert res.text == "a\nX\nc\n"


def test_added_lines_both_sides():
    base = "a\nb\n"
    local = "a\nb\nlocal-tail\n"
    remote = "remote-head\na\nb\n"
    res = merge_text(base, local, remote)
    assert res.clean
    assert "remote-head" in res.text and "local-tail" in res.text


# ── annotate_three_way (origin-tagged review projection) ────────────────────
from gitplucker.merge import annotate_three_way_text


def _tags(tagged):
    return [t for t, _ in tagged]


def test_annotate_update_only_change():
    base = "a\nb\nc\n"
    local = "a\nb\nc\n"        # user untouched
    remote = "a\nb\nc\nd\n"    # update appended a line
    tagged = annotate_three_way_text(base, local, remote)
    tags = _tags(tagged)
    assert "update_add" in tags
    assert "local_add" not in tags and "local_del" not in tags
    assert ("update_add", "d\n") in tagged


def test_annotate_local_only_change():
    base = "a\nb\nc\n"
    local = "a\nB\nc\n"        # user edited line 2
    remote = "a\nb\nc\n"       # update untouched
    tagged = annotate_three_way_text(base, local, remote)
    tags = _tags(tagged)
    assert "local_add" in tags and "local_del" in tags
    assert "update_add" not in tags
    assert ("local_add", "B\n") in tagged
    assert ("local_del", "b\n") in tagged


def test_annotate_both_sides_conflict_blocks():
    base = "a\nb\nc\n"
    local = "a\nLOCAL\nc\n"
    remote = "a\nREMOTE\nc\n"
    tagged = annotate_three_way_text(base, local, remote)
    tags = _tags(tagged)
    assert "conflict_marker" in tags
    assert ("conflict_local", "LOCAL\n") in tagged
    assert ("conflict_remote", "REMOTE\n") in tagged
    assert ("conflict_base", "b\n") in tagged
