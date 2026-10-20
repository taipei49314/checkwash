"""Content-bound keys for TEST_DISABLED (#512, round 2 of #421).

A legacy TEST_DISABLED key held the rule, path, unit and a fixed text: the
marker's name (an imperative skip's guard left out), `guard:<name>` for both
guard events, `parametrize` whatever rows went, a removed unit's assertions
through a JS matcher's `(`, and `test.focused` for any file-level focus. So one
approved skip, guard change or row deletion also covered later, different
changes to the same unit. Every shape now has a `TEST_DISABLED/path/unit/v2:`
key, built as the nine assertion-level rules' are, over an identity that holds
the legacy pre-image unchanged and the finding's shape as the event kind
(Q2). Legacy keys are retired at once: parsed, never honoured, refused by
`allow` (Q3 (a)). Pairing, move detection and finding counts do not change:
the marker identity alignment pairs on still leaves the guard out (Q1 (a),
D-019).
"""

import datetime
from collections import Counter

import pytest

import checkwash.findings as findings_module
from checkwash.allowlist import (
    AllowEntry,
    active_fingerprints,
    fingerprint_diagnostics,
    load_allowlist,
    summarize_allowlist,
)
from checkwash.change import FileChange
from checkwash.cli import main
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.detectors.test_disabled import finding_marker
from checkwash.engine import analyze
from checkwash.findings import fingerprint_issue, fingerprint_state, identity_text, make_fingerprint
from checkwash.report.sarif import _result

TODAY = datetime.date(2026, 10, 19)
BILLING = b"def total():\n    return 78.75\n"

PY_PATH = "tests/test_billing.py"
BASE = (
    "import os\nimport sys\n\nimport pytest\n\nfrom app.billing import total\n\n\n"
    "def test_total():\n    assert total() == 78.75\n"
)
# An imperative skip under a guard D6 cannot qualify, and the same skip with none.
ENV_SKIP = BASE.replace(
    "def test_total():\n",
    'def test_total():\n    if not os.environ.get("BILLING_DB"):\n        pytest.skip("needs a database")\n',
)
BARE_SKIP = BASE.replace("def test_total():\n", 'def test_total():\n    pytest.skip("needs a database")\n')
# THREATMODEL 54's two events on one guarded skip.
GUARDED = BASE.replace(
    "def test_total():\n",
    'def test_total():\n    if sys.version_info < (3, 9):\n        pytest.skip("needs 3.9")\n',
)
GUARD_REMOVED = BASE.replace("def test_total():\n", 'def test_total():\n    pytest.skip("needs 3.9")\n')
GUARD_ALWAYS = GUARDED.replace("if sys.version_info < (3, 9):", "if True:")

# Several markers of one name. Alignment pairs a skip on its name alone, so a
# skip inserted above another pairs with it and leaves that one unpaired; the
# key binds the inserted one.
VERSION_GUARD, ENV_GUARD = "sys.version_info < (3, 9)", 'not os.environ.get("BILLING_DB")'
ENV_BLOCK = f'    if {ENV_GUARD}:\n        pytest.skip("needs a database")\n'
VERSION_BLOCK = f'    if {VERSION_GUARD}:\n        pytest.skip("needs 3.9")\n'
ENV_ABOVE = GUARDED.replace("def test_total():\n", "def test_total():\n" + ENV_BLOCK)
BARE_ABOVE = GUARDED.replace("def test_total():\n", 'def test_total():\n    pytest.skip("needs a database")\n')
# An unguarded skip added above the guarded block ENV_SKIP adds.
BOTH_SKIPS = ENV_SKIP.replace("def test_total():\n", 'def test_total():\n    pytest.skip("whatever")\n')
# Two guarded skips of one name, and each guard removed in turn.
TWO_GUARDS = BASE.replace("def test_total():\n", "def test_total():\n" + VERSION_BLOCK + ENV_BLOCK)
FIRST_GUARD_REMOVED = TWO_GUARDS.replace(VERSION_BLOCK, '    pytest.skip("needs 3.9")\n')
SECOND_GUARD_REMOVED = TWO_GUARDS.replace(ENV_BLOCK, '    pytest.skip("needs a database")\n')
# A skip edited and another of its name added: by content the head holds two
# skips the base lacks for the one marker added.
EDITED = GUARDED.replace('pytest.skip("needs 3.9")', 'pytest.skip("needs Python 3.9")')
EDITED_AND_BARE = EDITED.replace("def test_total():\n", 'def test_total():\n    pytest.skip("needs a database")\n')
EDITED_AND_GUARDED = EDITED.replace("def test_total():\n", "def test_total():\n" + ENV_BLOCK)


