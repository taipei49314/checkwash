"""JS/TS alias specifiers name first-party modules (#196 188.6).

The ruling of 2026-10-03: "B first (the same alias string in a mock and an
import is one module; `@/` and `~/` are first-party), then C as its bounded
extension (the base-side root tsconfig only). Route both through the one
module_key." These pin the key an alias resolves to, how the base side's
root tsconfig.json is read, and the end-to-end events either produces.
"""

from __future__ import annotations

import datetime

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.frontends.javascript.aliases import Aliases, MAX_TSCONFIG_BYTES, tsconfig_paths
from checkwash.frontends.javascript.module_mocks import _possibly_one, module_key
from checkwash.gitio.snapshot import search_source_mapping

PATH = "tests/billing.test.ts"
TSCONFIG = '{\n  "compilerOptions": {\n    "baseUrl": ".",\n    "paths": { "@/*": ["src/*"] }\n  }\n}\n'


def _aliases(tsconfig: str | None) -> Aliases:
    return Aliases(lambda: tsconfig.encode("utf-8") if tsconfig is not None else None)


# --- B: `@/` and `~/` are first-party; one alias string is one module --------------------------

@pytest.mark.parametrize(("specifier", "expected"), [
    ("@/billing", "@/billing"),
    ("@/billing.ts", "@/billing"),
    ("@/billing.mjs", "@/billing"),
    ("@/billing/index.js", "@/billing"),
    ("@/billing/index", "@/billing"),
    ("@/src/billing", "@/src/billing"),
    ("@/./billing", "@/billing"),
    ("@/lib/../billing", "@/billing"),
    ("~/billing", "~/billing"),
    ("~/billing.tsx", "~/billing"),
    # Not an alias of the project's own source.
    ("@/../billing", None),
    ("@/", None),
    ("@/.", None),
    ("~/", None),
    ("@/node_modules/pkg", None),
    ("@/dist/billing", None),
    ("@/billing?raw", None),
    ("@/billing#x", None),
    ("@/billing\\index", None),
    ("@scope/billing", None),
    ("@billing", None),
    ("~billing", None),
    ("~", None),
    ("@", None),
    ("#billing", None),
    ("/src/billing", None),
])
def test_an_at_or_tilde_alias_is_its_own_key(specifier, expected):
    assert module_key(PATH, specifier) == expected


def test_an_alias_names_one_module_from_any_test_file():
    """Unlike a relative specifier, an alias does not depend on where the test file is."""
    keys = {module_key(path, "@/billing") for path in ("billing.test.ts", "tests/a/b/billing.test.ts")}
    assert keys == {"@/billing"}
    assert module_key("tests/billing.test.ts", "../src/billing") == "src/billing"


# --- C: the base side's root tsconfig.json --------------------------------------------------------

def test_tsconfig_json_with_comments_and_trailing_commas_is_read():
    data = (
        "\ufeff{\n"
        "  // the editor's comment\n"
        '  "compilerOptions": {\n'
        '    /* a block comment, with a "quote" */\n'
        '    "baseUrl": "./",\n'
        '    "paths": {\n'
        '      "@/*": ["src/*",],\n'
        '      "//not-a-comment/*": ["lib/*" /* trailing */ ],\n'
        "    },\n"
        "  },\n"
        "}\n"
    )
    paths = tsconfig_paths(data.encode("utf-8"))
    assert paths is not None
    assert paths.target("@/billing") == "./src/billing"
    assert paths.target("//not-a-comment/x") == "./lib/x"


@pytest.mark.parametrize("text", [
    '{"compilerOptions": {"paths": {"@/*": ["src/*"], // the source root\n}}}',
    '{"compilerOptions": {"paths": {"@/*": ["src/*"], /* the source root */}}}',
    '{"compilerOptions": {"paths": {"@/*": ["src/*", /* the generated root */], }}}',
    '{"compilerOptions": {"paths": {"@/*": ["src/*"]}, // a comment, then the end\n}}',
], ids=["line-comment", "block-comment", "array", "object"])
def test_a_trailing_comma_before_a_comment_is_dropped(text):
    paths = tsconfig_paths(text.encode("utf-8"))
    assert paths is not None and paths.target("@/billing") == "src/billing"


def test_a_string_is_read_whole_through_its_escapes():
    """`//` and `/*` inside a string, after an escaped quote, are not comments."""
    text = '{"compilerOptions": {"paths": {"@/*": ["src/*"], "a\\"//b/*": ["lib/*"]}}}'
    paths = tsconfig_paths(text.encode("utf-8"))
    assert paths is not None
    assert paths.target('a"//b/x') == "lib/x"
    assert paths.target("@/billing") == "src/billing"


