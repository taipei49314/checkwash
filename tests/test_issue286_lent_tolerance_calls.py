"""numpy's and torch's assertion calls are lent as a bare `assert` is (#286).

#222 made `numpy.testing.assert_allclose`, `assert_array_almost_equal`,
`assert_almost_equal` and `torch.testing.assert_close` assertions, read in a
test unit and in a same-file helper it calls. A fixture the test requests and
a helper another file defines lent the test their bare `assert`s only, so the
same call there was no assertion: widening its tolerance or deleting it
passed, while `assert np.allclose(...)` in the same place blocked.

`_classified_asserts`, which builds what a fixture and a module helper lend
(A5-x), reads the calls the unit's own walk reads.
"""
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.frontends.python.frontend import parse_python

TEST = "tests/test_billing.py"
HEAD = "import numpy as np\nimport pytest\n\nfrom app.billing import total\n\n\n"
FIXTURE = "@pytest.fixture\ndef checked():\n    {body}\n\n\ndef test_total(checked):\n    assert total() > 0\n"


def outcome(changes, head=None):
    reader = head.get if head else None
    _ir, findings, verdict = analyze(
        changes, Config(), Contract(), [], datetime.date(2026, 10, 6),
        head_reader=reader,
        head_searcher=(lambda needles: [p for p, data in sorted(head.items())
                                        if any(n.encode() in data for n in needles)]) if head else None,
    )
    return verdict, [(f.rule, f.severity, f.message.split(": ", 1)[1]) for f in findings]


def edit(before, after, path=TEST):
    return FileChange(path, "modified", before.encode(), after.encode())


LOOSENED_NP = ("block", [("TOLERANCE_LOOSENED", "high", "tolerance loosened (abs=0|rel=1e-7 -> abs=0|rel=0.5)")])
REMOVED = ("block", [("ASSERT_REMOVED", "high", "assertion removed (strength APPROX)")])


# --- the issue's rows ----------------------------------------------------------------

def test_f1_a_fixtures_call_widened_is_a_tolerance_loosened():
    before = HEAD + FIXTURE.format(body="np.testing.assert_allclose(total(), 78.75, rtol=1e-7)")
    after = HEAD + FIXTURE.format(body="np.testing.assert_allclose(total(), 78.75, rtol=0.5)")
    assert outcome([edit(before, after)]) == LOOSENED_NP


def test_f2_a_fixtures_call_deleted_is_an_assertion_removed():
    before = HEAD + FIXTURE.format(body="np.testing.assert_allclose(total(), 78.75, rtol=1e-7)")
    after = HEAD + FIXTURE.format(body="pass")
    assert outcome([edit(before, after)]) == REMOVED


def test_h1_a_test_that_stops_calling_another_files_helper_loses_its_assertion():
    helper = "import numpy as np\n\n\ndef check(value):\n    np.testing.assert_allclose(value, 78.75, rtol=1e-7)\n"
    head = {"tests/__init__.py": b"", "tests/helpers.py": helper.encode()}
    importer = "from app.billing import total\nfrom tests.helpers import check\n\n\ndef test_total():\n    {body}\n"
    before, after = importer.format(body="check(total())"), importer.format(body="total()")
    assert outcome([edit(before, after)], head) == REMOVED


def test_the_bare_assert_spelling_is_the_contrast():
    before = HEAD + FIXTURE.format(body="assert np.allclose(total(), 78.75, rtol=1e-5)")
    after = HEAD + FIXTURE.format(body="assert np.allclose(total(), 78.75, rtol=0.5)")
    assert outcome([edit(before, after)])[0] == "block"


# --- every channel that lends a bare assert lends the call -------------------------------

def test_a_conftest_fixture_lends_it():
    conftest = "import numpy as np\nimport pytest\n\n\n@pytest.fixture\ndef checked():\n    {call}\n"
    test = "from app.billing import total\n\n\ndef test_total(checked):\n    assert total() > 0\n"
    before = conftest.format(call="np.testing.assert_allclose(1.0, 1.0, rtol=1e-7)")
    after = conftest.format(call="np.testing.assert_allclose(1.0, 1.0, rtol=0.5)")
    verdict, findings = outcome([edit(before, after, "tests/conftest.py"), edit(test, test + "\n")])
    assert ("TOLERANCE_LOOSENED", "high") in [f[:2] for f in findings], findings


def test_an_autouse_fixture_lends_it():
    autouse = "@pytest.fixture(autouse=True)\ndef checked():\n    {body}\n\n\ndef test_total():\n    assert total() > 0\n"
    before = HEAD + autouse.format(body="np.testing.assert_allclose(total(), 78.75, rtol=1e-7)")
    after = HEAD + autouse.format(body="pass")
    assert outcome([edit(before, after)]) == REMOVED


def test_torch_assert_close_is_lent_too():
    head = "import pytest\nimport torch\n\nfrom app.billing import total\n\n\n"
    before = head + FIXTURE.format(body="torch.testing.assert_close(total(), 78.75)")
    after = head + FIXTURE.format(body="pass")
    assert outcome([edit(before, after)]) == REMOVED


def test_a_closure_inside_the_fixture_lends_it_as_its_asserts_are():
    """A fixture lends everything lexically inside it: the closure it returns is what the test calls."""
    body = "def check(value):\n        np.testing.assert_allclose(value, 78.75, rtol=1e-7)\n    return check"
    before = HEAD + FIXTURE.format(body=body)
    after = HEAD + FIXTURE.format(body=body.replace("rtol=1e-7", "rtol=0.5"))
    assert outcome([edit(before, after)]) == LOOSENED_NP


# --- controls --------------------------------------------------------------------------

@pytest.mark.parametrize("body", [
    "np.testing.assert_allclose(total(), 78.75, rtol=1e-7)",
    "np.testing.assert_almost_equal(total(), 78.75, decimal=6)",
])
def test_an_unchanged_call_is_no_event(body):
    source = HEAD + FIXTURE.format(body=body)
    assert outcome([edit(source, source + "\n")]) == ("pass", [])


def test_a_call_that_is_no_assertion_is_not_lent():
    """`np.allclose` returns a bool: only the assertion calls are statements."""
    module = parse_python((HEAD + FIXTURE.format(body="np.allclose(total(), 78.75)")).encode(), collect_tests=True)
    assert module.fixture_asserts == {}


@pytest.mark.parametrize("call", [
    "np.testing.assert_allclose(total(), 78.75, rtol=1e-7)",
    # two literals: the call can fail on nothing, so it is no real oracle
    "np.testing.assert_allclose(78.75, 78.75, rtol=1e-7)",
], ids=["subject", "two_literals"])
def test_the_lent_assertion_is_the_units_own_reading(call):
    """The same call in the test and in its fixture is one approximate comparison."""
    own = parse_python((HEAD + "def test_total():\n    " + call + "\n").encode(), collect_tests=True)
    lent = parse_python((HEAD + FIXTURE.format(body=call)).encode(), collect_tests=True)
    [a] = own.units[0].side.assertions
    [b] = lent.fixture_asserts["checked"]
    keep = ("form", "strength", "right_literal", "epsilon", "epsilon_kind", "positive", "left", "trivial")
    assert {k: getattr(a, k) for k in keep} == {k: getattr(b, k) for k in keep}
    assert b.inherited