def rows(*cells):
    return (
        "import pytest\n\nfrom app.billing import total\n\n\n"
        f'@pytest.mark.parametrize("n, expected", [{", ".join(cells)}])\n'
        "def test_total(n, expected):\n    assert total() * n == expected\n"
    )


R1, R2, R3 = "(1, 78.75)", "(2, 157.5)", "(3, 236.25)"
R1_SKIPPED = "pytest.param(1, 78.75, marks=pytest.mark.skip)"
THREE = rows(R1, R2, R3)

JS_TABLE_PATH = "tests/add.test.ts"


def js_table(*cells):
    return (
        'import { expect, test } from "vitest";\nimport { add } from "../src/add";\n\n'
        "test.each([\n" + "".join(f"  {cell},\n" for cell in cells)
        + '])("add(%i, %i) = %i", (a, b, sum) => {\n  expect(add(a, b)).toBe(sum);\n});\n'
    )


J1, J2, J3 = "[1, 2, 3]", "[2, 3, 5]", "[3, 4, 7]"

JS_UNIT_PATH = "tests/identity.test.ts"
REMOVED = "// the test was removed\n"


def js_unit(body):
    return 'test("sample", () => { ' + body + " });\n"


FOCUS_PATH = "test/billing.spec.js"
MOCHA = ('const assert = require("node:assert");\nconst { total, tax } = require("../src/value");\n'
         'describe("billing", function () {\n'
         '  it("total", function () { assert.strictEqual(total(), 78.75); });\n'
         '  it("tax", function () { assert.strictEqual(tax(), 3.75); });\n'
         '});\n')

# Pairs of changes whose findings shared one legacy key: (path, first, second),
# each change a (before, after) pair.
CASES = [
    pytest.param(PY_PATH, (BASE, ENV_SKIP), (BASE, BARE_SKIP), id="guarded-then-unguarded-skip"),
    pytest.param(PY_PATH, (GUARDED, GUARD_REMOVED), (GUARDED, GUARD_ALWAYS), id="guard-removed-then-always-true"),
    pytest.param(PY_PATH, (GUARDED, ENV_ABOVE), (GUARDED, BARE_ABOVE), id="guarded-then-unguarded-skip-above-another"),
    pytest.param(PY_PATH, (TWO_GUARDS, FIRST_GUARD_REMOVED), (TWO_GUARDS, SECOND_GUARD_REMOVED),
                 id="one-guard-removed-then-the-other"),
    pytest.param(PY_PATH, (THREE, rows(R2, R3)), (THREE, rows(R1, R3)), id="another-row-deleted"),
    pytest.param(PY_PATH, (THREE, rows(R2, R3)), (THREE, rows(R3)), id="more-rows-deleted"),
    pytest.param(PY_PATH, (THREE, rows(R2, R3)), (THREE, rows(R1_SKIPPED, R2, R3)), id="row-marked-not-deleted"),
    pytest.param(JS_TABLE_PATH, (js_table(J1, J2, J3), js_table(J2, J3)), (js_table(J1, J2, J3), js_table(J1, J3)),
                 id="another-js-table-row-deleted"),
    pytest.param(JS_UNIT_PATH, (js_unit("expect(first()).toBe(1);"), REMOVED),
                 (js_unit("expect(first()).toBe(2);"), REMOVED), id="unit-with-another-expected-value-removed"),
    pytest.param(FOCUS_PATH, (MOCHA, MOCHA.replace('describe("billing"', 'describe.only("billing"')),
                 (MOCHA, MOCHA.replace('describe("billing"', 'fdescribe("billing"')), id="another-focus-call"),
]


