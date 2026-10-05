"""Every `pytestmark` binding is read, with its path condition as its guard (#260).

260.Q1: a `pytestmark` was read in one spelling only, a top-level
`pytestmark = <mark>` or `= [<mark>, ...]` in a test module. A class body, an
`if`, `try` or `with`, an annotation, `+=`, `.append`, `.extend` or
`.insert`, a tuple target and a bound name all skipped tests with no finding.

260.Q2: the binding's path condition is the mark's guard, judged by D6 as a
body skip's is, together with the mark's own condition.

260.Q3: a mark keeps the name a decorator would mint, whatever the spelling.

M1, M2 (the issue's comment): a mark bound to a name at module level was read
as a module-level skip call, so a mark that was never applied blocked the
whole module.
"""
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.findings import make_fingerprint
from checkwash.frontends.python.frontend import parse_python

TEST_PATH = "tests/test_calc.py"
CONFTEST = "tests/conftest.py"
HEAD = "import sys\n\nimport pytest\n"
TEST = "\n\ndef test_add():\n    assert 1 + 1 == 2\n"
SKIP = 'pytest.mark.skip(reason="later")'
BEFORE = HEAD + TEST


def module(lines, test=TEST):
    return HEAD + "\n" + lines + "\n" + test


def units(source, path_conftest=False):
    parsed = parse_python(source.encode(), collect_tests=True, conftest=path_conftest)
    return {unit.qualname: unit.side.markers for unit in parsed.units}


def marks(source, unit="test_add"):
    """(name, text, guard) of each marker on one unit."""
    return [(m.name, m.text, m.guard) for m in units(source)[unit]]


def analyze_change(before, after, path=TEST_PATH):
    _ir, findings, verdict = analyze(
        [FileChange(path, "modified", before.encode(), after.encode())],
        Config(), Contract(), [], datetime.date(2026, 10, 5),
    )
    return [f for f in findings if f.rule == "TEST_DISABLED"], verdict


def outcome(before, after, path=TEST_PATH):
    found, verdict = analyze_change(before, after, path)
    return [(f.unit, f.severity, f.deescalators) for f in found], verdict


# --- 260.Q1: every binding of `pytestmark` in a module ---------------------------

UNGUARDED = [("pytest.mark.skip", SKIP, None)]

