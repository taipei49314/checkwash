"""Every bypass THREATMODEL calls Closed must be pinned by something that runs.

The Closed column was 51 rows of the author's word with nothing checking it,
and it has been wrong twice: row 10 (`assert f(x) == f(x)`) sat there marked
Closed while one non-ASCII character on the line reopened it, and the "the
GitHub Action is dogfooded" claim shipped while the job that would have proved
it had never once executed.

This gate cannot prove a bypass is closed — row 10 *had* a fixture, and the
fixture was simply too narrow. What it can do is make "Closed with nothing
behind it" impossible to ship, and make the mapping visible so a reader can
attack the fixture instead of taking the table on trust.
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
CASES = ROOT / "tests" / "cases"

# Rows pinned by a named end-to-end test rather than a .gwcase fixture,
# because they are about CLI/git behaviour a static diff fixture cannot express.
E2E_PINNED = {
    "5": "test_rename_test_file_out_of_tests_blocks",
    "11": "test_three_dot_range_uses_merge_base",
}


def _closed_rows() -> dict[str, str]:
    text = (ROOT / "THREATMODEL.md").read_text(encoding="utf-8")
    rows = {}
    for line in text.split("\n"):
        if not line.startswith("| ") or "|" not in line[2:]:
            continue
        parts = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(parts) < 3 or not parts[0].isdigit():
            continue
        if "Closed" in parts[2]:
            rows[parts[0]] = parts[1]
    return rows


def _claimed_rows() -> dict[str, list[str]]:
    claims: dict[str, list[str]] = {}
    for path in sorted(CASES.glob("*.gwcase")):
        for line in path.read_text(encoding="utf-8").split("\n"):
            if line.startswith("bypass:"):
                for row in re.split(r"[,\s]+", line.split(":", 1)[1].strip()):
                    if row:
                        claims.setdefault(row, []).append(path.stem)
    return claims


def test_every_closed_bypass_is_pinned():
    closed = _closed_rows()
    claimed = _claimed_rows()
    unpinned = sorted(
        (row for row in closed if row not in claimed and row not in E2E_PINNED),
        key=int,
    )
    assert not unpinned, (
        "THREATMODEL rows marked Closed with nothing pinning them: "
        + ", ".join(f"#{r} ({closed[r][:50]})" for r in unpinned)
        + ". Add a fixture with `bypass: <row>` in its meta block, or stop "
        "calling the row Closed."
    )


def test_no_fixture_claims_a_row_that_does_not_exist():
    closed = _closed_rows()
    stray = sorted(
        (row for row in _claimed_rows() if row not in closed),
        key=int,
    )
    assert not stray, (
        f"fixtures claim THREATMODEL rows that are not marked Closed: {stray}. "
        "Either the row was reopened and the fixture should have failed, or the "
        "claim is a typo."
    )


def test_e2e_pinning_names_a_test_that_exists():
    """The escape hatch has to be checked too.

    Writing this gate, I filled one row with the name of a test I assumed was
    there. It was not. An unverified name in the allow-map is the same defect
    the gate exists to catch, one level up.
    """
    sources = chr(10).join(
        p.read_text(encoding="utf-8") for p in (ROOT / "tests").rglob("test_*.py")
    )
    missing = {
        row: name for row, name in E2E_PINNED.items() if f"def {name}(" not in sources
    }
    assert not missing, (
        f"E2E_PINNED names tests that do not exist: {missing}. A pin that "
        "resolves to nothing is worse than an unpinned row, because it reads "
        "as covered."
    )


def test_the_pinning_map_is_not_silently_empty():
    """A gate that matches nothing is the failure mode this file exists for."""
    assert len(_closed_rows()) >= 45, "THREATMODEL parsing broke; the gate is vacuous"
    assert len(_claimed_rows()) >= 40, "no fixture claims any row; the gate is vacuous"
