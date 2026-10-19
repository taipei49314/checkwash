"""Content-bound keys for the assertion-level oracle rules (#421).

A legacy key held the rule, path, unit and the old assertion's text, so one
exemption for `assert add(2, 3) == 5` -> `>= 0` also covered every later
rewrite of the same line. The v2 key `rule/path/unit/v2:<64hex>` is the full
SHA256 of an identity that holds the legacy pre-image unchanged, the complete
before and after texts, the event kind, the before side's ordinal and count
of that text, and the rule's context (Q2 (b), Q3 (b)). Legacy keys of these
rules are retired at once: parsed, never honoured, refused by `allow`
(Q4 (a)).
"""

import datetime
import os
import pathlib
import subprocess
import sys

import pytest

import checkwash.findings as findings_module
from checkwash.allowlist import AllowEntry, active_fingerprints, summarize_allowlist
from checkwash.change import FileChange
from checkwash.cli import main
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.findings import (
    ASSERTION_FINGERPRINT_RULES,
    assertion_identity,
    assertion_key,
    assertion_position,
    canonical,
    fingerprint_issue,
    fingerprint_state,
    identity_text,
    make_assertion_fingerprint,
    make_fingerprint,
)
from checkwash.ir.model import Assertion, UnitSide, normalize_text
from checkwash.report.sarif import _result

TODAY = datetime.date(2026, 9, 6)
PATH = "tests/test_calc.py"


def _test(*lines, prefix=""):
    body = "".join(f"    {line}\n" for line in lines)
    return f"{prefix}import pytest\n\nfrom calc import add, double\n\n\ndef test_add():\n{body}".encode()


BEFORE = _test("assert add(2, 3) == 5")


def _run(before, after, allow=()):
    return analyze([FileChange(PATH, "modified", before, after)], Config(), Contract(), list(allow), TODAY)


def _hits(rule, before, after, allow=()):
    _ir, findings, verdict = _run(before, after, allow)
    return [f for f in findings if f.rule == rule], verdict


def _keys(rule, before, after):
    return [f.fingerprint for f in _hits(rule, before, after)[0]]


def _entry(key, **kwargs):
    fields = dict(rule=key.split("/", 1)[0], reason="reviewed exact change", author="reviewer",
                  created="2026-09-02", expires="2026-12-01")
    fields.update(kwargs)
    return AllowEntry(key, **fields)


def _identities(monkeypatch):
    seen = []
    real = findings_module.assertion_identity

    def record(*args, **kwargs):
        seen.append(real(*args, **kwargs))
        return seen[-1]

    monkeypatch.setattr(findings_module, "assertion_identity", record)
    return seen


# --- Q2 (b): another after state on the same before is another key ------------------

@pytest.mark.parametrize("rule,before,first,second", [
    ("ASSERT_WEAKENED", BEFORE, _test("assert add(2, 3) >= 0"), _test("assert add(2, 3)")),
    ("EXPECTED_VALUE_CHANGED", BEFORE, _test("assert add(2, 3) == 6"), _test("assert add(2, 3) == 7")),
    ("TOLERANCE_LOOSENED", _test("assert add(0.1, 0.2) == pytest.approx(0.3, rel=1e-9)"),
     _test("assert add(0.1, 0.2) == pytest.approx(0.3, rel=1e-3)"),
     _test("assert add(0.1, 0.2) == pytest.approx(0.3, rel=1e-2)")),
    ("EXPECTATION_DEFINITION_CHANGED", _test("assert double(2) == EXPECTED", prefix="EXPECTED = 4\n"),
     _test("assert double(2) == EXPECTED", prefix="EXPECTED = 5\n"),
     _test("assert double(2) == EXPECTED", prefix="EXPECTED = 6\n")),
])
def test_another_rewrite_of_the_same_line_is_another_key(rule, before, first, second, monkeypatch):
    identities = _identities(monkeypatch)
    one, two = _keys(rule, before, first), _keys(rule, before, second)
    assert one and two and not set(one) & set(two)
    assert all(key.startswith(f"{rule}/{PATH}/test_add/v2:") for key in one + two)
    assert all(fingerprint_state(key) == "supported" for key in one + two)
    # The legacy pre-image, which alone made the old key, is the same for both.
    legacy = {i["legacy"] for i in identities if assertion_key(i) in one + two}
    assert len(legacy) == 1 and legacy.pop().startswith(f"{rule}/{PATH}/test_add/")


