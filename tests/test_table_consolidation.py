"""Concrete table consolidation must preserve every input/expected pair."""

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
FIXTURE = b'''from app.chunk import chunk
import pytest

@pytest.fixture(params=''' + ROWS + b''')
def test_data(request):
    return request.param

def test_chunk(test_data):
    xs, n, expected = test_data
    assert chunk(xs, n) == expected
'''
PARAMETRIZE = b'''from app.chunk import chunk
import pytest

@pytest.mark.parametrize("xs,n,expected", ''' + ROWS + b''')
def test_chunk(xs, n, expected):
    assert chunk(xs, n) == expected
'''
LOOP = b'''from app.chunk import chunk

def test_chunk():
    for xs, n, expected in ''' + ROWS + b''':
        assert chunk(xs, n) == expected
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


@pytest.mark.parametrize("after", [FIXTURE, PARAMETRIZE, LOOP], ids=["fixture", "parametrize", "loop"])
def test_issue_130_concrete_table_keeps_each_oracle(after):
    _ir, findings, verdict = run(after)
    assert verdict == "pass", [(f.rule, f.severity) for f in findings]
    assert not findings


def test_issue_130_min_max_fixture():
    before = b'''from app.min_max import min_max
def test_mixed():
    assert min_max([3, 1, 2]) == (1, 3)
def test_negative():
    assert min_max([-5, 0]) == (-5, 0)
def test_singleton():
    assert min_max([7]) == (7, 7)
'''
    after = b'''import pytest
from app.min_max import min_max
@pytest.fixture(params=[([3, 1, 2], (1, 3)), ([-5, 0], (-5, 0)), ([7], (7, 7))])
def input_output(request):
    return request.param
def test_min_max(input_output):
    input, expected = input_output
    assert min_max(input) == expected
