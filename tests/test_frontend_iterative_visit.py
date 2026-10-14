"""Owned deep-input and lexical-context controls; never execute input sources."""

import sys
from dataclasses import asdict

import pytest

import test_string_chain_syntax as cases
from checkwash.frontends.python.frontend import parse_python


@pytest.mark.parametrize("side", [0, 1])
def test_original_deep_megabyte_preserves_the_complete_tail_unit(side):
    source = cases.pair(cases.DEEP)[side]
    tail = (cases.BEFORE, cases.AFTER)[side]
    shallow = cases.padded(b"padding = 0\n", tail, cases.SIZE)
    limit = sys.getrecursionlimit()
    assert len(source) == 1_000_000
    assert source.count(b" + ") == 9898
    expected = parse_python(shallow, collect_tests=True)
    actual = parse_python(source, collect_tests=True)
    assert sys.getrecursionlimit() == limit
    assert expected.parse_ok and actual.parse_ok
    assert len(expected.units) == len(actual.units) == 1
    assert actual.units[0].qualname == "test_total"
    assert len(actual.units[0].side.assertions) == 1
    assert [asdict(unit) for unit in actual.units] == [asdict(unit) for unit in expected.units]
    assert actual.imports == expected.imports
    assert actual.symbols == expected.symbols == {}


def test_collection_order_and_class_marks_do_not_leak_across_siblings():
    source = b"""import pytest
if enabled:
    class TestSkipped:
        pytestmark = pytest.mark.skip(reason='owned scope')
        def test_a(self):
            assert result() == 1
        class TestInner:
            def test_b(self):
                assert result() == 2
def helper():
    def test_hidden():
        assert result() == 99
    class TestHidden:
        def test_hidden_class(self):
            assert result() == 99
class TestLive:
    def test_c(self):
        assert result() == 3
def test_repeat():
    assert result() == 4
async def test_repeat():
    assert result() == 5
"""
    parsed = parse_python(source, collect_tests=True)
    assert parsed.parse_ok
    assert [unit.qualname for unit in parsed.units] == [
        "TestSkipped.test_a", "TestSkipped.TestInner.test_b",
        "TestLive.test_c", "test_repeat", "test_repeat#2",
    ]
    assert all(len(unit.side.assertions) == 1 for unit in parsed.units)
    marks = [[marker.name for marker in unit.side.markers] for unit in parsed.units]
    assert marks == [["pytest.mark.skip"], ["pytest.mark.skip"], [], [], []]


def test_symbol_scope_and_call_edges_survive_descent_and_return():
    source = b"""VALUE = 1
class Service:
    TIMEOUT = 30
    def run(self):
        def helper():
            return fetch()
        return helper()
def finish():
    return close()
"""
    before = parse_python(source, collect_tests=False)
    after = parse_python(source.replace(b"TIMEOUT = 30", b"TIMEOUT = 31"), collect_tests=False)
    assert before.parse_ok and after.parse_ok
    assert list(before.symbols) == list(after.symbols) == [
        "VALUE", "Service", "Service.TIMEOUT", "Service.run", "Service.run.helper", "finish",
    ]
    assert before.symbol_calls == after.symbol_calls == {
        "Service.run": ("fetch", "helper"),
        "Service.run.helper": ("fetch",),
        "finish": ("close",),
    }
    changed = {key for key in before.symbols if before.symbols[key] != after.symbols[key]}
    assert changed == {"Service", "Service.TIMEOUT"}


def test_invalid_source_still_reports_parse_failure():
    parsed = parse_python(b"def broken(:\n    pass\n", collect_tests=True)
    assert parsed.parse_ok is False
    assert parsed.units == []