def test_the_reviewed_rewrite_is_exempt_and_another_still_blocks():
    reviewed = _test("assert add(2, 3) >= 0")
    (hit,), _verdict = _hits("ASSERT_WEAKENED", BEFORE, reviewed)
    allow = [_entry(hit.fingerprint)]
    (exempt,), _verdict = _hits("ASSERT_WEAKENED", BEFORE, reviewed, allow)
    assert exempt.allowlisted and "ALLOWLISTED" in exempt.deescalators
    (later,), verdict = _hits("ASSERT_WEAKENED", BEFORE, _test("assert add(2, 3)"), allow)
    assert not later.allowlisted and later.severity == "high" and verdict == "block"


def test_reformatting_and_moving_the_line_keep_the_key():
    key = _keys("ASSERT_WEAKENED", BEFORE, _test("assert add(2, 3) >= 0"))
    assert _keys("ASSERT_WEAKENED", BEFORE, _test("assert add(2,3)>=0")) == key
    shifted = "# a comment that moves every line\n\n"
    assert _keys("ASSERT_WEAKENED", _test("assert add(2, 3) == 5", prefix=shifted),
                 _test("assert add(2, 3) >= 0", prefix=shifted)) == key


def test_two_identical_assertions_are_two_approvals(monkeypatch):
    identities = _identities(monkeypatch)
    twice = _test("assert add(2, 3) == 5", "assert add(2, 3) == 5")
    both = _keys("ASSERT_WEAKENED", twice, _test("assert add(2, 3) >= 0", "assert add(2, 3) >= 0"))
    assert len(both) == len(set(both)) == 2
    # One legacy key used to name both.
    assert len({i["legacy"] for i in identities if assertion_key(i) in both}) == 1


def test_the_count_is_part_of_the_identity():
    # The same texts at ordinal 0 on both sides: only the count tells them apart.
    alone = _keys("ASSERT_WEAKENED", BEFORE, _test("assert add(2, 3) >= 0"))
    both = _keys("ASSERT_WEAKENED", _test("assert add(2, 3) == 5", "assert add(2, 3) == 5"),
                 _test("assert add(2, 3) >= 0", "assert add(2, 3) >= 0"))
    assert len(alone) == 1 and len(both) == 2 and not set(alone) & set(both)


def test_identical_copies_are_ordered_as_the_side_holds_them():
    # Own and same-file assertions in source order, copies of one helper line
    # by call site, then other files: never re-sorted by span, which mixes files
    # and cannot tell copies apart (raised by a review of #477).
    own = Assertion("a0", "compare_eq", 90, "assert r == 200", (400, 415), left="r")
    first = Assertion("a1", "compare_eq", 90, "assert r == 200", (90, 105), left="r", inherited=True)
    second = Assertion("a2", "compare_eq", 90, "assert r == 200", (90, 105), left="r", inherited=True)
    side = UnitSide(span=(0, 500), assertions=[own, first, second])
    assert [assertion_position(side, a) for a in (own, first, second)] == [(0, 3), (1, 3), (2, 3)]
    assert assertion_position(side, Assertion("a3", "compare_eq", 90, "assert s == 1", (0, 9))) == (None, None)
    assert assertion_position(None, own) == (None, None)


def test_a_removed_assertion_is_keyed_by_its_place_among_copies():
    twice = _test("assert add(2, 3) == 5", "assert add(2, 3) == 5", "assert add(1, 1) == 2")
    keys = _keys("ASSERT_REMOVED", twice, _test("assert add(1, 1) == 2"))
    assert len(keys) == 2 and len(set(keys)) == 2


