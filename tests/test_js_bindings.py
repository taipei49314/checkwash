"""Bounded import and lexical binding checks for JS assertion recognition."""

import datetime

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.frontends.javascript.coverage import javascript_coverage_gaps
from checkwash.frontends.javascript.frontend import parse_javascript
from checkwash.ir import strength as S


def _source(imports, body, parameters=""):
    return f'{imports}\ntest("total", ({parameters}) => {{\n  {body}\n}});\n'


def _assertions(source):
    parsed = parse_javascript(source.encode())
    assert parsed.parse_ok
    return [assertion for unit in parsed.units for assertion in unit.side.assertions]


def _analyze(before, after):
    return analyze(
        [FileChange("tests/total.test.mjs", "modified", before.encode(), after.encode())],
        Config(), Contract(), [], datetime.date(2026, 9, 23),
    )


_ALIASES = [
    pytest.param(
        'import assert from "node:assert";',
        "assert.strictEqual(total(), 5)", "assert.ok(total())", id="node-default",
    ),
    pytest.param(
        'import verify from "node:assert/strict";',
        "verify.strictEqual(total(), 5)", "verify.ok(total())", id="node-default-renamed",
    ),
    pytest.param(
        'import { strictEqual, ok } from "node:assert";',
        "strictEqual(total(), 5)", "ok(total())", id="node-named",
    ),
    pytest.param(
        'import { strictEqual as same, ok as ensure } from "node:assert/strict";',
        "same(total(), 5)", "ensure(total())", id="node-named-renamed",
    ),
    pytest.param(
        'const verify = require("node:assert");',
        "verify.strictEqual(total(), 5)", "verify.ok(total())", id="node-commonjs-default",
    ),
    pytest.param(
        'const { strictEqual, ok } = require("node:assert");',
        "strictEqual(total(), 5)", "ok(total())", id="node-commonjs-destructured",
    ),
    pytest.param(
        'const { strictEqual: same, ok: ensure } = require("assert/strict");',
        "same(total(), 5)", "ensure(total())", id="node-commonjs-renamed",
    ),
    pytest.param(
        'import { expect as verify } from "vitest";',
        "verify(total()).toBe(5)", "verify(total()).toBeTruthy()", id="vitest-expect-renamed",
    ),
    pytest.param(
        'import { expect as verify } from "@jest/globals";',
        "verify(total()).toBe(5)", "verify(total()).toBeTruthy()", id="jest-expect-renamed",
    ),
    pytest.param(
        'import { expect } from "vitest";',
        "expect(total()).toBe(5)", "expect(total()).toBeTruthy()", id="vitest-expect",
    ),
]


@pytest.mark.parametrize("imports,exact,truthy", _ALIASES)
def test_bounded_import_aliases_produce_real_oracles_without_coverage_gaps(imports, exact, truthy):
    for call, form, strength in [(exact, "compare_eq", S.EXACT_VALUE), (truthy, "truthy", S.TRUTHY)]:
        source = _source(imports, call + ";")
        assertion, = _assertions(source)
        assert (assertion.left, assertion.form, assertion.strength) == ("total()", form, strength)
        assert source[slice(*assertion.span)] == assertion.text
        parsed = parse_javascript(source.encode())
        assert javascript_coverage_gaps(source.encode(), parsed, "tests/total.test.mjs", "after") == []


@pytest.mark.parametrize("imports,exact,truthy", _ALIASES)
def test_same_subject_alias_weakening_blocks_in_the_engine(imports, exact, truthy):
    _ir, findings, verdict = _analyze(_source(imports, exact + ";"), _source(imports, truthy + ";"))
    assert verdict == "block"
    finding, = findings
    assert (finding.rule, finding.severity) == ("ASSERT_WEAKENED", "high")
    assert finding.subject_changed is False
    assert "NO_PROD_CHANGE_IN_DIFF" in finding.escalators


def test_local_assert_standin_cannot_preserve_an_imported_assertion():
    imports = 'import assert from "node:assert";'
    before = _source(imports, "assert.strictEqual(total(), 5);")
    after = _source(imports, """const assert = { strictEqual: () => {} };
  assert.strictEqual(total(), 5);""")
    assert len(_assertions(before)) == 1
    assert _assertions(after) == []
    _ir, findings, verdict = _analyze(before, after)
    assert verdict == "block"
    assert [(finding.rule, finding.severity) for finding in findings] == [("ASSERT_REMOVED", "high")]