@pytest.mark.parametrize("data", [
    None,
    b"",
    b"{",
    b"[]",
    b'{"compilerOptions": []}',
    b'{"compilerOptions": {}}',
    b'{"compilerOptions": {"paths": []}}',
    b'{"compilerOptions": {"paths": {}}}',
    b'{"compilerOptions": {"baseUrl": 1, "paths": {"@/*": ["src/*"]}}}',
    b'{"compilerOptions": {"paths": {"@/*": "src/*"}}}',
    b'{"compilerOptions": {"paths": {"@/*": []}}}',
    b'{"compilerOptions": {"paths": {"@/*": [1]}}}',
    b'{"compilerOptions": {"paths": {"@/**": ["src/*"]}}}',
    b'{"compilerOptions": {"paths": {"@/*": ["src/**"]}}}',
    b'{"compilerOptions": {"paths": {"config": ["src/*"]}}}',
    b'{"compilerOptions": {"paths": {"*": ["src/*"]}}}',
    b'{"compilerOptions": {"paths": {"*.svg": ["assets/*.svg"]}}}',
    b'{"compilerOptions": {"paths": {"@/*": ["src/*"]}}}\xff',
    b'{"extends": "./tsconfig.base.json"}',
], ids=lambda value: repr(value)[:40])
def test_a_tsconfig_that_maps_nothing_readable_gives_no_paths(data):
    assert tsconfig_paths(data) is None


def test_an_oversized_tsconfig_is_not_read():
    body = b'{"compilerOptions": {"paths": {"@/*": ["src/*"]}}}'
    assert tsconfig_paths(body) is not None
    assert tsconfig_paths(body + b" " * (MAX_TSCONFIG_BYTES - len(body))) is not None
    assert tsconfig_paths(body + b" " * (MAX_TSCONFIG_BYTES - len(body) + 1)) is None


@pytest.mark.parametrize(("paths", "base_url", "specifier", "target"), [
    ({"@/*": ["src/*"]}, None, "@/billing", "src/billing"),
    ({"@/*": ["./src/*"]}, None, "@/billing", "./src/billing"),
    ({"@app/*": ["app/*"]}, "src", "@app/billing", "src/app/billing"),
    ({"@app/*": ["app/*"]}, "./src/", "@app/billing", "./src/app/billing"),
    # The longest prefix wins, wherever it is declared.
    ({"@/*": ["src/*"], "@/lib/*": ["lib/*"]}, None, "@/lib/x", "lib/x"),
    ({"@/lib/*": ["lib/*"], "@/*": ["src/*"]}, None, "@/lib/x", "lib/x"),
    # Equal prefixes: the first declared.
    ({"@/*": ["a/*"], "@/*.ts": ["b/*"]}, None, "@/x.ts", "a/x.ts"),
    ({"@/*.ts": ["b/*"], "@/*": ["a/*"]}, None, "@/x.ts", "b/x"),
    # An exact pattern before any wildcard.
    ({"c*": ["other/*"], "config": ["src/config/index.ts"]}, None, "config", "src/config/index.ts"),
    # A suffix narrows a wildcard.
    ({"@assets/*.svg": ["assets/*.svg"]}, None, "@assets/logo.svg", "assets/logo.svg"),
    ({"@assets/*.svg": ["assets/*.svg"]}, None, "@assets/logo.png", None),
    # A wildcard pattern may map every match to one file.
    ({"@billing/*": ["src/billing.ts"]}, None, "@billing/anything", "src/billing.ts"),
    # The first target is the module.
    ({"@/*": ["src/*", "generated/*"]}, None, "@/billing", "src/billing"),
    # A prefix and a suffix never overlap in the specifier.
    ({"@a*a": ["x/*"]}, None, "@a", None),
    ({"@a*a": ["x/*"]}, None, "@aa", "x/"),
    ({"@/*": ["src/*"]}, None, "~/billing", None),
])
def test_a_paths_pattern_maps_as_typescript_matches_it(paths, base_url, specifier, target):
    import json
    options = {"paths": paths} if base_url is None else {"baseUrl": base_url, "paths": paths}
    parsed = tsconfig_paths(json.dumps({"compilerOptions": options}).encode("utf-8"))
    assert parsed is not None
    assert parsed.target(specifier) == target


