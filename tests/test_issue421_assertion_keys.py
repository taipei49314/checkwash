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
    canonical,
    fingerprint_issue,
    fingerprint_state,
    identity_text,
    make_assertion_fingerprint,
    make_fingerprint,
)
from checkwash.ir.model import normalize_text
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
    alone = _keys("ASSERT_WEAKENED", BEFORE, _test("assert add(2, 3) >= 0"))
    beside = _keys("ASSERT_WEAKENED", _test("assert add(2, 3) == 5", "assert add(2, 3) == 5"),
                   _test("assert add(2, 3) >= 0", "assert add(2, 3) == 5"))
    assert len(alone) == len(beside) == 1 and alone != beside


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


def test_a_context_that_cannot_be_encoded_is_recorded_as_null():
    identity = assertion_identity("ASSERT_WEAKENED", PATH, "test_add", "assert x", before="assert x",
                                  after=None, kind="k", context={"a": 1, 2: "b"})
    assert assertion_key(identity) == assertion_key({**identity, "context": None})
    assert assertion_key(identity).startswith(f"ASSERT_WEAKENED/{PATH}/test_add/v2:")


def test_a_set_in_the_context_keys_the_same_under_every_hash_seed():
    # `ast.literal_eval` makes sets of literal arguments and table cells, and a
    # set's order follows the hash seed (raised by GLM, verified by Claude).
    assert canonical([{"b", "a"}, frozenset({3, 1, 2}), (b"x",)]) == [["a", "b"], [1, 2, 3], ["b'x'"]]
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
