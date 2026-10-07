"""Issue #332: a quote-style respelling (black) is no change.

flask `025589ee` ("Reformat with black") blocked with 20 ASSERT_WEAKENED and
2 TEST_DISABLED findings, all high. Black respelled `'...'` as `"..."`, and
normalized text, which pairs assertions and names markers, keeps quote
characters as written:
- a skipif whose condition was respelled read as one marker removed and
  another added, and an added marker whose condition cannot be evaluated is
  TEST_DISABLED, high without a production change;
- a respelled assertion matched nothing by text, every bare assert of a unit
  shares the `(form, subject)` key `("truthy", "")` (#331), and they paired
  in span order. An assertion a conftest fixture lends the test carries the
  conftest's offsets, so when black moved them, the test's own check paired
  with the fixture's: a flipped polarity.

In Python, two statements that parse the same now pair before the
`(form, subject)` step, and a marker condition that parses the same is the
same marker. Fingerprints keep normalized text.
"""
import ast
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.ir.astutil import stable_dump
from checkwash.ir.diffalign import _marker_key, _parsed_key
from checkwash.ir.model import Marker


def run(before, after):
    changes = [FileChange(path, "modified", before[path], after[path]) for path in before]
    snapshot = dict(after)
    return analyze(changes, Config(), Contract(), [], datetime.date(2026, 10, 7),
                   root_reader=snapshot.get, root_path_lister=lambda: sorted(snapshot),
                   root_batch_reader=lambda paths: {p: snapshot.get(p) for p in paths})


def judge(before, after):
    _ir, findings, verdict = run(before, after)
    return verdict, [(f.rule, f.severity, f.message.split(": ", 1)[-1]) for f in findings]


def black(source):
    return source.replace(b"'", b'"')


SKIPIF = b"""import pytest
from werkzeug.datastructures import Range


class TestSendfile:
    @pytest.mark.skipif(not callable(getattr(Range, 'to_content_range_header', None)),
                        reason='not implemented within werkzeug')
    def test_send_file_range_request(self):
        assert send('x') == 'x'
"""
CONFTEST = b"""import pytest


@pytest.fixture(autouse=True)
def no_warnings(recwarn):
    yield
    assert not recwarn.list, '\\n'.join(str(w.message) for w in recwarn.list)
"""
CONFTEST_BLACK = b"""import gc
import os
import sys

import pytest


@pytest.fixture(autouse=True)
def no_warnings(recwarn):
    yield
    gc.collect()
    assert not recwarn.list, "\\n".join(str(w.message) for w in recwarn.list)
"""
TEST = (b"# The jinja environment's registered tests, read back by name.\n" * 4
        + b"from app import tests\n\n\ndef test_boolean():\n    assert tests['boolean'](False)\n")


# --- the issue's rows ---------------------------------------------------------------------------

def test_Q1_a_respelled_skipif_is_the_same_marker():
    assert judge({"tests/test_h.py": SKIPIF}, {"tests/test_h.py": black(SKIPIF)}) == ("pass", [])


def test_Q2_a_respelled_test_and_conftest_pair_their_own_assertions():
    before = {"tests/conftest.py": CONFTEST, "tests/test_x.py": TEST}
    after = {"tests/conftest.py": CONFTEST_BLACK, "tests/test_x.py": black(TEST)}
    assert judge(before, after) == ("pass", [])


def test_control_the_test_respelled_alone():
    assert judge({"tests/test_x.py": TEST}, {"tests/test_x.py": black(TEST)}) == ("pass", [])


# --- what is still a change ---------------------------------------------------------------------

def test_a_skipif_whose_condition_changed_is_still_a_new_marker():
    after = black(SKIPIF).replace(b"not callable", b"callable")
    verdict, findings = judge({"tests/test_h.py": SKIPIF}, {"tests/test_h.py": after})
    assert verdict == "block"
    assert [(rule, severity) for rule, severity, _ in findings] == [("TEST_DISABLED", "high")]


def test_a_respelled_assertion_is_paired_as_itself_not_by_position():
    """The same statement, not two leftovers paired in span order: the IR
    (`--emit-ir`) records no fallback pair, the guess ASSERT_SUBSTITUTED reads."""
    before = b"def test_name():\n    assert name('a') == 'checkwash'\n"
    ir, findings, verdict = run({"tests/test_n.py": before}, {"tests/test_n.py": black(before)})
    (delta,) = [unit.delta for file in ir.files for unit in file.units if unit.delta is not None]
    assert (verdict, findings) == ("pass", [])
    assert [(pair.strength_change, pair.fallback) for pair in delta.assertion_pairs] == [(0, False)]