SPELLINGS = {
    # the issue's rows
    "A5_annotated": (f"pytestmark: list = [{SKIP}]", UNGUARDED),
    "A6_augmented": (f"pytestmark = []\npytestmark += [{SKIP}]", UNGUARDED),
    "A7_append": (f"pytestmark = []\npytestmark.append({SKIP})", UNGUARDED),
    "A8_tuple_target": (f"pytestmark, other = {SKIP}, 1", UNGUARDED),
    "A10_with": (f"import contextlib\n\nwith contextlib.suppress(Exception):\n    pytestmark = {SKIP}", UNGUARDED),
    "A11_bound_mark": (f"SKIP = {SKIP}\npytestmark = SKIP", UNGUARDED),
    "A12_bound_list": (f"MARKS = [{SKIP}]\npytestmark = MARKS", UNGUARDED),
    # the other ways to put a mark into it
    "extend": (f"pytestmark = []\npytestmark.extend([{SKIP}])", UNGUARDED),
    "insert": (f"pytestmark = [pytest.mark.slow]\npytestmark.insert(0, {SKIP})", UNGUARDED),
    "subscript": (f"pytestmark = [pytest.mark.slow]\npytestmark[0] = {SKIP}", UNGUARDED),
    "concatenated": (f"COMMON = [pytest.mark.slow]\npytestmark = COMMON + [{SKIP}]", UNGUARDED),
    "concatenated_first": (f"COMMON = [pytest.mark.slow]\npytestmark = [{SKIP}] + COMMON", UNGUARDED),
    "starred": (f"MARKS = [{SKIP}]\npytestmark = [*MARKS, pytest.mark.slow]", UNGUARDED),
    "chained_names": (f"SKIP = {SKIP}\nLATER = SKIP\npytestmark = [LATER]", UNGUARDED),
    "annotated_name": (f"SKIP: object = {SKIP}\npytestmark = SKIP", UNGUARDED),
    "name_bound_in_an_if": (f"if sys.version_info >= (3, 8):\n    SKIP = {SKIP}\npytestmark = SKIP", UNGUARDED),
    "name_bound_in_an_except": (f"try:\n    import numpy\nexcept ImportError:\n    SKIP = {SKIP}\npytestmark = SKIP",
                                UNGUARDED),
    "nested_tuple_target": (f"(pytestmark, a), b = ({SKIP}, 1), 2", UNGUARDED),
    "beside_a_starred_target": (f"*rest, pytestmark = 1, {SKIP}", UNGUARDED),
    "starred_target": (f"*pytestmark, other = {SKIP}, 1", UNGUARDED),
    "two_targets": (f"pytestmark = other = {SKIP}", UNGUARDED),
    "bare_attribute": ("pytestmark = pytest.mark.skip", [("pytest.mark.skip", "pytest.mark.skip", None)]),
    "from_import": (f"from pytest import mark\n\npytestmark = mark.skip(reason=\"later\")",
                    [("pytest.mark.skip", 'mark.skip(reason="later")', None)]),
    # a body that adds no guard: a loop, a `try`, its `finally`, a `match` case
    "for_body": (f"for _ in range(1):\n    pytestmark = {SKIP}", UNGUARDED),
    "while_body": (f"while True:\n    pytestmark = {SKIP}\n    break", UNGUARDED),
    "try_body": (f"try:\n    pytestmark = {SKIP}\nexcept ImportError:\n    pass", UNGUARDED),
    "finally_body": (f"try:\n    pass\nfinally:\n    pytestmark = {SKIP}", UNGUARDED),
    "match_case": (f'match sys.platform:\n    case "win32":\n        pytestmark = {SKIP}', UNGUARDED),
    # every binding counts, so a later reset still leaves the mark recorded
    "reset_after": (f"pytestmark = {SKIP}\npytestmark = []", UNGUARDED),
    # A1-A4: an `if`, an `else`, an `elif` and an `except` give the guard
    "A1_if_true": (f"if True:\n    pytestmark = {SKIP}", [("pytest.mark.skip", SKIP, "True")]),
    "A2_if_linux": (f'if sys.platform.startswith("linux"):\n    pytestmark = {SKIP}',
                    [("pytest.mark.skip", SKIP, 'sys.platform.startswith("linux")')]),
    "A3_except": (f"try:\n    import numpy\nexcept ImportError:\n    pytestmark = {SKIP}",
                  [("pytest.mark.skip", SKIP, 'find_spec("numpy") is None')]),
    "A4_else": (f"if sys.version_info < (3, 0):\n    pass\nelse:\n    pytestmark = {SKIP}",
                [("pytest.mark.skip", SKIP, "not (sys.version_info < (3, 0))")]),
    "elif": (f'if sys.platform == "darwin":\n    pass\nelif sys.platform == "win32":\n    pytestmark = {SKIP}',
             [("pytest.mark.skip", SKIP, 'not (sys.platform == "darwin") and sys.platform == "win32"')]),
    "nested_ifs": (f'if sys.platform == "win32" or IS_PYPY:\n    if sys.version_info < (3, 12):\n        pytestmark = {SKIP}',
                   [("pytest.mark.skip", SKIP, '(sys.platform == "win32" or IS_PYPY) and sys.version_info < (3, 12)')]),
    "other_except": (f"try:\n    import numpy\nexcept Exception:\n    pytestmark = {SKIP}",
                     [("pytest.mark.skip", SKIP, "except Exception")]),
    "guarded_alias": (f'SKIP = {SKIP}\nif sys.platform == "win32":\n    pytestmark = SKIP',
                      [("pytest.mark.skip", SKIP, 'sys.platform == "win32"')]),
}


@pytest.mark.parametrize("name", SPELLINGS)
def test_every_binding_of_pytestmark_is_read(name):
    lines, expected = SPELLINGS[name]
    assert marks(module(lines)) == expected


def test_each_mark_records_its_own_call():
    source = module(f'pytestmark = [pytest.mark.slow, {SKIP}, pytest.mark.skipif(sys.platform == "win32")]')
    markers = units(source)["test_add"]
    assert [m.text for m in markers] == [SKIP, 'pytest.mark.skipif(sys.platform == "win32")']
    for m in markers:
        assert source[m.span[0]:m.span[1]] == m.text