# --- Q4 (a): legacy keys are retired -------------------------------------------------

@pytest.mark.parametrize("rule", sorted(ASSERTION_FINGERPRINT_RULES))
def test_a_legacy_key_of_a_migrated_rule_is_retired(rule):
    legacy = make_fingerprint(rule, PATH, "test_add", "assert add(2, 3) == 5")
    assert fingerprint_state(legacy) == "retired"
    assert "#421" in fingerprint_issue(legacy) and "retired" in fingerprint_issue(legacy)
    assert active_fingerprints([_entry(legacy)], TODAY) == set()


@pytest.mark.parametrize("rule", sorted(ASSERTION_FINGERPRINT_RULES))
def test_a_content_bound_key_is_validated_like_the_other_v2_keys(rule):
    key = make_assertion_fingerprint(rule, PATH, "test_add", "assert add(2, 3) == 5",
                                     before="assert add(2, 3) == 5", after="assert add(2, 3) >= 0", kind="k")
    assert fingerprint_issue(key) is None and active_fingerprints([_entry(key)], TODAY) == {key}
    other = next(r for r in sorted(ASSERTION_FINGERPRINT_RULES) if r != rule)
    assert "does not match" in fingerprint_issue(key, other)
    assert active_fingerprints([_entry(key, rule=other)], TODAY) == set()
    assert fingerprint_state(key[:-1]) == fingerprint_state(key + "a") == "invalid"
    assert fingerprint_issue(key.upper()) is not None


def test_the_ledger_counts_a_retired_assertion_key():
    legacy = make_fingerprint("ASSERT_WEAKENED", PATH, "test_add", "assert add(2, 3) == 5")
    data = (
        '[[allow]]\nfingerprint = "' + legacy + '"\nrule = "ASSERT_WEAKENED"\nreason = "old"\n'
        'author = "reviewer"\ncreated = "2026-09-02"\nexpires = "2026-12-01"\n'
    ).encode()
    summary = summarize_allowlist(data, TODAY)
    assert (summary.entries, summary.active, summary.retired) == (1, 0, 1)
    (hit,), verdict = _hits("ASSERT_WEAKENED", BEFORE, _test("assert add(2, 3) >= 0"), [_entry(legacy)])
    assert not hit.allowlisted and verdict == "block"


def test_allow_refuses_a_legacy_assertion_key(tmp_path, capsys):
    legacy = make_fingerprint("ASSERT_WEAKENED", PATH, "test_add", "assert add(2, 3) == 5")
    assert main(["allow", legacy, "--reason", "copied from an old report", "--repo", str(tmp_path)]) == 2
    assert "#421" in capsys.readouterr().err
    assert not (tmp_path / ".greenwash").exists()


def test_a_future_created_content_bound_key_is_still_capped():
    (hit,), _verdict = _hits("ASSERT_WEAKENED", BEFORE, _test("assert add(2, 3) >= 0"))
    entry = _entry(hit.fingerprint, created="2030-01-01", expires="2030-06-01")
    data = (
        "[[allow]]\n" + "".join(f'{k} = "{v}"\n' for k, v in vars(entry).items())
    ).encode()
    summary = summarize_allowlist(data, TODAY)
    assert (summary.active, summary.over_cap) == (0, 1)
    (again,), verdict = _hits("ASSERT_WEAKENED", BEFORE, _test("assert add(2, 3) >= 0"), [entry])
    assert not again.allowlisted and verdict == "block"


