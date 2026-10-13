"""SOURCE_ONLY future hosted preflight; trusted owned inputs, no verdict decoding."""
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import tarfile
import time
from pathlib import Path

ENGINE = 'fa11d5f305cb2cce77f9e389939d0b607a78d908'
SOURCE = os.environ.get('COLLECTOR_SOURCE_SHA', '')
HELPER_SHA = 'fc2cc0629b83d4a5f0f0db2fe571b4318ced037c17781a1cfa6472024f63a381'
CONTRACT_SHA = '38dc62ea33988cf18e7de4388816b7bbf05f4dcdf6676ba332e1d400d2950524'
V3_SEAL = '6349812df5b8c24666233c15a3502581eb16b2e302ecac08a34f462ca823f7c1'
PYPROJECT_SHA = 'fe795f69d6771fd9726128078a9fa3d0ab7ccbe76f516505c123cf0155006574'
NODE_URL = 'https://nodejs.org/dist/v22.21.1/node-v22.21.1-linux-x64.tar.xz'
NODE_SHA = '680d3f30b24a7ff24b98db5e96f294c0070f8f9078df658da1bce1b9c9873c88'
PINS = ['pip==25.0.1', 'pytest==8.4.2', 'iniconfig==2.3.1', 'packaging==26.3',
        'pluggy==1.6.0', 'Pygments==2.21.0']