@pytest.mark.parametrize("lines", [
    # a function's own `pytestmark` is a local, which pytest never reads
    f"def helper():\n    pytestmark = {SKIP}\n    return pytestmark",
    # a mark that only labels the tests
    "pytestmark = [pytest.mark.slow, pytest.mark.timeout(30)]",
    # a tuple target that does not unpack a literal of its length
    "pytestmark, other = make_marks()",
    # a starred value spreads over targets by its length, which is unknown:
    # here `pytestmark` gets the slow mark
    f"MARKS = [pytest.mark.slow, {SKIP}]\nEMPTY = []\npytestmark, other = *MARKS, *EMPTY",
    # residual: a starred target that does not unpack a literal of its length
    f"pytestmark, *rest = {SKIP}, 1, 2",
    # a call on pytestmark that adds nothing, and a list grown through another
    # name (residual)
    f"pytestmark = []\npytestmark.count({SKIP})",
    f"MARKS = []\nMARKS.append({SKIP})\npytestmark = MARKS",
    # a name bound by an import holds nothing this reading can see (residual)
    "from tests.marks import SKIP\n\npytestmark = SKIP",
    # names bound to each other only
    "A = B\nB = A\npytestmark = A",
])
def test_what_holds_no_mark_it_can_read(lines):
    assert marks(module(lines)) == []


def test_a_name_bound_more_than_once_holds_every_value():
    # The ruling names a name bound once. One bound twice may hold either
    # value when `pytestmark` is bound, so both count: the reading fails
    # toward flagging. Before #260 the second line was read as a module-level
    # skip call, so this spelling blocked, and it still does.
    assert [m[0] for m in marks(module(f"SKIP = pytest.mark.slow\nSKIP = {SKIP}\npytestmark = SKIP"))] == [
        "pytest.mark.skip"]
    # a name that refers to itself ends where it does
    assert [m[0] for m in marks(module(f"MARKS = [pytest.mark.slow]\nMARKS = MARKS + [{SKIP}]\npytestmark = MARKS"))] == [
        "pytest.mark.skip"]


# --- 260.Q1: a class body, for that class's units only ---------------------------

def test_a_class_body_pytestmark_reaches_its_units_only():
    source = HEAD + (
        "\n\nclass TestCalc:\n"
        f"    pytestmark = {SKIP}\n\n"
        "    def test_add(self):\n        assert 1 + 1 == 2\n\n"
        "    class TestInner:\n        def test_deep(self):\n            assert 1\n"
        "\n\ndef test_sub():\n    assert 2 - 1 == 1\n"
    )
    found = {name: [m.name for m in markers] for name, markers in units(source).items()}
    assert found == {
        "TestCalc.test_add": ["pytest.mark.skip"],
        "TestCalc.TestInner.test_deep": ["pytest.mark.skip"],
        "test_sub": [],
    }


def test_a_class_body_guard_and_aliases():
    source = HEAD + (
        "\nLATER = pytest.mark.skip\n\n\nclass TestCalc:\n"
        '    if sys.platform == "win32":\n        pytestmark = LATER\n\n'
        "    def test_add(self):\n        assert 1 + 1 == 2\n"
    )
    assert marks(source, "TestCalc.test_add") == [("pytest.mark.skip", "pytest.mark.skip", 'sys.platform == "win32"')]


def test_an_inherited_test_carries_its_base_class_pytestmark():
    source = HEAD + (
        f"\n\nclass Base:\n    pytestmark = {SKIP}\n\n    def test_add(self):\n        assert 1 + 1 == 2\n"
        "\n\nclass TestChild(Base):\n    pass\n"
    )
    assert [m.name for m in units(source)["TestChild.test_add"]] == ["pytest.mark.skip"]


def test_residual_a_subclass_s_own_test_does_not_carry_its_base_s_pytestmark():
    # pytest looks a class's `pytestmark` up through its bases, so
    # `TestChild.test_b` is skipped too. A base class's decorators reach a
    # subclass's own tests the same way and are not read either.
    source = HEAD + (
        f"\n\nclass TestBase:\n    pytestmark = {SKIP}\n\n    def test_a(self):\n        assert 1\n"
        "\n\nclass TestChild(TestBase):\n    def test_b(self):\n        assert 2\n"
    )
    found = units(source)
    assert [m.name for m in found["TestChild.test_a"]] == ["pytest.mark.skip"]
    assert found["TestChild.test_b"] == []


# --- M1, M2: a mark bound to a name is a mark, not a module-level skip call ------

