"""The assertion-neutralization family, as a spelling x type matrix (issue #57).

Tonight's history was per-spelling patching: `except AssertionError` covered,
then `pytest.raises(AssertionError)` bypassed, then `contextlib.suppress`,
then the tuple spelling — each closed individually while the next dialect
stayed open. This module is the family-level answer the issue demanded: every
(neutralizing-context spelling) x (exception type) cell is generated, and
every cell either fires BROAD_EXCEPT_ADDED or is a *named* residual in
RESIDUALS below. A residual that starts firing fails the test until it is
struck from the list — the same record-or-fail discipline the refactor gate
uses — and a covered cell that goes silent fails immediately.

The type-set truth lives in one place (`_catches_assertionerror`, shared with
the except path's `_BROAD_EXCEPTIONS`), so the two paths cannot drift again.
"""

import datetime

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.pyenv import known_baseline

TODAY = datetime.date(2026, 1, 1)

PYTEST_BEFORE = """from shop import add


def test_add():
    assert add(2, 2) == 4
"""

UNITTEST_BEFORE = """import unittest

from shop import add


class TestAdd(unittest.TestCase):
    def test_add(self):
        assert add(2, 2) == 4
"""

# (spelling id, template family, extra import lines, context format string).
# `{T}` receives the type cell. The except spelling renders its own shape.
WITH_SPELLINGS = [
    ("suppress_dotted", "pytest", "import contextlib\n\n", "contextlib.suppress({T})"),
    ("suppress_bare", "pytest", "from contextlib import suppress\n\n", "suppress({T})"),
    ("pytest_raises", "pytest", "import pytest\n\n", "pytest.raises({T})"),
    ("raises_bare", "pytest", "from pytest import raises\n\n", "raises({T})"),
    ("assertRaises", "unittest", "", "self.assertRaises({T})"),
    ("assertRaisesRegex", "unittest", "", 'self.assertRaisesRegex({T}, "boom")'),
]

# (type id, source text, catches an AssertionError?)
TYPES = [
    ("assertionerror", "AssertionError", True),
    ("exception", "Exception", True),
    ("baseexception", "BaseException", True),
    ("tuple", "(AssertionError, ValueError)", True),
    ("valueerror", "ValueError", False),  # direction pin: must never fire
    ("aliased", "E", False),  # E = AssertionError — dynamic, priced below
]

# Named residuals (issue #57 §3): cells whose spelling can catch an
# AssertionError at runtime but that the static matcher deliberately does not
# decide. Aliased exception *values* (`E = AssertionError`) and a callee bound
# to a bare name (`r = pytest.raises`) would need binding resolution, and a
# wrong guess silences a genuine `except E` where E is a narrow type. They are
# asserted silent: closing one later means striking it from this list.
RESIDUALS = {
    ("except", "aliased"),
    ("suppress_dotted", "aliased"),
    ("suppress_bare", "aliased"),
    ("pytest_raises", "aliased"),
    ("raises_bare", "aliased"),
    ("assertRaises", "aliased"),
    ("assertRaisesRegex", "aliased"),
    ("dynamic_callee", "assertionerror"),
}


def _pytest_after(imports: str, context: str, alias_line: str = "") -> str:
    return (
        imports + alias_line + "from shop import add\n\n\n"
        "def test_add():\n"
        f"    with {context}:\n"
        "        assert add(2, 2) == 4\n"
    )


def _unittest_after(context: str, alias_line: str = "") -> str:
    return (
        "import unittest\n\n" + alias_line + "from shop import add\n\n\n"
        "class TestAdd(unittest.TestCase):\n"
        "    def test_add(self):\n"
        f"        with {context}:\n"
        "            assert add(2, 2) == 4\n"
    )


def _except_after(type_text: str, alias_line: str = "") -> str:
    return (
        alias_line + "from shop import add\n\n\n"
        "def test_add():\n"
        "    try:\n"
        "        assert add(2, 2) == 4\n"
        f"    except {type_text}:\n"
        "        pass\n"
    )


def _run(before: str, after: str):
    changes = [
        FileChange(
            path="tests/test_shop.py",
            status="modified",
            before=before.encode("utf-8"),
            after=after.encode("utf-8"),
        )
    ]
    _ir, findings, verdict = analyze(
        changes, Config(), Contract(), [], TODAY, known_modules=known_baseline()
    )
    return verdict, [f for f in findings if not f.allowlisted]


def _cell(spelling: str, type_id: str) -> tuple[str, str]:
    """(before, after) sources for one matrix cell."""
    type_text = dict((t, s) for t, s, _ in TYPES)[type_id]
    alias = "E = AssertionError\n\n" if type_id == "aliased" else ""
    if spelling == "except":
        return PYTEST_BEFORE, _except_after(type_text, alias)
    if spelling == "dynamic_callee":
        after = _pytest_after(
            "import pytest\n\n", f"r({type_text})", "r = pytest.raises\n\n"
        )
        return PYTEST_BEFORE, after
    sid, family, imports, ctx = next(s for s in WITH_SPELLINGS if s[0] == spelling)
    context = ctx.format(T=type_text)
    if family == "unittest":
        return UNITTEST_BEFORE, _unittest_after(context, alias)
    return PYTEST_BEFORE, _pytest_after(imports, context, alias)


ALL_SPELLINGS = ["except"] + [s[0] for s in WITH_SPELLINGS]
CELLS = [(sp, t) for sp in ALL_SPELLINGS for t, _s, _c in TYPES] + [
    ("dynamic_callee", "assertionerror")
]


@pytest.mark.parametrize("spelling,type_id", CELLS, ids=lambda v: v)
def test_matrix_cell(spelling, type_id):
    catches = dict((t, c) for t, _s, c in TYPES)[type_id]
    must_fire = catches and (spelling, type_id) not in RESIDUALS
    verdict, findings = _run(*_cell(spelling, type_id))
    hits = [f for f in findings if f.rule == "BROAD_EXCEPT_ADDED"]
    if must_fire:
        assert hits, (
            f"{spelling} x {type_id}: neutralization not caught — "
            f"verdict={verdict}, findings={[f.rule for f in findings]}"
        )
        assert hits[0].severity == "high", hits[0].severity
        assert "NO_PROD_CHANGE_IN_DIFF" in hits[0].escalators
        assert verdict == "block"
    else:
        assert not hits, (
            f"{spelling} x {type_id}: expected silent "
            f"({'named residual' if (spelling, type_id) in RESIDUALS else 'cannot catch AssertionError'}), "
            f"but BROAD_EXCEPT_ADDED fired — if this is a deliberate closure, "
            f"strike the cell from RESIDUALS"
        )
        assert verdict == "pass", (verdict, [f.rule for f in findings])


def test_residuals_are_cells():
    """Every named residual must be a real matrix cell — a typo here would
    silently assert nothing."""
    valid = set(CELLS)
    assert RESIDUALS <= valid, sorted(RESIDUALS - valid)