def _run(path, before, after, allow=()):
    _ir, findings, verdict = analyze(
        [FileChange(path, "modified", before.encode(), after.encode())], Config(), Contract(), list(allow), TODAY,
        head_reader={"app/billing.py": BILLING, "app/__init__.py": b""}.get,
    )
    return [f for f in findings if f.rule == "TEST_DISABLED"], verdict


def _entry(key, **kwargs):
    fields = dict(rule=key.split("/", 1)[0], reason="reviewed exact change", author="reviewer",
                  created="2026-10-19", expires="2026-12-01")
    fields.update(kwargs)
    return AllowEntry(key, **fields)


def _identities(monkeypatch):
    """The identity behind each key computed while the test runs."""
    seen = {}
    real = findings_module.assertion_identity

    def record(*args, **kwargs):
        identity = real(*args, **kwargs)
        seen[findings_module.assertion_key(identity)] = identity
        return identity

    monkeypatch.setattr(findings_module, "assertion_identity", record)
    return seen


# --- Q2: another change of the same shape is another key -----------------------------

@pytest.mark.parametrize("path, first, second", CASES)
def test_another_change_that_shared_the_legacy_key_is_another_key(path, first, second, monkeypatch):
    identities = _identities(monkeypatch)
    (one,), _verdict = _run(path, *first)
    (two,), _verdict = _run(path, *second)
    assert one.shape == two.shape
    assert one.fingerprint != two.fingerprint
    for finding in (one, two):
        assert finding.fingerprint.startswith(f"TEST_DISABLED/{path}/{finding.unit or '<file>'}/v2:")
        assert fingerprint_state(finding.fingerprint) == "supported"
    # One legacy key used to name both.
    assert identities[one.fingerprint]["legacy"] == identities[two.fingerprint]["legacy"]
    assert identities[one.fingerprint]["kind"] == one.shape


@pytest.mark.parametrize("path, first, second", CASES)
def test_the_reviewed_change_is_exempt_and_another_still_blocks(path, first, second):
    (hit,), _verdict = _run(path, *first)
    allow = [_entry(hit.fingerprint)]
    (exempt,), _verdict = _run(path, *first, allow=allow)
    assert exempt.allowlisted and "ALLOWLISTED" in exempt.deescalators
    (later,), _verdict = _run(path, *second, allow=allow)
    assert not later.allowlisted and later.severity == "high"


def test_reformatting_and_moving_the_lines_keep_the_key():
    (hit,), _verdict = _run(PY_PATH, BASE, ENV_SKIP)
    reformatted = ENV_SKIP.replace('if not os.environ.get("BILLING_DB"):', 'if not os.environ.get( "BILLING_DB" ):')
    reformatted = reformatted.replace('pytest.skip("needs a database")', 'pytest.skip( "needs a database" )')
    shifted = "# a comment that moves every line\n\n"
    (again,), _verdict = _run(PY_PATH, shifted + BASE, shifted + reformatted)
    assert again.fingerprint == hit.fingerprint


# --- Q2: what each shape binds -------------------------------------------------------