@pytest.mark.parametrize("lines", [
    'skip_slow = pytest.mark.skip(reason="slow")',
    'xfail_on_ci = pytest.mark.xfail(reason="flaky on CI")',
    'skip_win = pytest.mark.skipif(sys.platform == "win32")',
    'pytest.mark.skip(reason="never applied")',
    'from pytest import mark\n\nlater = mark.skip(reason="later")',
])
def test_a_mark_that_is_never_applied_disables_nothing(lines):
    assert marks(module(lines)) == []
    assert outcome(BEFORE, module(lines)) == ([], "pass")


@pytest.mark.parametrize("lines, name", [
    ('pytest.skip("later", allow_module_level=True)', "module.skip"),
    ('pytest.xfail("later")', "module.xfail"),
    ('numpy = pytest.importorskip("numpy")', "module.importorskip"),
])
def test_a_module_level_skip_call_still_disables_the_module(lines, name):
    assert [m[0] for m in marks(module(lines))] == [name]


@pytest.mark.parametrize("before_test, decorated, expected", [
    # M1 applied: the name's mark, recorded as its own call
    ('skip_slow = pytest.mark.skip(reason="slow")\n', "@skip_slow\n",
     [("pytest.mark.skip", 'pytest.mark.skip(reason="slow")')]),
    ('skip_win = pytest.mark.skipif(sys.platform == "win32", reason="posix")\n', "@skip_win\n",
     [('pytest.mark.skipif(sys.platform=="win32")', 'pytest.mark.skipif(sys.platform == "win32", reason="posix")')]),
    # a called name: the decorator's call carries the condition
    ("skip_if = pytest.mark.skipif\n", '@skip_if(sys.platform == "win32")\n',
     [('pytest.mark.skipif(sys.platform=="win32")', 'skip_if(sys.platform == "win32")')]),
    # a name a decorator reads as a mark already keeps that reading
    ("skip = pytest.mark.skip\n", "@skip\n", [("skip", "@skip")]),
])
def test_an_applied_mark_name_is_read_as_its_mark(before_test, decorated, expected):
    source = HEAD + "\n" + before_test + "\n\n" + decorated + "def test_add():\n    assert 1 + 1 == 2\n"
    assert [(name, text.lstrip("@")) for name, text, _guard in marks(source)] == [
        (name, text.lstrip("@")) for name, text in expected]


def test_an_applied_mark_name_in_a_class_and_on_a_class():
    method = HEAD + (
        "\n\nclass TestCalc:\n    later = pytest.mark.skip\n\n"
        "    @later\n    def test_add(self):\n        assert 1 + 1 == 2\n"
    )
    assert [m[0] for m in marks(method, "TestCalc.test_add")] == ["pytest.mark.skip"]
    module_name = HEAD + (
        "\nlater = pytest.mark.skip\n\n\nclass TestCalc:\n"
        "    @later\n    def test_add(self):\n        assert 1 + 1 == 2\n"
    )
    assert [m[0] for m in marks(module_name, "TestCalc.test_add")] == ["pytest.mark.skip"]
    decorated_class = HEAD + (
        "\nlater = pytest.mark.skip\n\n\n@later\nclass TestCalc:\n"
        "    def test_add(self):\n        assert 1 + 1 == 2\n"
    )
    assert [m[0] for m in marks(decorated_class, "TestCalc.test_add")] == ["pytest.mark.skip"]


def test_an_applied_name_is_followed_through_names_and_ends_in_a_cycle():
    chained = HEAD + "\nlater = pytest.mark.skip\nagain = later\n\n\n@again\ndef test_add():\n    assert 1 + 1 == 2\n"
    assert [m[0] for m in marks(chained)] == ["pytest.mark.skip"]
    cycle = HEAD + "\na = b\nb = a\n\n\n@a\ndef test_add():\n    assert 1 + 1 == 2\n"
    assert marks(cycle) == []


def test_a_name_bound_twice_applies_every_mark_it_may_hold():
    source = HEAD + (
        "\nlater = pytest.mark.slow\nlater = pytest.mark.skip\n\n\n"
        "@later\ndef test_add():\n    assert 1 + 1 == 2\n"
    )
    assert [m[0] for m in marks(source)] == ["pytest.mark.skip"]


# --- 260.Q2: D6 judges the binding's guard with the mark's own condition --------