'''
    _ir, findings, verdict = run(after, before)
    assert verdict == "pass", [(f.rule, f.severity) for f in findings]
    assert not findings


@pytest.mark.parametrize("after", [FIXTURE, PARAMETRIZE, LOOP])
def test_consolidation_cannot_change_a_concrete_expected_row(after):
    after = after.replace(b"[[1, 2], [3, 4], [5]]", b"[[1, 2], [3, 4]]")
    _ir, findings, verdict = run(after)
    assert verdict == "block"
    assert any(f.rule == "EXPECTED_VALUE_CHANGED" and f.severity == "high" for f in findings)


@pytest.mark.parametrize("after", [FIXTURE, PARAMETRIZE, LOOP])
def test_consolidation_cannot_drop_a_row(after):
    after = after.replace(b", ([1, 2, 3, 4, 5], 2, [[1, 2], [3, 4], [5]])", b"")
    _ir, findings, verdict = run(after)
    assert verdict == "block"
    assert any(f.rule == "TEST_DISABLED" and f.severity == "high" for f in findings)


@pytest.mark.parametrize("after", [
    FIXTURE.replace(b"return request.param", b"return request.param if False else ([], 2, [])"),
    FIXTURE.replace(b"    assert chunk", b"    expected = []\n    assert chunk"),
    FIXTURE.replace(b"    assert chunk", b"    chunk = lambda *args: expected\n    assert chunk"),
    FIXTURE.replace(b"    assert chunk", b"    xs.clear()\n    assert chunk"),
    FIXTURE.replace(b"    assert chunk", b"    if False:\n        assert chunk"),
    FIXTURE.replace(b"    assert chunk(xs, n) == expected", b"    assert chunk(xs, n) == expected\n    assert True"),
    FIXTURE.replace(b"import chunk", b"import wrong as chunk"),
    FIXTURE.replace(ROWS, b"load_rows()"),
    FIXTURE.replace(b"params=", b"autouse=True, params="),
    FIXTURE.replace(b"params=", b"scope='module', params="),
    FIXTURE.replace(b"return request.param", b"yield request.param"),
    FIXTURE.replace(b"def test_chunk", b"@pytest.mark.skip\ndef test_chunk"),
    LOOP.replace(b"        assert chunk", b"        if n == 0:\n            assert chunk"),
    LOOP.replace(b"        assert chunk", b"        break\n        assert chunk"),
    LOOP.replace(b"        assert chunk", b"        continue\n        assert chunk"),
])
def test_unsupported_consolidation_gets_no_credit_and_keeps_blocking(after):
    ir, _findings, verdict = run(after)
    assert verdict == "block"
    assert not any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)


@pytest.mark.parametrize("before", [
    BEFORE.replace(b"    assert chunk", b"    assert True\n    assert chunk", 1),
    BEFORE.replace(b"    assert chunk", b"    chunk = other\n    assert chunk", 1),
    BEFORE.replace(b"def test_even():", b"def test_even(extra):"),
    BEFORE + b"\ndef mutate():\n    chunk.__code__ = (lambda *a: []).__code__\n",
    BEFORE + b"\nchunk = other\n",
])
def test_unsafe_or_opaque_baseline_cannot_prove_consolidation(before):
    ir, _findings, _verdict = run(FIXTURE, before)
    assert not any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)


def test_duplicate_case_multiplicity_is_preserved():
    duplicate_before = BEFORE.replace(b"test_remainder", b"test_even_again").replace(
        b"[1, 2, 3, 4, 5]", b"[1, 2, 3, 4]").replace(b"[[1, 2], [3, 4], [5]]", b"[[1, 2], [3, 4]]")
    duplicate_after = FIXTURE.replace(b"[1, 2, 3, 4, 5]", b"[1, 2, 3, 4]").replace(
        b"[[1, 2], [3, 4], [5]]", b"[[1, 2], [3, 4]]")
    ir, findings, verdict = run(duplicate_after, duplicate_before)
    assert verdict == "pass"
    assert not findings
    assert len({unit.qualname for unit in ir.files[0].units}) == 2


def test_projection_keeps_real_source_spans_and_concrete_values():
    from checkwash.report.context import ReportContext
    from checkwash.findings import Evidence
    context = ReportContext()
    ir, _findings, _verdict = analyze(
        [FileChange("tests/test_chunk.py", "modified", BEFORE, FIXTURE)],
        Config(), Contract(), [], datetime.date(2026, 9, 6), report_context=context, root_reader={}.get,
        root_searcher=lambda _needles: [],
    )
    unit = ir.files[0].units[1]
    assertion = unit.after.assertions[0]
    assert assertion.left == "chunk([1, 2, 3, 4, 5], 2)"
    assert assertion.right_value == "[[1, 2], [3, 4], [5]]"
    assert context.location("tests/test_chunk.py", Evidence(text=assertion.text, span=assertion.span)) == (
        "tests/test_chunk.py", 10,
    )


def test_other_changed_files_preclude_local_consolidation_proof():
    extra = (FileChange("src/app/chunk.py", "modified", b"x = 1\n", b"x = 2\n"),)
    ir, _findings, _verdict = run(FIXTURE, extra=extra)
    assert not any(unit.qualname.startswith("test_concrete_") for file in ir.files for unit in file.units)


def test_local_literal_table_can_be_bound_once_before_loop():
    after = LOOP.replace(b"    for xs, n, expected in " + ROWS,
                         b"    rows = " + ROWS + b"\n    for xs, n, expected in rows")
    _ir, findings, verdict = run(after)
    assert verdict == "pass"
    assert not findings


@pytest.mark.parametrize("after", [FIXTURE, PARAMETRIZE, LOOP])
def test_new_rows_can_follow_all_the_preserved_cases(after):
    after = after.replace(ROWS, ROWS[:-1] + b", ([], 2, [])]")
    ir, findings, verdict = run(after)
    assert verdict == "pass"
    assert not findings
    assert len(ir.files[0].units) == 3


def test_mutable_row_cannot_be_both_subject_input_and_expected():
    before = b'''from app.clean import clean
def test_first():
    assert clean([1]) == [1]
def test_second():
    assert clean([2]) == [2]
'''
    after = b'''from app.clean import clean
import pytest
@pytest.fixture(params=[[1], [2]])
def data(request):
    return request.param
def test_clean(data):
    xs = data
    assert clean(xs) == xs
'''
    ir, _findings, verdict = run(after, before)
    assert verdict == "block"
    assert not any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)


def test_repeated_row_subject_arguments_cannot_hide_object_identity_bug(tmp_path):
    import os
    import subprocess
    import sys

    before = b'''from app.identity import check
def test_first():
    assert check([1], [1]) is True
def test_second():
    assert check([2], [2]) is True