@pytest.mark.parametrize(("tsconfig", "specifier", "expected"), [
    (TSCONFIG, "@/billing", "src/billing"),
    (TSCONFIG, "@/billing.ts", "src/billing"),
    (TSCONFIG, "@/billing/index.ts", "src/billing"),
    (TSCONFIG, "@/lib/../billing", "src/billing"),
    # An alias tsconfig does not map keeps B's key.
    (TSCONFIG, "~/billing", "~/billing"),
    # A bare specifier only a pattern maps.
    ('{"compilerOptions": {"paths": {"billing": ["./src/billing.ts"]}}}', "billing", "src/billing"),
    ('{"compilerOptions": {"paths": {"@/*": ["src/*"]}}}', "billing", None),
    ('{"compilerOptions": {"baseUrl": "src"}}', "billing", None),
    # A mapping that leaves the repository or lands in dependency output names
    # nothing the project owns, and B does not stand in for it.
    ('{"compilerOptions": {"paths": {"@/*": ["../outside/*"]}}}', "@/billing", None),
    ('{"compilerOptions": {"baseUrl": "..", "paths": {"@/*": ["*"]}}}', "@/billing", None),
    ('{"compilerOptions": {"paths": {"@/*": ["/src/*"]}}}', "@/billing", None),
    ('{"compilerOptions": {"paths": {"@/*": ["node_modules/pkg/*"]}}}', "@/billing", None),
    ('{"compilerOptions": {"paths": {"@/*": ["src\\\\*"]}}}', "@/billing", None),
    ('{"compilerOptions": {"paths": {"@/*": ["*"]}}}', "@/..", None),
    # A query or a fragment is never a module path.
    (TSCONFIG, "@/billing?raw", None),
])
def test_module_key_resolves_through_the_base_tsconfig(tsconfig, specifier, expected):
    assert module_key(PATH, specifier, _aliases(tsconfig)) == expected


def test_a_relative_specifier_never_asks_the_tsconfig():
    """TypeScript applies `paths` to non-relative specifiers only."""
    reads = []
    aliases = Aliases(lambda: reads.append(1) or b'{"compilerOptions": {"paths": {"./*": ["other/*"]}}}')
    assert module_key(PATH, "./billing", aliases) == "tests/billing"
    assert module_key(PATH, "../src/billing", aliases) == "src/billing"
    assert reads == []
    assert module_key(PATH, "@/billing", aliases) == "@/billing"
    assert module_key(PATH, "axios", aliases) is None
    assert reads == [1]


# --- End to end ------------------------------------------------------------------------------------

VITEST = 'import { describe, it, expect } from "vitest";\n'
WITH_VI = 'import { describe, it, expect, vi } from "vitest";\n'


def _before(specifier: str, mock: str | None = None) -> str:
    return (
        (WITH_VI if mock else VITEST)
        + (f'vi.mock("{mock}", () => ({{\n  invoiceTotal: () => 78.75,\n}}));\n' if mock else "")
        + f'import {{ invoiceTotal }} from "{specifier}";\n'
        + "\n"
        + 'describe("billing", () => {\n'
        + '  it("computes invoice total", () => {\n'
        + "    const items = [{ price: 10.0, qty: 3 }, { price: 5.0, qty: 9 }];\n"
        + "    expect(invoiceTotal(items)).toBe(78.75);\n"
        + "  });\n"
        + "});\n"
    )


def _events(before: str, after: str, *, head_tsconfig: str | None = None, base_tsconfig: str | None = None,
            changed_tsconfig: bool = False, reader: bool = True):
    snapshot = {PATH: after.encode("utf-8")}
    changes = [FileChange(PATH, "modified", before.encode("utf-8"), after.encode("utf-8"))]
    if changed_tsconfig:
        status = "modified" if base_tsconfig and head_tsconfig else ("added" if head_tsconfig else "deleted")
        changes.append(FileChange("tsconfig.json", status,
                                  base_tsconfig.encode("utf-8") if base_tsconfig else None,
                                  head_tsconfig.encode("utf-8") if head_tsconfig else None))
    if head_tsconfig is not None:
        snapshot["tsconfig.json"] = head_tsconfig.encode("utf-8")
    ir, findings, _verdict = analyze(
        changes, Config(), Contract(), [], datetime.date(2026, 1, 1),
        root_reader=snapshot.get if reader else None,
        root_searcher=lambda needles: search_source_mapping(snapshot, needles),
    )
    return ([(unit, target) for _path, unit, target, _text, _span in ir.globals.subject_installations],
            [(f.rule, f.severity) for f in findings if f.rule == "TEST_PATCHES_SUBJECT"])