@pytest.mark.parametrize("lines, expected", [
    # the guard holds the mark at warn, as its `skipif` spelling does
    ('if sys.platform == "win32":\n    pytestmark = pytest.mark.skip(reason="posix only")', ("warn", ["COMPAT_GATE"])),
    (f'if sys.platform.startswith("linux"):\n    pytestmark = {SKIP}', ("warn", ["COMPAT_GATE"])),
    (f'if sys.platform == "darwin":\n    pass\nelif sys.platform == "win32":\n    pytestmark = {SKIP}',
     ("warn", ["COMPAT_GATE"])),
    ('if sys.platform == "win32":\n    pytestmark = pytest.mark.xfail(reason="flaky there")', ("warn", ["COMPAT_GATE"])),
    # the guard and the mark's condition are judged together
    ('if sys.platform == "win32":\n    pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="old")',
     ("warn", ["COMPAT_GATE"])),
    ('if True:\n    pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="posix")', ("warn", ["COMPAT_GATE"])),
    ('if sys.platform == "win32":\n    pytestmark = pytest.mark.skipif(True, reason="never")', ("warn", ["COMPAT_GATE"])),
    ("pytestmark = pytest.mark.skipif(True, reason='always')", ("high", [])),
    # a guard that always holds, or names no interpreter or OS, earns nothing
    (f"if True:\n    pytestmark = {SKIP}", ("high", [])),
    (f"if sys.version_info < (3, 0):\n    pass\nelse:\n    pytestmark = {SKIP}", ("high", [])),
    (f"try:\n    import numpy\nexcept ImportError:\n    pytestmark = {SKIP}", ("high", [])),
    (f'if os_name() == "nt":\n    pytestmark = {SKIP}', ("high", [])),
    # a strict xfail inverts the oracle under any guard
    ('if sys.platform == "win32":\n    pytestmark = pytest.mark.xfail(strict=True)', ("high", [])),
    # a `with`, loop or `match` body adds no guard
    (f'match sys.platform:\n    case "win32":\n        pytestmark = {SKIP}', ("high", [])),
    # a guard the reading cannot parse earns nothing, whatever the mark's own condition
    (f"try:\n    import numpy\nexcept Exception:\n    pytestmark = {SKIP}", ("high", [])),
    ('try:\n    import numpy\nexcept Exception:\n    pytestmark = pytest.mark.skipif(sys.platform == "win32")',
     ("high", [])),
])
def test_d6_judges_the_binding_guard(lines, expected):
    found, verdict = outcome(BEFORE, module(lines))
    assert found == [("test_add", *expected)]
    assert verdict == ("pass" if expected[0] == "warn" else "block")


def test_every_mark_of_the_name_must_qualify():
    guarded = 'if sys.platform == "win32":\n    pytestmark = pytest.mark.skip(reason="x")\n'
    # two guarded bindings, each on the platform: both held
    found, verdict = outcome(BEFORE, module(guarded + 'if sys.platform == "darwin":\n    pytestmark = pytest.mark.skip(reason="x")'))
    assert found == [("test_add", "warn", ["COMPAT_GATE"])] * 2 and verdict == "pass"
    # one unguarded beside it: neither is
    found, verdict = outcome(BEFORE, module(guarded + 'pytestmark = pytest.mark.skip(reason="x")'))
    assert found == [("test_add", "high", [])] * 2 and verdict == "block"


def test_a_class_body_guard_is_judged_the_same_way():
    before = HEAD + "\n\nclass TestCalc:\n    def test_add(self):\n        assert 1 + 1 == 2\n"
    platform = before.replace("class TestCalc:\n", 'class TestCalc:\n    if sys.platform == "win32":\n'
                                                  f"        pytestmark = {SKIP}\n\n")
    always = before.replace("class TestCalc:\n", f"class TestCalc:\n    if True:\n        pytestmark = {SKIP}\n\n")
    assert outcome(before, platform) == ([("TestCalc.test_add", "warn", ["COMPAT_GATE"])], "pass")
    assert outcome(before, always) == ([("TestCalc.test_add", "high", [])], "block")


# --- a guard made always true, or removed, is reported ----------------------------

GUARDED = module('if sys.platform == "win32":\n    pytestmark = pytest.mark.skip(reason="posix only")')


@pytest.mark.parametrize("after, message", [
    (GUARDED.replace('if sys.platform == "win32":', "if True:"),
     "test_add: skip guard now always fires ('True') (pytestmark: pytest.mark.skip)"),
    (module('pytestmark = pytest.mark.skip(reason="posix only")'),
     "test_add: skip guard removed (was 'sys.platform == \"win32\"') (pytestmark: pytest.mark.skip)"),
])
def test_a_guard_made_always_true_or_removed_is_reported(after, message):
    found, verdict = analyze_change(GUARDED, after)
    assert [(f.message, f.severity, f.shape) for f in found] == [(message, "high", "guard_weakened")]
    assert found[0].fingerprint == make_fingerprint("TEST_DISABLED", TEST_PATH, "test_add", "guard:pytest.mark.skip")
    assert verdict == "block"


