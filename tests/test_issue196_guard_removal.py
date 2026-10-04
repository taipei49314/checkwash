"""A body skip whose guard the diff removed is reported (#196 183.2).

THREATMODEL 54. `if sys.version_info < (3, 9): pytest.skip()` becoming
`if True: pytest.skip()` has reported "skip guard now always fires" since
T1.8, because the edited guard can be evaluated. Removing the `if` instead
left nothing to evaluate: the call keeps its name, so no marker is added, and
the verdict passed. A skip that ran only under an `if` guard, or inside an
`except` block, and now runs under neither is reported as TEST_DISABLED with
the guard family's identity, so no recorded fingerprint moves.
"""
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.findings import make_fingerprint

PATH = "tests/test_billing.py"
APP = FileChange("app/__init__.py", "added", None, b"")
BILLING = b"def total():\n    return 78.75\n"

GUARDED = '''import sys

import pytest

from app.billing import total


def test_total():
    if sys.version_info < (3, 9):
        pytest.skip("needs 3.9")
    assert total() == 78.75
'''
BARE = GUARDED.replace('    if sys.version_info < (3, 9):\n        pytest.skip("needs 3.9")\n',
                       '    pytest.skip("needs 3.9")\n')
EXCEPT = '''import pytest

from app.billing import total


def test_total():
    try:
        import numpy
    except ImportError:
        pytest.skip("needs numpy")
    assert total() == 78.75
'''
UNITTEST = '''import sys
import unittest

from app.billing import total


class TestTotal(unittest.TestCase):
    def test_total(self):
        if sys.platform == "win32":
            self.skipTest("posix only")
        self.assertEqual(total(), 78.75)
'''


def analyze_test(before, after, *extra):
    changes = [FileChange(PATH, "modified", before.encode(), after.encode()), *extra]
    _ir, findings, verdict = analyze(
        changes, Config(), Contract(), [], datetime.date(2026, 10, 4),
        head_reader={"app/billing.py": BILLING, "app/__init__.py": b""}.get,
    )
    return [f for f in findings if f.rule == "TEST_DISABLED"], verdict


def removed(before, after):
    found, verdict = analyze_test(before, after)
    assert verdict == "block", found
    assert len(found) == 1, found
    return found[0]


@pytest.mark.parametrize("before, after, was", [
    (GUARDED, BARE, "sys.version_info < (3, 9)"),
    (GUARDED.replace('pytest.skip("needs 3.9")', 'pytest.xfail("needs 3.9")'),
     BARE.replace('pytest.skip("needs 3.9")', 'pytest.xfail("needs 3.9")'), "sys.version_info < (3, 9)"),
    (UNITTEST, UNITTEST.replace('        if sys.platform == "win32":\n            self.skipTest("posix only")\n',
                                '        self.skipTest("posix only")\n'), 'sys.platform == "win32"'),
    # An unevaluable guard still ran the test somewhere.
    (GUARDED.replace("sys.version_info < (3, 9)", 'not os.environ.get("BILLING_DB")').replace("import sys", "import os"),
     BARE.replace("import sys", "import os"), 'not os.environ.get("BILLING_DB")'),
    # The else branch records the negated test.
    (GUARDED.replace('    if sys.version_info < (3, 9):\n        pytest.skip("needs 3.9")\n',
                     '    if sys.version_info >= (3, 9):\n        pass\n    else:\n        pytest.skip("needs 3.9")\n'),
     BARE, "not (sys.version_info >= (3, 9))"),
    # Nested guards are one conjunction.
    (GUARDED.replace('    if sys.version_info < (3, 9):\n        pytest.skip("needs 3.9")\n',
                     '    if sys.platform == "win32":\n        if sys.version_info < (3, 9):\n'
                     '            pytest.skip("needs 3.9")\n'),
     BARE, 'sys.platform == "win32" and sys.version_info < (3, 9)'),
    # Out of an `except` block: it ran only when the import failed.
    (EXCEPT, EXCEPT.replace('    try:\n        import numpy\n    except ImportError:\n        pytest.skip("needs numpy")\n',
                            '    pytest.skip("needs numpy")\n'), "except ImportError:"),
    # A `with` or `try` body runs; the skip in it fires.
    (GUARDED, BARE.replace('    pytest.skip("needs 3.9")\n',
                           '    with open(__file__):\n        pytest.skip("needs 3.9")\n'), "sys.version_info < (3, 9)"),
    (GUARDED, BARE.replace('    pytest.skip("needs 3.9")\n',
                           '    try:\n        pytest.skip("needs 3.9")\n    finally:\n        pass\n'),
     "sys.version_info < (3, 9)"),
    # The reason may change with it.
    (GUARDED, BARE.replace("needs 3.9", "flaky on CI"), "sys.version_info < (3, 9)"),
])
def test_a_removed_guard_is_reported(before, after, was):
    finding = removed(before, after)
    assert finding.severity == "high"
    assert finding.escalators == ["NO_PROD_CHANGE_IN_DIFF"]
    assert finding.message.endswith(f": skip guard removed (was {was!r})")


