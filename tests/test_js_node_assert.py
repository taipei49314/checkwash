"""Issue #164: Node's exact assertions must not disappear from oracle checks."""

import datetime
import json
import os
import subprocess
import sys

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.frontends.javascript.frontend import parse_javascript
from checkwash.ir import strength as S


_EXACT_METHODS = [
    ("equal", S.EXACT_VALUE),
    ("strictEqual", S.EXACT_VALUE),
    ("deepEqual", S.EXACT_STRUCT),
    ("deepStrictEqual", S.EXACT_STRUCT),
]


def _source(body, declaration="test"):
    return (
        'import assert from "node:assert/strict";\n'
        'import { test, it } from "node:test";\n'
        f'{declaration}("total", (t) => {{\n  {body}\n}});\n'
    )


def _analyze(before, after, declaration="test", path="tests/total.test.js"):
    return analyze(
        [FileChange(path, "modified", _source(before, declaration).encode(),
                    _source(after, declaration).encode())],
        Config(), Contract(), [], datetime.date(2026, 9, 23),
    )


@pytest.mark.parametrize("receiver", ["assert", "t.assert"])
@pytest.mark.parametrize("method,strength", _EXACT_METHODS)
def test_node_exact_assertions_keep_strength_subject_and_source(receiver, method, strength):
    call = f'{receiver}.{method}(total([2, 3]), 5, "correct total")'
    source = _source(call + ";")
    parsed = parse_javascript(source.encode())
    assert parsed.parse_ok
    unit, = parsed.units
    assertion, = unit.side.assertions
    assert (assertion.form, assertion.strength, assertion.left) == (
        "compare_eq", strength, "total([2, 3])",
    )
    assert assertion.text == call
    assert source[slice(*assertion.span)] == call


@pytest.mark.parametrize("callee", ["assert", "assert.ok", "t.assert.ok"])
def test_node_truthiness_assertions_have_a_truthy_oracle(callee):
    source = _source(f'{callee}(total([2, 3]), "nonzero total");')
    unit, = parse_javascript(source.encode()).units
    assertion, = unit.side.assertions
    assert (assertion.form, assertion.strength, assertion.left) == (
        "truthy", S.TRUTHY, "total([2, 3])",
    )


@pytest.mark.parametrize("declaration", ["test", "it"])
@pytest.mark.parametrize("method,strength", _EXACT_METHODS)
@pytest.mark.parametrize("weak_callee", ["assert.ok", "assert"])
def test_exact_to_truthiness_blocks_in_the_engine(declaration, method, strength, weak_callee):
    ir, findings, verdict = _analyze(
        f"assert.{method}(total([2, 3]), 5);",
        f"{weak_callee}(total([2, 3]));",
        declaration,
    )
    unit, = ir.files[0].units
    assert unit.before.assertions[0].strength == strength
    assert unit.after.assertions[0].strength == S.TRUTHY
    finding, = findings
    assert (finding.rule, finding.severity, verdict) == ("ASSERT_WEAKENED", "high", "block")
    assert "NO_PROD_CHANGE_IN_DIFF" in finding.escalators


@pytest.mark.parametrize("method,strength", _EXACT_METHODS)
def test_node_test_context_assertion_weakening_blocks(method, strength):
    ir, findings, verdict = _analyze(
        f"t.assert.{method}(total([2, 3]), 5);",
        "t.assert.ok(total([2, 3]));",
    )
    assert ir.files[0].units[0].before.assertions[0].strength == strength
    assert verdict == "block"
    assert [(f.rule, f.severity) for f in findings] == [("ASSERT_WEAKENED", "high")]