def test_a_marker_added_binds_its_complete_text_and_its_guard(monkeypatch):
    identities = _identities(monkeypatch)
    (guarded,), _verdict = _run(PY_PATH, BASE, ENV_SKIP)
    (bare,), _verdict = _run(PY_PATH, BASE, BARE_SKIP)
    one, two = identities[guarded.fingerprint], identities[bare.fingerprint]
    assert one["scheme"] == "checkwash/assertion-fingerprint/v2"
    assert one["legacy"] == two["legacy"] == f"TEST_DISABLED/{PY_PATH}/test_total/pytest.skip"
    assert one["kind"] == two["kind"] == "marker_added"
    assert one["after"] == two["after"] == identity_text('pytest.skip("needs a database")')
    assert one["context"] == {"guard": identity_text('not os.environ.get("BILLING_DB")')}
    assert two["context"] == {"guard": None}
    assert (one["before"], one["ordinal"], one["count"]) == (None, None, None)
    assert not {"span", "line", "message", "severity"} & set(one)


def test_a_guard_event_binds_the_guard_before_and_after(monkeypatch):
    identities = _identities(monkeypatch)
    (gone,), _verdict = _run(PY_PATH, GUARDED, GUARD_REMOVED)
    (always,), _verdict = _run(PY_PATH, GUARDED, GUARD_ALWAYS)
    one, two = identities[gone.fingerprint], identities[always.fingerprint]
    assert one["legacy"] == two["legacy"] == f"TEST_DISABLED/{PY_PATH}/test_total/guard:pytest.skip"
    assert one["kind"] == two["kind"] == "guard_weakened"
    assert (one["before"], one["after"]) == (identity_text("sys.version_info < (3, 9)"), None)
    assert (two["before"], two["after"]) == (identity_text("sys.version_info < (3, 9)"), "True")


def test_a_guard_event_binds_what_every_marker_of_its_name_ran_under(monkeypatch):
    # The message, and the guard before and after, name the first base
    # condition whichever guard was removed; the conditions tell the two apart.
    identities = _identities(monkeypatch)
    (first,), _verdict = _run(PY_PATH, TWO_GUARDS, FIRST_GUARD_REMOVED)
    (second,), _verdict = _run(PY_PATH, TWO_GUARDS, SECOND_GUARD_REMOVED)
    one, two = identities[first.fingerprint], identities[second.fingerprint]
    assert (one["before"], one["after"]) == (two["before"], two["after"]) == (identity_text(VERSION_GUARD), None)
    both = Counter([identity_text(VERSION_GUARD), identity_text(ENV_GUARD)])
    assert Counter(one["context"]["conditions"]["before"]) == Counter(two["context"]["conditions"]["before"]) == both
    assert Counter(one["context"]["conditions"]["after"]) == Counter([None, identity_text(ENV_GUARD)])
    assert Counter(two["context"]["conditions"]["after"]) == Counter([identity_text(VERSION_GUARD), None])


def _unit_and_findings(path, before, after, allow=()):
    """The unit `test_total` of the analysed change, its TEST_DISABLED findings and the verdict."""
    ir, findings, verdict = analyze(
        [FileChange(path, "modified", before.encode(), after.encode())], Config(), Contract(), list(allow), TODAY,
        head_reader={"app/billing.py": BILLING, "app/__init__.py": b""}.get,
    )
    (unit,) = [u for file in ir.files for u in file.units if u.qualname == "test_total"]
    return unit, [f for f in findings if f.rule == "TEST_DISABLED"], verdict