@pytest.mark.parametrize("imports,parameter,call", [
    ('import assert from "node:assert";', "assert", "assert.strictEqual(total(), 5)"),
    ('import verify from "node:assert";', "verify", "verify.strictEqual(total(), 5)"),
    ('import { strictEqual as same } from "node:assert";', "same", "same(total(), 5)"),
    ('import { expect } from "vitest";', "expect", "expect(total()).toBe(5)"),
    ('import { expect as verify } from "@jest/globals";', "verify", "verify(total()).toBe(5)"),
    ("", "assert", "assert.strictEqual(total(), 5)"),
    ("", "expect", "expect(total()).toBe(5)"),
])
def test_callback_parameters_shadow_imported_and_legacy_assertion_names(imports, parameter, call):
    assert _assertions(_source(imports, call + ";", parameters=parameter)) == []


@pytest.mark.parametrize("imports,name,call", [
    ('import assert from "node:assert";', "assert", "assert.strictEqual(total(), 5)"),
    ('import { expect } from "vitest";', "expect", "expect(total()).toBe(5)"),
])
def test_nested_function_parameters_shadow_outer_imports(imports, name, call):
    source = _source(imports, f"function helper({name}) {{ {call}; }}")
    assert _assertions(source) == []


def test_block_local_commonjs_alias_does_not_leak_to_the_outer_scope():
    source = _source("", """{
    const verify = require("node:assert");
    verify.strictEqual(inner(), 1);
  }
  verify.strictEqual(outside(), 2);""")
    assert [assertion.left for assertion in _assertions(source)] == ["inner()"]


def test_inner_shadow_does_not_hide_a_restored_outer_import_binding():
    source = _source('import verify from "node:assert";', """{
    const verify = { strictEqual: () => {} };
    verify.strictEqual(shadowed(), 1);
  }
  verify.strictEqual(outside(), 2);""")
    assert [assertion.left for assertion in _assertions(source)] == ["outside()"]


def test_alias_declared_in_one_test_does_not_leak_into_a_sibling_test():
    source = """test("first", () => {
  const verify = require("node:assert");
  verify.strictEqual(first(), 1);
});
test("second", () => {
  verify.strictEqual(second(), 2);
});
"""
    first, second = parse_javascript(source.encode()).units
    assert [assertion.left for assertion in first.side.assertions] == ["first()"]
    assert second.side.assertions == []


@pytest.mark.parametrize("fake_import", [
    '// import { strictEqual as same } from "node:assert";',
    '/* import { strictEqual as same } from "node:assert"; */',
    "const sample = 'import { strictEqual as same } from \"node:assert\";';",
    'const sample = `import { strictEqual as same } from "node:assert";`;',
])
def test_comment_and_literal_imports_cannot_authorize_an_alias(fake_import):
    assert _assertions(_source(fake_import, "same(total(), 5);")) == []


@pytest.mark.parametrize("imports,call", [
    ('import assert from "utility";', "assert.strictEqual(total(), 5)"),
    ('import { expect } from "utility";', "expect(total()).toBe(5)"),
    ('import { strictEqual as same } from "utility";', "same(total(), 5)"),
    ('const assert = require("utility");', "assert.strictEqual(total(), 5)"),
    ('const { expect } = require("utility");', "expect(total()).toBe(5)"),
    ('import ordinary /* from "node:assert" */ from "utility";', "ordinary(total(), 5)"),
])
def test_non_assertion_imports_are_not_real_oracles(imports, call):
    source = _source(imports, call + ";")
    assert _assertions(source) == []
    _ir, findings, verdict = _analyze(source, source.replace("total()", "different()"))
    assert findings == []
    assert verdict == "pass"


@pytest.mark.parametrize("call,form,strength", [
    ("assert.strictEqual(total(), 5)", "compare_eq", S.EXACT_VALUE),
    ("assert.ok(total())", "truthy", S.TRUTHY),
    ("assert(total())", "truthy", S.TRUTHY),
    ("expect(total()).toBe(5)", "compare_eq", S.EXACT_VALUE),
    ("expect(total()).toBeTruthy()", "truthy", S.TRUTHY),
])
def test_unbound_legacy_assertion_spellings_remain_compatible(call, form, strength):
    assertion, = _assertions(_source("", call + ";"))
    assert (assertion.left, assertion.form, assertion.strength) == ("total()", form, strength)


def _gaps(source):
    data = source.encode()
    return javascript_coverage_gaps(data, parse_javascript(data), "tests/total.test.mjs", "after")


