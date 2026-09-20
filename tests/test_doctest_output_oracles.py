"""Issue #132 C7: an explicitly executed doctest's expected output is an oracle."""
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.frontends.python import parse_python

BEFORE = '''import doctest
import sys
from app import twice
def _oracle():
    """
    >>> twice(4)
    8
    """
def test_twice():
    failures, _ = doctest.testmod(sys.modules[__name__])
    assert failures == 0
'''


def run(before, after):
    return analyze(
        [FileChange("tests/test_twice.py", "modified", before.encode(), after.encode())],
        Config(), Contract(), [], datetime.date(2026, 9, 21),
        root_reader={}.get, root_searcher=lambda _: [],
    )


def test_changed_output_is_a_blocking_expectation_rewrite():
    _, findings, verdict = run(BEFORE, BEFORE.replace("    8\n", "    9\n"))
    assert verdict == "block"
    assert any(f.rule == "EXPECTED_VALUE_CHANGED" and f.severity == "high" for f in findings)


def test_removing_the_runner_removes_its_output_oracle():
    after = BEFORE[:BEFORE.index("    failures, _")] + "    assert _oracle.__doc__ is not None\n"
    _, findings, verdict = run(BEFORE, after)
    assert verdict == "block"
    assert any(f.rule == "ASSERT_REMOVED" for f in findings)


def test_unchanged_checked_doctest_passes():
    _, findings, verdict = run(BEFORE, BEFORE.replace("def _oracle():", "# Example\ndef _oracle():"))
    assert verdict == "pass"
    assert not findings


@pytest.mark.parametrize("source", [
    BEFORE.replace("assert failures == 0", "assert True"),
    BEFORE.replace("    assert failures", "    failures = 0\n    assert failures"),
    BEFORE.replace("doctest.testmod(sys.modules[__name__])", "doctest.testmod(other)"),
    BEFORE.replace("doctest.testmod(sys.modules[__name__])", "doctest.testmod(optionflags=doctest.ELLIPSIS)"),
    BEFORE.replace(">>> twice(4)", ">>> twice(4)  # doctest: +SKIP"),
    BEFORE.replace("def test_twice():", "doctest = external\ndef test_twice():"),
    BEFORE.replace("def test_twice():", "def test_twice(doctest):"),
    BEFORE.replace("def test_twice():", "def test_twice(sys):"),
    BEFORE.replace("import doctest", "import doctest\nimport external as doctest"),
    BEFORE.replace("def test_twice():", "doctest.testmod = external\ndef test_twice():"),
    BEFORE[:BEFORE.index("def test_twice")],
])
def test_unchecked_or_dynamic_runner_does_not_claim_execution(source):
    parsed = parse_python(source.encode(), collect_tests=True)
    assert not any(assertion.inherited for unit in parsed.units for assertion in unit.side.assertions)


def test_live_doctest_output_rewrite_hides_bug(tmp_path):
    import os
    import subprocess
    import sys

    statuses = []
    for number, source in enumerate((BEFORE, BEFORE.replace("    8\n", "    9\n"))):
        checkout = tmp_path / str(number)
        checkout.mkdir()
        (checkout / "app.py").write_text("def twice(n):\n    return n * 2 + 1\n", encoding="utf-8")
        (checkout / "test_twice.py").write_text(source, encoding="utf-8")
        result = subprocess.run([sys.executable, "-m", "pytest", "-q", "test_twice.py"],
                                cwd=checkout, capture_output=True, text=True, timeout=30,
                                env=dict(os.environ, PYTHONPATH=str(checkout), PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"))
        statuses.append(result.returncode)
    assert statuses == [1, 0]
