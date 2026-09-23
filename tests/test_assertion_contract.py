"""Independent recognition and mutation contracts prevent silent API omissions.

Do not replace the reviewed JSON with values generated from frontend tables:
the point is to fail when a whole assertion family is no longer recognized.
"""

import copy
import json
from pathlib import Path
import re
import runpy

import pytest

from checkwash.frontends.javascript import frontend

# The pytest console script need not put the repository root on sys.path.
# Load the development tool by its owned path, independently of installation.
_CONTRACT_TOOLS = runpy.run_path(str(Path(__file__).resolve().parents[1] / "tools/assertion_contract.py"))
check_api_case = _CONTRACT_TOOLS["check_api_case"]
check_mutation_case = _CONTRACT_TOOLS["check_mutation_case"]
load_contract = _CONTRACT_TOOLS["load_contract"]
mutation_cases = _CONTRACT_TOOLS["mutation_cases"]
validate_contract = _CONTRACT_TOOLS["validate_contract"]
verify_contract = _CONTRACT_TOOLS["verify_contract"]


CONTRACT = load_contract()
APIS = CONTRACT["apis"]
MUTATIONS = mutation_cases(CONTRACT)


@pytest.mark.parametrize("case", APIS, ids=lambda case: case["id"])
def test_declared_api_support(case):
    check_api_case(case)


@pytest.mark.parametrize("case", MUTATIONS, ids=lambda case: case["id"])
def test_mutation_detection_and_negative_controls(case):
    check_mutation_case(case)


def test_node_public_direct_api_inventory_is_explicit():
    # Inventory from nodejs.org/api/assert.html, not the detector's supported
    # methods. Unsupported methods must stay visible as honest boundaries.
    public_api = {
        "assert", "deepEqual", "deepStrictEqual", "doesNotMatch", "doesNotReject",
        "doesNotThrow", "equal", "fail", "ifError", "match", "notDeepEqual",
        "notDeepStrictEqual", "notEqual", "notStrictEqual", "ok", "rejects",
        "strictEqual", "throws", "partialDeepStrictEqual",
    }
    actual = {case["id"].removeprefix("node.") for case in APIS
              if case["id"].startswith("node.") and case["id"].count(".") == 1}
    assert actual == public_api
    supported = {case["id"] for case in APIS if case["status"] == "supported"}
    assert "node.strictEqual" in supported
    assert "node.partialDeepStrictEqual" not in supported


def test_jest_declared_matchers_have_positive_and_negative_spellings():
    matchers = {
        "toBe", "toEqual", "toStrictEqual", "toBeCloseTo", "toContain", "toMatch",
        "toBeTruthy", "toBeFalsy", "toBeDefined", "toBeUndefined", "toBeNull",
        "toBeGreaterThan", "toBeGreaterThanOrEqual", "toBeLessThan", "toBeLessThanOrEqual",
    }
    supported = {case["id"] for case in APIS
                 if case["framework"] == "jest" and case["status"] == "supported"
                 and not case["id"].startswith("jest.import.")}
    assert supported == {f"jest.{prefix}{matcher}" for prefix in ("", "not.") for matcher in matchers}


def test_static_alias_and_context_contract_inventory_is_explicit():
    supported = {case["id"] for case in APIS if case["status"] == "supported"}
    required = {
        "node.import.esm-renamed-default", "node.import.esm-named-method",
        "node.import.esm-renamed-named", "node.import.cjs-destructured",
        "node.import.cjs-renamed", "node.import.strict-member",
        "node.import.esm-renamed-namespace", "node.import.esm-strict-renamed",
        "node.import.cjs-renamed-destructured", "node.import.cjs-strict-destructured",
        "node.import.cjs-strict-renamed", "node.import.local-method-alias",
        "jest.import.expect-alias", "jest.import.cjs-expect-alias", "jest.import.namespace",
        "vitest.import.esm-expect-alias", "vitest.import.cjs-expect-alias",
        "node.context.renamed-arrow", "node.context.renamed-function", "node.context.cjs-renamed",
    }
    assert required <= supported
    for case_id in required:
        assert {case["kind"] for case in MUTATIONS if case["id"].startswith(case_id + ".")} == {
            "removal", "preserving", "weakening", "strengthening",
        }, case_id


def test_node_discovery_paths_have_loss_and_normal_controls():
    expected = {
        "test/example.js", "test.js", "test-total.cjs", "total_test.mjs",
        "nested/total-test.ts", "nested/total.test.cts", "packages/api/test/example.mts",
    }
    paths = {case["path"] for case in APIS if case["id"].startswith("syntax.path.node-")}
    assert paths == expected
    for path in paths:
        assert {case["kind"] for case in MUTATIONS if case["path"] == path} == {
            "removal", "preserving", "weakening", "strengthening",
        }, path


def test_unbound_dynamic_unknown_and_shadowed_assertions_remain_explicit_boundaries():
    unsupported = {case["id"] for case in APIS if case["status"] == "unsupported"}
    assert {
        "node.unsupported.renamed-context", "node.unsupported.assert-instance",
        "node.unsupported.bracket-member", "node.partialDeepStrictEqual",
        "jest.unsupported.custom-matcher", "jest.unsupported.resolves", "jest.unsupported.rejects",
        "control.local-standin", "control.callback-parameter", "control.named-alias-parameter",
    } <= unsupported
    for name in ("local-standin", "callback-parameter", "named-alias-parameter"):
        case = next(case for case in MUTATIONS if case["id"] == f"node.binding.{name}.remove")
        assert case["kind"] == "removal"
        assert case["rule"] == "ASSERT_REMOVED"