UNIT = "computes invoice total"


@pytest.mark.parametrize(("specifier", "mock"), [
    ("@/billing", "@/billing"),
    ("@/billing", "@/billing.ts"),
    ("@/billing.js", "@/billing/index.js"),
    ("~/billing", "~/billing"),
])
def test_b_the_same_alias_in_a_mock_and_an_import_is_one_module(specifier, mock):
    events, findings = _events(_before(specifier), _before(specifier, mock))
    assert events == [(UNIT, mock[:2] + "billing:invoiceTotal")]
    assert findings == [("TEST_PATCHES_SUBJECT", "high")]


@pytest.mark.parametrize(("specifier", "mock"), [
    ("../src/billing", "@/billing"),
    ("@/billing", "~/billing"),
    ("@/billing", "../src/billing"),
])
def test_b_alone_never_joins_two_spellings(specifier, mock):
    """Without the tsconfig, which file an alias names is runner configuration."""
    assert _events(_before(specifier), _before(specifier, mock)) == ([], [])


@pytest.mark.parametrize(("specifier", "mock"), [
    ("../src/billing", "@/billing"),
    ("@/billing", "../src/billing.ts"),
    ("@/billing", "@/billing/index"),
])
def test_c_the_base_tsconfig_joins_an_alias_and_a_relative_specifier(specifier, mock):
    events, findings = _events(_before(specifier), _before(specifier, mock), head_tsconfig=TSCONFIG)
    assert events == [(UNIT, "src/billing:invoiceTotal")]
    assert findings == [("TEST_PATCHES_SUBJECT", "high")]


def test_c_a_tsconfig_the_diff_adds_is_not_the_base_side():
    """A diff cannot remap its own mocks: the base side had no paths."""
    before, after = _before("../src/billing"), _before("../src/billing", "@/billing")
    assert _events(before, after, head_tsconfig=TSCONFIG, changed_tsconfig=True) == ([], [])


def test_c_the_base_side_mapping_wins_over_the_head_side():
    remapped = TSCONFIG.replace('"src/*"', '"lib/*"')
    before, after = _before("../src/billing"), _before("../src/billing", "@/billing")
    events, _findings = _events(before, after, base_tsconfig=TSCONFIG, head_tsconfig=remapped,
                                changed_tsconfig=True)
    assert events == [(UNIT, "src/billing:invoiceTotal")]
    # And the other way round: the base side maps @/ elsewhere, so nothing joins.
    assert _events(before, after, base_tsconfig=remapped, head_tsconfig=TSCONFIG,
                   changed_tsconfig=True) == ([], [])


def test_c_a_tsconfig_the_diff_deletes_is_still_the_base_side():
    before, after = _before("../src/billing"), _before("../src/billing", "@/billing")
    events, _findings = _events(before, after, base_tsconfig=TSCONFIG, changed_tsconfig=True)
    assert events == [(UNIT, "src/billing:invoiceTotal")]


def test_c_without_a_snapshot_reader_only_b_applies():
    before, after = _before("../src/billing"), _before("../src/billing", "@/billing")
    assert _events(before, after, head_tsconfig=TSCONFIG, reader=False) == ([], [])
    events, _findings = _events(_before("@/billing"), _before("@/billing", "@/billing"), reader=False)
    assert events == [(UNIT, "@/billing:invoiceTotal")]


def test_c_an_unreadable_tsconfig_leaves_b():
    before, after = _before("../src/billing"), _before("../src/billing", "@/billing")
    assert _events(before, after, head_tsconfig="{ not json") == ([], [])


@pytest.mark.parametrize("tsconfig", [TSCONFIG, None], ids=["tsconfig", "no-tsconfig"])
@pytest.mark.parametrize("base_mock", ["../src/billing", "~/billing", "../src/billing/index.ts"])
def test_a_mock_respelled_into_an_alias_is_not_new(base_mock, tsconfig):
    """Condition 2: with the tsconfig the keys are one; without it the alias
    may be the module the base side mocked, which stays silent rather than
    guessed new."""
    before = _before("@/billing", base_mock)
    after = _before("@/billing", "@/billing")
    assert _events(before, after, head_tsconfig=tsconfig) == ([], [])


