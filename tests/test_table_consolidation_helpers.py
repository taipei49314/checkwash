"""Delegated row checks: a same-file assert helper, and a literal table fixture.

Both spellings still have to survive the same per-row concretization as an
inline table. Crediting the *call* would credit any call; these tests pin that
the helper is inlined and every existing strictness then applies to the
resulting concrete assertion.
"""

import datetime

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze


BEFORE = b'''from app.chunk import chunk

def test_even():
    assert chunk([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]

def test_remainder():
    assert chunk([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]
'''
ROWS = b"[([1, 2, 3, 4], 2, [[1, 2], [3, 4]]), ([1, 2, 3, 4, 5], 2, [[1, 2], [3, 4], [5]])]"
HELPER_LOOP = b'''from app.chunk import chunk

def check(xs, n, expected):
    assert chunk(xs, n) == expected

def test_chunk():
    for xs, n, expected in ''' + ROWS + b''':
        check(xs, n, expected)
'''
TABLE_FIXTURE = b'''import pytest
from app.chunk import chunk

@pytest.fixture
def cases():
    return ''' + ROWS + b'''

def test_chunk(cases):
    for xs, n, expected in cases:
        assert chunk(xs, n) == expected
'''
HELPER_BOTH_SIDES_BEFORE = b'''from app.chunk import chunk

def check(xs, n, expected):
    assert chunk(xs, n) == expected

def test_even():
    check([1, 2, 3, 4], 2, [[1, 2], [3, 4]])

def test_remainder():
    check([1, 2, 3, 4, 5], 2, [[1, 2], [3, 4], [5]])
'''


def run(after, before=BEFORE, extra=(), snapshot=None):
    snapshot = snapshot or {}
    return analyze(
        [FileChange("tests/test_chunk.py", "modified", before, after), *extra],
        Config(), Contract(), [], datetime.date(2026, 9, 6),
        root_reader=snapshot.get,
        root_searcher=lambda needles: [path for path, data in sorted(snapshot.items())
                                       if any(needle.encode() in data for needle in needles)],
    )


@pytest.mark.parametrize("after", [HELPER_LOOP, TABLE_FIXTURE], ids=["helper", "table_fixture"])
def test_delegated_row_check_keeps_each_oracle(after):
    _ir, findings, verdict = run(after)
    assert verdict == "pass", [(f.rule, f.severity) for f in findings]
    assert not findings


def test_helper_on_both_sides_keeps_each_oracle():
    _ir, findings, verdict = run(HELPER_LOOP, HELPER_BOTH_SIDES_BEFORE)
    assert verdict == "pass", [(f.rule, f.severity) for f in findings]
    assert not findings


@pytest.mark.parametrize("after", [HELPER_LOOP, TABLE_FIXTURE], ids=["helper", "table_fixture"])
def test_delegated_row_check_cannot_change_a_concrete_expected_row(after):
    after = after.replace(b"[[1, 2], [3, 4], [5]]", b"[[1, 2], [3, 4]]")
    _ir, findings, verdict = run(after)
    assert verdict == "block"
    assert any(f.rule == "EXPECTED_VALUE_CHANGED" and f.severity == "high" for f in findings)


@pytest.mark.parametrize("after", [HELPER_LOOP, TABLE_FIXTURE], ids=["helper", "table_fixture"])
def test_delegated_row_check_cannot_drop_a_row(after):
    after = after.replace(b", ([1, 2, 3, 4, 5], 2, [[1, 2], [3, 4], [5]])", b"")
    _ir, findings, verdict = run(after)
    assert verdict == "block"
    assert any(f.rule == "TEST_DISABLED" and f.severity == "high" for f in findings)


def test_weakened_helper_assertion_is_not_credited():
    """The helper's own assertion is the oracle; weakening it must show up."""
    after = HELPER_LOOP.replace(b"assert chunk(xs, n) == expected", b"assert chunk(xs, n) is not None")
    _ir, findings, verdict = run(after)
    assert verdict == "block", [(f.rule, f.severity) for f in findings]