def test_an_unguarded_skip_added_beside_a_reviewed_guarded_one_still_blocks(monkeypatch):
    # Both skips are added. Each finding binds its own skip, so the approval
    # of the guarded one covers that finding alone.
    identities = _identities(monkeypatch)
    (reviewed,), _verdict = _run(PY_PATH, BASE, ENV_SKIP)
    unit, both, _verdict = _unit_and_findings(PY_PATH, BASE, BOTH_SKIPS)
    assert len(both) == 2 and len({f.fingerprint for f in both}) == 2
    assert [f.fingerprint for f in both].count(reviewed.fingerprint) == 1
    (unguarded,) = [f for f in both if f.fingerprint != reviewed.fingerprint]
    assert identities[unguarded.fingerprint]["after"] == identity_text('pytest.skip("whatever")')
    assert identities[unguarded.fingerprint]["context"] == {"guard": None}
    assert [finding_marker(f, unit) for f in both] == ["pytest.skip", "pytest.skip"]
    _unit, exempt, verdict = _unit_and_findings(PY_PATH, BASE, BOTH_SKIPS, allow=[_entry(reviewed.fingerprint)])
    (still,) = [f for f in exempt if not f.allowlisted]
    assert len(exempt) == 2 and still.fingerprint == unguarded.fingerprint and still.severity == "high"
    assert verdict == "block"


def test_a_skip_inserted_above_another_binds_its_own_text_and_guard(monkeypatch):
    identities = _identities(monkeypatch)
    (alone,), _verdict = _run(PY_PATH, BASE, ENV_SKIP)
    (guarded,), _verdict = _run(PY_PATH, GUARDED, ENV_ABOVE)
    (bare,), _verdict = _run(PY_PATH, GUARDED, BARE_ABOVE)
    one, two = identities[guarded.fingerprint], identities[bare.fingerprint]
    assert one["after"] == two["after"] == identity_text('pytest.skip("needs a database")')
    assert one["context"] == {"guard": identity_text(ENV_GUARD)}
    assert two["context"] == {"guard": None}
    # The key of that skip, wherever it is added.
    assert guarded.fingerprint == alone.fingerprint


def test_markers_that_cannot_be_told_apart_bind_every_marker_of_the_unit(monkeypatch):
    identities = _identities(monkeypatch)
    unit, (bare,), _verdict = _unit_and_findings(PY_PATH, GUARDED, EDITED_AND_BARE)
    (guarded,), _verdict = _run(PY_PATH, GUARDED, EDITED_AND_GUARDED)
    assert bare.fingerprint != guarded.fingerprint
    identity = identities[bare.fingerprint]
    assert identity["legacy"] == f"TEST_DISABLED/{PY_PATH}/test_total/pytest.skip"
    assert (identity["kind"], identity["after"]) == ("marker_added", None)
    markers = identity["context"]["unit_markers"]
    version = identity_text(VERSION_GUARD)
    assert markers["before"] == [["pytest.skip", identity_text('pytest.skip("needs 3.9")'), version]]
    assert Counter(map(tuple, markers["after"])) == Counter([
        ("pytest.skip", identity_text('pytest.skip("needs a database")'), None),
        ("pytest.skip", identity_text('pytest.skip("needs Python 3.9")'), version),
    ])
    assert finding_marker(bare, unit) == "pytest.skip"


def test_rows_removed_bind_which_rows_went_and_the_live_counts(monkeypatch):
    identities = _identities(monkeypatch)
    (deleted,), _verdict = _run(PY_PATH, THREE, rows(R2, R3))
    (marked,), _verdict = _run(PY_PATH, THREE, rows(R1_SKIPPED, R2, R3))
    row = {"names": ["n", "expected"], "cells": ["1", "78.75"]}
    one, two = identities[deleted.fingerprint], identities[marked.fingerprint]
    assert one["legacy"] == two["legacy"] == f"TEST_DISABLED/{PY_PATH}/test_total/parametrize"
    assert one["context"] == {"deleted": [row], "disabled": [], "live_before": 3, "live_after": 2}
    assert two["context"] == {"deleted": [], "disabled": [row], "live_before": 3, "live_after": 2}


def test_a_removed_unit_binds_its_own_complete_assertions(monkeypatch):
    identities = _identities(monkeypatch)
    (gone,), _verdict = _run(JS_UNIT_PATH, js_unit("expect(first()).toBe(1); expect(second()).toEqual(2);"), REMOVED)
    identity = identities[gone.fingerprint]
    assert identity["legacy"] == f"TEST_DISABLED/{JS_UNIT_PATH}/sample/expect(first()).toBe(expect(second()).toEqual("
    assert identity["kind"] == "unit_removed"
    assert identity["context"] == {"assertions": ["expect(first()).toBe(1)", "expect(second()).toEqual(2)"]}