def test_a_hand_edited_expiry_past_the_cap_is_not_honoured():
    """THREATMODEL row 39 in its own spelling: an expiry hand-edited past the cap (#501).

    `created` 2026-03-01 is well before TODAY, and the default `expires`
    2026-12-01 is 275 days after it but 86 days after TODAY. So the entry
    would be honoured if the cap were not enforced on read, or if it were
    anchored at today alone. The same key under the cap is honoured, so the
    block is the cap's.
    """
    reviewed = _test("assert add(2, 3) >= 0")
    (hit,), _verdict = _hits("ASSERT_WEAKENED", BEFORE, reviewed)
    (exempt,), _verdict = _hits("ASSERT_WEAKENED", BEFORE, reviewed, [_entry(hit.fingerprint)])
    assert exempt.allowlisted
    entry = _entry(hit.fingerprint, created="2026-03-01")
    assert entry.expires == "2026-12-01"
    data = (
        "[[allow]]\n" + "".join(f'{k} = "{v}"\n' for k, v in vars(entry).items())
    ).encode()
    summary = summarize_allowlist(data, TODAY)
    assert (summary.active, summary.over_cap) == (0, 1)
    (again,), verdict = _hits("ASSERT_WEAKENED", BEFORE, reviewed, [entry])
    assert not again.allowlisted and verdict == "block"


# --- Q3 (b): what the identity holds ---------------------------------------------------

def test_the_identity_holds_the_legacy_pre_image_and_both_texts(monkeypatch):
    identities = _identities(monkeypatch)
    (hit,), _verdict = _hits("ASSERT_WEAKENED", BEFORE, _test("assert add(2, 3) >= 0"))
    identity = next(i for i in identities if assertion_key(i) == hit.fingerprint)
    assert identity["scheme"] == "checkwash/assertion-fingerprint/v2"
    assert identity["legacy"] == f"ASSERT_WEAKENED/{PATH}/test_add/assertadd(2,3)==5"
    assert hit.fingerprint.rsplit("/", 1)[0] == make_fingerprint(
        "ASSERT_WEAKENED", PATH, "test_add", "assert add(2, 3) == 5").rsplit("/", 1)[0]
    assert (identity["before"], identity["after"]) == ("assertadd(2,3)==5", "assertadd(2,3)>=0")
    assert (identity["ordinal"], identity["count"]) == (0, 1)
    assert not {"span", "line", "message", "severity", "strength"} & set(identity)


def test_template_literal_whitespace_is_part_of_the_identity():
    assert normalize_text("expect(x).toBe(`a  b`)") == normalize_text("expect(x).toBe(`a b`)")
    assert identity_text("expect(x).toBe(`a  b`)") != identity_text("expect(x).toBe(`a b`)")
    assert identity_text("expect( x ).toBe(`a b`)") == identity_text("expect(x).toBe(`a b`)")
    assert identity_text('assert x == "a  b"') == normalize_text('assert x == "a  b"')
    assert identity_text(None) is None
    # The code of a `${...}` is code (raised by a review of #477).
    assert identity_text("expect(x).toBe(`a ${ b + c } d`)") == identity_text("expect(x).toBe(`a ${b+c} d`)")
    assert identity_text("expect(x).toBe(`a ${b} d`)") != identity_text("expect(x).toBe(`a  ${b} d`)")
    assert identity_text("t(`x ${ `y ${ z }` } w`)") == identity_text("t(`x ${`y ${z}`} w`)")
    assert identity_text("t(`${ {a: 1}.a }`)") == identity_text("t(`${{a:1}.a}`)")


def test_a_unit_named_with_a_slash_keeps_a_valid_key():
    # A JS unit is the raw test title (raised by a review of #477).
    for unit in ("GET /", "/", "a/b", "redirects to /"):
        key = make_assertion_fingerprint("ASSERT_WEAKENED", "test/app.test.js", unit, "expect(status()).toBe(",
                                         before="expect(status()).toBe(200)", after="expect(status()).toBeTruthy()",
                                         kind="strength")
        assert fingerprint_state(key) == "supported", key
        assert active_fingerprints([_entry(key)], TODAY) == {key}
    assert fingerprint_state("ASSERT_WEAKENED/a.py/v2:" + "0" * 64) == "invalid"

    def source(body):
        return ('test("GET /", () => { ' + body + " });\n").encode()

    _ir, findings, _verdict = analyze(
        [FileChange("tests/app.test.ts", "modified", source("expect(status()).toBe(200);"),
                    source("expect(status()).toBeTruthy();"))],
        Config(), Contract(), [], TODAY)
    hit, = [f for f in findings if f.rule == "ASSERT_WEAKENED"]
    assert hit.unit == "GET /" and fingerprint_state(hit.fingerprint) == "supported"


