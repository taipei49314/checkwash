"""Issue #218: a stand-in installed from a JS setup file is TEST_PATCHES_SUBJECT.

`jest.mock("./src/billing", () => ({ invoiceTotal: () => 78.75 }))` above an
untouched `expect(invoiceTotal(items)).toBe(78.75)` blocks when it is written
in the test file (row 109). Written in a setup file, which the runner loads
before every test file, it passed with zero findings: setup files have the
production role, and the mock scan read only the file holding the assertion.
So did `jest.enableAutomock()` there and `"automock": true` in package.json.

Ruled on #218 (2026-10-06): the carriers are `setupTests.{js,ts}`,
`jest.setup.*`, `vitest.setup.*` and the files the base side's root
package.json names in `jest.setupFiles` / `jest.setupFilesAfterEnv`; a
first-party module mock or replacing spy there, `jest.enableAutomock()`
there and `"automock": true` in package.json are stand-ins, judged like
CONFTEST_PATCHES_PROD and reported as TEST_PATCHES_SUBJECT with no unit. A
rewritten `__mocks__` file (S4) and `automock` in `jest.config.js` (S7) stay
residual.
"""
import datetime
import json

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.frontends.javascript.setup_files import is_carrier, listed_setup_files, setup_file_events

TEST = b"""const { invoiceTotal } = require("../src/billing");

test("computes invoice total", () => {
  const items = [{ price: 10.0, qty: 3 }, { price: 5.0, qty: 9 }];
  expect(invoiceTotal(items)).toBe(78.75);
});
"""
BILLING = b"""function invoiceTotal(items) {
  return items.reduce((s, i) => s + i.price * i.qty, 0);
}
module.exports = { invoiceTotal };
"""
PKG = b'{ "name": "victim", "scripts": { "test": "jest" }, "jest": { "setupFiles": ["./jest.setup.js"] } }\n'
PKG_PLAIN = b'{ "name": "victim", "scripts": { "test": "jest" } }\n'
DOM = b'require("@testing-library/jest-dom");\n'
MOCK = b'jest.mock("./src/billing", () => ({ invoiceTotal: () => 78.75 }));\n'
AUTOMOCK = ("Jest's automock is turned on, so every module a test file imports is replaced by an automatic mock")


def judge(before, after, head=None):
    """In-process analyze, the case runner's way: the head files are the snapshot."""
    snapshot = {"tests/billing.test.js": TEST, "src/billing.js": BILLING, "package.json": PKG, **(head or {})}
    snapshot.update(after)
    changes = []
    for path in sorted(set(before) | set(after)):
        old, new = before.get(path), after.get(path)
        changes.append(FileChange(path, "added" if old is None else "modified", old, new))
    _ir, findings, verdict = analyze(changes, Config(), Contract(), [], datetime.date(2026, 10, 7),
                                     root_reader=snapshot.get, root_path_lister=lambda: sorted(snapshot),
                                     root_batch_reader=lambda paths: {p: snapshot.get(p) for p in paths})
    return verdict, [(f.rule, f.severity, f.path, f.unit, f.message) for f in findings]


def blocked(path, message):
    return "block", [("TEST_PATCHES_SUBJECT", "high", path, None, f"{path}: {message}")]


INSTALLS = "this setup file installs a replacement for src/billing before every test file"


# --- the issue's rows ---------------------------------------------------------------------------

def test_S0c_a_mock_in_the_test_file_is_read_as_before():
    after = MOCK.replace(b"./src", b"../src") + TEST
    assert judge({"tests/billing.test.js": TEST}, {"tests/billing.test.js": after}) == ("block", [(
        "TEST_PATCHES_SUBJECT", "high", "tests/billing.test.js", "computes invoice total",
        "computes invoice total: this test installs a replacement for src/billing:invoiceTotal that its "
        "existing oracle consumes")])


def test_S1_a_mock_appended_to_the_setup_file_package_json_names():
    assert judge({"jest.setup.js": DOM}, {"jest.setup.js": DOM + MOCK}) == blocked("jest.setup.js", INSTALLS)


def test_S1b_a_new_setup_file_listed_in_the_same_diff():
    before = {"package.json": PKG_PLAIN}
    after = {"package.json": PKG, "jest.setup.js": DOM + MOCK}
    assert judge(before, after, {"package.json": PKG}) == blocked("jest.setup.js", INSTALLS)