def test_the_finding_shares_the_guard_familys_identity():
    finding = removed(GUARDED, BARE)
    assert finding.unit == "test_total"
    assert finding.fingerprint == make_fingerprint("TEST_DISABLED", PATH, "test_total", "guard:pytest.skip")
    always = removed(GUARDED, GUARDED.replace("if sys.version_info < (3, 9):", "if True:"))
    assert always.fingerprint == finding.fingerprint
    assert always.message.endswith(": skip guard now always fires ('True')")
    assert finding.after is not None and finding.after.text == 'pytest.skip("needs 3.9")'


def test_every_base_instance_must_have_run_under_a_condition():
    # The base already skipped unconditionally at one site; removing the other
    # guard disables nothing that ran.
    before = GUARDED.replace("    assert total()", '    pytest.skip("always")\n    assert total()')
    after = BARE.replace("    assert total()", '    pytest.skip("always")\n    assert total()')
    assert analyze_test(before, after) == ([], "pass")


def test_one_guard_of_two_removed_is_reported():
    before = GUARDED.replace("    assert total()",
                             '    if not os.environ.get("BILLING_DB"):\n        pytest.skip("no db")\n    assert total()'
                             ).replace("import sys\n", "import os\nimport sys\n")
    after = before.replace('    if sys.version_info < (3, 9):\n        pytest.skip("needs 3.9")\n',
                           '    pytest.skip("needs 3.9")\n')
    assert removed(before, after).message.endswith(": skip guard removed (was 'sys.version_info < (3, 9)')")


def test_an_honest_gate_beside_it_holds_it_at_warn():
    # Residual (#208): D6 grants COMPAT_GATE per unit, not per marker, so a
    # qualified version or platform gate left on the unit holds the removed
    # guard at warn. The finding is still reported.
    before = GUARDED.replace("    assert total()",
                             '    if sys.platform == "win32":\n        pytest.skip("posix only")\n    assert total()')
    after = before.replace('    if sys.version_info < (3, 9):\n        pytest.skip("needs 3.9")\n',
                           '    pytest.skip("needs 3.9")\n')
    found, verdict = analyze_test(before, after)
    assert verdict == "pass"
    assert [(f.severity, f.deescalators, f.message) for f in found] == [
        ("warn", ["COMPAT_GATE"], "test_total: skip guard removed (was 'sys.version_info < (3, 9)')")
    ]


