"""The JS/TS parser's linear lookups answer what its scans answered (#235).

Each lookup that #235 made linear is pinned against the scan it replaced, on
well-formed and malformed sources alike: `Bindings.scope()` against a scan
of every scope, and `follows_new` against the regex search over all the text
before a call. `tests/test_perf_js.py` holds the time budget; the corpus
(`tools/emit_corpus.py`) holds every record byte for byte.
"""

from __future__ import annotations

import random
import re

import pytest

from checkwash.frontends.javascript.bindings import Bindings
from checkwash.frontends.javascript.coverage import javascript_coverage_gaps
from checkwash.frontends.javascript.frontend import _code_positions, _decoded, follows_new, parse_javascript


def _bindings(source: str) -> Bindings:
    text = _decoded(source.encode("utf-8"))
    return Bindings(text, _code_positions(text), _code_positions(text, keep_strings=True))


def _scanned_scope(bindings: Bindings, position: int) -> int:
    """The scan `scope()` replaced: the shortest scope holding the position, the latest of equal ones."""
    candidates = [(scope.end - scope.start, -index, index) for index, scope in enumerate(bindings.scopes)
                  if scope.start <= position <= scope.end]
    return min(candidates)[2] if candidates else 0


SOURCES = [
    "",
    "const x = 1;\n",
    'test("t", () => {\n  const v = [1, 2].map((x) => x * 2);\n  expect(v).toEqual([2, 4]);\n});\n',
    'describe("d", function () {\n  it("i", async () => { await f(() => ({ a: 1 })); });\n});\n',
    "a => b => c => d\n",
    "f(x => x + 1, y => { return y; }, z => (z))\n",
    "class A { m() { return () => this; } }\n",
    "{}{}{{}}\n",
    # Malformed: unclosed and unbalanced code.
    "x => { a(",
    "f(() => { g(x => x + (",
    "}}} => {",
    "a => b => c => { d => (e",
    "{ { } x => y }",
    "(((",
    "))) => }",
]


@pytest.mark.parametrize("source", SOURCES, ids=range(len(SOURCES)))
def test_scope_answers_what_the_scan_answered(source):
    bindings = _bindings(source)
    for position in range(-2, len(bindings.text) + 3):
        assert bindings.scope(position) == _scanned_scope(bindings, position), position


def test_scope_answers_what_the_scan_answered_on_random_sources():
    rng = random.Random(235)
    alphabet = "{}()[] =>x;,\n\"'`/*"
    for _ in range(300):
        bindings = _bindings("".join(rng.choice(alphabet) for _ in range(rng.randint(0, 60))))
        for position in range(-1, len(bindings.text) + 2):
            assert bindings.scope(position) == _scanned_scope(bindings, position)


def test_scope_rebuilds_its_index_when_a_scope_is_added():
    bindings = _bindings("f(() => { g(); });\n")
    before = [bindings.scope(position) for position in range(len(bindings.text) + 1)]
    assert before == [_scanned_scope(bindings, position) for position in range(len(bindings.text) + 1)]
    bindings.scopes.append(type(bindings.scopes[0])(2, 4, 0))
    assert [bindings.scope(position) for position in range(len(bindings.text) + 1)] == [
        _scanned_scope(bindings, position) for position in range(len(bindings.text) + 1)]


@pytest.mark.parametrize("text", [
    "", "new", " new", "xnew", "_new", "$new", "1new", "ñnew", "a.new", "renew", "nnew",
    "new\n", "x new\n", "new\n\n", "(new", "new  ", "\nnew", "new(",
])
def test_follows_new_answers_what_the_search_answered(text):
    for previous in range(-1, len(text)):
        assert follows_new(text, previous) is bool(re.search(r"\bnew$", text[:previous + 1])), previous


def test_token_starts_are_the_tokens_starts():
    bindings = _bindings('it("t", () => { expect(f(1)).toBe(2); });\n')
    assert bindings.token_starts == [start for _token, start, _end in bindings.tokens]


def test_a_unit_keeps_only_the_nested_functions_inside_its_own_body():
    """The file's nested functions are read once; each unit keeps those inside it."""
    source = (
        'import { it, expect } from "vitest";\n'
        'it("a", () => {\n  const helper = () => { expect(1).toBe(1); };\n  expect(2).toBe(2);\n});\n'
        'it("b", () => {\n  items.forEach((x) => { expect(x).toBe(1); });\n  expect(3).toBe(3);\n});\n'
    )
    parsed = parse_javascript(source.encode("utf-8"))
    by_unit = {unit.qualname: [a.text for a in unit.side.assertions] for unit in parsed.units}
    # The helper's assertion is not unit a's; forEach's inline callback keeps
    # the established lexical coverage for unit b.
    assert by_unit == {"a": ["expect(2).toBe(2)"], "b": ["expect(x).toBe(1)", "expect(3).toBe(3)"]}


HEAD = 'import { it, expect } from "vitest";\nimport assert from "node:assert";\n'


@pytest.mark.parametrize("helper", [
    "function helper() { expect(1).toBe(1); }",
    "const check = (x: number): Promise<void> => { expect(x).toBe(1); };",
    "const check = (x: number): number[] => [expect(x).toBe(1)];",
], ids=["function", "annotated-arrow", "annotated-arrow-expression"])
def test_a_nested_function_donates_no_assertion_to_its_unit(helper):
    """A declared function, and an arrow whose TypeScript return annotation
    hides its parameters from the binding scanner, are nested functions."""
    source = HEAD + 'it("a", () => {\n  ' + helper + '\n  expect(2).toBe(2);\n});\n'
    parsed = parse_javascript(source.encode("utf-8"))
    assert [[a.text for a in unit.side.assertions] for unit in parsed.units] == [["expect(2).toBe(2)"]]


@pytest.mark.parametrize("construction", [
    "new assert(true)", "new assert.throws(() => {})", "new assert.strictEqual(1, 1)",
])
def test_a_constructed_assertion_name_is_no_assertion(construction):
    """`new` before a call makes it a construction in every scan that asks."""
    source = HEAD + 'it("a", () => {\n  const e = ' + construction + ';\n  expect(2).toBe(2);\n});\n'
    data = source.encode("utf-8")
    parsed = parse_javascript(data)
    assert [[a.text for a in unit.side.assertions] for unit in parsed.units] == [["expect(2).toBe(2)"]]
    assert javascript_coverage_gaps(data, parsed, "tests/a.test.ts", "after") == []
