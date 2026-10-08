"""Kill independent #358 fallback mutants in isolated source copies.

Run on remote CI/pool, never on a work-machine. Each substitution must
match once, and collection/import errors are not accepted as mutant kills.
"""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
OWN = 'checkwash/frontends/python/own_marks.py'
MUTANTS = [
    ('fixture params', OWN, 'node.arg == "params"', 'node.arg == "never_params"'),
    ('hook bindings', OWN, 'name.startswith("pytest_")', 'name.startswith("never_pytest_")'),
    ('object marker assignment', OWN, 'node.attr in {"pytestmark", "keywords"}', 'False'),
    ('mark mutating call', OWN, 'id(node) not in read_calls and _mark_name(full) is not None', 'False'),
    ('module getattr', OWN, '"__getattr__", "__init_subclass__", "bool",', '"never_getattr", "__init_subclass__", "bool",'),
    ('fixture request binding', 'checkwash/frontends/python/setup_skip_controls.py',
     "return 'request' not in _names(function.body)", 'return True'),
    ('config plugin marks', 'checkwash/engine.py', 'if configured_marks:', 'if False:'),
    ('metaclass', OWN, 'isinstance(node, ast.ClassDef) and node.keywords', 'False'),
]


def main():
    output = ROOT / 'review-output'
    output.mkdir(exist_ok=True)
    records = []
    for label, relative, old, new in MUTANTS:
        with tempfile.TemporaryDirectory(prefix='checkwash-mutant-') as directory:
            source = Path(directory) / 'src'
            shutil.copytree(ROOT / 'src', source)
            path = source / relative
            text = path.read_text(encoding='utf-8')
            if text.count(old) != 1:
                raise RuntimeError(f'{label}: anchor must match exactly once')
            path.write_text(text.replace(old, new, 1), encoding='utf-8')
            result = subprocess.run(
                [sys.executable, '-m', 'pytest', '-o', 'addopts=', '-q',
                 str(ROOT / 'tests/test_issue358_review.py')],
                cwd=directory,
                env={**os.environ, 'PYTHONPATH': str(source), 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1'},
                capture_output=True, text=True, timeout=180,
            )
            log = result.stdout + result.stderr
            # Pytest exit 1 plus an assertion failure: exit 2/3/4/5 and
            # import/collection errors cannot masquerade as a detection.
            killed = result.returncode == 1 and 'FAILED ' in log and 'ERROR ' not in log
            records.append({'name': label, 'exit_code': result.returncode, 'killed': killed})
            (output / (label.replace(' ', '-') + '.log')).write_text(log, encoding='utf-8')
            print(label, 'KILLED' if killed else 'NOT_KILLED', flush=True)
    (output / 'mutants.json').write_text(json.dumps(records, indent=2) + '\n', encoding='utf-8')
    return 0 if all(row['killed'] for row in records) else 1


if __name__ == '__main__':
    sys.exit(main())
