"""SPEC §2's role table must be the role table the engine actually uses.

It drifted once already: the 2026-08-02 audit added `pytest.ini`, `tox.ini`,
`setup.cfg` and `**/pyproject.toml` to the `ci` role in code, the SPEC kept
listing three globs, and the rule row further down the same file described the
new behaviour — so the document disagreed with itself for five days. This is
the same failure the STATE table now has a test for, in the file that calls
itself the judge.
"""

import pathlib
import re

from checkwash.config import DEFAULT_ROLES
from checkwash.detectors import REGISTRY

SPEC = pathlib.Path(__file__).resolve().parents[1] / "SPEC.md"

_COUNT_WORDS = {
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20, "twenty-one": 21, "twenty-two": 22,
    "twenty-three": 23, "twenty-four": 24, "twenty-five": 25,
}


def _rule_section() -> str:
    text = SPEC.read_text(encoding="utf-8")
    start = text.index("## 4. Rule IDs (frozen)")
    return text[start : text.index("\n## ", start + 1)]


def _table_roles() -> dict[str, list[str]]:
    """The table under `## 2. File roles`, and only that one."""
    text = SPEC.read_text(encoding="utf-8")
    start = text.index("## 2. File roles")
    section = text[start : text.index("\n## ", start + 1)]
    rows = {}
    for line in section.splitlines():
        m = re.match(r"^\|\s*(\w+)\s*\|(.+?)\|\s*$", line)
        if not m or m.group(1) in ("role", "prod"):
            continue
        globs = re.findall(r"`([^`]+)`", m.group(2))
        if globs:
            rows.setdefault(m.group(1), globs)
    return rows


def test_spec_role_table_matches_the_engine():
    table = _table_roles()
    assert set(table) == set(DEFAULT_ROLES), (
        f"SPEC §2 lists roles {sorted(table)}, the engine has {sorted(DEFAULT_ROLES)}"
    )
    for role, globs in DEFAULT_ROLES.items():
        assert table[role] == list(globs), (
            f"SPEC §2 role `{role}` is stale.\n  spec: {table[role]}\n  code: {list(globs)}"
        )


def test_spec_rule_table_covers_the_registry():
    """§4 calls itself frozen; nothing checked that it listed what ships.

    STATE.md's detector count has been recomputed from the registry since
    2026-08-04. The SPEC's was not, and by v0.1.24 its table had twenty rows
    under a sentence reading "All fourteen are live" — six rules' worth of
    drift in the document that defines the rule IDs, while the file with the
    weaker claim was the one being checked.
    """
    listed = set(re.findall(r"^\| `([A-Z_]+)` \|", _rule_section(), re.M))
    missing = sorted(set(REGISTRY) - listed)
    invented = sorted(listed - set(REGISTRY))
    assert not missing, f"registered rules with no SPEC §4 row: {missing}"
    assert not invented, f"SPEC §4 rows for rules that do not exist: {invented}"


def test_spec_rule_count_prose_matches_the_table():
    section = _rule_section()
    rows = len(re.findall(r"^\| `([A-Z_]+)` \|", section, re.M))
    m = re.search(r"All (\S+) are live", section)
    assert m, "SPEC §4 no longer states how many rules are live"
    claimed = _COUNT_WORDS.get(m.group(1))
    assert claimed is not None, f"unrecognised count word in SPEC §4: {m.group(1)!r}"
    assert claimed == rows, (
        f"SPEC §4 says {m.group(1)} ({claimed}) rules are live; the table has {rows}"
    )


def test_spec_documents_the_content_gated_upgrade():
    """The one role decision a glob table cannot express must be written down."""
    text = SPEC.read_text(encoding="utf-8")
    assert "decided by content" in text
    assert "noxfile.py" in text
