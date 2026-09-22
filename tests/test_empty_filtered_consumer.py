"""An empty filtered consumer must retain its ordinary execution evidence."""
import pytest

from test_fixture_consumers import AFTER, projected, run


@pytest.mark.parametrize("predicate", [b"False", b"1 > 2", b"n < 0", b"expected == -1"])
def test_an_entirely_disabled_consumer_cannot_borrow_later_duplicate_rows(predicate):
    after = AFTER.replace(b"    assert percent", b"    if " + predicate + b":\n        assert percent", 1)
    ir, findings, verdict = run(after)
    assert not projected(ir)
    assert verdict == "block"
    assert any(f.severity == "high" for f in findings)


@pytest.mark.parametrize("predicate", [b"True", b"n > 0"])
def test_filter_preserving_consumer_rows_keeps_existing_equivalence(predicate):
    after = AFTER.replace(b"    assert percent", b"    if " + predicate + b":\n        assert percent", 1)
    ir, findings, verdict = run(after)
    assert projected(ir)
    assert verdict == "pass" and not findings
