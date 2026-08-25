"""`ORACLE_RULES` decides what can block, and nothing pinned it.

Found during the 86a promotion round (2026-08-25): `grep -rn ORACLE_RULES
tests/` returned nothing — the set could be edited in either direction with
all 463 tests green, which is how SPEC §4 carried "outside `ORACLE_RULES`,
cannot gate" about a rule for six days after measurement said otherwise, and
how the detector's base severity drifted below the "every finding is `warn`"
sentence in the same frozen document without anything going red.

Three pins, weakest to strongest:

- every member names a rule that exists, because membership of a misspelled
  name silently does nothing;
- no §4 row of a member claims the rule cannot gate;
- the membership itself is frozen here, so changing what can block is a
  visible edit to a test file and not a quiet one to a policy set.
"""

import pathlib
import re

from greenwash.detectors import REGISTRY
from greenwash.gating import ORACLE_RULES

SPEC = pathlib.Path(__file__).resolve().parents[1] / "SPEC.md"

# The one conditional member: BROAD_EXCEPT_ADDED joins the oracle path only
# for test/conftest files, in code, and is deliberately not in the set.
FROZEN = {
    "ASSERT_REMOVED",
    "ASSERT_SUBSTITUTED",
    "ASSERT_WEAKENED",
    "TEST_DISABLED",
    "TOLERANCE_LOOSENED",
    "EXPECTED_VALUE_CHANGED",
    "EXPECTED_VALUE_DERIVED",
    "SUBJECT_NORMALIZED",
    "EXPECTED_VALUE_HARDCODED",
    "CONFTEST_PATCHES_PROD",
    "TEST_PATCHES_SUBJECT",
    "EXPECTATION_DEFINITION_CHANGED",
}


def _rule_rows() -> dict[str, str]:
    text = SPEC.read_text(encoding="utf-8")
    start = text.index("## 4. Rule IDs (frozen)")
    section = text[start : text.index("\n## ", start + 1)]
    rows = {}
    for line in section.splitlines():
        m = re.match(r"^\|\s*`(\w+)`\s*\|(.+)\|\s*$", line)
        if m:
            rows[m.group(1)] = m.group(2)
    return rows


def test_every_member_is_a_real_rule():
    ghosts = ORACLE_RULES - set(REGISTRY)
    assert not ghosts, (
        f"ORACLE_RULES names rules that do not exist: {sorted(ghosts)}. "
        "A misspelled member escalates nothing and fails nothing."
    )


def test_membership_is_frozen_here():
    assert ORACLE_RULES == FROZEN, (
        "ORACLE_RULES changed. That is a policy decision about what can "
        "block: update this pin in the same commit, with the fixture and "
        "ledger changes the round requires — not as a side effect."
    )


def test_no_member_row_claims_it_cannot_gate():
    rows = _rule_rows()
    liars = [
        rule
        for rule in sorted(ORACLE_RULES)
        if rule in rows
        and ("cannot gate" in rows[rule] or "outside `ORACLE_RULES`" in rows[rule])
    ]
    assert not liars, (
        f"SPEC §4 says these ORACLE_RULES members cannot gate: {liars}. "
        "One of the two documents is wrong, and both are frozen."
    )
