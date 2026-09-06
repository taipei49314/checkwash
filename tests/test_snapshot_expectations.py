"""Stored oracle rewrites are judged without running arbitrary repository code."""
import datetime
import json
import os
import subprocess
import sys

import pytest

from checkwash.allowlist import AllowEntry
from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze

TODAY = datetime.date(2026, 9, 6)


def check(changes, entries=()):
    return analyze(changes, Config(), Contract(), list(entries), TODAY)


@pytest.mark.parametrize('path', [
    'tests/golden/invoice.txt', 'tests/expected/invoice.txt',
    'tests/invoice.expected', 'tests/__snapshots__/invoice.snap',
])
def test_golden_only_rewrite_hides_a_real_bug_but_must_block(tmp_path, path):
    """The issue's actual red->green laundering, with production/test bytes fixed."""
    target = tmp_path / path
    target.parent.mkdir(parents=True)
    target.write_bytes(b'105.3\n')
    production = tmp_path / 'billing.py'
    production.write_text('def invoice_total():\n    return "104.0"\n', encoding='utf-8')
    test = tmp_path / 'tests/test_invoice.py'
    test.write_text(
        'from pathlib import Path\nfrom billing import invoice_total\n'
        f'def test_invoice():\n    assert invoice_total() == Path({path!r}).read_text().strip()\n',
        encoding='utf-8',
    )
    fixed = (production.read_bytes(), test.read_bytes())
    env = {**os.environ, 'PYTHONPATH': str(tmp_path), 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1'}
    before = subprocess.run([sys.executable, '-m', 'pytest', '-q', 'tests'], cwd=tmp_path,
                            env=env, capture_output=True, timeout=30)
    assert before.returncode == 1 and b'AssertionError' in before.stdout
    target.write_bytes(b'104.0\n')
    after = subprocess.run([sys.executable, '-m', 'pytest', '-q', 'tests'], cwd=tmp_path,
                           env=env, capture_output=True, timeout=30)
    assert after.returncode == 0, after.stdout.decode(errors='replace')
    assert fixed == (production.read_bytes(), test.read_bytes())
    ir, findings, verdict = check([FileChange(path, 'modified', b'105.3\n', b'104.0\n')])
    assert verdict == 'block'
    hit, = findings
    assert hit.rule == 'EXPECTED_VALUE_CHANGED' and hit.severity == 'high'
    assert ir.files[0].role == 'snapshot'
    assert '/-/v2:' in hit.fingerprint


def test_comment_does_not_explain_rewriting_the_stored_expectation():
    _, findings, verdict = check([
        FileChange('tests/golden/invoice.txt', 'modified', b'105.3\n', b'104.0\n'),
        FileChange('billing.py', 'modified', b'def total():\n    return 104\n',
                   b'def total():\n    return 104  # noqa\n'),
    ])
    assert verdict == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' and f.severity == 'high' for f in findings)


def test_real_production_cochange_keeps_the_existing_cochange_policy():
    _, findings, verdict = check([
        FileChange('tests/golden/invoice.txt', 'modified', b'105.3\n', b'104.0\n'),
        FileChange('billing.py', 'modified', b'def total():\n    return 105.3\n',
                   b'def total():\n    return 104.0\n'),
    ])
    assert verdict == 'pass'
    assert [(f.rule, f.severity) for f in findings] == [('SNAPSHOT_CODE_COCHANGE', 'warn')]


@pytest.mark.parametrize('path,status,before,after', [
    ('tests/golden/invoice.txt', 'added', None, b'104.0\n'),
    ('tests/golden/invoice.txt', 'modified', b'104.0\r\n', b'104.0\n'),
    ('tests/data/invoice.txt', 'modified', b'105.3\n', b'104.0\n'),
])
def test_new_unchanged_or_unclassified_data_is_not_a_rewritten_expectation(path, status, before, after):
    _, findings, verdict = check([FileChange(path, status, before, after)])
    assert verdict == 'pass'
    assert not any(f.rule == 'EXPECTED_VALUE_CHANGED' for f in findings)


def test_snapshot_approval_is_specific_to_both_contents_and_preserves_spaces():
    path = 'tests/invoice.expected'
    first = FileChange(path, 'modified', b'105.3\n', b'104.0\n')
    _, initial, _ = check([first])
    hit, = initial
    entry = AllowEntry(fingerprint=hit.fingerprint, rule=hit.rule, reason='reviewed change',
                       author='reviewer', created=TODAY.isoformat(),
                       expires=(TODAY + datetime.timedelta(days=1)).isoformat())
    _, approved, verdict = check([first], [entry])
    assert verdict == 'pass' and approved[0].allowlisted
    for before, after in [(b'105.3\n', b'104.0 \n'), (b'105.3 \n', b'104.0\n')]:
        _, findings, verdict = check([FileChange(path, 'modified', before, after)], [entry])
        assert verdict == 'block' and not findings[0].allowlisted
        assert findings[0].fingerprint != hit.fingerprint


def test_snapshot_detection_uses_roundtrippable_ir_evidence():
    from checkwash.engine import run_detectors
    from checkwash.ir.model import IR, FileIR, ChangeEvidence, DiffGlobals, to_jsonable
    ir, findings, _ = check([FileChange('tests/a.expected', 'modified', b'good', b'bad')])
    payload = json.loads(json.dumps(to_jsonable(ir)))
    files = []
    for item in payload.pop('files'):
        item['change_evidence'] = ChangeEvidence(**item['change_evidence'])
        files.append(FileIR(**item))
    reconstructed = IR(files=files, globals=DiffGlobals(**payload.pop('globals')), **payload)
    assert [f.fingerprint for f in run_detectors(reconstructed, Config())] == [f.fingerprint for f in findings]


def test_stored_expectation_keys_are_validated_without_retiring_assertion_keys():
    from checkwash.findings import fingerprint_state
    _, findings, _ = check([FileChange('tests/a.expected', 'modified', b'good', b'bad')])
    key = findings[0].fingerprint
    assert fingerprint_state(key) == 'supported'
    assert fingerprint_state(key[:-1]) == 'invalid'
    assert fingerprint_state(key, 'ASSERT_REMOVED') == 'invalid'
    assert fingerprint_state(key.replace('/-/v2:', '/test_fake/v2:')) == 'invalid'
    assert fingerprint_state('EXPECTED_VALUE_CHANGED/v2:broken') == 'invalid'
    assert fingerprint_state('EXPECTED_VALUE_CHANGED/tests/test_api.py/test_one/abcdef123456') == 'supported'


def test_stored_expectation_sarif_uses_content_bound_version():
    from checkwash.report.sarif import _result
    _, findings, _ = check([FileChange('tests/a.expected', 'modified', b'good', b'bad')])
    hit, = findings
    assert _result(hit, None)['partialFingerprints'] == {'checkwash/v2': hit.fingerprint}


def test_unrelated_production_change_retains_existing_snapshot_cochange_policy():
    _, findings, verdict = check([
        FileChange('tests/golden/invoice.txt', 'modified', b'105.3', b'104.0'),
        FileChange('unused.py', 'added', None, b'def unrelated():\n    return 3\n'),
    ])
    assert verdict == 'pass'
    assert not any(f.rule == 'EXPECTED_VALUE_CHANGED' for f in findings)


def test_missing_stored_expectation_evidence_is_an_engine_error():
    from checkwash.change import EngineError
    from checkwash.engine import run_detectors
    ir, _, _ = check([FileChange('tests/a.expected', 'modified', b'good', b'bad')])
    ir.files[0].change_evidence = None
    with pytest.raises(EngineError, match='missing content-bound'):
        run_detectors(ir, Config())
