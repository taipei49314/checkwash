"""Tolerances compared as one absolute bound, in either language (#196 190.3).

`assertAlmostEqual(x, y, places=7)` -> `delta=7` widened the check from
5e-8 to 7 and passed: a tolerance change took the new side's kind, so the
two bare sevens read as one delta left alone. `places=2` -> `delta=10` was
reported as "delta=2 -> delta=10", and `delta=5` -> `places=3`, a tightening,
blocked as places shrinking from 5 to 3.

Three kinds state an absolute bound on |actual - expected|: `abs`,
unittest's `delta`, and decimal places, which bound it by 5 * 10**-(p + 1)
in unittest (round(a - b, p) == 0) as in Jest (|x - expected| < 10**-p / 2).
One reading converts a pair of two of them to that bound in both languages;
`rel` and several tolerances at once are still compared per kind.
"""

import datetime
import functools
import unittest
from decimal import Decimal

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.detectors.tolerance_loosened import _absolute_bound, _mixed, _recorded
from checkwash.engine import analyze
from checkwash.findings import make_fingerprint

PY_PATH = "tests/test_physics.py"
JS_PATH = "src/total.test.ts"


def _py_source(line):
    return ("import unittest\n\nimport pytest\n\nfrom sim import energy\n\nEPS = 0.5\nN = 2\n\n\n"
            "class TestEnergy(unittest.TestCase):\n    def test_energy(self):\n"
            f"        {line}\n")


def _js_source(line):
    return ('import { test, expect } from "vitest";\nimport { total } from "./total";\n\n'
            'test("total", () => {\n'
            f"  {line}\n"
            "});\n")


@functools.lru_cache(maxsize=None)
def _analyze(path, before, after):
    changes = [FileChange(path, "modified", before.encode(), after.encode())]
    return analyze(changes, Config(), Contract(), [], datetime.date(2026, 10, 6))


def _py(before, after):
    return _analyze(PY_PATH, _py_source(before), _py_source(after))


def _js(before, after):
    return _analyze(JS_PATH, _js_source(before), _js_source(after))


def _changes(outcome):
    ir, _findings, _verdict = outcome
    return [change for file in ir.files for unit in file.units if unit.delta is not None
            for change in unit.delta.tolerance_changes]


def _loosened(outcome):
    _ir, findings, _verdict = outcome
    return [finding for finding in findings if finding.rule == "TOLERANCE_LOOSENED"]


def _almost(tolerance):
    return f"self.assertAlmostEqual(energy(2.0), 19.62{tolerance})"


HAND_ROLLED = "assert abs(energy(2.0) - 19.62) < {}"
APPROX = "assert energy(2.0) == pytest.approx(19.62{})"


# --- The bound each kind states ------------------------------------------------------

@pytest.mark.parametrize("kind,number,bound,label", [
    ("places", "0", "0.5", "places=0"),
    ("places", "2", "0.005", "places=2"),
    ("places", "7", "5E-8", "places=7"),
    ("places", "-1", "5", "places=-1"),
    ("places", "-2", "50", "places=-2"),
    ("places", "307", "5E-308", "places=307"),
    ("places", "-308", "5E+307", "places=-308"),
    ("delta", "0.5", "0.5", "delta=0.5"),
    ("delta", "1e-9", "1E-9", "delta=1e-9"),
    ("abs", "0.01", "0.01", "abs=0.01"),
    ("abs", "1E+12", "1E+12", "abs=1E+12"),
    ("abs", "Infinity", "Infinity", "abs=Infinity"),
])
def test_each_absolute_kind_states_its_bound_exactly(kind, number, bound, label):
    value, shown = _absolute_bound(kind, number)
    assert value == Decimal(bound) and shown == label
    if kind == "places":
        # Written from its digits: one 5 at the place the precision names.
        assert value.as_tuple() == (0, (5,), -int(number) - 1)


@pytest.mark.parametrize("kind,number", [
    ("places", "1.5"), ("places", "308"), ("places", "-309"), ("places", "N"),
    ("places", "Infinity"), ("places", "NaN"), ("places", "sNaN"), ("places", "1e99999999999999999999"),
    ("delta", "EPS"), ("delta", "1/100"), ("delta", "NaN"), ("delta", "sNaN"),
    ("abs", "NaN"), ("rel", "1e-6"), ("multi", "1"),
])
def test_a_tolerance_with_no_readable_bound_has_none(kind, number):
    assert _absolute_bound(kind, number) is None


@pytest.mark.parametrize("places", [-2, -1, 0, 1, 2, 3, 7])
def test_the_places_bound_is_the_one_unittest_enforces(places):
    bound = float(_absolute_bound("places", str(places))[0])
    case = unittest.TestCase()
    case.assertAlmostEqual(0.0, bound * 0.9, places=places)
    with pytest.raises(AssertionError):
        case.assertAlmostEqual(0.0, bound * 1.1, places=places)


# --- Two absolute kinds compared in one unit ---------------------------------------------