def identity(path):
    return {'path': str(path), 'bytes': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def save(path, data):
    with path.open('x', encoding='utf-8') as output:
        output.write(json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + '\n')
        output.flush()
        os.fsync(output.fileno())
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def verify(path, expected):
    if not path.is_file() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('regular source file required: ' + str(path))
    found = identity(path)
    if found['sha256'] != expected['sha256'] or found['bytes'] != expected['bytes']:
        raise ValueError('source byte mismatch: ' + str(path))
    if 'git_blob' in expected:
        raw = path.read_bytes()
        blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        if blob != expected['git_blob']:
            raise ValueError('source blob mismatch')


DISTRIBUTIONS = """
import hashlib, importlib.metadata, json, pathlib, sys
root = pathlib.Path(sys.prefix).resolve()
result = []
for dist in sorted(importlib.metadata.distributions(), key=lambda d: d.metadata['Name'].lower()):
    files = []
    for member in dist.files or []:
        path = pathlib.Path(dist.locate_file(member)).absolute()
        if not path.is_file() or path.is_symlink():
            raise ValueError('distribution file absent/symlink')
        path.relative_to(root)
        raw = path.read_bytes()
        files.append(dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
    result.append(dict(name=dist.metadata['Name'], version=dist.version, files=files))
print(json.dumps(result, sort_keys=True))
"""


def build(collector, observer, run_root):
    prep = run_root / 'prep'
    expected = json.loads((prep / 'expected24.json').read_text())
    setup, preflight, missing = {}, {}, None
    try:
        if os.name != 'posix' or sys.version_info[:3] != (3, 12, 15):
            raise ValueError('exact hosted CPython3.12.15/POSIX required')
        if len(SOURCE) != 40 or any(c not in '0123456789abcdef' for c in SOURCE):
            raise ValueError('unbound reviewed collector source commit')
        stage = collector / 'tools' / 'owned_env_evidence'
        helper_path, contract_path = stage / 'capture_owned_env.py', stage / 'INPUT-CONTRACT.json'
        if not helper_path.is_file() or helper_path.is_symlink() or not contract_path.is_file() or contract_path.is_symlink():
            raise ValueError('regular helper/contract sources required')
        if identity(helper_path)['sha256'] != HELPER_SHA or identity(contract_path)['sha256'] != CONTRACT_SHA:
            raise ValueError('reviewed helper/contract pin mismatch')
        contract = json.loads(contract_path.read_text())
        if expected != [s['id'] for s in contract['slots']]:
            raise ValueError('prep expected24 denominator mismatch')
        if contract['engine_subject'] != ENGINE:
            raise ValueError('engine convention mismatch')
        module_spec = importlib.util.spec_from_file_location('owned_capture', helper_path)
        capture = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(capture)
        if any(c in str(run_root) for c in (chr(39), chr(10), chr(13))):
            raise ValueError('unsafe engine bootstrap path')
        roots = {name: run_root / name for name in ('engine', 'runtime', 'input', 'ground_truth', 'pairs', 'evidence')}
        roots['ground_truth'] = run_root / 'ground-truth'
        roots['pairs'] = run_root / 'engine-pairs'
        for name, path in roots.items():
            if name not in ('engine', 'evidence'):
                path.mkdir()
        # Preserve original qualified Git checkout, without symlink dereference.
        shutil.copytree(observer, roots['engine'], symlinks=True)
        package = roots['engine'] / 'src'
        expected_members = {m['path']: m for m in contract['engine_identity']['members']}
        actual_members = {str(p.relative_to(package)) for p in (package / 'checkwash').rglob('*') if not p.is_dir()}
        if actual_members != set(expected_members) or len(actual_members) != 208:
            raise ValueError('qualified complete208 inventory mismatch')
        for name, item in expected_members.items():
            verify(package / name, item)
        verify(roots['engine'] / 'pyproject.toml', {'sha256': PYPROJECT_SHA, 'bytes': 1434, 'git_blob': '58224c2ef90892036379141cd56e490cebd983e8'})
        source_files = []
        for fixture in contract['source_fixtures']:
            for arm in ('before', 'after'):
                relative = Path(fixture['case']) / arm / fixture['repository_path']
                source = stage / 'fixtures' / relative
                verify(source, fixture[arm])
                target = roots['input'] / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())
                target.chmod(0o644)
                source_files.append(identity(target))
        save(prep / 'verified-source.json', {'collector_source_commit': SOURCE, 'helper': identity(helper_path), 'contract': identity(contract_path), 'engine_members': [identity(package / name) for name in sorted(expected_members)], 'inputs': source_files, 'pyproject': identity(roots['engine'] / 'pyproject.toml')})
        runtime = roots['runtime']
        empty_template, temp = runtime / 'empty-git-template', runtime / 'tmp'
        empty_template.mkdir()
        temp.mkdir()
        env = dict(contract['environment_set'], PATH='/usr/bin:/bin', TMPDIR=str(temp), TMP=str(temp), TEMP=str(temp))
        if 'HOME' in os.environ:
            env['HOME'] = os.environ['HOME']
        save(prep / 'child-env.json', env)
        prep_deadline = time.monotonic() + 900

        def command(key, argv, cwd, seconds=30, wanted=None, native=False):
            prefix = prep / ('command-%03d' % (len(setup) + len(preflight)))
            raw = capture.capture(argv, str(cwd), dict(env), prefix, seconds, 8388608, None if key == 'capture-wrapper' else prep_deadline)
            receipt = {'argv': argv, 'cwd': str(cwd), 'exit_code': raw['exit_code'], 'raw': raw,
                       'stdout': identity(prefix.with_suffix('.stdout')), 'stderr': identity(prefix.with_suffix('.stderr'))}
            (preflight if native else setup)[key] = receipt
            save(prep / ('receipt-%03d.json' % (len(setup) + len(preflight))), {'key': key, **receipt})
            if not raw['capture_complete'] or not raw['cleanup_complete'] or raw['exit_code'] != 0:
                raise RuntimeError('native preflight/setup failed: ' + key)
            output = Path(receipt['stdout']['path']).read_bytes()
            if wanted is not None and (output != wanted or Path(receipt['stderr']['path']).read_bytes()):
                raise ValueError('native output mismatch: ' + key)
            return output

        # First native command verifies collector checkout; no unreviewed source replay.
        system_git = Path('/usr/bin/git')
        command('collector/commit', [str(system_git), '-C', str(collector), 'rev-parse', 'HEAD'], collector, wanted=(SOURCE + '\n').encode())
        command('venv', [sys.executable, '-I', '-B', '-X', 'utf8', '-m', 'venv', str(runtime / 'venv')], runtime, 120)
        python = runtime / 'venv' / 'bin' / 'python'
        command('pip-install', [str(python), '-I', '-B', '-X', 'utf8', '-m', 'pip', '--isolated', 'install',
                '--no-cache-dir', '--disable-pip-version-check', '--no-input', '--no-compile',
                '--index-url', 'https://pypi.org/simple', '--report', str(prep / 'pip-report.json'), *PINS], runtime, 300)
        command('pip-freeze', [str(python), '-I', '-B', '-X', 'utf8', '-m', 'pip', '--isolated', 'freeze', '--all'], runtime)
        distributions = json.loads(command('distribution-inventory', [str(python), '-I', '-B', '-X', 'utf8', '-c', DISTRIBUTIONS], runtime))
        save(prep / 'distributions.json', distributions)
        archive = runtime / 'node.tar.xz'
        command('node-download', ['/usr/bin/curl', '--fail', '--location', '--retry', '0', '--max-time', '120', '--output', str(archive), NODE_URL], runtime, 150)
        archive_identity = identity(archive)
        if archive_identity['sha256'] != NODE_SHA:
            raise ValueError('official archive bytes mismatch')
        save(prep / 'node-acquisition.json', {'url': NODE_URL, **archive_identity})
        with tarfile.open(archive, 'r:xz') as packed:
            packed.extractall(runtime, filter='data')
        node = runtime / 'node-v22.21.1-linux-x64' / 'bin' / 'node'
        git = runtime / 'git'
        git.symlink_to(system_git)
        runtime_files = {name: identity(path) for name, path in (('python', python), ('node', node), ('git', git))}
        runtime_resolved = {name: identity(Path(item['path']).resolve()) for name, item in runtime_files.items()}
        versions = {}
        for name, path in (('python', python), ('node', node), ('git', git)):
            output = command('runtime/' + name, [str(path), '--version'], runtime, native=True)
            versions[name] = output.decode('ascii').rstrip('\n')
        if versions['python'] != 'Python 3.12.15' or versions['node'] != 'v22.21.1' or not versions['git'].startswith('git version '):
            raise ValueError('exact Python/Node runtime mismatch')
        command('runtime/pytest', [str(python), '-I', '-B', '-m', 'pytest', '--version'], runtime, wanted=b'pytest 8.4.2\n', native=True)
        for key, query, value in (('engine/commit', 'HEAD', ENGINE), ('engine/tree', 'HEAD^{tree}', contract['engine_identity']['tree']), ('engine/package', 'HEAD:src/checkwash', contract['engine_identity']['package_tree'])):
            command(key, [str(git), '-C', str(roots['engine']), 'rev-parse', query], roots['engine'], wanted=(value + '\n').encode(), native=True)
        tokens = {'<RUN_ROOT>': str(run_root), '<ENGINE_ROOT>': str(roots['engine']), '<EVIDENCE_ROOT>': str(roots['evidence']),
                  '<ABSOLUTE_TRUSTED_PYTHON>': str(python), '<ABSOLUTE_TRUSTED_NODE>': str(node), '<ABSOLUTE_TRUSTED_GIT>': str(git)}

        def expanded(value):
            for token, replacement in tokens.items():
                value = value.replace(token, replacement)
            return value

        slots = []
        for planned in contract['slots']:
            slot = {key: planned.get(key) for key in ('id', 'observer', 'case', 'arm', 'environment_state')}
            cwd = Path(expanded(planned['cwd']))
            # Contract names are ground-truth/engine-pairs; map physical roots accordingly below.
            cwd.mkdir(parents=True)
            fixture = planned['fixture']
            if slot['observer'] == 'ground_truth':
                path = cwd / fixture['repository_path']
                path.parent.mkdir(parents=True)
                path.write_bytes((roots['input'] / fixture['case'] / slot['arm'] / fixture['repository_path']).read_bytes())
                path.chmod(0o644)
            else:
                command(slot['id'] + '/init', [str(git), '-c', 'core.autocrlf=false', '-c', 'core.hooksPath=/dev/null', '-c', 'commit.gpgsign=false', 'init', '--object-format=sha1', '--initial-branch=main', '--template=' + str(empty_template), str(cwd)], runtime)
                for arm in ('before', 'after'):
                    path = cwd / fixture['repository_path']
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes((roots['input'] / fixture['case'] / arm / fixture['repository_path']).read_bytes())
                    path.chmod(0o644)
                    prefix = [str(git), '-C', str(cwd)]
                    command(slot['id'] + '/add-' + arm, [*prefix, '-c', 'core.autocrlf=false', '-c', 'core.hooksPath=/dev/null', 'add', '--', fixture['repository_path']], cwd)
                    tree = fixture[arm]['root_tree']
                    command(slot['id'] + '/tree-' + arm, [*prefix, 'write-tree'], cwd, wanted=(tree + '\n').encode())
                    parents = [] if arm == 'before' else ['-p', fixture['expected_base_sha1']]
                    commit = fixture['expected_base_sha1'] if arm == 'before' else fixture['expected_head_sha1']
                    command(slot['id'] + '/commit-' + arm, [*prefix, '-c', 'commit.gpgsign=false', 'commit-tree', tree, *parents, '-m', 'Owned environment witness ' + arm], cwd, wanted=(commit + '\n').encode())
                    previous = '0' * 40 if arm == 'before' else fixture['expected_base_sha1']
                    command(slot['id'] + '/ref-' + arm, [*prefix, 'update-ref', 'refs/heads/main', commit, previous], cwd)
                for index, query in enumerate(planned['git_queries']):
                    command(slot['id'] + '/' + str(index), [str(git), '-C', str(cwd), *query['args']], cwd, wanted=query['stdout'].encode(), native=True)
            slot.update(argv=[expanded(v) for v in planned['argv']], cwd=str(cwd), prefix=expanded(planned['prefix']), env=dict(env))
            if slot['environment_state'] == 'SET1':
                slot['env']['CW_RUN_TOTAL'] = '1'
            slots.append(slot)
        binding = {'status': 'NATIVE_BOUND', 'engine_commit': ENGINE, 'engine_tree': contract['engine_identity']['tree'],
                   'package_tree': contract['engine_identity']['package_tree'], 'source_reference_seal': V3_SEAL,
                   'hosted_identity': json.loads((prep / 'hosted.json').read_text()), 'image_identity': json.loads((prep / 'image.json').read_text()),
                   'python_version': '3.12.15', 'pytest_version': '8.4.2', 'node_version': '22.21.1', 'git_version': versions['git'][12:],
                   'roots': {name: str(path) for name, path in roots.items()}, 'tokens': tokens, 'trusted_PATH': env['PATH'],
                   'runtime_files': runtime_files, 'runtime_resolved_files': runtime_resolved, 'runtime_versions': versions,
                   'distributions': distributions, 'node_archive': archive_identity, 'preflight': preflight,
                   'byte_inventory': [*source_files, *runtime_files.values()], 'slots': slots}
        bound = prep / 'bound.json'
        save(bound, binding)
        # The exact helper creates evidence/expected.json before validating/launching.
        result = command('capture-wrapper', [str(python), '-I', '-B', '-X', 'utf8', str(helper_path), str(contract_path), str(bound), str(roots['evidence'])], runtime, 3500)
        save(prep / 'completed.json', {'status': 'RAW_CAPTURE_WRAPPER_EXIT0', 'labels': 'NOT_ADJUDICATED', 'stdout_bytes': len(result)})
        return 0
    except Exception as error:
        missing = repr(error)
        save(prep / 'failure.json', {'state': 'PREFLIGHT_OR_WRAPPER_FAILED', 'reason': missing,
             'expected24': [{'slot_id': slot, 'missing_reason': 'READ_CAPTURE_LEDGER_IF_PRESENT; ' + missing} for slot in expected],
             'labels': 'NOT_ADJUDICATED'})
        return 2
    finally:
        save(prep / 'setup-ledger.json', setup)
        save(prep / 'preflight-ledger.json', preflight)


if __name__ == '__main__':
    raise SystemExit(build(*(Path(arg).absolute() for arg in sys.argv[1:])))
