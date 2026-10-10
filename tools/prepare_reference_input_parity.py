"""Remote-only original synthetic corpus parity, never historical/held-out data."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BASE = '8c70efbf93975bf3210acb8eafbaf4b38044a770'
ALLOWED = {'src/checkwash/cli.py', 'src/checkwash/gitio/__init__.py',
           'src/checkwash/gitio/git.py', 'src/checkwash/gitio/snapshot.py', 'src/checkwash/sweep.py'}


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args], timeout=90)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('COMPUTERNAME', '').upper() == 'LAPTOP-16NUA5I8':
        raise ValueError('remote synthetic qualification only')
    out = ROOT / 'reference-input-receipts'
    out.mkdir(exist_ok=True)
    current = git('rev-parse', 'HEAD').decode().strip()
    changed = set(git('diff', '--name-only', BASE, current, '--', 'src').decode().splitlines())
    if not changed or not changed <= ALLOWED:
        raise ValueError('reference detector or policy source changed')
    if git('diff', BASE, current, '--', 'tests/cases', 'tests/gates', 'SPEC.md', 'THREATMODEL.md', 'DECISIONS.md',
           'tools/emit_corpus.py', 'pyproject.toml'):
        raise ValueError('original fixtures, oracle, emitter or version changed')
    report = dict(schema='reference-input-parity-v1', source=current, original_reference=BASE,
                  run_id=os.environ['GITHUB_RUN_ID'], run_attempt=os.environ['GITHUB_RUN_ATTEMPT'],
                  changed_source=sorted(changed), synthetic_only=True, adopted=False, ready=False,
                  byte_equal=False, observations={})
    try:
        with tempfile.TemporaryDirectory(prefix='original-reference-') as temporary:
            old = Path(temporary) / 'checkout'
            subprocess.run(['git', 'clone', '--no-hardlinks', '--no-checkout', str(ROOT), str(old)], check=True, capture_output=True, timeout=90)
            subprocess.run(['git', '-C', str(old), 'checkout', '--detach', BASE], check=True, capture_output=True, timeout=90)
            results = {}
            for name, checkout in (('original', old), ('proposed', ROOT)):
                env = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONHASHSEED': '0', 'CHECKWASH_TODAY': '2026-01-01'}
                done = subprocess.run([sys.executable, '-I', '-B', str(checkout/'tools/emit_corpus.py')],
                                      cwd=checkout, env=env, capture_output=True, timeout=300)
                (out/(name+'-corpus.json')).write_bytes(done.stdout)
                (out/(name+'-stderr.txt')).write_bytes(done.stderr)
                report['observations'][name] = dict(exit_code=done.returncode, bytes=len(done.stdout),
                    sha256=digest(done.stdout), stderr_sha256=digest(done.stderr),
                    case_headers=sum(line.startswith(b'# ') for line in done.stdout.splitlines()))
                if done.returncode != 0 or done.stderr or not done.stdout:
                    raise ValueError('synthetic corpus emitter did not complete cleanly')
                results[name] = done.stdout
            report['byte_equal'] = results['original'] == results['proposed']
            if not report['byte_equal']:
                raise ValueError('readable original-reference corpus changed')
    finally:
        (out/'parity.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
