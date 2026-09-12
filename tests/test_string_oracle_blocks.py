"""A helper retains all three string checks and evaluates the subject once."""

import datetime
from pathlib import Path

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.gitio.snapshot import search_source_mapping


PATH = 'tests/test_rpad.py'
CASE = Path(__file__).parents[1] / 'benchmarks/refactors/cases/EXT_005_rpad'
BEFORE = (CASE / 'BEFORE' / PATH).read_bytes()
AFTER = (CASE / 'AFTER' / PATH).read_bytes()
PRODUCTION = (CASE / 'PROD-GOOD/src/app/rpad.py').read_bytes()


def run(after=AFTER, before=BEFORE, production=PRODUCTION, context=None):
    snapshot = {PATH: after, 'src/app/rpad.py': production, 'src/app/__init__.py': b'', **(context or {})}
    if production is None:
        snapshot.pop('src/app/rpad.py')
    return analyze([FileChange(PATH, 'modified', before, after)], Config(), Contract(), [],
                   datetime.date(2026, 9, 12), root_reader=snapshot.get,
                   root_searcher=lambda needles: search_source_mapping(snapshot, needles))


def projected(ir):
    return any(unit.qualname.startswith('test_concrete_') for file in ir.files for unit in file.units)


def test_retained_rpad_helper_keeps_every_check_and_the_single_call_in_both_directions():
    for before, after in [(BEFORE, AFTER), (AFTER, BEFORE)]:
        ir, findings, verdict = run(after, before)
        assert projected(ir) and verdict == 'pass'
        assert not findings
        assert len(ir.files[0].units) == 2
        assert all(len(unit.before.assertions) == len(unit.after.assertions) == 3 for unit in ir.files[0].units)


def test_changed_final_expected_value_remains_high_with_auxiliary_checks_retained():
    ir, findings, verdict = run(AFTER.replace(b'"hi..."', b'"wrong"'))
    assert projected(ir) and verdict == 'block'
    assert any(finding.rule == 'EXPECTED_VALUE_CHANGED' and finding.severity == 'high' for finding in findings)


@pytest.mark.parametrize('after', [
    AFTER.replace(b'assert len(got) == max(len(s), width)', b'assert len(got) >= 0'),
    AFTER.replace(b'    assert got.startswith(s)\n', b''),
    AFTER.replace(b'got.startswith(s)', b'got.startswith("")'),
    AFTER.replace(b'max(len(s), width)', b'len(s)'),
    AFTER.replace(b'    assert got == expected', b'    install_patch()\n    assert got == expected'),
    AFTER.replace(b'from app.rpad import rpad', b'from app.rpad import rpad\nfrom custom import len'),
])
def test_changed_or_dropped_auxiliary_oracles_and_builtin_shadowing_receive_no_credit(after):
    ir, _findings, _verdict = run(after)
    assert not projected(ir)


@pytest.mark.parametrize('production', [
    None,
    b'counter = 0\ndef rpad(s, width, fill=" "):\n    global counter\n    counter += 1\n    return s\n',
    b'import builtins\nbuiltins.max = lambda *args: 5\ndef rpad(s, width, fill=" "):\n    return s\n',
    b'def rpad(s, width, fill=" "):\n    return external(s)\n',
    b'class Text:\n    def __len__(self):\n        mutate()\ndef rpad(s, width, fill=" "):\n    return Text()\n',
    b'def __getattr__(name):\n    raise ValueError("stop")\ndef rpad(s, width, fill=" "):\n    return s\n',
    b'def set():\n    raise ValueError("stop")\ndef rpad(s, width, fill=set()):\n    return s\n',
])
def test_multicheck_constant_specialization_requires_closed_pure_production(production):
    ir, _findings, _verdict = run(production=production)
    assert not projected(ir)


def test_production_package_initializers_and_ambiguous_import_roots_preclude_purity():
    for context in [{'src/app/__init__.py': b'install_patch()\n'}, {'app/rpad.py': PRODUCTION}]:
        ir, _findings, _verdict = run(context=context)
        assert not projected(ir)


@pytest.mark.parametrize('hook', ['setup_function', 'teardown_function', 'setup_module', 'pytest_generate_tests'])
def test_string_helpers_cannot_erase_implicit_module_entry_points(hook):
    after = AFTER.replace(b'assert_rpadded', hook.encode())
    ir, _findings, _verdict = run(after)
    assert not projected(ir)
