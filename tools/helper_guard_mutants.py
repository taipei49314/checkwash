"""Remote-only #357 mutation checks; assertion failures alone count as kills."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
HELPERS = 'checkwash/frontends/python/helper_skips.py'
MUTANTS = [
    ('drop guarded outcomes', HELPERS,
     'for helper, effect, evidence, conds in self._helpers.of(name, target, self._bindings)',
     'for helper, effect, evidence, conds in self._helpers.of(name, target, self._bindings) if not conds'),
    ('lose conditions', HELPERS,
     '(helper, effect, self._foreign(evidence, helper), conds)',
     '(helper, effect, self._foreign(evidence, helper), ())'),
    ('read test scope', HELPERS,
     'HelperGuard(tree, self._text.seg, self._text.span)',
     'lambda node: self._text.seg(node) or ast.unparse(node)'),
    ('compat token prefix', HELPERS, "_prefix = 'helper'", "_prefix = 'platform'"),
    ('nested local leakage', HELPERS,
     'bound = bound | _shadowed(node)', 'bound = bound'),
    ('lose enclosing bindings', HELPERS,
     'bound = bound | _shadowed(node)', 'bound = _shadowed(node)'),
    ('reuse stale module constants', HELPERS,
     'if name not in uncertain', 'if True'),
]


def mutation_evidence(path, returncode, expected_cases):
    """Separate assertion failures from crashes using per-test JUnit evidence."""
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return {'collected': 0, 'assertion_failures': 0, 'runtime_failures': 0,
                'collection_or_setup_errors': 0, 'skipped': 0, 'case_identity_complete': False,
                'evidence_error': 'missing_or_invalid_junit', 'killed': False}
    cases = root.findall('.//testcase')
    identities = [(case.get('classname'), case.get('name')) for case in cases]
    failures = [failure for case in cases for failure in case.findall('failure')]
    assertions = [failure for failure in failures
                  if (failure.get('message', '').lstrip().startswith(('assert ', 'AssertionError')))]
    errors = sum(len(case.findall('error')) for case in cases)
    skipped = sum(len(case.findall('skipped')) for case in cases)
    complete = (bool(cases) and len(identities) == len(set(identities))
                and set(identities) == set(expected_cases))
    return {
        'collected': len(cases), 'assertion_failures': len(assertions),
        'runtime_failures': len(failures) - len(assertions),
        'collection_or_setup_errors': errors, 'skipped': skipped,
        'case_identity_complete': complete,
        'killed': (returncode == 1 and complete and bool(assertions)
                   and len(assertions) == len(failures) and not errors and not skipped),
    }


def main():
    output = ROOT / 'review-output'
    output.mkdir(exist_ok=True)
    baseline = subprocess.run(
        [sys.executable, '-m', 'pytest', '-o', 'addopts=', '-q',
         '--junitxml=' + str(output / 'mutant-baseline.xml'),
         str(ROOT / 'tests/test_issue357_helper_guards.py')],
        cwd=ROOT, env={**os.environ, 'PYTHONPATH': str(ROOT / 'src'),
                       'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1'},
        capture_output=True, text=True, timeout=180,
    )
    (output / 'mutant-baseline.log').write_text(baseline.stdout + baseline.stderr, encoding='utf-8')
    if baseline.returncode != 0:
        raise RuntimeError('The unmodified test baseline must pass before measuring mutants')
    baseline_cases = ET.parse(output / 'mutant-baseline.xml').getroot().findall('.//testcase')
    expected_cases = {(case.get('classname'), case.get('name')) for case in baseline_cases}
    baseline_evidence = mutation_evidence(output / 'mutant-baseline.xml', baseline.returncode, expected_cases)
    if (not baseline_evidence['case_identity_complete'] or baseline_evidence['assertion_failures']
            or baseline_evidence['runtime_failures'] or baseline_evidence['collection_or_setup_errors']
            or baseline_evidence['skipped']):
        raise RuntimeError('Complete unmodified per-test evidence is required')
    records = []
    for label, relative, old, new in MUTANTS:
        with tempfile.TemporaryDirectory(prefix='checkwash-helper-mutant-') as directory:
            src = Path(directory) / 'src'
            shutil.copytree(ROOT / 'src', src)
            path = src / relative
            text = path.read_text(encoding='utf-8')
            if text.count(old) != 1:
                raise RuntimeError(f'{label}: anchor must match exactly once')
            path.write_text(text.replace(old, new, 1), encoding='utf-8')
            junit = output / (label.replace(' ', '-') + '.xml')
            try:
                result = subprocess.run(
                    [sys.executable, '-m', 'pytest', '-o', 'addopts=', '-q',
                     '--junitxml=' + str(junit),
                     str(ROOT / 'tests/test_issue357_helper_guards.py')],
                    cwd=directory, env={**os.environ, 'PYTHONPATH': str(src),
                                        'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1'},
                    capture_output=True, text=True, timeout=180,
                )
                code, log = result.returncode, result.stdout + result.stderr
            except subprocess.TimeoutExpired as error:
                code = 'timeout'
                log = ''.join(part.decode('utf-8', 'replace') if isinstance(part, bytes) else part
                              for part in (error.stdout or '', error.stderr or ''))
            evidence = mutation_evidence(junit, code, expected_cases)
            killed = evidence['killed']
            records.append({'name': label, 'exit_code': code, **evidence})
            (output / (label.replace(' ', '-') + '.log')).write_text(log, encoding='utf-8')
            print(label, 'KILLED' if killed else 'NOT_KILLED', flush=True)
    (output / 'mutants.json').write_text(json.dumps(records, indent=2) + '\n', encoding='utf-8')
    return 0 if all(row['killed'] for row in records) else 1


if __name__ == '__main__':
    sys.exit(main())