def test_a_file_level_focus_binds_its_call(monkeypatch):
    identities = _identities(monkeypatch)
    (focus,), _verdict = _run(FOCUS_PATH, MOCHA, MOCHA.replace('describe("billing"', 'describe.only("billing"'))
    assert focus.unit is None and focus.fingerprint.startswith(f"TEST_DISABLED/{FOCUS_PATH}/<file>/v2:")
    identity = identities[focus.fingerprint]
    assert identity["legacy"] == f"TEST_DISABLED/{FOCUS_PATH}/<file>/test.focused"
    assert (identity["after"], identity["kind"]) == ("describe.only", "marker_added")


# --- Q3 (a): legacy keys are retired -------------------------------------------------

@pytest.mark.parametrize("unit, legacy_text", [
    ("test_total", "pytest.skip"),
    ("test_total", "guard:pytest.skip"),
    ("test_total", "parametrize"),
    ("<file>", "test.focused"),
])
def test_a_legacy_test_disabled_key_is_retired(unit, legacy_text):
    legacy = make_fingerprint("TEST_DISABLED", PY_PATH, unit, legacy_text)
    assert fingerprint_state(legacy) == "retired"
    assert "#512" in fingerprint_issue(legacy) and "retired" in fingerprint_issue(legacy)
    assert active_fingerprints([_entry(legacy)], TODAY) == set()


def test_the_ledger_counts_a_retired_test_disabled_key_and_never_honours_it():
    legacy = make_fingerprint("TEST_DISABLED", PY_PATH, "test_total", "pytest.skip")
    data = (
        '[[allow]]\nfingerprint = "' + legacy + '"\nrule = "TEST_DISABLED"\nreason = "old"\n'
        'author = "reviewer"\ncreated = "2026-10-01"\nexpires = "2026-12-01"\n'
    ).encode()
    summary = summarize_allowlist(data, TODAY)
    assert (summary.entries, summary.active, summary.retired) == (1, 0, 1)
    entries, error = load_allowlist(data)
    assert error is None and len(entries) == 1
    assert "#512" in fingerprint_diagnostics(entries)[0]
    (hit,), _verdict = _run(PY_PATH, BASE, BARE_SKIP, allow=entries)
    assert not hit.allowlisted and hit.fingerprint != legacy


def test_allow_refuses_a_legacy_test_disabled_key(tmp_path, capsys):
    legacy = make_fingerprint("TEST_DISABLED", PY_PATH, "test_total", "pytest.skip")
    assert main(["allow", legacy, "--reason", "copied from an old report", "--repo", str(tmp_path)]) == 2
    assert "#512" in capsys.readouterr().err
    assert not (tmp_path / ".greenwash").exists() and not (tmp_path / ".checkwash").exists()


def test_a_content_bound_test_disabled_key_is_validated_like_the_other_v2_keys():
    (hit,), _verdict = _run(PY_PATH, BASE, BARE_SKIP)
    key = hit.fingerprint
    assert fingerprint_issue(key) is None and active_fingerprints([_entry(key)], TODAY) == {key}
    assert "does not match" in fingerprint_issue(key, "ASSERT_REMOVED")
    assert active_fingerprints([_entry(key, rule="ASSERT_REMOVED")], TODAY) == set()
    assert fingerprint_state(key[:-1]) == fingerprint_state(key + "a") == "invalid"


def test_sarif_reports_a_test_disabled_key_as_content_bound():
    (hit,), _verdict = _run(PY_PATH, BASE, BARE_SKIP)
    assert _result(hit, None)["partialFingerprints"] == {"checkwash/v2": hit.fingerprint}