@pytest.mark.parametrize("subject", [
    "total([2, 3], { tax: 0, discount: 1 })",
    "(record(2, 3), total([2, 3]))",
    "items.map((value, index) => ({ value, index }))",
    "lookup(\"comma, and ) brackets\", [1, 2])",
    "lookup(/[,)]/, `comma, and ) brackets`)",
    "lookup('two  spaces')",
])
def test_argument_boundaries_preserve_nested_comma_subjects(subject):
    before = f'assert.deepStrictEqual({subject}, [2, 3], "expected, exact ) result");'
    after = f'assert.ok({subject}, "must be truthy");'
    ir, findings, verdict = _analyze(before, after)
    unit, = ir.files[0].units
    assert unit.before.assertions[0].left == subject
    assert unit.after.assertions[0].left == subject
    assert [(f.rule, f.severity) for f in findings] == [("ASSERT_WEAKENED", "high")]
    assert verdict == "block"


@pytest.mark.parametrize("noise", [
    '// assert.strictEqual(fake(), 1);',
    '/* assert.deepStrictEqual(fake(), [1]); */',
    'const sample = "assert.equal(fake(), 1)";',
    "const sample = 'assert.ok(fake())';",
    'const template = `assert.deepEqual(fake(), [1])`;',
    'const template = `${assert.ok(fake())}`;',
    'const pattern = /assert.strictEqual(fake(), 1)/;',
    'const pattern = /t.assert.deepStrictEqual(fake(), [1])/;',
])
def test_comments_and_literal_contents_cannot_supply_node_assertions(noise):
    source = _source(noise + "\n  assert.strictEqual(real(), 1);")
    unit, = parse_javascript(source.encode()).units
    assert [assertion.left for assertion in unit.side.assertions] == ["real()"]
    _ir, findings, verdict = _analyze(noise, noise.replace("fake()", "other()"))
    assert findings == []
    assert verdict == "pass"


@pytest.mark.parametrize("callee", [
    "reassert.equal", "$assert.equal", "assertion.equal", "assert$.equal",
    "assert.equalMore", "assert.deepStrictEqualMore", "assert.okay",
    "reassert", "$assert", "assertion", "t.$assert.ok",
    "object.assert.equal", "object . /* comment */ assert.equal",
    "object.assert", "object . /* comment */ assert", "t.assert",
])
def test_identifier_boundaries_do_not_invent_node_assertions(callee):
    unit, = parse_javascript(_source(f"{callee}(fake(), 1);").encode()).units
    assert unit.side.assertions == []


@pytest.mark.parametrize("declaration", [
    "function assert(value) {}",
    "function* assert(value) {}",
    "class Helper { assert(value) {} }",
    "const helper = { assert(value) {} };",
])
def test_function_and_method_declarations_are_not_bare_assert_calls(declaration):
    unit, = parse_javascript(_source(declaration).encode()).units
    assert unit.side.assertions == []


@pytest.mark.parametrize("call,strength", [
    ("assert.strictEqual(value, 5)", S.EXACT_VALUE),
    ("assert.ok(value)", S.TRUTHY),
    ("assert(value)", S.TRUTHY),
])
def test_assertion_before_a_separate_block_keeps_its_oracle(call, strength):
    unit, = parse_javascript(_source(call + "\n  { doOther(); }").encode()).units
    assertion, = unit.side.assertions
    assert (assertion.left, assertion.strength, assertion.text) == ("value", strength, call)


@pytest.mark.parametrize("weak_callee", ["assert.ok", "assert"])
def test_weakening_before_a_separate_block_still_blocks(weak_callee):
    _ir, findings, verdict = _analyze(
        "assert.strictEqual(value, 5)\n  { doOther(); }",
        f"{weak_callee}(value)\n  {{ doOther(); }}",
    )
    assert [(f.rule, f.severity) for f in findings] == [("ASSERT_WEAKENED", "high")]
    assert verdict == "block"


@pytest.mark.parametrize("declaration", [
    "function assert(value: number): boolean { return true; }",
    "class Helper { assert(value: number): boolean { return true; } }",
])
def test_typed_declarations_do_not_supply_or_remove_oracles(declaration):
    source = _source(declaration)
    unit, = parse_javascript(source.encode()).units
    assert unit.side.assertions == []
    _ir, findings, verdict = _analyze(declaration, "", path="tests/total.test.ts")
    assert findings == []
    assert verdict == "pass"