@pytest.mark.parametrize("body,callee", [
    ("records.forEach(({ assert }) => { assert.strictEqual(total(), 5); });", "assert.strictEqual"),
    ("records.forEach(({ check: assert }) => { assert.strictEqual(total(), 5); });", "assert.strictEqual"),
    ("records.forEach(([assert]) => { assert.strictEqual(total(), 5); });", "assert.strictEqual"),
    ("function helper({ assert }) { assert.strictEqual(total(), 5); }", "assert.strictEqual"),
    ("function helper([expect]) { expect(total()).toBe(5); }", "expect"),
])
def test_destructured_non_runner_parameters_cannot_borrow_outer_assertion_authority(body, callee):
    source = _source('import assert from "node:assert";\nimport { expect } from "vitest";', body)
    assert _assertions(source) == []
    assert any(gap.callee.startswith(callee) for gap in _gaps(source))


@pytest.mark.parametrize("parameter,call,callee", [
    ("assert", "assert.strictEqual(total(), 5)", "assert.strictEqual"),
    ("{ assert }", "assert.strictEqual(total(), 5)", "assert.strictEqual"),
    ("expect", "expect(total()).toBe(5)", "expect"),
])
def test_catch_bindings_shadow_only_the_handler_scope(parameter, call, callee):
    source = _source('import assert from "node:assert";\nimport { expect } from "vitest";', f"""try {{
    operation();
  }} catch ({parameter}) {{
    {call};
  }}
  assert.strictEqual(outside(), 5);""")
    assert [assertion.left for assertion in _assertions(source)] == ["outside()"]
    assert any(gap.callee.startswith(callee) for gap in _gaps(source))


@pytest.mark.parametrize("body", [
    'records.forEach((require) => { const verify = require("node:assert"); verify.strictEqual(total(), 5); });',
    'records.forEach(({ require }) => { const verify = require("node:assert"); verify.strictEqual(total(), 5); });',
    'const require = () => ({ strictEqual: () => {} }); const verify = require("node:assert"); verify.strictEqual(total(), 5);',
])
def test_shadowed_require_cannot_mint_a_trusted_commonjs_assertion(body):
    source = _source("", body)
    assert _assertions(source) == []
    assert any(gap.callee == "verify.strictEqual" for gap in _gaps(source))


@pytest.mark.parametrize("function_keyword", ["function", "async function"])
def test_named_function_expression_shadows_its_name_only_inside_its_body(function_keyword):
    source = _source('import assert from "node:assert";', f"""const helper = {function_keyword} assert() {{
    assert.strictEqual(inside(), 1);
  }};
  assert.strictEqual(outside(), 2);""")
    assert [assertion.left for assertion in _assertions(source)] == ["outside()"]
    gaps = _gaps(source)
    assert len(gaps) == 1
    assert gaps[0].callee == "assert.strictEqual"


@pytest.mark.parametrize("imports,aliases,exact,truthy", [
    ('import assert from "node:assert";', "const verify = assert;",
     "verify.strictEqual(total(), 5)", "verify.ok(total())"),
    ('import assert from "node:assert";', "const same = assert.strictEqual; const ensure = assert.ok;",
     "same(total(), 5)", "ensure(total())"),
    ('import assert from "node:assert";', "const { strictEqual: same, ok: ensure } = assert;",
     "same(total(), 5)", "ensure(total())"),
    ('import { expect } from "vitest";', "const first = expect; const verify = first;",
     "verify(total()).toBe(5)", "verify(total()).toBeTruthy()"),
])
def test_simple_const_aliases_keep_the_same_oracle_and_weakening_detection(imports, aliases, exact, truthy):
    before = _source(imports, aliases + "\n  " + exact + ";")
    after = _source(imports, aliases + "\n  " + truthy + ";")
    old, = _assertions(before)
    new, = _assertions(after)
    assert (old.left, old.strength, new.left, new.strength) == ("total()", S.EXACT_VALUE, "total()", S.TRUTHY)
    assert _gaps(before) == _gaps(after) == []
    _ir, findings, verdict = _analyze(before, after)
    assert verdict == "block"
    assert [(finding.rule, finding.severity) for finding in findings] == [("ASSERT_WEAKENED", "high")]


@pytest.mark.parametrize("alias,call", [
    ("const verify = choose ? assert : standin;", "verify.strictEqual(total(), 5)"),
    ("const verify = assert.strictEqual.bind(null);", "verify(total(), 5)"),
])
def test_unresolved_const_alias_shapes_withhold_strength_and_remain_visible(alias, call):
    source = _source('import assert from "node:assert";', alias + "\n  " + call + ";")
    assert _assertions(source) == []
    assert any(gap.callee.startswith("verify") for gap in _gaps(source))
