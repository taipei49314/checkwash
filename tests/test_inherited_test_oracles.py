"""Issue #132 C8: pytest collects methods inherited from non-Test bases."""

import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.frontends.python import parse_python


BEFORE = '''from app import total
class Base:
    def test_total(self):
        assert total() == 3
class TestTotal(Base):
    pass
'''


def run(before, after):
    return analyze(
        [FileChange("tests/test_total.py", "modified", before.encode(), after.encode())],
        Config(), Contract(), [], datetime.date(2026, 9, 21),
        root_reader={}.get, root_searcher=lambda _needles: [],
    )


def test_inherited_expectation_rewrite_blocks():
    ir, findings, verdict = run(BEFORE, BEFORE.replace("== 3", "== 2"))
    assert verdict == "block"
    assert any(f.rule == "EXPECTED_VALUE_CHANGED" and f.severity == "high" for f in findings)
    assert [u.qualname for u in ir.files[0].units] == ["TestTotal.test_total"]


def test_inherited_method_extraction_preserves_the_same_unit():
    inline = BEFORE[:BEFORE.index("class Base:")] + '''class TestTotal:
    def test_total(self):
        assert total() == 3
'''
    _, findings, verdict = run(inline, BEFORE)
    assert verdict == "pass"
    assert not findings


def test_deleting_collecting_subclass_disables_inherited_test():
    _, findings, verdict = run(BEFORE, BEFORE[:BEFORE.index("class TestTotal")])
    assert verdict == "block"
    assert any(f.rule == "TEST_DISABLED" for f in findings)


@pytest.mark.parametrize("body", ["test_total = None", "def test_total(self):\n        assert total() == 3"])
def test_subclass_binding_overrides_inherited_method(body):
    source = BEFORE.replace("    pass", "    " + body)
    parsed = parse_python(source.encode(), collect_tests=True)
    assert len(parsed.units) == (1 if body.startswith("def") else 0)


def test_diamond_uses_c3_method_resolution():
    source = BEFORE[:BEFORE.index("class TestTotal")] + '''class Left(Base):
    pass
class Right(Base):
    def test_total(self):
        assert total() == 4
class TestTotal(Left, Right):
    pass
'''
    parsed = parse_python(source.encode(), collect_tests=True)
    assert len(parsed.units) == 1
    assert parsed.units[0].side.assertions[0].right_value == "4"


@pytest.mark.parametrize("suffix", [
    "class TestTotal(Base):\n    __test__ = False\n",
    "class TestTotal(Unknown, Base):\n    pass\n",
    "@decorate\nclass TestTotal(Base):\n    pass\n",
    "class TestTotal(Base, metaclass=Meta):\n    pass\n",
    "class TestTotal(Base):\n    def __init__(self):\n        pass\n",
])
def test_disabled_or_dynamic_hierarchy_has_no_inherited_proof(suffix):
    source = BEFORE[:BEFORE.index("class TestTotal")] + suffix
    assert not parse_python(source.encode(), collect_tests=True).units


def test_two_collectors_keep_two_inherited_oracles():
    source = BEFORE + "class TestOther(Base):\n    pass\n"
    parsed = parse_python(source.encode(), collect_tests=True)
    assert [unit.qualname for unit in parsed.units] == ["TestTotal.test_total", "TestOther.test_total"]


def test_runtime_inherited_rewrite_hides_the_bug(tmp_path):
    import os
    import subprocess
    import sys

    statuses = []
    for number, source in enumerate((BEFORE, BEFORE.replace("== 3", "== 2"))):
        checkout = tmp_path / str(number)
        checkout.mkdir()
        (checkout / "app.py").write_text("def total():\n    return 2\n", encoding="utf-8")
        test = checkout / "test_total.py"
        test.write_text(source, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--import-mode=importlib", str(test)],
            cwd=checkout, capture_output=True, text=True, timeout=30,
            env=dict(os.environ, PYTHONPATH=str(checkout), PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"),
        )
        statuses.append(result.returncode)
    assert statuses == [1, 0]