@pytest.mark.parametrize("private_member", [
    "this.#assert(value);",
    "class Helper { #assert(value) {} }",
    "class Helper { #assert(value: number): boolean { return true; } }",
])
def test_private_members_are_not_node_assertions(private_member):
    unit, = parse_javascript(_source(private_member).encode()).units
    assert unit.side.assertions == []


@pytest.mark.parametrize("malformed", [
    "assert.equal();",
    "assert.strictEqual(value);",
    "assert.deepEqual(value, );",
    "assert.deepStrictEqual(, expected);",
    "assert.ok();",
    "assert();",
    "assert.ok(,);",
    "assert.strictEqual(value, 5;",
    "assert.deepStrictEqual([value}, expected);",
    "assert.deepStrictEqual({ value], expected);",
])
def test_missing_arguments_and_unbalanced_calls_do_not_steal_the_next_assertion(malformed):
    source = _source(malformed + "\n  assert.strictEqual(real(), 1);")
    unit, = parse_javascript(source.encode()).units
    assertion, = unit.side.assertions
    assert assertion.left == "real()"
    assert assertion.text == "assert.strictEqual(real(), 1)"


@pytest.mark.parametrize("before,after", [
    ("assert.ok(value);", "assert(value);"),
    ("assert(value);", "assert.ok(value);"),
])
def test_bare_assert_and_ok_are_preserving_rewrites(before, after):
    _ir, findings, verdict = _analyze(before, after)
    assert findings == []
    assert verdict == "pass"


@pytest.mark.parametrize("expression", [
    "flag ? {call} : cleanup();",
    "flag ? await {call} : cleanup();",
    "outer ? inner ? keep() : {call} : cleanup();",
])
def test_bare_assert_in_a_ternary_arm_remains_an_oracle(expression):
    source = _source(expression.format(call="assert(value)")).replace(
        "(t) => {", "async (t) => {",
    )
    unit, = parse_javascript(source.encode()).units
    assertion, = unit.side.assertions
    assert (assertion.left, assertion.strength, assertion.text) == (
        "value", S.TRUTHY, "assert(value)",
    )


@pytest.mark.parametrize("expression", [
    "flag ? {call} : cleanup();",
    "flag ? await {call} : cleanup();",
    "outer ? inner ? keep() : {call} : cleanup();",
])
def test_exact_to_bare_assert_in_a_ternary_arm_blocks(expression):
    def source(call):
        return _source(expression.format(call=call)).replace(
            "(t) => {", "async (t) => {",
        ).encode()

    _ir, findings, verdict = analyze(
        [FileChange("tests/total.test.js", "modified",
                    source("assert.strictEqual(value, 5)"), source("assert(value)"))],
        Config(), Contract(), [], datetime.date(2026, 9, 23),
    )
    assert [(f.rule, f.severity) for f in findings] == [("ASSERT_WEAKENED", "high")]
    assert verdict == "block"


def test_node_and_expect_assertions_keep_source_order_and_ids():
    source = _source("""assert.equal(first(), 1);
  expect(second()).toBe(2);
  t.assert.deepStrictEqual(third(), [3]);
  expect(fourth()).toBeTruthy();
  assert(fifth());""")
    unit, = parse_javascript(source.encode()).units
    assert [a.left for a in unit.side.assertions] == [
        "first()", "second()", "third()", "fourth()", "fifth()",
    ]
    assert [a.id for a in unit.side.assertions] == ["a0", "a1", "a2", "a3", "a4"]
    assert [a.span[0] for a in unit.side.assertions] == sorted(a.span[0] for a in unit.side.assertions)


