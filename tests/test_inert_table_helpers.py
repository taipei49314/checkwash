"""Issue #130: an unused non-oracle helper cannot erase table equivalence."""
import ast
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.frontends.python.inert_helpers import prune_inert_helpers

HELPER = '''def hamming_distance(a, b):
    if len(a) != len(b):
        raise ValueError("length mismatch")
    return sum(x != y for x, y in zip(a, b))
'''
BEFORE = '''from app.hamming import hamming
def test_hamming_a():
    assert hamming("karolin", "kathrin") == 3
def test_hamming_b():
    assert hamming("000", "111") == 3
def test_hamming_c():
    assert hamming("abc", "abc") == 0
'''
AFTER = '''import pytest
from app.hamming import hamming
@pytest.fixture
def test_data():
    return [("karolin", "kathrin", 3), ("000", "111", 3), ("abc", "abc", 0)]
''' + HELPER + '''def test_hamming_distance(test_data):
    for a, b, expected in test_data:
        assert hamming(a, b) == expected
'''


def run(after):
    return analyze([FileChange("tests/test_hamming.py", "modified", BEFORE.encode(), after.encode())],
                   Config(), Contract(), [], datetime.date(2026, 9, 21),
                   root_reader={}.get, root_searcher=lambda _: [])


def test_unused_pure_helper_keeps_exact_table_oracles():
    _, findings, verdict = run(AFTER)
    assert verdict == "pass"
    assert not findings


@pytest.mark.parametrize("after", [AFTER.replace('"abc", "abc", 0', '"abc", "abc", 1'),
                                       AFTER.replace(', ("abc", "abc", 0)', '')])
def test_unused_pure_helper_does_not_hide_rewritten_or_missing_row(after):
    _, findings, verdict = run(after)
    assert verdict == "block"
    assert any(f.severity == "high" for f in findings)


@pytest.mark.parametrize("source", [
    HELPER.replace("a, b", "a=external(), b=0", 1),
    "@external\n" + HELPER,
    HELPER.replace("a, b", "a: external(), b", 1),
    HELPER + "saved = hamming_distance\n",
    HELPER + "hamming_distance = external\n",
    HELPER + "value = namespace.hamming_distance\n",
    HELPER + 'value = getattr(namespace, "hamming_distance")\n',
    HELPER + 'value = globals()["hamming_" + "distance"]\n',
    HELPER + "hamming_distance.__code__ = external\n",
    HELPER + "def hamming_distance():\n    return 0\n",
    HELPER.replace("return sum", "assert a == b\n    return sum"),
    HELPER.replace("return sum", "mutate()\n    return sum"),
    "from other import sum\n" + HELPER,
    HELPER.replace("def hamming_distance", "def test_hamming_distance"),
])
def test_callable_context_and_non_inert_helpers_are_retained(source):
    tree = ast.parse(source)
    before = ast.dump(tree)
    prune_inert_helpers(tree)
    assert ast.dump(tree) == before