def test_an_unguarded_binding_beside_a_guarded_one_is_a_mark_added():
    after = GUARDED + 'pytestmark.append(pytest.mark.skip(reason="posix only"))\n'
    found, verdict = analyze_change(GUARDED, after)
    assert [(f.message, f.severity, f.shape) for f in found] == [
        ("test_add: disabling marker added (pytest.mark.skip)", "high", "marker_added")]
    assert verdict == "block"


def test_a_guard_moved_to_another_platform_is_no_event():
    after = GUARDED.replace('"win32"', '"darwin"')
    assert outcome(GUARDED, after) == ([], "pass")


# --- 260.Q3: a mark keeps its name across spellings --------------------------------

@pytest.mark.parametrize("lines", [
    f"pytestmark = {SKIP}",
    f"pytestmark = [{SKIP}]",
    f"pytestmark: list = [{SKIP}]",
    f"pytestmark = []\npytestmark.append({SKIP})",
    f"LATER = {SKIP}\npytestmark = LATER",
    f'if sys.platform == "win32":\n    pytestmark = {SKIP}',
])
def test_a_mark_keeps_the_name_a_decorator_mints(lines):
    decorated = HEAD + f"\n\n@{SKIP}\ndef test_add():\n    assert 1 + 1 == 2\n"
    assert [m[0] for m in marks(module(lines))] == [m[0] for m in marks(decorated)] == ["pytest.mark.skip"]


def test_moving_a_mark_from_the_test_into_pytestmark_is_no_event():
    decorated = HEAD + f"\n\n@{SKIP}\ndef test_add():\n    assert 1 + 1 == 2\n"
    assert outcome(decorated, module(f"pytestmark = {SKIP}")) == ([], "pass")


def test_a11_is_reported_under_its_mark_s_name():
    found, _verdict = analyze_change(BEFORE, module(f"SKIP = {SKIP}\npytestmark = SKIP"))
    assert [(f.message, f.fingerprint) for f in found] == [(
        "test_add: disabling marker added (pytest.mark.skip)",
        make_fingerprint("TEST_DISABLED", TEST_PATH, "test_add", "pytest.mark.skip"),
    )]
    assert found[0].after.text == SKIP


# --- a conftest: every spelling is read, and disables nothing (#209 Q3) -----------

@pytest.mark.parametrize("lines", [
    f"if True:\n    pytestmark = {SKIP}",
    f"pytestmark = []\npytestmark += [{SKIP}]",
    f"MARKS = [{SKIP}]\npytestmark = MARKS",
])
def test_a_conftest_pytestmark_in_any_spelling_is_reported_at_info(lines):
    found, verdict = analyze_change(HEAD, HEAD + "\n" + lines + "\n", path=CONFTEST)
    assert [(f.unit, f.severity, f.shape) for f in found] == [("<suite>", "info", "inert_mark")]
    assert verdict == "pass"


CONFTEST_GUARDED = HEAD + '\nif sys.platform == "win32":\n    pytestmark = pytest.mark.skip(reason="posix only")\n'


@pytest.mark.parametrize("after, said", [
    (CONFTEST_GUARDED.replace('if sys.platform == "win32":', "if True:"), "skip guard now always fires ('True')"),
    (HEAD + '\npytestmark = pytest.mark.skip(reason="posix only")\n',
     "skip guard removed (was 'sys.platform == \"win32\"')"),
])
def test_a_conftest_pytestmark_s_guard_guards_nothing_either(after, said):
    found, verdict = analyze_change(CONFTEST_GUARDED, after, path=CONFTEST)
    assert [(f.message, f.severity, f.shape) for f in found] == [(
        f"<suite>: {said} (pytestmark: pytest.mark.skip): pytest does not collect conftest.py "
        "as a test module, so this pytestmark disables nothing",
        "info", "inert_mark",
    )]
    assert found[0].fingerprint == make_fingerprint("TEST_DISABLED", CONFTEST, "<suite>", "guard:pytest.mark.skip")
    assert verdict == "pass"