def test_mixed_matcher_unit_reports_only_the_weakened_node_assertion():
    before = "expect(first()).toBe(1); assert.strictEqual(second(), 2); expect(third()).toBe(3);"
    after = "expect(first()).toBe(1); assert.ok(second()); expect(third()).toBe(3);"
    _ir, findings, verdict = _analyze(before, after)
    assert [(f.rule, f.severity) for f in findings] == [("ASSERT_WEAKENED", "high")]
    assert verdict == "block"


@pytest.mark.parametrize("method,strength", _EXACT_METHODS)
def test_unchanged_node_assertions_do_not_flag_comment_edits(method, strength):
    assertion = f"assert.{method}(total([2, 3]), 5);"
    ir, findings, verdict = _analyze(assertion, assertion + " // explanation")
    assert ir.files[0].units[0].after.assertions[0].strength == strength
    assert findings == []
    assert verdict == "pass"


@pytest.mark.parametrize("before,after", [
    ("assert(total([2, 3]));", "assert.strictEqual(total([2, 3]), 5);"),
    ("assert.ok(total([2, 3]));", "assert.deepStrictEqual(total([2, 3]), [2, 3]);"),
    ("t.assert.ok(total([2, 3]));", "t.assert.deepEqual(total([2, 3]), [2, 3]);"),
    ("assert.equal(total([2, 3]), 5);", "assert.strictEqual(total([2, 3]), 5);"),
    ("assert.deepEqual(total([2, 3]), [2, 3]);", "assert.deepStrictEqual(total([2, 3]), [2, 3]);"),
])
def test_strengthening_and_equal_strength_node_rewrites_do_not_flag(before, after):
    _ir, findings, verdict = _analyze(before, after)
    assert findings == []
    assert verdict == "pass"


@pytest.mark.parametrize("suffix", ["test.mjs", "spec.cjs", "test.ts"])
def test_node_assertion_weakening_uses_existing_js_and_ts_test_paths(suffix):
    _ir, findings, verdict = _analyze(
        "assert.strictEqual(total([2, 3]), 5);", "assert.ok(total([2, 3]));",
        path=f"tests/total.{suffix}",
    )
    assert [(f.rule, f.severity) for f in findings] == [("ASSERT_WEAKENED", "high")]
    assert verdict == "block"


@pytest.mark.parametrize("before,after,exit_code", [
    ("assert.strictEqual(total([2, 3]), 5);", "assert.ok(total([2, 3]));", 1),
    ("assert.deepStrictEqual(total([2, 3]), [2, 3]);", "assert(total([2, 3]));", 1),
    ("assert.ok(total([2, 3]));", "assert.strictEqual(total([2, 3]), 5);", 0),
])
def test_node_assertions_through_worktree_and_committed_cli(tmp_path, before, after, exit_code):
    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    git("init", "-b", "main")
    git("config", "user.name", "e2e")
    git("config", "user.email", "e2e@example.invalid")
    git("config", "commit.gpgsign", "false")
    test_file = tmp_path / "total.test.mjs"
    test_file.write_text(_source(before), encoding="utf-8")
    git("add", "-A")
    git("commit", "-m", "base")
    test_file.write_text(_source(after), encoding="utf-8")

    for revision in [[], ["HEAD~1..HEAD"]]:
        if revision:
            git("commit", "-am", "change assertion")
        result = subprocess.run(
            [sys.executable, "-m", "checkwash", "check", *revision,
             "--repo", str(tmp_path), "--format", "json"],
            capture_output=True, text=True,
            env={**os.environ, "GREENWASH_TODAY": "2026-09-23", "NO_COLOR": "1"},
        )
        assert result.returncode == exit_code, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        if exit_code:
            assert payload["verdict"] == "block"
            finding, = payload["findings"]
            assert (finding["rule"], finding["severity"]) == ("ASSERT_WEAKENED", "high")
            assert "NO_PROD_CHANGE_IN_DIFF" in finding["escalators"]
        else:
            assert payload["verdict"] == "pass"
            assert payload["findings"] == []