def test_a_respelled_assertion_whose_value_changed_is_still_read():
    before = b"def test_name():\n    assert name() == 'checkwash'\n"
    after = b'def test_name():\n    assert name() == "greenwash"\n'
    verdict, findings = judge({"tests/test_n.py": before}, {"tests/test_n.py": after})
    assert verdict == "block"
    assert [(rule, severity) for rule, severity, _ in findings] == [("EXPECTED_VALUE_CHANGED", "high")]


def test_a_respelled_assertion_whose_polarity_flipped_is_still_an_inversion():
    before = b"def test_ready():\n    assert ready('a')\n    assert not stopped('b')\n"
    after = b'def test_ready():\n    assert ready("a")\n    assert stopped("b")\n'
    assert judge({"tests/test_r.py": before}, {"tests/test_r.py": after}) == (
        "block", [("ASSERT_WEAKENED", "high",
                   "assertion polarity inverted (negative -> positive) — the test now proves the opposite")])


# --- the keys -----------------------------------------------------------------------------------

@pytest.mark.parametrize("one, other, same", [
    ("assert x == 'a'", 'assert x == "a"', True),
    ("assert (\n    x == 'a'\n)", "assert x == 'a'", True),
    ("assert x == 'a', 'why'", 'assert x == "a", "why"', True),
    ("assert x == 'a'", "assert x == 'b'", False),
    ("assert x == 'a'", "assert y == 'a'", False),
    ("assert x == 'a', 'why'", "assert x == 'a'", False),
], ids=["quotes", "lines", "message_quotes", "value", "subject", "message_dropped"])
def test_two_statements_parse_the_same(one, other, same):
    assert (_parsed_key(one) == _parsed_key(other)) is same


def test_text_that_does_not_parse_has_no_key():
    assert _parsed_key("expect(x).not.toBe(`a ${b}`)") is None


def condition(text):
    return stable_dump(ast.parse(text, mode="eval").body)


@pytest.mark.parametrize("marker, python, key", [
    (Marker(name="pytest.mark.skipif(sys.platform=='win32')", span=(0, 0),
            text="pytest.mark.skipif(sys.platform == 'win32', reason='posix')"), True,
     ("pytest.mark.skipif", condition("sys.platform == 'win32'"))),
    (Marker(name='pytest.mark.skipif(sys.platform=="win32")', span=(0, 0),
            text='@pytest.mark.skipif(sys.platform == "win32", reason="posix")'), True,
     ("pytest.mark.skipif", condition("sys.platform == 'win32'"))),
    (Marker(name="pytest.mark.skip", span=(0, 0), text="pytest.mark.skip(reason='slow')"), True,
     "pytest.mark.skip"),
    (Marker(name="pytest.mark.skipif(WIN)", span=(0, 0), text="skip_on_windows"), True,
     "pytest.mark.skipif(WIN)"),
    (Marker(name="pytest.skip", span=(0, 0), text="pytest.skip('slow')"), True, "pytest.skip"),
    (Marker(name="pytest.mark.skipif(sys.platform=='win32')", span=(0, 0),
            text="pytest.mark.skipif(sys.platform == 'win32')"), False,
     "pytest.mark.skipif(sys.platform=='win32')"),
], ids=["condition", "respelled_with_at_sign", "no_condition", "alias", "imperative_skip", "not_python"])
def test_a_markers_identity(marker, python, key):
    assert _marker_key(marker, python) == key


def test_javascript_keeps_its_marker_names():
    """Python's parser reads Python only: JS's twin, a respelled `skipIf`, is #333."""
    before = (b"import {test, expect} from 'vitest';\n\n"
              b"test.skipIf(isWindows('ci'))('path', () => {\n  expect(sep()).toBe('/');\n});\n")
    verdict, findings = judge({"test/path.test.js": before}, {"test/path.test.js": black(before)})
    assert verdict == "block"
    assert [(rule, severity) for rule, severity, _ in findings] == [("TEST_DISABLED", "high")]