@pytest.mark.parametrize("kind,before,after,expected", [
    ("delta", "places=7", "7", (True, "places=7", "delta=7")),
    ("delta", "places=2", "0.5", (True, "places=2", "delta=0.5")),
    ("delta", "places=2", "0.005", (False, "places=2", "delta=0.005")),
    ("delta", "places=2", "0.001", (False, "places=2", "delta=0.001")),
    ("places", "delta=0.001", "1", (True, "delta=0.001", "places=1")),
    ("places", "delta=5", "3", (False, "delta=5", "places=3")),
    ("places", "abs=0.01", "1", (True, "abs=0.01", "places=1")),
    ("places", "abs=0.01", "3", (False, "abs=0.01", "places=3")),
    ("delta", "abs=0.01", "0.01", (False, "abs=0.01", "delta=0.01")),
    ("abs", "delta=0.01", "abs=0.02", (True, "delta=0.01", "abs=0.02")),
    ("abs", "places=2", "abs=Infinity", (True, "places=2", "abs=Infinity")),
    # A side that cannot be read is no finding: no guess, no noise.
    ("delta", "places=N", "0.5", (False, "places=N", "0.5")),
    ("delta", "places=2", "EPS", (False, "places=2", "EPS")),
])
def test_two_absolute_kinds_compare_their_bounds(kind, before, after, expected):
    assert _mixed(kind, before, after) == expected


@pytest.mark.parametrize("kind,before,after", [
    ("delta", "0.01", "0.02"),
    ("places", "2", "5"),
    ("abs", "abs=0.01", "abs=1E+12"),
    ("rel", "places=2", "rel=1e-06"),
    ("places", "rel=1e-06", "2"),
    ("delta", "abs=0.01|rel=1e-9", "0.01"),
    ("multi", "places=2", "abs=0.01|rel=1e-9"),
])
def test_one_kind_or_a_kind_with_no_bound_is_compared_per_kind(kind, before, after):
    assert _mixed(kind, before, after) is None


# --- Alignment keeps the old side's kind -----------------------------------------------

@pytest.mark.parametrize("before,after,changes", [
    (_almost(", places=7"), _almost(", delta=7"), [("delta", "places=7", "7")]),
    (_almost(""), _almost(", delta=0.5"), [("delta", "places=7", "0.5")]),
    (_almost(", 2"), _almost(", delta=0.5"), [("delta", "places=2", "0.5")]),
    (_almost(", delta=0.5"), _almost(", places=2"), [("places", "delta=0.5", "2")]),
    (_almost(", delta=7"), _almost(", places=7"), [("places", "delta=7", "7")]),
    (_almost(", delta=0.01"), HAND_ROLLED.format("0.01"), [("abs", "delta=0.01", "abs=0.01")]),
    (_almost(", places=2"), APPROX.format(""), [("rel", "places=2", "rel=1e-06")]),
    # A keyed value carries its kind already.
    (HAND_ROLLED.format("0.01"), _almost(", delta=0.01"), [("delta", "abs=0.01", "0.01")]),
    (APPROX.format(""), _almost(", places=2"), [("places", "rel=1e-06", "2")]),
    # One kind: recorded as before, and a respelled value is no change.
    (_almost(", places=7"), _almost(", places=1"), [("places", "7", "1")]),
    (_almost(", delta=0.010"), _almost(", delta=0.01"), []),
    (_almost(", places=2"), _almost(", 2"), []),
])
def test_alignment_keys_an_old_bare_value_of_another_kind(before, after, changes):
    assert _changes(_py(before, after)) == changes


@pytest.mark.parametrize("before,after,changes", [
    ("expect(total()).toBeCloseTo(78.75, 2);", "expect(total()).to.be.closeTo(78.75, 0.01);",
     [("abs", "places=2", "abs=0.01")]),
    ("expect(total()).to.be.closeTo(78.75, 0.01);", "expect(total()).toBeCloseTo(78.75, 2);",
     [("places", "abs=0.01", "2")]),
    ("expect(total()).toBeCloseTo(78.75, 3);", "expect(total()).toBeCloseTo(78.75, 2);",
     [("places", "3", "2")]),
])
def test_javascript_changes_carry_the_same_kinds(before, after, changes):
    assert _changes(_js(before, after)) == changes


# --- What TOLERANCE_LOOSENED reports ---------------------------------------------------

