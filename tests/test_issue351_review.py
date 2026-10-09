"""Bounds and cross-file evidence regressions from the #351 handover."""
import ast

from checkwash.frontends.python.frontend import _Offsets, parse_conftest_level
from checkwash.frontends.python.setup_skip_controls import ConftestGuard, _CLOSE_TOTAL
from checkwash.ir.markers import skip_condition
from checkwash.ir.model import Marker
from test_issue351_conftest_guards import conftest, guard_of, module
from test_issue358_own_mark_guards import setup_markers


def test_stacked_own_mark_guard_keeps_conftest_evidence():
    source = "import pytest\n@pytest.fixture(autouse=True)\ndef gate(request):\n"
    source += "    if request.node.get_closest_marker('slow'):\n        pytest.skip('off')\n"
    level = parse_conftest_level(source.encode(), "tests/conftest.py")
    assert setup_markers(module("test_total()"), (level,))["test_total"] == []
    marked = module("test_total()").replace("def test_total", "@pytest.mark.slow\ndef test_total")
    assert setup_markers(marked, (level,))["test_total"] == [("setup.gate.skip", None)]


def test_mapping_rest_capture_does_not_read_a_conftest_constant():
    source = "import pytest\nextra = True\n@pytest.fixture\ndef gate(value):\n"
    source += "    match value:\n        case {**extra}:\n            pass\n"
    source += "    if extra:\n        pytest.skip('off')\n"
    assert guard_of(source) == "conftest.extra"


def test_a_long_condition_is_unknown_before_copying_its_source():
    source = conftest(" or ".join("UNKNOWN" for _ in range(1500)))
    tree = ast.parse(source)
    off = _Offsets(source)
    reads = []

    def text_of(node):
        reads.append(node)
        return off.seg(node)

    closer = ConftestGuard(tree, text_of, off.span)
    condition = next(node.test for node in ast.walk(tree) if isinstance(node, ast.If))
    assert closer(condition) == "conftest.<unreadable>"
    assert reads == []


def test_closure_budget_is_shared_across_conditions():
    source = conftest(" or ".join("FLAG" for _ in range(180)), prelude="import pytest\nFLAG = '" + "a" * 200 + "'\n")
    tree = ast.parse(source)
    off = _Offsets(source)
    closer = ConftestGuard(tree, off.seg, off.span)
    condition = next(node.test for node in ast.walk(tree) if isinstance(node, ast.If))
    for _ in range(100):
        assert len(closer(condition)) <= 4096
    assert closer._remaining <= 0 or closer._remaining < _CLOSE_TOTAL // 10
    assert closer(condition) == "conftest.<unreadable>"


def test_setup_evidence_does_not_use_a_test_modules_handler_offsets():
    from types import SimpleNamespace

    marker = Marker("setup.gate.skip", "pytest.skip('off')", (10, 20))
    side = SimpleNamespace(handlers=[SimpleNamespace(span=(0, 30), text="except ImportError:")])
    assert skip_condition(marker, side) is None


def test_source_offsets_scan_each_ascii_line_once():
    off = _Offsets("a" * 10000 + "\n")
    for column in (1, 50, 9999):
        assert off._char_col(1, column) == column
    assert off._ascii_lines == {0: True}
