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


def run(after, before=BEFORE, production=None):
    sources = production if production is not None else {
        'app/hamming.py': HELPER.replace('def hamming_distance(', 'def hamming(').encode(),
    }
    return analyze([FileChange("tests/test_hamming.py", "modified", before.encode(), after.encode())],
                   Config(), Contract(), [], datetime.date(2026, 9, 21),
                   root_reader=sources.get, root_searcher=lambda _: [])


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
    "def load_tests(loader, tests, pattern):\n    return []\n",
    "def setUpModule():\n    return 1\n",
    "def tearDownModule():\n    return 1\n",
])
def test_callable_context_and_non_inert_helpers_are_retained(source):
    tree = ast.parse(source)
    before = ast.dump(tree)
    prune_inert_helpers(tree)
    assert ast.dump(tree) == before


@pytest.mark.parametrize('production', [
    {},
    {'app/hamming.py': b'from tests.test_hamming import hamming_distance\ndef hamming(a,b):\n    return hamming_distance(a,b)\n'},
    {'app/hamming.py': b'def hamming(a,b):\n    return globals()["callback"](a,b)\n'},
    {'app/hamming.py': b'def sum(values):\n    return 0\ndef hamming(a,b):\n    return sum(x != y for x,y in zip(a,b))\n'},
])
def test_unreferenced_local_helper_needs_closed_production_call_graph(production):
    ir, _, _ = run(AFTER, production=production)
    assert not any(unit.qualname.startswith('test_concrete_') for unit in ir.files[0].units)


def test_production_backlink_cannot_hide_red_to_green_helper_change():
    before = '''from app.prod import f
def hidden(value):
    return 0
def test_one():
    assert f(1) == 1
def test_two():
    assert f(2) == 2
'''
    after = '''import pytest
from app.prod import f
def hidden(value):
    return value
@pytest.mark.parametrize("value,expected", [(1, 1), (2, 2)])
def test_values(value, expected):
    assert f(value) == expected
'''
    sources = {'app/prod.py': b'def f(value):\n    from tests.test_hamming import hidden\n    return hidden(value)\n'}
    ir, _, _ = run(after, before, sources)
    assert not any(unit.qualname.startswith('test_concrete_') for unit in ir.files[0].units)
