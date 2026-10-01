"""Runner zero-configuration layouts reach the assertion pipeline (issue #175).

Jest collects every JS/TS file beneath a `__tests__` directory with no
configuration, and a weakening in `__tests__/billing.js` passed with zero
findings: the path classifier modelled Node's defaults and the `.test.` /
`.spec.` suffixes only. This inventory is written from each runner's
documented defaults, not from the implementation's table; the negative list
pins the neighbours that are not tests.
"""

import datetime

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.frontends.javascript.frontend import is_js_test_path as frontend_test_path
from checkwash.frontends.javascript.paths import is_js_test_path


# Jest's default `testMatch`, as far as its default `moduleFileExtensions`
# reach: https://jestjs.io/docs/configuration#testmatch-arraystring
JEST_EXTENSIONS = ("js", "cjs", "mjs", "jsx", "ts", "cts", "mts", "tsx")
JEST_PATTERNS = (
    "__tests__/billing.{ext}",
    "src/__tests__/billing.{ext}",
    "packages/api/src/__tests__/nested/billing.{ext}",
    # Jest ignores only node_modules by default, so helpers and fixtures
    # beneath __tests__ are collected as well.
    "src/__tests__/__fixtures__/items.{ext}",
    "spec.{ext}",
    "test.{ext}",
    "src/billing.spec.{ext}",
    "src/billing.test.{ext}",
)
# Bun's default discovery: https://bun.sh/docs/cli/test
BUN_EXTENSIONS = ("js", "jsx", "ts", "tsx")
BUN_PATTERNS = ("src/billing_test.{ext}", "src/billing_spec.{ext}")


@pytest.mark.parametrize("extension", JEST_EXTENSIONS)
@pytest.mark.parametrize("pattern", JEST_PATTERNS)
def test_jest_default_test_match_is_recognized(pattern, extension):
    path = pattern.format(ext=extension)
    assert is_js_test_path(path)
    assert frontend_test_path(path)


@pytest.mark.parametrize("extension", BUN_EXTENSIONS)
@pytest.mark.parametrize("pattern", BUN_PATTERNS)
def test_bun_default_names_are_recognized(pattern, extension):
    path = pattern.format(ext=extension)
    assert is_js_test_path(path)
    assert frontend_test_path(path)


def test_jest_directory_follows_the_existing_case_convention():
    assert is_js_test_path("SRC/__TESTS__/Billing.JSX")


@pytest.mark.parametrize("path", [
    # Beside the tests, but collected by no default.
    "__mocks__/billing.js", "src/__mocks__/billing.ts", "__fixtures__/items.js",
    "transforms/__testfixtures__/billing.input.js",
    # Only the exact directory segment is a default.
    "src/tests__/billing.js", "src/__tests__x/billing.js", "src/__tests__.js",
    # Non-JS files beneath __tests__ keep their own roles.
    "__tests__/billing.json", "__tests__/__snapshots__/billing.test.js.snap",
    "__tests__/README.md", "__tests__/billing",
    # A name must be exactly the runner's word, not merely contain it.
    "src/specification.js", "src/inspect.js", "src/respec.js", "src/my-spec.js",
    "src/billing-spec.js", "src/spec-helpers.js", "src/billing.specs.js",
    # Generated and dependency trees stay excluded.
    "node_modules/pkg/__tests__/billing.js", "dist/__tests__/billing.js",
    "packages/api/build/__tests__/billing.ts",
])
def test_neighbours_and_look_alike_names_are_not_test_paths(path):
    assert not is_js_test_path(path)
    assert not frontend_test_path(path)


SOURCE = """const { invoiceTotal } = require("../src/billing.js");

describe("billing", () => {
  it("computes invoice total", () => {
    const items = [{ price: 10.0, qty: 3 }, { price: 5.0, qty: 9 }];
    expect(invoiceTotal(items)).MATCHER;
  });
});
"""
EXACT = SOURCE.replace("MATCHER", "toBe(78.75)").encode()
WEAK = SOURCE.replace("MATCHER", "toBeTruthy()").encode()


def _analyze(change):
    return analyze([change], Config(), Contract(), [], datetime.date(2026, 10, 1))


@pytest.mark.parametrize("path", [
    "__tests__/billing.js", "src/__tests__/billing.ts", "src/components/__tests__/Invoice.tsx",
    "spec.js", "src/billing_spec.ts",
])
def test_default_layouts_block_real_weakening_through_the_engine(path):
    ir, findings, verdict = _analyze(FileChange(path, "modified", EXACT, WEAK))
    assert verdict == "block"
    assert [(finding.rule, finding.severity) for finding in findings] == [("ASSERT_WEAKENED", "high")]
    assert [file.role for file in ir.files] == ["test"]


def test_default_layouts_preserve_unchanged_assertions():
    commented = EXACT.replace(b"toBe(78.75);", b"toBe(78.75); // explanation")
    _ir, findings, verdict = _analyze(FileChange("__tests__/billing.js", "modified", EXACT, commented))
    assert (findings, verdict) == ([], "pass")


@pytest.mark.parametrize("old,new", [
    ("__tests__/billing.js", "src/billing.js"),
    ("src/__tests__/billing.ts", "src/__mocks__/billing.ts"),
    ("src/billing_spec.tsx", "src/billing.tsx"),
])
def test_moving_out_of_a_default_layout_retains_the_disappeared_test(old, new):
    ir, findings, verdict = _analyze(FileChange(new, "renamed", EXACT, EXACT, old_path=old))
    assert verdict == "block"
    assert [(finding.rule, finding.severity, finding.path) for finding in findings] == [
        ("TEST_DISABLED", "high", old),
    ]
    assert any(file.path == old and file.role == "test" for file in ir.files)


@pytest.mark.parametrize("old,new", [
    # Before #175 this move was expanded as a removal from test coverage,
    # although Jest still collects the destination with no configuration.
    ("src/billing.test.js", "src/__tests__/billing.js"),
    ("__tests__/billing.js", "packages/api/__tests__/billing.js"),
    ("__tests__/billing.js", "__tests__/billing.test.js"),
])
def test_moves_that_jest_still_collects_remain_benign(old, new):
    _ir, findings, verdict = _analyze(FileChange(new, "renamed", EXACT, EXACT, old_path=old))
    assert (findings, verdict) == ([], "pass")