@pytest.mark.parametrize("before, after", [
    # Into an `except` block: the skip still runs only when the import fails.
    (GUARDED.replace("sys.version_info < (3, 9)", "not HAS_NUMPY").replace("import sys\n", "HAS_NUMPY = False\n"),
     EXCEPT),
    # One discriminating guard rewritten into another.
    (GUARDED, GUARDED.replace("(3, 9)", "(3, 10)")),
    # The skip deleted with its guard.
    (GUARDED, BARE.replace('    pytest.skip("needs 3.9")\n', "")),
    # Only the reason changed.
    (GUARDED, GUARDED.replace("needs 3.9", "needs Python 3.9")),
    # An always-true guard removed: the base skipped everywhere already.
    (GUARDED.replace("sys.version_info < (3, 9)", "True"), BARE),
    # The base skip had no condition either.
    (BARE, BARE.replace("needs 3.9", "flaky")),
    # Still inside the same `except` block.
    (EXCEPT, EXCEPT.replace("needs numpy", "numpy missing")),
    # `importorskip` is conditional by itself; its guard is not D6's condition.
    (GUARDED.replace('pytest.skip("needs 3.9")', 'pytest.importorskip("numpy")'),
     BARE.replace('pytest.skip("needs 3.9")', 'pytest.importorskip("numpy")')),
])
def test_a_skip_that_keeps_a_condition_is_quiet(before, after):
    assert analyze_test(before, after) == ([], "pass")


def test_a_second_bare_skip_is_a_marker_added_not_a_removed_guard():
    # The guarded skip stays; the bare one is new, and markers count as a
    # multiset, so the existing marker-added path reports it.
    after = GUARDED.replace("    assert total()", '    pytest.skip("later")\n    assert total()')
    found, _verdict = analyze_test(GUARDED, after)
    assert [f.message for f in found] == ["test_total: disabling marker added (pytest.skip)"]


def test_a_production_change_explains_it_as_any_disable():
    billing = FileChange("app/billing.py", "modified", BILLING, b"def total():\n    return 78.7\n")
    found, verdict = analyze_test(GUARDED, BARE, billing)
    assert verdict == "pass", found
    assert len(found) == 1 and found[0].severity == "warn"
    assert "REPAIR_EVIDENCE" in found[0].deescalators


def test_a_loop_body_records_no_condition():
    # Residual (row 54): a skip moved into a loop body or a `match` case with
    # no `if` is read as unconditional, although the loop may not run.
    after = BARE.replace('    pytest.skip("needs 3.9")\n',
                         '    for case in CASES:\n        pytest.skip("needs 3.9")\n').replace(
        "import pytest\n", "import pytest\n\nCASES = [1]\n")
    finding = removed(GUARDED.replace("import pytest\n", "import pytest\n\nCASES = [1]\n"), after)
    assert finding.message.endswith(": skip guard removed (was 'sys.version_info < (3, 9)')")


def test_the_innermost_except_block_names_the_condition():
    before = EXCEPT.replace(
        '    try:\n        import numpy\n    except ImportError:\n        pytest.skip("needs numpy")\n',
        '    try:\n        import numpy\n    except ImportError:\n        try:\n'
        '            import numpy_compat as numpy\n        except ModuleNotFoundError:\n'
        '            pytest.skip("needs numpy")\n')
    after = EXCEPT.replace('    try:\n        import numpy\n    except ImportError:\n        pytest.skip("needs numpy")\n',
                           '    pytest.skip("needs numpy")\n')
    assert removed(before, after).message.endswith(": skip guard removed (was 'except ModuleNotFoundError:')")


def test_the_evidence_is_the_skip_that_lost_its_guard():
    # The guarded skip comes first in the unit's marker order here.
    extra = '    if not os.environ.get("BILLING_DB"):\n        pytest.skip("no db")\n'
    before = GUARDED.replace("import sys\n", "import os\nimport sys\n").replace(
        '    if sys.version_info < (3, 9):', extra + '    if sys.version_info < (3, 9):')
    after = before.replace('    if sys.version_info < (3, 9):\n        pytest.skip("needs 3.9")\n',
                           '    with open(__file__):\n        pytest.skip("needs 3.9")\n')
    finding = removed(before, after)
    assert finding.after is not None and finding.after.text == 'pytest.skip("needs 3.9")'