@pytest.mark.parametrize("after", [
    # 兩個語句的 helper:沒證明第一句沒有副作用
    HELPER_LOOP.replace(b"    assert chunk(xs, n) == expected",
                        b"    got = chunk(xs, n)\n    assert got == expected"),
    # helper 有 message:超出既有 `_concrete` 的形狀
    HELPER_LOOP.replace(b"== expected", b"== expected, 'nope'"),
    # helper 有 decorator
    HELPER_LOOP.replace(b"def check", b"@staticmethod\ndef check"),
    # 同一列的值餵給兩個參數:執行期是同一個物件,投影會複製成兩份
    HELPER_LOOP.replace(b"        check(xs, n, expected)", b"        check(xs, xs, expected)"),
    # 呼叫傳的不是列名也不是字面值
    HELPER_LOOP.replace(b"        check(xs, n, expected)", b"        check(list(xs), n, expected)"),
    # 參數數目對不上
    HELPER_LOOP.replace(b"def check(xs, n, expected)", b"def check(xs, n, expected, extra=None)"),
    # 沒人呼叫的 helper 留在模組裡
    HELPER_LOOP.replace(b"def test_chunk():", b"def unused(a):\n    assert a == a\n\ndef test_chunk():"),
    # table fixture 帶 params:那是會乘上收集數的另一種 fixture
    TABLE_FIXTURE.replace(b"@pytest.fixture\ndef cases():\n    return ",
                          b"@pytest.fixture(scope='module')\ndef cases():\n    return "),
    # table fixture 的表不是字面值
    TABLE_FIXTURE.replace(ROWS, b"load_rows()"),
    # table fixture 回傳前先動了一手
    TABLE_FIXTURE.replace(b"    return ", b"    rows = []\n    return "),
], ids=[
    "two_statement_helper", "helper_message", "decorated_helper",
    "row_reaches_two_parameters", "computed_argument", "helper_arity", "unused_helper",
    "scoped_table_fixture", "dynamic_table_fixture", "table_fixture_with_statement",
])
def test_unsupported_delegation_gets_no_credit_and_keeps_blocking(after):
    ir, _findings, verdict = run(after)
    assert verdict == "block"
    assert not any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)


def test_collected_helper_is_not_a_helper():
    """A `test_*`-named delegate is a collected item, not an inlinable helper.

    Its own arguments make it unresolvable here, so the module stays outside
    the projection entirely (the ordinary frontend then judges the diff).
    """
    after = HELPER_LOOP.replace(b"check", b"test_check")
    ir, _findings, _verdict = run(after)
    assert not any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)


# --- the helper has to be the helper at run time --------------------------------


@pytest.mark.parametrize("after", [
    # the loop target rebinds the helper's name: `check` is the row's first cell
    HELPER_LOOP.replace(b"    for xs, n, expected in ", b"    for check, n, expected in ")
               .replace(b"        check(xs, n, expected)", b"        check(check, n, expected)"),
    # the local the table is assigned to rebinds it: `check` is the list
    HELPER_LOOP.replace(b"    for xs, n, expected in " + ROWS + b":",
                        b"    check = " + ROWS + b"\n    for xs, n, expected in check:"),
], ids=["loop_target_shadows_helper", "table_local_shadows_helper"])
def test_helper_shadowed_in_the_test_scope_gets_no_credit(after):
    """`for check, n, expected in rows: check(check, n, expected)` calls an int.

    Inlining the module helper there would credit a check that never runs
    (the plan's static counterexample); the projection declines and the
    ordinary frontend judges the diff."""
    ir, _findings, verdict = run(after)
    assert not any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)
    assert verdict == "block"


def test_helper_shadowed_by_a_parametrize_argname_gets_no_credit():
    after = (b"import pytest\n" + HELPER_LOOP.split(b"def test_chunk", 1)[0]
             + b'@pytest.mark.parametrize("check,n,expected", ' + ROWS + b")\n"
             + b"def test_chunk(check, n, expected):\n    check(check, n, expected)\n")
    ir, findings, _verdict = run(after)
    assert not any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)
    # No projection: whatever the ordinary frontend says about the consolidation stands.
    assert any(f.rule == "TEST_DISABLED" for f in findings)


