"""A D10 survivor reaches the conftest fixtures above it at head (#266).

D10 credits a disappeared unit when an identical live copy of its body runs
at head in a collectable test file the diff does not touch (THREATMODEL row
58). The copy's liveness was read from its own file only, so a copy that an
always-skip conftest fixture skips counted as live, and deleting the running
copy passed at info.

Ruled 2026-10-06:
1. a candidate survivor's conftest chain is read at head, as #223 reads a
   changed module's head side, and the survivor is parsed with it. A
   survivor that an always-skip conftest fixture reaches is not live and
   earns nothing. The chain's reads keep #223's bounds;
2. D10's survivors only.
"""
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.gitio.snapshot import search_source_mapping

TEST = "def test_total():\n    assert total() == 78.75\n"
OTHER = "\n\ndef test_other():\n    assert total() > 0\n"
IMPORT = "from app.billing import total\n\n\n"
SKIPPING = (
    "import pytest\n\n\n@pytest.fixture\ndef needs_network():\n"
    "    pytest.skip(\"network tests are disabled\")\n"
)


def survivor(decorator=""):
    return "import pytest\n\n" + IMPORT + decorator + TEST


def outcome(head, changed=None, *, root=True):
    """The TEST_DISABLED findings when the diff deletes `test_total` from tests/test_billing.py."""
    changed = changed or {}
    before = {"tests/test_billing.py": IMPORT + TEST + OTHER, **{p: b for p, (b, _a) in changed.items()}}
    after = {"tests/test_billing.py": IMPORT + OTHER.lstrip("\n"), **{p: a for p, (_b, a) in changed.items()}}
    changes = [
        FileChange(path, "modified", before[path].encode(), after[path].encode()) for path in sorted(before)
    ]
    files = {p: s.encode() for p, s in head.items()}
    snapshot = {**files, **{p: s.encode() for p, s in after.items()}}
    _ir, findings, verdict = analyze(
        changes, Config(), Contract(), [], datetime.date(2026, 10, 6),
        head_reader=files.get,
        head_searcher=lambda needles: [p for p, d in sorted(files.items()) if any(n.encode() in d for n in needles)],
        root_reader=snapshot.get if root else None,
        root_searcher=(lambda needles: search_source_mapping(snapshot, needles)) if root else None,
    )
    return verdict, [(f.unit, f.severity, f.deescalators) for f in findings if f.rule == "TEST_DISABLED"]


CREDITED = ("pass", [("test_total", "info", ["DUPLICATE_REMAINS"])])
UNCREDITED = ("block", [("test_total", "high", [])])


def test_u1_a_survivor_an_always_skip_conftest_fixture_skips_earns_nothing():
    head = {"tests/conftest.py": SKIPPING,
            "tests/test_copy.py": survivor('@pytest.mark.usefixtures("needs_network")\n')}
    assert outcome(head) == UNCREDITED


def test_u2_a_survivor_that_requests_no_skipping_fixture_is_credited():
    assert outcome({"tests/conftest.py": SKIPPING, "tests/test_copy.py": survivor()}) == CREDITED


@pytest.mark.parametrize("head", [
    # from the conftest at the repository root, two levels up
    {"conftest.py": SKIPPING,
     "tests/unit/test_copy.py": survivor('@pytest.mark.usefixtures("needs_network")\n')},
    # an autouse fixture reaches every test beneath it
    {"tests/conftest.py": SKIPPING.replace("@pytest.fixture", "@pytest.fixture(autouse=True)"),
     "tests/test_copy.py": survivor()},
], ids=["from_the_root", "autouse"])
def test_every_way_a_survivor_reaches_the_fixture_counts(head):
    """A fixture requested as a parameter changes the signature, and so the body
    hash: that copy is no survivor whatever its liveness."""
    assert outcome(head) == UNCREDITED


@pytest.mark.parametrize("head", [
    # a conftest beside the survivor's directory is not above it
    {"other/conftest.py": SKIPPING.replace("@pytest.fixture", "@pytest.fixture(autouse=True)"),
     "tests/test_copy.py": survivor()},
    # a skip the fixture runs only on one platform is a compatibility gate (D6)
    {"tests/conftest.py": SKIPPING.replace(
        "import pytest\n", "import sys\n\nimport pytest\n").replace(
        "    pytest.skip(", "    if sys.platform == \"win32\":\n        pytest.skip("),
     "tests/test_copy.py": survivor('@pytest.mark.usefixtures("needs_network")\n')},
], ids=["sibling_directory", "compat_gate"])
def test_a_survivor_the_chain_does_not_skip_is_credited(head):
    assert outcome(head) == CREDITED


def test_a_conftest_the_diff_changes_is_read_on_its_head_side():
    """The diff changes the survivor's conftest while deleting the running copy.
    Adding the skip is reported on the conftest's own `<suite>` unit too (#223)."""
    head = {"tests/conftest.py": SKIPPING,
            "tests/test_copy.py": survivor('@pytest.mark.usefixtures("needs_network")\n')}
    plain = "import pytest\n\n\n@pytest.fixture\ndef needs_network():\n    return None\n"
    verdict, findings = outcome(head, {"tests/conftest.py": (plain, SKIPPING)})
    assert (verdict, [f for f in findings if f[0] == "test_total"]) == UNCREDITED
    assert outcome({**head, "tests/conftest.py": plain}, {"tests/conftest.py": (SKIPPING, plain)}) == CREDITED


def test_without_a_strict_snapshot_the_chain_is_unknown_and_reads_as_before():
    """The chain is read from the strict snapshot, as #223 reads it. Without one,
    no level is known and the survivor keeps the reading it had."""
    head = {"tests/conftest.py": SKIPPING,
            "tests/test_copy.py": survivor('@pytest.mark.usefixtures("needs_network")\n')}
    assert outcome(head, root=False) == CREDITED