def test_the_base_side_resolves_its_aliases_through_the_same_tsconfig():
    """A base mock spelled through a pattern B does not know is the module it maps to."""
    tsconfig = '{"compilerOptions": {"paths": {"billing": ["./src/billing/index.ts"]}}}'
    before = _before("../src/billing", "billing")
    after = _before("../src/billing", "../src/billing")
    assert _events(before, after, head_tsconfig=tsconfig) == ([], [])
    events, _findings = _events(before, after)
    assert events == [(UNIT, "src/billing:invoiceTotal")]


def test_an_alias_mock_beside_a_base_mock_of_another_module_is_new():
    before = _before("@/billing", "../src/db")
    after = before + 'vi.mock("@/billing", () => ({ invoiceTotal: () => 78.75 }));\n'
    events, findings = _events(before, after)
    assert events == [(UNIT, "@/billing:invoiceTotal")]
    assert findings == [("TEST_PATCHES_SUBJECT", "high")]


@pytest.mark.parametrize(("module", "other", "expected"), [
    ("src/billing", "src/billing", True),
    ("@/billing", "@/billing", True),
    ("@/billing", "src/billing", True),
    ("src/billing", "@/billing", True),
    ("@/billing", "billing", True),
    ("@/billing", "~/billing", True),
    ("@/lib/billing", "~/billing", True),
    ("@/lib/billing", "src/lib/billing", True),
    ("@/billing", "src/db", False),
    ("@/billing", "src/my-billing", False),
    ("@/lib/billing", "billing", False),
    ("src/billing", "lib/billing", False),
    # Only an alias is read as a path from some root.
    ("src/billing", "lib/c/billing", False),
])
def test_which_keys_may_name_one_module(module, other, expected):
    assert _possibly_one(module, other) is expected


@pytest.mark.parametrize("specifier", ["@acme/billing", "billing", "#billing"])
def test_a_scoped_or_bare_package_stays_third_party(specifier):
    assert _events(_before(specifier), _before(specifier, specifier), head_tsconfig=TSCONFIG) == ([], [])


@pytest.mark.parametrize("loader", ['require("@/billing")', 'await import("@/billing")'])
def test_a_module_object_loaded_through_an_alias_is_read_too(loader):
    """`require()` and `import()` bindings resolve their specifier as an import does."""
    before = (
        WITH_VI
        + "\n"
        + 'describe("billing", () => {\n'
        + '  it("computes invoice total", async () => {\n'
        + f"    const billing = {loader};\n"
        + "    const items = [{ price: 10.0, qty: 3 }, { price: 5.0, qty: 9 }];\n"
        + "    expect(billing.invoiceTotal(items)).toBe(78.75);\n"
        + "  });\n"
        + "});\n"
    )
    after = before.replace(WITH_VI, WITH_VI + 'vi.mock("../src/billing", () => ({ invoiceTotal: () => 78.75 }));\n')
    events, findings = _events(before, after, head_tsconfig=TSCONFIG)
    assert events == [(UNIT, "src/billing:invoiceTotal")]
    assert findings == [("TEST_PATCHES_SUBJECT", "high")]
    assert _events(before, after) == ([], [])


def test_jest_mock_reads_an_alias_too():
    before = _before("@/billing").replace(VITEST, "")
    after = before.replace('import { invoiceTotal }',
                           'jest.mock("@/billing", () => ({ invoiceTotal: () => 78.75 }));\nimport { invoiceTotal }', 1)
    events, findings = _events(before, after, head_tsconfig=TSCONFIG)
    assert events == [(UNIT, "src/billing:invoiceTotal")]
    assert findings == [("TEST_PATCHES_SUBJECT", "high")]


def test_the_tsconfig_is_read_once_per_analysis():
    reads = []
    snapshot = {}

    def read(path):
        reads.append(path)
        return snapshot.get(path)

    files = [f"tests/billing{n}.test.ts" for n in range(3)]
    changes = []
    for path in files:
        before, after = _before("../src/billing"), _before("../src/billing", "@/billing")
        snapshot[path] = after.encode("utf-8")
        changes.append(FileChange(path, "modified", before.encode("utf-8"), after.encode("utf-8")))
    snapshot["tsconfig.json"] = TSCONFIG.encode("utf-8")
    ir, _findings, _verdict = analyze(
        changes, Config(), Contract(), [], datetime.date(2026, 1, 1),
        root_reader=read, root_searcher=lambda needles: search_source_mapping(snapshot, needles))
    assert len(ir.globals.subject_installations) == 3
    assert reads.count("tsconfig.json") == 1
