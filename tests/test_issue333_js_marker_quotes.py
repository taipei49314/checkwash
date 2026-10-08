"""Issue #333: a quote-style respelling (prettier) of a JS `skipIf` condition is no change.

#332's JavaScript twin. A JS marker's identity is its name and its
condition's normalized text (`test.skipIf(process.platform==='win32')`), and
normalized text keeps quote characters as written, so a condition respelled
`"win32"` (prettier's `singleQuote: false`) read as one marker removed and
another added: TEST_DISABLED, high without a production change.

A JS condition is now compared as `literals.comparable_operand` reads an
operand (#226): a quoted string in double quotes, tokens joined by one space,
no comma before a closing bracket. The marker's name stays its reported
identity, so fingerprints do not move. Every conditional JS marker is named
`test.skipIf(...)`: Vitest's `skipIf` and `runIf`, node:test's `skip` option
and Vitest's `ctx.skip(condition)`.
"""
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.ir.diffalign import _marker_key
from checkwash.ir.model import Marker


def judge(before, after):
    changes = [FileChange(path, "modified", before[path], after[path]) for path in before]
    snapshot = dict(after)
    _ir, findings, verdict = analyze(changes, Config(), Contract(), [], datetime.date(2026, 10, 7),
                                     root_reader=snapshot.get, root_path_lister=lambda: sorted(snapshot),
                                     root_batch_reader=lambda paths: {p: snapshot.get(p) for p in paths})
    return verdict, [(f.rule, f.severity, f.message.split(": ", 1)[-1]) for f in findings]


def prettier(source):
    return source.replace(b"'", b'"')


SKIP_IF = b"""import {test, expect} from 'vitest';
import {sep} from 'node:path';

test.skipIf(process.platform === 'win32')('path', () => {
  expect(sep).toBe('/');
});
"""
FLAGS = b"""import {test, expect} from 'vitest';
import {flags} from '../src/flags.js';

test('flags', () => {
  expect(flags['a']).toBe(1);
  expect(flags['b']).toBe(2);
});
"""


# --- the issue's rows ---------------------------------------------------------------------------

def test_a_respelled_skipIf_is_the_same_marker():
    assert judge({"test/path.test.js": SKIP_IF}, {"test/path.test.js": prettier(SKIP_IF)}) == ("pass", [])


def test_control_assertions_respelled_alone():
    assert judge({"test/flags.test.js": FLAGS}, {"test/flags.test.js": prettier(FLAGS)}) == ("pass", [])


# --- every conditional marker -------------------------------------------------------------------

@pytest.mark.parametrize("source", [
    b"import {test, expect} from 'vitest';\n\n"
    b"test.runIf(process.platform !== 'win32')('path', () => {\n  expect(sep()).toBe('/');\n});\n",
    b"import {test} from 'node:test';\nimport assert from 'node:assert';\n\n"
    b"test('path', {skip: process.platform === 'win32'}, () => {\n  assert.equal(sep(), '/');\n});\n",
    b"import {test, expect} from 'vitest';\n\n"
    b"test('path', (ctx) => {\n  ctx.skip(process.platform === 'win32');\n  expect(sep()).toBe('/');\n});\n",
    b"import {test, expect} from 'vitest';\n\n"
    b"test.skipIf(\n  isPlatform(\n    'win32',\n  )\n)('path', () => {\n  expect(sep()).toBe('/');\n});\n",
], ids=["runIf", "node_test_skip_option", "context_skip", "trailing_comma"])
def test_a_respelled_condition_is_the_same_marker(source):
    after = prettier(source).replace(b'"win32",\n', b'"win32"\n')
    assert judge({"test/path.test.js": source}, {"test/path.test.js": after}) == ("pass", [])


# --- what is still a change ---------------------------------------------------------------------

def test_a_skipIf_whose_condition_changed_is_still_a_new_marker():
    after = prettier(SKIP_IF).replace(b'"win32"', b'"darwin"')
    verdict, findings = judge({"test/path.test.js": SKIP_IF}, {"test/path.test.js": after})
    assert verdict == "block"
    assert findings == [("TEST_DISABLED", "high", 'disabling marker added (test.skipIf(process.platform==="darwin"))')]


def test_a_respelled_string_whose_value_changed_is_still_a_new_marker():
    """`'it\\'s'` respelled `"it's"` is one value; `"its"` is another."""
    before = SKIP_IF.replace(b"'win32'", b"'it\\'s'")
    respelled = SKIP_IF.replace(b"'win32'", b'"it\'s"')
    changed = SKIP_IF.replace(b"'win32'", b'"its"')
    assert judge({"test/path.test.js": before}, {"test/path.test.js": respelled}) == ("pass", [])
    verdict, findings = judge({"test/path.test.js": before}, {"test/path.test.js": changed})
    assert verdict == "block"
    assert [(rule, severity) for rule, severity, _ in findings] == [("TEST_DISABLED", "high")]


# --- the key ------------------------------------------------------------------------------------

@pytest.mark.parametrize("name, key", [
    ("test.skipIf(process.platform==='win32')", ("test.skipIf(", 'process . platform === "win32"')),
    ('test.skipIf(process.platform==="win32")', ("test.skipIf(", 'process . platform === "win32"')),
    ("test.skipIf(isPlatform('win32',))", ("test.skipIf(", 'isPlatform ( "win32" )')),
    ("test.skip", "test.skip"),
    ("test.fails", "test.fails"),
], ids=["single_quotes", "double_quotes", "trailing_comma", "unconditional", "fails"])
def test_a_javascript_markers_identity(name, key):
    assert _marker_key(Marker(name=name, span=(0, 0), text=name), python=False) == key