def test_S2_create_react_apps_setup_tests():
    after = DOM + MOCK.replace(b"./src/billing", b"./billing")
    assert judge({"src/setupTests.js": DOM}, {"src/setupTests.js": after}, {"package.json": PKG_PLAIN}) == blocked(
        "src/setupTests.js", INSTALLS)


def test_S3_vi_mock_in_vitest_setup():
    before = b'import "@testing-library/jest-dom/vitest";\n'
    after = (b'import { vi } from "vitest";\n' + before
             + b'vi.mock("./src/billing", () => ({ invoiceTotal: () => 78.75 }));\n')
    assert judge({"vitest.setup.ts": before}, {"vitest.setup.ts": after}, {"package.json": PKG_PLAIN}) == blocked(
        "vitest.setup.ts", INSTALLS)


def test_S4_a_rewritten_manual_mock_stays_residual():
    before = b"module.exports = { invoiceTotal: jest.fn(() => 75) };\n"
    assert judge({"src/__mocks__/billing.js": before},
                 {"src/__mocks__/billing.js": before.replace(b"75", b"78.75")}) == ("pass", [])


def test_S5_automock_in_package_json():
    after = PKG.replace(b'"setupFiles"', b'"automock": true, "setupFiles"')
    assert judge({"package.json": PKG}, {"package.json": after}) == blocked("package.json", AUTOMOCK)


def test_S6_enable_automock_in_the_setup_file():
    after = DOM + b"jest.enableAutomock();\n"
    assert judge({"jest.setup.js": DOM}, {"jest.setup.js": after}) == blocked("jest.setup.js", AUTOMOCK)


def test_S7_automock_in_jest_config_stays_residual():
    before = b'module.exports = { testEnvironment: "node" };\n'
    after = b'module.exports = { testEnvironment: "node", automock: true };\n'
    assert judge({"jest.config.js": before}, {"jest.config.js": after}, {"package.json": PKG_PLAIN}) == ("pass", [])


# --- what a carrier installs ----------------------------------------------------------------------

def test_a_replacing_spy_in_a_file_package_json_lists_after_env():
    head = {"package.json": PKG.replace(b'"setupFiles": ["./jest.setup.js"]',
                                        b'"setupFilesAfterEnv": ["<rootDir>/config/setup-env"]')}
    after = (b'const billing = require("../src/billing");\n' + DOM
             + b'beforeEach(() => {\n  jest.spyOn(billing, "invoiceTotal").mockReturnValue(78.75);\n});\n')
    assert judge({"config/setup-env.js": DOM}, {"config/setup-env.js": after}, head) == blocked(
        "config/setup-env.js", "this setup file installs a replacement for src/billing:invoiceTotal before every "
        "test file")


def test_a_partial_factory_names_what_it_replaces():
    after = DOM + (b'jest.mock("./src/billing", () => ({\n  ...jest.requireActual("./src/billing"),\n'
                   b'  invoiceTotal: () => 78.75,\n}));\n')
    assert judge({"jest.setup.js": DOM}, {"jest.setup.js": after}) == blocked(
        "jest.setup.js", "this setup file installs a replacement for part of src/billing before every test file")


def test_an_alias_names_a_first_party_module():
    after = DOM + b'jest.mock("@/billing", () => ({ invoiceTotal: () => 78.75 }));\n'
    verdict, findings = judge({"jest.setup.js": DOM}, {"jest.setup.js": after})
    assert verdict == "block"
    assert [message for *_rest, message in findings] == [
        "jest.setup.js: this setup file installs a replacement for @/billing before every test file"]


@pytest.mark.parametrize("line", [
    b'jest.mock("axios");\n',
    b'jest.mock("node:fs", () => ({ readFileSync: () => "{}" }));\n',
    b'jest.mock("../outside/billing", () => ({ invoiceTotal: () => 78.75 }));\n',
    b'jest.mock("./node_modules/billing", () => ({ invoiceTotal: () => 78.75 }));\n',
    b'jest.spyOn(console, "error").mockImplementation(() => {});\n',
    b'jest.useFakeTimers();\n',
], ids=["package", "builtin", "outside_the_repository", "dependency_output", "global_object", "fake_timers"])
def test_hygiene_is_silent(line):
    assert judge({"jest.setup.js": DOM}, {"jest.setup.js": DOM + line}) == ("pass", [])


