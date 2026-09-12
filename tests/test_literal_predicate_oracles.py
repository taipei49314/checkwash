"""Literal helper predicates preserve the equality versus identity contract."""

import datetime
from pathlib import Path

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.gitio.snapshot import search_source_mapping


PATH = 'tests/test_numbers.py'
HEADER = 'from app.numbers import positive\n'
BEFORE = (HEADER + 'def test_first():\n    assert positive(1) is True\n'
          'def test_second():\n    assert positive(0) is False\n').encode()
LAMBDA = (HEADER + 'def check(value, pred):\n    assert pred(positive(value))\n'
          'def test_first():\n    check(1, lambda r: r is True)\n'
          'def test_second():\n    check(0, lambda r: r is False)\n').encode()
OPERATOR = (HEADER + 'import operator\n'
            'def check(got, expected):\n    assert operator.is_(got, expected)\n'
            'def test_first():\n    check(positive(1), True)\n'
            'def test_second():\n    check(positive(0), False)\n').encode()


def run(after, before=BEFORE, context=None):
    snapshot = {PATH: after, **(context or {})}
    return analyze([FileChange(PATH, 'modified', before, after)], Config(), Contract(), [],
                   datetime.date(2026, 9, 12), root_reader=snapshot.get,
                   root_searcher=lambda needles: search_source_mapping(snapshot, needles))


def projected(ir):
    return any(unit.qualname.startswith('test_concrete_') for file in ir.files for unit in file.units)


@pytest.mark.parametrize('after', [LAMBDA, OPERATOR])
def test_closed_literal_predicates_keep_subjects_and_identity(after):
    ir, findings, verdict = run(after)
    assert projected(ir) and verdict == 'pass'
    assert not findings


def test_a_lambda_parameter_name_does_not_capture_a_helper_parameter():
    ir, findings, verdict = run(LAMBDA.replace(b'lambda r: r', b'lambda value: value'))
    assert projected(ir) and verdict == 'pass'
    assert not findings


@pytest.mark.parametrize('after', [LAMBDA.replace(b'is True', b'is False'),
                                    OPERATOR.replace(b'positive(1), True', b'positive(1), False')])
def test_literal_predicates_cannot_hide_answer_rewrites(after):
    ir, findings, verdict = run(after)
    assert projected(ir) and verdict == 'block'
    assert any(finding.rule == 'EXPECTED_VALUE_CHANGED' and finding.severity == 'high' for finding in findings)


@pytest.mark.parametrize('after', [
    LAMBDA.replace(b'lambda r: r is True', b'lambda r: True'),
    LAMBDA.replace(b'lambda r: r is True', b'lambda r: mask(r) is True'),
    LAMBDA.replace(b'lambda r: r is True', b'lambda r: r == True'),
    LAMBDA.replace(b'lambda r: r is True', b'lambda r: r is want'),
    OPERATOR.replace(b'operator.is_(got, expected)', b'operator.eq(got, expected)'),
    OPERATOR.replace(b'operator.is_(got, expected)', b'operator.is_(positive(1), expected)'),
    OPERATOR.replace(b'check(positive(1), True)', b'check(mask(positive(1)), True)'),
    OPERATOR.replace(b'def check(got, expected)', b'def check(operator, expected)'),
])
def test_unproved_predicates_changed_strength_and_discarded_calls_get_no_credit(after):
    ir, _findings, _verdict = run(after)
    assert not projected(ir)


def test_operator_module_authority_must_not_be_repository_local():
    ir, _findings, _verdict = run(OPERATOR, context={'operator.py': b''})
    assert not projected(ir)


@pytest.mark.parametrize('case_name', ['CASE_022_safe_div', 'CASE_025_all_equal'])
def test_retained_operator_and_lambda_sources_preserve_every_original_oracle(case_name):
    case = Path(__file__).parents[1] / 'benchmarks' / 'refactors' / 'cases' / case_name
    before_root, after_root = case / 'before', case / 'after'
    before = {path.relative_to(before_root).as_posix(): path.read_bytes() for path in before_root.rglob('*') if path.is_file()}
    after = {path.relative_to(after_root).as_posix(): path.read_bytes() for path in after_root.rglob('*') if path.is_file()}
    changes = [FileChange(path, 'modified', before[path], after[path]) for path in before.keys() & after.keys()
               if before[path] != after[path]]
    ir, findings, verdict = analyze(changes, Config(), Contract(), [], datetime.date(2026, 9, 12),
                                    root_reader=after.get,
                                    root_searcher=lambda needles: search_source_mapping(after, needles))
    assert projected(ir) and verdict == 'pass'
    assert not findings
