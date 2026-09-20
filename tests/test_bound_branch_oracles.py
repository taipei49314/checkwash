"""Issue #132 C6: immutable local/fixture values can disable an assertion."""
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.frontends.python import parse_python


LOCAL = '''from app import total
def test_total():
    enabled = True
    if enabled:
        assert total() == 3
'''
FIXTURE = '''import pytest
from app import total
@pytest.fixture
def enabled():
    return True
def test_total(enabled):
    if enabled:
        assert total() == 3
'''


@pytest.mark.parametrize("before", [LOCAL, FIXTURE, LOCAL.replace("if enabled:", "if not not enabled:")])
def test_constant_flip_removes_the_executed_oracle(before):
    after = before.replace("True", "False")
    _, findings, verdict = analyze(
        [FileChange("tests/test_total.py", "modified", before.encode(), after.encode())],
        Config(), Contract(), [], datetime.date(2026, 9, 21),
        root_reader={}.get, root_searcher=lambda _: [],
    )
    assert verdict == "block"
    assert any(f.rule == "ASSERT_REMOVED" and f.severity == "high" for f in findings)


@pytest.mark.parametrize("source", [
    LOCAL.replace("enabled = True", "enabled = False\n    enabled = external()"),
    LOCAL.replace("enabled = True", "enabled = False\n    if external():\n        enabled = True"),
    LOCAL.replace("enabled = True", "enabled = False\n    for enabled in [True]:\n        pass"),
    LOCAL.replace("enabled = True", "enabled = False\n    def activate():\n        nonlocal enabled\n        enabled = True\n    activate()"),
    LOCAL.replace("enabled = True", "enabled = False\n    exec('enabled = True')"),
    FIXTURE.replace("return True", "return False").replace("def test_total(enabled):", "@pytest.mark.parametrize('enabled', [True])\ndef test_total(enabled):"),
    FIXTURE.replace("return True", "return external()"),
])
def test_dynamic_or_overridden_binding_does_not_kill_the_assertion(source):
    parsed = parse_python(source.encode(), collect_tests=True)
    assert len(parsed.units[0].side.assertions) == 1


def test_literal_alias_tracks_source_order():
    source = LOCAL.replace("enabled = True", "active = False\n    enabled = active\n    active = True")
    parsed = parse_python(source.encode(), collect_tests=True)
    assert not parsed.units[0].side.assertions


def test_false_branch_does_not_overwrite_later_binding():
    source = LOCAL.replace("enabled = True", "enabled = True\n    if False:\n        enabled = False")
    assert len(parse_python(source.encode(), collect_tests=True).units[0].side.assertions) == 1


@pytest.mark.parametrize("before", [LOCAL, FIXTURE])
def test_runtime_closed_branch_hides_failed_oracle(tmp_path, before):
    import os
    import subprocess
    import sys

    statuses = []
    for number, source in enumerate((before, before.replace("True", "False"))):
        checkout = tmp_path / str(number)
        checkout.mkdir()
        (checkout / "app.py").write_text("def total():\n    return 2\n", encoding="utf-8")
        (checkout / "test_total.py").write_text(source, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "test_total.py"], cwd=checkout,
            capture_output=True, text=True, timeout=30,
            env=dict(os.environ, PYTHONPATH=str(checkout), PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"),
        )
        statuses.append(result.returncode)
    assert statuses == [1, 0]