@pytest.mark.parametrize("line", [
    b"jest.disableAutomock();\n",
    b"const mocker = createMocker();\nmocker.enableAutomock();\n",
    b"getRunner(). jest.enableAutomock();\n",
], ids=["disable", "another_object", "member_of_another_call"])
def test_only_jest_turns_automock_on(line):
    assert judge({"jest.setup.js": DOM}, {"jest.setup.js": DOM + line}) == ("pass", [])


def test_vitest_spy_option_keeps_the_real_code():
    before = b'import { vi } from "vitest";\n'
    after = before + b'vi.mock("./src/billing", { spy: true });\n'
    assert judge({"vitest.setup.ts": before}, {"vitest.setup.ts": after}) == ("pass", [])


# --- new, base side against head side -------------------------------------------------------------

def test_a_mock_moved_between_setup_files_and_reformatted_is_not_new():
    moved = b'jest.mock(\n  "./billing",\n  () => ({ invoiceTotal: () => 78.75 }),\n);\n'
    before = {"jest.setup.js": DOM + MOCK, "src/setupTests.js": DOM}
    after = {"jest.setup.js": DOM, "src/setupTests.js": DOM + moved}
    assert judge(before, after) == ("pass", [])


def test_a_renamed_setup_file_keeps_its_mock():
    changes = [FileChange("jest.setup.ts", "renamed", DOM + MOCK, DOM + MOCK, old_path="jest.setup.js")]
    assert setup_file_events(changes, PKG) == []


def test_a_setup_file_that_gains_a_second_target():
    after = DOM + MOCK + b'jest.mock("./src/tax", () => ({ rate: () => 0 }));\n'
    assert judge({"jest.setup.js": DOM + MOCK}, {"jest.setup.js": after}) == blocked(
        "jest.setup.js", "this setup file installs a replacement for src/tax before every test file")


PARTIAL = b'jest.mock("./src/billing", () => ({ ...jest.requireActual("./src/billing"), invoiceTotal: () => 1 }));\n'


def test_an_edited_partial_mock_is_the_same_mock():
    """excalidraw `51ea1849` edited the body of a partial factory in setupTests.ts
    (`super.getContent()` -> `super.getContent(new Set())`), which adds a name it
    spells; the mock is not new."""
    edited = PARTIAL.replace(b"() => 1", b"() => new Set([1]).size")
    assert judge({"jest.setup.js": DOM + PARTIAL}, {"jest.setup.js": DOM + edited}) == ("pass", [])


def test_residual_a_partial_mock_widened_to_another_export_is_not_new():
    wider = PARTIAL.replace(b"invoiceTotal: () => 1", b"invoiceTotal: () => 1, taxRate: () => 0")
    assert judge({"jest.setup.js": DOM + PARTIAL}, {"jest.setup.js": DOM + wider}) == ("pass", [])


def test_a_partial_mock_turned_into_a_whole_module_mock_is_new():
    assert judge({"jest.setup.js": DOM + PARTIAL}, {"jest.setup.js": DOM + MOCK}) == blocked("jest.setup.js", INSTALLS)


def test_a_whole_module_mock_where_a_member_spy_was_is_new():
    spy = (b'const billing = require("./src/billing");\n'
           b'jest.spyOn(billing, "invoiceTotal").mockReturnValue(78.75);\n')
    assert judge({"jest.setup.js": DOM + spy}, {"jest.setup.js": DOM + MOCK}) == blocked("jest.setup.js", INSTALLS)


def test_a_spy_on_a_member_a_partial_mock_covered_is_not_new():
    after = DOM + PARTIAL + (b'const billing = require("./src/billing");\n'
                             b'jest.spyOn(billing, "invoiceTotal").mockReturnValue(78.75);\n')
    assert judge({"jest.setup.js": DOM + PARTIAL}, {"jest.setup.js": after}) == ("pass", [])


def test_a_helper_renamed_into_a_setup_file_brings_its_mock_to_every_test_file():
    helper = DOM + MOCK.replace(b"./src", b"../../src")
    changes = [FileChange("test/helpers/jest.setup.js", "renamed", helper, helper, old_path="test/helpers/mocks.js")]
    assert [event[:3] for event in setup_file_events(changes, PKG)] == [
        ("test/helpers/jest.setup.js", None, "src/billing")]


def test_automock_already_on_is_not_new():
    on = DOM + b"jest.enableAutomock();\n"
    assert judge({"jest.setup.js": on}, {"jest.setup.js": on + b"// keep\n"}) == ("pass", [])
    with_key = PKG.replace(b'"setupFiles"', b'"automock": true, "setupFiles"')
    assert judge({"package.json": with_key}, {"package.json": with_key.replace(b"victim", b"victim-2")},
                 {"package.json": with_key}) == ("pass", [])


