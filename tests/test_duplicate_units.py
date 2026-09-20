"""Unit alignment retains all occurrences of duplicate test names (#158)."""

from checkwash.detectors.test_disabled import detect
from checkwash.frontends.javascript.frontend import parse_javascript
from checkwash.ir.diffalign import align_file
from checkwash.ir.model import DiffGlobals, IR


def _align(before, after):
    return align_file("dup.test.js", "test", "modified",
                      parse_javascript(before.encode()), parse_javascript(after.encode()))


def _test(subject, name="same"):
    return f'test("{name}", () => {{ expect({subject}).toBe(1); }});\n'


def test_duplicate_names_survive_a_comment_only_edit():
    before = _test("a") + _test("b")
    file = _align(before, before + "// comment\n")
    assert len(file.units) == 2
    assert all(u.match == "by_name" and u.before and u.after for u in file.units)
    assert detect(IR(base="base", head="head", files=[file], globals=DiffGlobals())) == []


def test_deleted_duplicate_still_reports_a_removed_unit():
    file = _align(_test("a") + _test("b"), _test("b"))
    removed = [u for u in file.units if u.after is None]
    assert len(removed) == 1
    assert removed[0].before.assertions[0].left == "a"
    assert len(detect(IR(base="base", head="head", files=[file], globals=DiffGlobals()))) == 1


def test_inserted_duplicate_preserves_existing_oracle_pairing():
    file = _align(_test("a") + _test("b"), _test("new") + _test("a") + _test("b"))
    added = [u for u in file.units if u.before is None]
    assert len(added) == 1
    assert added[0].after.assertions[0].left == "new"
    assert all(u.before.assertions[0].left == u.after.assertions[0].left
               for u in file.units if u.before and u.after)


def test_reordered_duplicates_follow_their_unchanged_bodies():
    file = _align(_test("a") + _test("b"), _test("b") + _test("a"))
    assert len(file.units) == 2
    assert all(u.before.assertions[0].left == u.after.assertions[0].left for u in file.units)


def test_fingerprint_pairing_does_not_reuse_duplicate_names():
    file = _align(_test("a") + _test("b"), _test("a", "renamed") + _test("b", "renamed"))
    assert len(file.units) == 2
    assert all(u.match == "by_fingerprint" for u in file.units)
    assert len({u.before.span for u in file.units}) == 2
    assert len({u.after.span for u in file.units}) == 2


def test_identical_duplicates_are_a_multiset():
    file = _align(_test("a") * 3, _test("a") * 2)
    assert sum(u.before is not None and u.after is not None for u in file.units) == 2
    assert sum(u.after is None for u in file.units) == 1


def test_weakened_duplicate_keeps_its_own_assertion_delta():
    before = _test("a") + _test("b")
    file = _align(before, before.replace("expect(a).toBe(1)", "expect(a).toBeTruthy()"))
    assert len(file.units) == 2
    assert file.units[0].delta.assertion_pairs[0].strength_change < 0
    assert file.units[1].delta.assertion_pairs[0].strength_change == 0
