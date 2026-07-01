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