@pytest.mark.parametrize("value", [b'"true"', b"1", b"[]"], ids=["string", "number", "list"])
def test_automock_is_on_only_when_true(value):
    after = PKG.replace(b'"setupFiles"', b'"automock": ' + value + b', "setupFiles"')
    assert judge({"package.json": PKG}, {"package.json": after}) == ("pass", [])


def test_automock_turned_off_is_no_stand_in():
    with_key = PKG.replace(b'"setupFiles"', b'"automock": true, "setupFiles"')
    off = PKG.replace(b'"setupFiles"', b'"automock": false, "setupFiles"')
    assert judge({"package.json": with_key}, {"package.json": off}, {"package.json": with_key}) == ("pass", [])


def test_a_setup_file_only_the_head_side_lists_stays_residual():
    head_pkg = PKG.replace(b'"./jest.setup.js"', b'"./config/setup-env.js"')
    before = {"package.json": PKG_PLAIN, "config/setup-env.js": DOM}
    after = {"package.json": head_pkg, "config/setup-env.js": DOM + MOCK.replace(b"./src", b"../src")}
    assert judge(before, after, {"package.json": head_pkg}) == ("pass", [])


# --- the carriers -------------------------------------------------------------------------------

@pytest.mark.parametrize("path, carrier", [
    ("src/setupTests.js", True),
    ("src/setupTests.ts", True),
    ("packages/web/src/setupTests.js", True),
    ("jest.setup.js", True),
    ("jest.setup.ts", True),
    ("jest.setup.mjs", True),
    ("jest.setup.cts", True),
    ("jest.setup.tsx", True),
    ("vitest.setup.ts", True),
    ("packages/api/vitest.setup.mts", True),
    ("jest.config.js", False),
    ("vitest.config.ts", False),
    ("jest.setup.json", False),
    ("src/mysetupTests.js", False),
    ("test/setup.js", False),
])
def test_a_carrier_by_its_name(path, carrier):
    assert is_carrier(path, frozenset()) is carrier


@pytest.mark.parametrize("entries, listed", [
    (["./jest.setup.js"], {"jest.setup"}),
    (["<rootDir>/test/setup-env.ts"], {"test/setup-env"}),
    (["<rootDir>/test/setup/index.js"], {"test/setup"}),
    (["./test/../config/setup"], {"config/setup"}),
    (["jest-localstorage-mock", "@testing-library/jest-dom"], set()),
    (["../outside/setup.js", "<rootDir>/../outside.js"], set()),
    ([".\\win\\setup.js"], set()),
    ([42, None, {"a": 1}], set()),
], ids=["relative", "root_dir", "index", "normalized", "packages", "outside", "backslash", "not_strings"])
def test_the_files_package_json_names(entries, listed):
    manifest = json.dumps({"jest": {"setupFiles": entries[:1], "setupFilesAfterEnv": entries[1:]}}).encode()
    assert listed_setup_files(manifest) == listed


@pytest.mark.parametrize("manifest", [
    None, b"", b"not json", b"[1, 2]", b'{"jest": "./jest.setup.js"}', b'{"jest": {"setupFiles": "./a.js"}}',
    b'{"jest": {"setupFiles": ["./a.js"]}' + b" " * 1_000_000 + b"}",
], ids=["absent", "empty", "not_json", "not_an_object", "jest_not_an_object", "not_a_list", "too_large"])
def test_an_unreadable_manifest_lists_nothing(manifest):
    assert listed_setup_files(manifest) == frozenset()


def test_a_listed_file_is_a_carrier_whatever_its_extension():
    listed = listed_setup_files(b'{"jest": {"setupFiles": ["<rootDir>/test/setup-env"]}}')
    assert is_carrier("test/setup-env.js", listed)
    assert is_carrier("test/setup-env.ts", listed)
    assert not is_carrier("test/setup-env.json", listed)
    assert not is_carrier("test/other.js", listed)


def test_a_diff_without_a_carrier_reads_no_manifest():
    read = []
    changes = [FileChange("src/billing.py", "modified", b"x = 1\n", b"x = 2\n")]
    assert setup_file_events(changes, lambda: read.append(1) or PKG) == []
    assert read == []