def test_every_supported_spelling_has_removal_and_preserving_checks():
    by_source = {}
    for case in MUTATIONS:
        by_source.setdefault((case["path"], case["before"]), set()).add(case["kind"])
    for case in APIS:
        if case["status"] == "supported":
            assert {"removal", "preserving"} <= by_source[(case["path"], case["source"])], case["id"]
    assert {case["kind"] for case in MUTATIONS} == {
        "weakening", "removal", "preserving", "strengthening",
    }


@pytest.mark.parametrize("case", [case for case in MUTATIONS if case["kind"] == "weakening"],
                         ids=lambda case: case["id"])
def test_weakening_mutations_keep_the_same_subject(case):
    before = [a for unit in frontend.parse_javascript(case["before"].encode()).units
              for a in unit.side.assertions]
    after = [a for unit in frontend.parse_javascript(case["after"].encode()).units
             for a in unit.side.assertions]
    assert [a.left for a in before] == [a.left for a in after]
    assert sum(old.strength > new.strength for old, new in zip(before, after)) == 1


def test_recognition_checker_catches_entire_node_family_omission(monkeypatch):
    monkeypatch.setattr(frontend, "_node_assertions", lambda *args: [])
    case = next(case for case in APIS if case["id"] == "node.strictEqual")
    with pytest.raises(AssertionError, match="node.strictEqual: expected recognition"):
        check_api_case(case)


def test_engine_checker_catches_both_sides_silently_omitted(monkeypatch):
    # Recreate #164's critical failure: before AND after contain zero parsed
    # assertions, so an ordinary engine test without a fixed outcome passes.
    monkeypatch.setattr(frontend, "_node_assertions", lambda *args: [])
    case = next(case for case in MUTATIONS if case["id"] == "node.strictEqual.truthiness")
    with pytest.raises(AssertionError, match=r"got \('pass', \[\]\)"):
        check_mutation_case(case)


def test_contract_catches_entire_jest_family_omission(monkeypatch):
    monkeypatch.setattr(frontend, "_EXPECT_RE", re.compile(r"(?!)"))
    case = next(case for case in APIS if case["id"] == "jest.toBe")
    with pytest.raises(AssertionError, match="jest.toBe: expected recognition"):
        check_api_case(case)


def test_receipt_retains_recognition_and_mutation_failures(monkeypatch):
    monkeypatch.setattr(frontend, "_node_assertions", lambda *args: [])
    receipt = verify_contract(CONTRACT)
    assert receipt["status"] == "fail"
    assert any(message.startswith("node.strictEqual: expected recognition") for message in receipt["failures"])
    assert any(message.startswith("node.strictEqual.truthiness:") for message in receipt["failures"])


def test_contract_can_load_from_explicit_path_and_returns_independent_records(tmp_path):
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(CONTRACT), encoding="utf-8")
    contract = load_contract(path)
    cases = mutation_cases(contract)
    cases[0]["before"] = "changed by caller"
    assert contract["mutations"][0]["before"] != cases[0]["before"]
    assert load_contract(path) == CONTRACT


@pytest.mark.parametrize("collection,field,value,match", [
    ("apis", "status", "supported-but-unknown", "invalid support status"),
    ("apis", "assertions", [], "contradicts expected recognition"),
    ("apis", "path", "../escape.test.js", "unsafe or non-test path"),
    ("apis", "path", "C:/escape.test.js", "unsafe or non-test path"),
    ("apis", "path", ".", "unsafe or non-test path"),
    ("apis", "path", "test/", "unsafe or non-test path"),
    ("apis", "path", ".git/injected.test.js", "unsafe or non-test path"),
    ("apis", "path", ".GIT/injected.test.js", "unsafe or non-test path"),
    ("apis", "path", "test/../escape.js", "unsafe or non-test path"),
    ("apis", "path", "/test/example.js", "unsafe or non-test path"),
    ("apis", "path", "src/example.js", "unsafe or non-test path"),
    ("apis", "path", "tests/example.js", "unsafe or non-test path"),
    ("apis", "path", "test/example.jsx", "unsafe or non-test path"),
    ("apis", "source", "", "source is required"),
    ("mutations", "verdict", "pass", "outcome contradicts mutation kind"),
    ("mutations", "rule", None, "outcome contradicts mutation kind"),
    ("mutations", "severity", "warn", "outcome contradicts mutation kind"),
    ("mutations", "after", "", "after source is required"),
    ("mutations", "kind", "unknown", "invalid mutation kind"),
])
def test_invalid_contract_records_fail_before_qualification(collection, field, value, match):
    contract = copy.deepcopy(CONTRACT)
    contract[collection][0][field] = value
    with pytest.raises(ValueError, match=match):
        validate_contract(contract)


def test_duplicate_case_ids_are_rejected():
    contract = copy.deepcopy(CONTRACT)
    contract["apis"].append(contract["apis"][0])
    with pytest.raises(ValueError, match="duplicate apis id"):
        validate_contract(contract)