'''
    after = b'''from app.identity import check
import pytest
@pytest.mark.parametrize("value", [[1], [2]])
def test_identity(value):
    assert check(value, value) is True
'''
    production = b"def check(a, b):\n    return a is b\n"
    snapshot = {"app/__init__.py": b"", "app/identity.py": production}
    for side, source, status in (("before", before, 1), ("after", after, 0)):
        checkout = tmp_path / side
        for path, data in {**snapshot, "tests/test_identity.py": source}.items():
            target = checkout / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "tests/test_identity.py"], cwd=checkout,
            capture_output=True, text=True, timeout=30,
            env=dict(os.environ, PYTHONPATH=str(checkout), PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"),
        )
        assert result.returncode == status, result.stdout + result.stderr
    ir, _findings, _verdict = run(after, before, snapshot=snapshot)
    # The ordinary compensation policy may still allow this unsupported
    # table; the precision projection must not remove its evidence.
    assert not any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)


def test_consolidation_supports_crlf_source():
    _ir, findings, verdict = run(FIXTURE.replace(b"\n", b"\r\n"), BEFORE.replace(b"\n", b"\r\n"))
    assert verdict == "pass"
    assert not findings


def test_unknown_snapshot_cannot_prove_fixture_lifecycle_is_unchanged():
    ir, _findings, verdict = analyze(
        [FileChange("tests/test_chunk.py", "modified", BEFORE, LOOP)],
        Config(), Contract(), [], datetime.date(2026, 9, 6),
    )
    assert verdict == "block"
    assert not any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)


@pytest.mark.parametrize("path", ["pytest.py", "src/pytest.py", "tests/pytest.py", "pytest/__init__.py"])
@pytest.mark.parametrize("after", [FIXTURE, PARAMETRIZE])
def test_local_pytest_substitute_cannot_grant_table_projection(path, after):
    # Even an empty local module shadows the imported decorator authority.
    ir, _findings, _verdict = run(after, snapshot={path: b""})
    assert not any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)


@pytest.mark.parametrize("error", [OSError("read failed"), ValueError("incomplete snapshot")])
def test_snapshot_failure_is_not_treated_as_known_absence(error):
    def reader(_path):
        raise error
    with pytest.raises(type(error), match=str(error)):
        analyze([FileChange("tests/test_chunk.py", "modified", BEFORE, LOOP)],
                Config(), Contract(), [], datetime.date(2026, 9, 6), root_reader=reader,
                root_searcher=lambda _needles: [])


@pytest.mark.parametrize("path", ["conftest.py", "tests/conftest.py", "tests/__init__.py"])
def test_ancestor_execution_precludes_consolidation_proof(path):
    ir, _findings, verdict = run(LOOP, snapshot={path: b"reset_subject_state()\n"})
    assert verdict == "block"
    assert not any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)


def test_unchanged_autouse_reset_can_make_a_loop_hide_the_bug(tmp_path):
    import os
    import subprocess
    import sys

    production = b'''count = 0
def next_value():
    global count
    count += 1
    return count
'''
    conftest = b'''import pytest
from app import counter
@pytest.fixture(autouse=True)
def reset():
    counter.count = 0
'''
    before = b'''from app.counter import next_value
def test_one():
    assert next_value() == 1
def test_two():
    assert next_value() == 2
'''
    after = b'''from app.counter import next_value
def test_values():
    for expected in [1, 2]:
        assert next_value() == expected
'''
    snapshot = {"app/__init__.py": b"", "app/counter.py": production, "conftest.py": conftest}
    for side, tests, expected_status in (("before", before, 1), ("after", after, 0)):
        checkout = tmp_path / side
        checkout.mkdir()
        for path, data in {**snapshot, "tests/test_counter.py": tests}.items():
            target = checkout / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        outcome = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "tests/test_counter.py", "--confcutdir", str(checkout)],
            cwd=checkout, capture_output=True, text=True, timeout=30,
            env=dict(os.environ, PYTHONPATH=str(checkout), PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"),
        )
        assert outcome.returncode == expected_status, outcome.stdout + outcome.stderr
    ir, _findings, verdict = run(after, before, snapshot=snapshot)
    assert verdict == "block"
    assert not any(unit.qualname.startswith("test_concrete_") for unit in ir.files[0].units)