@pytest.mark.parametrize("before,after,shown", [
    (_almost(", places=7"), _almost(", delta=7"), "(places=7 -> delta=7)"),
    (_almost(""), _almost(", delta=7"), "(places=7 -> delta=7)"),
    (_almost(", places=2"), _almost(", delta=0.5"), "(places=2 -> delta=0.5)"),
    (_almost(", 2"), _almost(", delta=0.5"), "(places=2 -> delta=0.5)"),
    (_almost(", places=2"), _almost(", delta=10"), "(places=2 -> delta=10)"),
    (_almost(", places=-1"), _almost(", delta=10"), "(places=-1 -> delta=10)"),
    (_almost(", delta=0.001"), _almost(", places=1"), "(delta=0.001 -> places=1)"),
    (_almost(", delta=1e-9"), _almost(", places=1"), "(delta=1e-9 -> places=1)"),
    (_almost(", delta=0.3"), _almost(", places=0"), "(delta=0.3 -> places=0)"),
    (HAND_ROLLED.format("0.01"), _almost(", places=1"), "(abs=0.01 -> places=1)"),
    (_almost(", places=2"), HAND_ROLLED.format("0.01"), "(places=2 -> abs=0.01)"),
    (_almost(", delta=0.01"), APPROX.format(", abs=0.02"), "(delta=0.01 -> abs=0.02)"),
    # Still per kind: a relative tolerance states no absolute bound.
    (_almost(", places=2"), APPROX.format(""), "(places=2 -> rel=1e-06)"),
    (APPROX.format(""), _almost(", places=2"), "(rel=1e-06 -> places=2)"),
])
def test_a_wider_bound_in_another_kind_is_reported_in_both_kinds(before, after, shown):
    outcome = _py(before, after)
    loosened = _loosened(outcome)
    assert [finding.message.endswith(shown) for finding in loosened] == [True]
    assert outcome[2] == "block"


@pytest.mark.parametrize("before,after", [
    (_almost(", delta=5"), _almost(", places=3")),
    (_almost(", delta=7"), _almost(", places=7")),
    (_almost(", places=2"), _almost(", delta=0.005")),
    (_almost(", places=2"), _almost(", delta=0.001")),
    (_almost(", places=-1"), _almost(", delta=5")),
    (HAND_ROLLED.format("0.01"), _almost(", delta=0.01")),
    (HAND_ROLLED.format("0.01"), _almost(", places=3")),
    (APPROX.format(", abs=0.01"), _almost(", delta=0.01")),
    (_almost(", delta=0.01"), HAND_ROLLED.format("0.01")),
    (_almost(", places=2"), HAND_ROLLED.format("0.001")),
    (_almost(", places=N"), _almost(", delta=0.5")),
    (_almost(", places=2"), _almost(", delta=EPS")),
])
def test_an_equal_tighter_or_unreadable_bound_in_another_kind_is_not_loosened(before, after):
    # Only the tolerance claim is pinned: a hand-rolled bound replacing
    # assertAlmostEqual is judged by the lattice, which this reading leaves alone.
    assert _loosened(_py(before, after)) == []


@pytest.mark.parametrize("before,after,shown", [
    ("expect(total()).toBeCloseTo(78.75, 2);", "expect(total()).to.be.closeTo(78.75, 0.01);",
     "(places=2 -> abs=0.01)"),
    ("expect(total()).toBeCloseTo(78.75);", "expect(total()).to.be.closeTo(78.75, Infinity);",
     "(places=2 -> abs=Infinity)"),
])
def test_javascript_reports_as_it_did(before, after, shown):
    loosened = _loosened(_js(before, after))
    assert [finding.message.endswith(shown) for finding in loosened] == [True]


@pytest.mark.parametrize("before,after", [
    ("expect(total()).to.be.closeTo(78.75, 0.005);", "expect(total()).toBeCloseTo(78.75, 2);"),
    ("expect(total()).toBeCloseTo(78.75, 2);", "expect(total()).to.be.closeTo(78.75, 0.001);"),
])
def test_javascript_stays_silent_as_it_did(before, after):
    assert _loosened(_js(before, after)) == []


# --- Fingerprints ------------------------------------------------------------------------

@pytest.mark.parametrize("value,recorded", [
    ("places=2", "2"), ("delta=0.5", "0.5"), ("7", "7"),
    ("abs=0.01", "abs=0.01"), ("rel=1e-06", "rel=1e-06"), ("abs=1.0|rel=1e-9", "abs=1.0|rel=1e-9"),
])
def test_the_fingerprint_reads_the_value_as_its_frontend_recorded_it(value, recorded):
    assert _recorded(value) == recorded


@pytest.mark.parametrize("outcome,path,unit,key", [
    (lambda: _py(_almost(", places=2"), _almost(", delta=10")), PY_PATH, "TestEnergy.test_energy", "delta:2"),
    (lambda: _py(_almost(", delta=0.3"), _almost(", places=0")), PY_PATH, "TestEnergy.test_energy", "places:0.3"),
    (lambda: _py(_almost(", places=2"), APPROX.format("")), PY_PATH, "TestEnergy.test_energy", "rel:2"),
    (lambda: _js("expect(total()).toBeCloseTo(78.75);", "expect(total()).to.be.closeTo(78.75, Infinity);"),
     JS_PATH, "total", "abs:2"),
])
def test_a_finding_reported_before_keeps_its_fingerprint(outcome, path, unit, key):
    # Each of these was reported before 190.3, keyed `kind:old value` with the
    # old value as recorded; keying the old value's kind changes the message only.
    finding, = _loosened(outcome())
    assert finding.fingerprint == make_fingerprint("TOLERANCE_LOOSENED", path, unit, key)
