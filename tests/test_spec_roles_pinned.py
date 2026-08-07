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

from greenwash.config import DEFAULT_ROLES

SPEC = pathlib.Path(__file__).resolve().parents[1] / "SPEC.md"


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


def test_spec_documents_the_content_gated_upgrade():
    """The one role decision a glob table cannot express must be written down."""
    text = SPEC.read_text(encoding="utf-8")
    assert "decided by content" in text
    assert "noxfile.py" in text