def test_reordered_rows_get_no_credit():
    """Ordered coverage is part of the proof; a helper does not relax it."""
    reordered = b"[([1, 2, 3, 4, 5], 2, [[1, 2], [3, 4], [5]]), ([1, 2, 3, 4], 2, [[1, 2], [3, 4]])]"
    ir, _findings, verdict = run(HELPER_LOOP.replace(ROWS, reordered))
    assert not any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)
    assert verdict == "block"


def test_helper_that_recomputes_the_expectation_gets_no_credit():
    """`assert chunk(xs, n) == expected[:1]` is not a literal expectation after inlining."""
    ir, _findings, verdict = run(HELPER_LOOP.replace(b"== expected", b"== expected[:1]"))
    assert not any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)
    assert verdict == "block"


def test_second_definition_of_the_helper_name_keeps_the_module_out():
    """`_module` admits uniquely named defs only, so a later `def check` that
    would win at run time cannot leave the first one's assertion inlined."""
    after = HELPER_LOOP.replace(b"def test_chunk():", b"def check(xs, n, expected):\n    pass\n\ndef test_chunk():")
    ir, _findings, verdict = run(after)
    assert not any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)
    assert verdict == "block"


# --- literal table fixtures: function scope only, any number of readers ----------


@pytest.mark.parametrize("decorator", [b"@pytest.fixture(scope='session')", b"@pytest.fixture(autouse=True)",
                                       b"@pytest.fixture(scope='function')"],
                         ids=["session_scope", "autouse", "explicit_function_scope"])
def test_table_fixture_with_any_keyword_gets_no_credit(decorator):
    """Only the bare decorator is a literal table: a scope keyword would let
    one list object survive across tests, and the projection substitutes
    fresh literals per row. Even an explicit function scope is declined,
    so the accepted spelling is exactly one."""
    ir, _findings, verdict = run(TABLE_FIXTURE.replace(b"@pytest.fixture\n", decorator + b"\n"))
    assert not any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)
    assert verdict == "block"


SHARED_TABLE_BEFORE = b'''from app.normalize import normalize

def test_collapse_and_lower():
    assert normalize("  Hello   WORLD  ") == "hello world"

def test_already_clean():
    assert normalize("ok") == "ok"
'''
SHARED_TABLE_AFTER = b'''from app.normalize import normalize
import pytest

@pytest.fixture
def normalize_cases():
    return [
        ("  Hello   WORLD  ", "hello world"),
        ("ok", "ok"),
    ]

def test_collapse_and_lower(normalize_cases):
    for input_str, expected in normalize_cases:
        assert normalize(input_str) == expected

def test_already_clean(normalize_cases):
    for input_str, expected in normalize_cases:
        assert normalize(input_str) == expected
'''


def test_shared_table_fixture_projects_every_reader():
    """Corpus family false_positives/045: one literal table, two readers.

    A function-scope fixture is re-evaluated per test, so each reader walks
    its own fresh literal list; the projection concretizes each reader's
    rows independently and the old ordered coverage is a prefix of the new."""
    ir, findings, verdict = run(SHARED_TABLE_AFTER, SHARED_TABLE_BEFORE)
    assert verdict == "pass", [(f.rule, f.severity) for f in findings]
    assert not findings
    concrete = [u for u in ir.files[0].units if u.qualname.startswith("test_concrete_")]
    assert len(concrete) == 4  # two readers x two rows on the after side


def test_shared_table_fixture_cannot_hide_a_rewritten_row():
    after = SHARED_TABLE_AFTER.replace(b'("ok", "ok")', b'("ok", "OK")')
    _ir, findings, verdict = run(after, SHARED_TABLE_BEFORE)
    assert verdict == "block"
    assert any(f.rule == "EXPECTED_VALUE_CHANGED" and f.severity == "high" for f in findings)