def test_a_tolerance_change_is_keyed_by_the_assertion_that_changed(monkeypatch):
    # The unchanged `places=2` beside it records a bare `2` as well (raised by a
    # review of #477): the change is matched as alignment records it.
    identities = _identities(monkeypatch)
    head = "import unittest\n\nfrom calc import a, b\n\n\nclass T(unittest.TestCase):\n    def test_t(self):\n"
    before = head + ("        self.assertAlmostEqual(a(), 1.0, places=2)\n"
                     "        self.assertAlmostEqual(b(), 2.0, places=2)\n")
    after = before.replace("2.0, places=2", "2.0, delta=2")
    _ir, findings, _verdict = analyze([FileChange(PATH, "modified", before.encode(), after.encode())],
                                      Config(), Contract(), [], TODAY)
    hit, = [f for f in findings if f.rule == "TOLERANCE_LOOSENED"]
    identity = next(i for i in identities if assertion_key(i) == hit.fingerprint)
    assert identity["before"] == identity_text("self.assertAlmostEqual(b(), 2.0, places=2)")
    assert identity["after"] == identity_text("self.assertAlmostEqual(b(), 2.0, delta=2)")


def test_a_context_that_cannot_be_encoded_is_recorded_as_null():
    loop = []
    loop.append(loop)
    identity = assertion_identity("ASSERT_WEAKENED", PATH, "test_add", "assert x", before="assert x",
                                  after=None, kind="k", context=loop)
    assert assertion_key(identity) == assertion_key({**identity, "context": None})
    assert assertion_key(identity).startswith(f"ASSERT_WEAKENED/{PATH}/test_add/v2:")


def test_a_set_in_the_context_keys_the_same_under_every_hash_seed():
    # `ast.literal_eval` makes sets of literal arguments and table cells, and a
    # set's order follows the hash seed (raised by GLM, verified by Claude).
    assert canonical([{"b", "a"}, frozenset({3, 1, 2}), (b"x",)]) == [["a", "b"], [1, 2, 3], ["b'x'"]]
    # A key that is not text is written as json.dumps writes an int key.
    assert canonical({1: "a", (1, 2): "b", None: "c"}) == {"1": "a", "[1, 2]": "b", "null": "c"}
    snippet = (
        "import sys; sys.path.insert(0, 'src');"
        "from checkwash.findings import assertion_identity, assertion_key;"
        "print(assertion_key(assertion_identity('SUBJECT_INPUT_CHANGED', 'tests/test_calc.py', 'test_add', 'x',"
        " before='x', after='y', kind='input_changed',"
        " context=[['argument 0', {'d', 'c', 'b', 'a'}, frozenset({'f', 'e'})]])))"
    )
    keys = set()
    for seed in ("0", "1", "42", "12345", "99999"):
        proc = subprocess.run([sys.executable, "-c", snippet], capture_output=True,
                              cwd=str(pathlib.Path(__file__).resolve().parent.parent),
                              env={**os.environ, "PYTHONHASHSEED": seed})
        assert proc.returncode == 0, proc.stderr
        keys.add(proc.stdout.decode().strip())
    assert len(keys) == 1
    assert keys.pop().startswith("SUBJECT_INPUT_CHANGED/tests/test_calc.py/test_add/v2:")


def test_sarif_reports_an_assertion_key_as_content_bound():
    (hit,), _verdict = _hits("ASSERT_WEAKENED", BEFORE, _test("assert add(2, 3) >= 0"))
    assert _result(hit, None)["partialFingerprints"] == {"checkwash/v2": hit.fingerprint}
