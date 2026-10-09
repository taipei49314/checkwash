"""Remote-only #357 mutation checks; assertion failures alone count as kills."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile

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
]


def main():
    output = ROOT / 'review-output'
    output.mkdir(exist_ok=True)
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
            result = subprocess.run(
                [sys.executable, '-m', 'pytest', '-o', 'addopts=', '-q',
                 str(ROOT / 'tests/test_issue357_helper_guards.py')],
                cwd=directory, env={**os.environ, 'PYTHONPATH': str(src),
                                    'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1'},
                capture_output=True, text=True, timeout=180,
            )
            log = result.stdout + result.stderr
            killed = result.returncode == 1 and 'FAILED ' in log and 'ERROR ' not in log
            records.append({'name': label, 'exit_code': result.returncode, 'killed': killed})
            (output / (label.replace(' ', '-') + '.log')).write_text(log, encoding='utf-8')
            print(label, 'KILLED' if killed else 'NOT_KILLED', flush=True)
    (output / 'mutants.json').write_text(json.dumps(records, indent=2) + '\n', encoding='utf-8')
    return 0 if all(row['killed'] for row in records) else 1


if __name__ == '__main__':
    sys.exit(main())
