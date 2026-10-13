"""Owned Ubuntu subprocess evidence, extracted from the reviewed R1 capture.

No engine classifier, cohort, artifact qualification or scheduler is imported.
The absolute launch path preserves venv identity; resolution is evidence only.
"""
import hashlib
import json
import os
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path


def facts():
    return {"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def kill(child):
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    if child.poll() is None:
        child.kill()
    child.wait(timeout=10)


def capture(argv, cwd, env, prefix, timeout, limit, deadline=None):
    """Retain exact streams, or explicitly bounded prefixes on output limit."""
    if os.name != 'posix':
        raise RuntimeError('owned reproduction capture supports Ubuntu/POSIX only')
    started = time.perf_counter()
    overflow, drain_failed = threading.Event(), threading.Event()
    files = {name: prefix.with_suffix("." + name) for name in ("stdout", "stderr")}
    sizes, failures, readers = {}, [], []
    child, spawned, first_stop, exit_code, executable = None, False, None, None, None
    pid, root_reaped, group_absent = None, False, False
    intent = {"argv": argv, "streams": {name: path.name for name, path in files.items()},
                  "state": "LAUNCH_INTENT", "timeout_seconds": timeout, "utc": facts()["utc"]}
    write(prefix.with_suffix(".intent.json"), intent)
    with files["stdout"].open("xb") as stdout, files["stderr"].open("xb") as stderr:
        def drain(name, pipe, output):
            observed = kept = 0
            try:
                while chunk := pipe.read(65536):
                    observed += len(chunk)
                    if observed > limit:
                        overflow.set()
                    remaining = max(0, limit - kept)
                    output.write(chunk[:remaining])
                    kept += min(remaining, len(chunk))
            except Exception as error:
                failures.append(repr(error))
                drain_failed.set()
            finally:
                sizes[name] = {"observed_bytes": observed, "retained_bytes": kept}

        try:
            executable = shutil.which(argv[0], path=env.get("PATH"))
            if not executable:
                raise FileNotFoundError("executable not found")
            # A venv interpreter may be a symlink to the base interpreter.
            # Resolve for evidence, but launch the original path so Python can
            # still locate that venv's adjacent pyvenv.cfg.
            actual = [os.path.abspath(executable), *argv[1:]]
            executable = str(Path(executable).resolve())
            remaining = timeout if deadline is None else min(timeout, deadline - time.monotonic())
            if remaining <= 0:
                first_stop = "DEADLINE_NOT_LAUNCHED"
            else:
                child = subprocess.Popen(actual, cwd=cwd, env=env, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, start_new_session=True)
                spawned = True
                pid = child.pid
                intent.update(state="LAUNCHED", executable=executable, launch_executable=actual[0])
                write(prefix.with_suffix(".launch.json"), intent)
                readers = [threading.Thread(target=drain, args=(name, pipe, output), daemon=True)
                           for name, pipe, output in (("stdout", child.stdout, stdout), ("stderr", child.stderr, stderr))]
                for reader in readers:
                    reader.start()
                process_deadline = time.monotonic() + remaining
                if deadline is not None:
                    process_deadline = min(process_deadline, deadline)
                while child.poll() is None:
                    if drain_failed.is_set():
                        first_stop = "CAPTURE_FAILED"
                        break
                    if overflow.is_set():
                        first_stop = "OUTPUT_LIMIT"
                        break
                    if time.monotonic() >= process_deadline:
                        first_stop = "TIMEOUT"
                        break
                    time.sleep(.02)
                exit_code = child.poll()
        except Exception as error:
            first_stop = first_stop or ("CAPTURE_FAILED" if spawned else "SPAWN_FAILED")
            failures.append(repr(error))
        finally:
            if child is not None:
                # Always close the invocation tree, even if its root exited
                # while a descendant still owns stdout/stderr handles.
                try:
                    kill(child)
                    exit_code = child.returncode
                    root_reaped = child.returncode is not None
                    try:
                        os.killpg(pid, 0)
                    except ProcessLookupError:
                        group_absent = True
                    if not group_absent:
                        failures.append('process group absence unproved')
                except Exception as error:
                    failures.append("tree cleanup: " + repr(error))
                for reader in readers:
                    reader.join(timeout=10)
                if any(reader.is_alive() for reader in readers):
                    failures.append("reader did not complete after tree termination")
                for pipe in (child.stdout, child.stderr):
                    if pipe and not any(reader.is_alive() for reader in readers):
                        pipe.close()
    # Output handles are closed before the immutable retained-file hashes.
    # A lingering reader cannot write additional bytes to these closed files;
    # missing byte accounting is explicitly unknown and never capture-complete.
    streams = {}
    for name, path in files.items():
        try:
            streams[name] = dict(path=path.name, sha256=digest(path), bytes=path.stat().st_size,
                **sizes.get(name, {"observed_bytes": None if spawned else 0, "retained_bytes": path.stat().st_size}))
        except OSError as error:
            failures.append("retained stream identity unknown: " + repr(error))
            streams[name] = {"path": path.name, "sha256": None, "bytes": None, "observed_bytes": None, "retained_bytes": None}
    status = first_stop or ("CAPTURE_FAILED" if failures else "OUTPUT_LIMIT" if overflow.is_set() else "EXITED")
    observation = {"argv": argv, "executable": executable, "spawned": spawned, "exit_code": exit_code,
                "output_limit_bytes": limit,
                "elapsed_seconds": time.perf_counter() - started, "first_stop_reason": first_stop,
                "output_limit_observed": overflow.is_set(), "pid": pid, "root_reaped": root_reaped, "streams_complete": len(sizes) == 2 and not any(r.is_alive() for r in readers), "group_absent": group_absent, "cleanup_complete": not failures and (not spawned or root_reaped and group_absent),
                "status": status, "capture_complete": status == "EXITED" and not failures,
                "capture_errors": failures, "streams": streams}
    write(prefix.with_suffix(".observation.json"), observation)
    return observation


# Dedicated owned caller: the template is deliberately non-dispatchable.
def immutable(path, value):
    with path.open('x', encoding='utf-8') as output:
        output.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')
        output.flush()
        os.fsync(output.fileno())
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def checked_bytes(item):
    path = Path(item['path'])
    if not path.is_absolute() or digest(path) != item['sha256']:
        raise ValueError('byte identity mismatch')
    if path.stat().st_size != item['bytes']:
        raise ValueError('byte count mismatch')


def bind(contract, binding):
    # Full qualification is deliberately a remaining workflow/review boundary.
    if os.name != 'posix' or binding['status'] != 'NATIVE_BOUND':
        raise ValueError('missing native binding')
    for field in ('engine_commit', 'engine_tree', 'package_tree', 'hosted_identity',
                  'python_version', 'pytest_version', 'node_version', 'git_version',
                  'image_identity', 'source_reference_seal'):
        if not binding.get(field) or 'TO_' in str(binding[field]):
            raise ValueError('unbound identity: ' + field)
    if binding['pytest_version'] != '8.4.2' or binding['node_version'] != '22.21.1':
        raise ValueError('runtime convention mismatch')
    for item in binding['byte_inventory']:
        checked_bytes(item)
    preflight = binding['preflight']
    if not preflight:
        raise ValueError('missing real preflight evidence')
    for receipt in preflight.values():
        if not receipt['argv'] or not Path(receipt['cwd']).is_absolute():
            raise ValueError('missing preflight command identity')
        if receipt['exit_code'] != 0:
            raise ValueError('preflight failed')
        checked_bytes(receipt['stdout'])
        checked_bytes(receipt['stderr'])
    slots = binding['slots']
    if len(slots) != 24 or [s['id'] for s in slots] != [s['id'] for s in contract['slots']]:
        raise ValueError('24-slot identity mismatch')
    prefixes = set()
    for planned, slot in zip(contract['slots'], slots):
        for field in ('observer', 'case', 'arm', 'environment_state'):
            if slot.get(field) != planned.get(field):
                raise ValueError('slot binding mismatch')
        prefix = Path(slot['prefix'])
        if not prefix.is_absolute() or prefix.suffix or str(prefix) in prefixes:
            raise ValueError('prefix must be unique absolute suffix-free')
        prefixes.add(str(prefix))
        if not Path(slot['cwd']).is_absolute() or not Path(slot['argv'][0]).is_absolute():
            raise ValueError('absolute launch identity required')
        env = slot['env']
        tokens = binding['tokens']
        def expanded(value):
            for token, replacement in tokens.items():
                value = value.replace(token, replacement)
            if '<' in value or '>' in value:
                raise ValueError('unresolved command token')
            return value
        if slot['argv'] != [expanded(v) for v in planned['argv']]:
            raise ValueError('explicit argv mismatch')
        if slot['cwd'] != expanded(planned['cwd']) or slot['prefix'] != expanded(planned['prefix']):
            raise ValueError('directory binding mismatch')
        for runtime in ('python', 'node', 'git'):
            checked_bytes(binding['runtime_files'][runtime])
        if slot['argv'][0] not in [v['path'] for v in binding['runtime_files'].values()]:
            raise ValueError('launch executable lacks byte binding')
        allowed = set(contract['environment_set']) | {'PATH', 'TMPDIR', 'TMP', 'TEMP', 'CW_RUN_TOTAL', 'HOME'}
        if set(env) - allowed:
            raise ValueError('child environment must use declared allowlist')
        if env.get('HOME') != os.environ.get('HOME') or 'CODEX_HOME' in env:
            raise ValueError('system-variable override prohibited')
        if not env.get('PATH') or not env.get('TMPDIR'):
            raise ValueError('explicit child PATH/temp required')
        for name, value in contract['environment_set'].items():
            if env.get(name) != value:
                raise ValueError('Git/pytest isolation mismatch')
        if slot['environment_state'] == 'UNSET':
            if 'CW_RUN_TOTAL' in env:
                raise ValueError('CW_RUN_TOTAL must be absent')
        elif env.get('CW_RUN_TOTAL') != '1':
            raise ValueError('CW_RUN_TOTAL must be literal 1')
    validate_native(contract, binding, slots)
    return slots


def main(contract_path, binding_path, evidence_directory):
    contract = json.loads(Path(contract_path).read_text(encoding='utf-8'))
    root = Path(evidence_directory)
    root.mkdir(parents=True, exist_ok=False)
    expected = contract['slots']
    immutable(root / 'expected.json', expected)  # before any source launch
    deadline = time.monotonic() + contract['global_seconds']
    ledger = []
    stop = None
    try:
        binding = json.loads(Path(binding_path).read_text(encoding='utf-8'))
        slots = bind(contract, binding)
        immutable(root / 'binding.json', binding)
    except Exception as error:
        slots, stop = expected, 'PRELAUNCH_BINDING_FAILED: ' + repr(error)
    for index, slot in enumerate(slots):
        entry = {'slot_id': slot['id'], 'state': 'NOT_ATTEMPTED', 'missing_reason': stop}
        if stop is None:
            try:
                prefix = Path(slot['prefix'])
                prefix.relative_to(root)
                prefix.parent.mkdir(parents=True, exist_ok=True)
                if any(prefix.parent.glob(prefix.name + '.*')):
                    raise FileExistsError('old prefix prohibited')
                immutable(root / ('attempt-%02d.json' % index), slot)
                result = capture(slot['argv'], slot['cwd'], dict(slot['env']), prefix, 120, 8388608, deadline)
                entry['raw'] = result
                if slot['observer'] == 'ground_truth' and slot['case'] != 'JSENVWRAP':
                    ancillary = prefix.with_suffix('.junit.xml')
                    if not ancillary.is_file() or ancillary.is_symlink() or ancillary.stat().st_size > 8388608:
                        raise ValueError('JUnit absent/invalid/oversized')
                    result['junit'] = {'path': str(ancillary), 'bytes': ancillary.stat().st_size, 'sha256': digest(ancillary)}
                entry.update(state=result['status'], raw=result, missing_reason=None)
                if not result['capture_complete'] or not result['cleanup_complete']:
                    stop = 'RAW_OR_CLEANUP_UNPROVED: ' + slot['id']
            except Exception as error:
                stop = 'CAPTURE_WRAPPER_FAILED: ' + repr(error)
                entry.update(state='MISSING_OBSERVATION', missing_reason=stop)
        ledger.append(entry)
        try:
            immutable(root / ('ledger-%02d.json' % index), entry)
        except Exception as error:
            stop = 'LEDGER_WRITE_FAILED: ' + repr(error)
            # The expected ledger survives; no later launch after storage failure.
    immutable(root / 'final-ledger.json', ledger)
    return 0 if stop is None else 2



def regular(path):
    if not path.is_file() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('regular nonsymlink file required')


def exact_file(path, expected):
    regular(path)
    checked_bytes(dict(expected, path=str(path)))
    raw = path.read_bytes()
    if 'git_blob' in expected and hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() != expected['git_blob']:
        raise ValueError('blob identity mismatch')


def native_receipt(binding, key, argv, cwd, expected):
    receipt = binding['preflight'][key]
    if receipt['argv'] != argv or receipt['cwd'] != str(cwd) or receipt['exit_code'] != 0:
        raise ValueError('native preflight command mismatch: ' + key)
    for stream in ('stdout', 'stderr'):
        checked_bytes(receipt[stream])
    if Path(receipt['stdout']['path']).read_bytes() != expected or Path(receipt['stderr']['path']).read_bytes():
        raise ValueError('native preflight output mismatch: ' + key)


def validate_native(contract, binding, slots):
    for field, expected in (('engine_commit', contract['engine_identity']['commit']),
                            ('engine_tree', contract['engine_identity']['tree']),
                            ('package_tree', contract['engine_identity']['package_tree'])):
        if binding[field] != expected:
            raise ValueError('qualified source binding mismatch')
    roots = {name: Path(binding['roots'][name]) for name in ('engine', 'runtime', 'input', 'ground_truth', 'pairs', 'evidence')}
    for name, path in roots.items():
        if not path.is_absolute() or path.resolve() != path or not path.is_dir():
            raise ValueError('absolute real root required')
        for other, candidate in roots.items():
            if other != name and (path == candidate or path in candidate.parents):
                raise ValueError('root overlap')
    tokens = binding['tokens']
    if tokens['<ENGINE_ROOT>'] != str(roots['engine']) or tokens['<EVIDENCE_ROOT>'] != str(roots['evidence']):
        raise ValueError('root token mismatch')
    for key, query, value in (('engine/commit', 'HEAD', binding['engine_commit']), ('engine/tree', 'HEAD^{tree}', binding['engine_tree']), ('engine/package', 'HEAD:src/checkwash', binding['package_tree'])):
        native_receipt(binding, key, [binding['runtime_files']['git']['path'], '-C', str(roots['engine']), 'rev-parse', query], roots['engine'], (value + '\n').encode())
    package = roots['engine'] / 'src' / 'checkwash'
    expected = {m['path']: m for m in contract['engine_identity']['members']}
    actual = {str(p.relative_to(package.parent)): p for p in package.rglob('*') if not p.is_dir()}
    if len(expected) != 208 or set(actual) != set(expected):
        raise ValueError('complete package inventory mismatch')
    for name, path in actual.items():
        exact_file(path, expected[name])
    if any(p.is_symlink() for p in package.rglob('*')):
        raise ValueError('package symlink')
    for fixture in contract['source_fixtures']:
        for arm in ('before', 'after'):
            exact_file(roots['input'] / fixture['case'] / arm / fixture['repository_path'], fixture[arm])
    if not binding['distributions'] or any(not d['name'] or not d['version'] or not d['files'] for d in binding['distributions']):
        raise ValueError('explicit distribution/dependency inventory required')
    if not any(d['name'] == 'pytest' and d['version'] == '8.4.2' for d in binding['distributions']):
        raise ValueError('pytest distribution missing')
    for distribution in binding['distributions']:
        for item in distribution['files']:
            exact_file(Path(item['path']), item)
            Path(item['path']).relative_to(roots['runtime'])
    archive = binding['node_archive']
    if archive['sha256'] != contract['runtime']['node']['official_archive_sha256']:
        raise ValueError('official Node archive mismatch')
    checked_bytes(archive)
    baseline = {k: v for k, v in slots[0]['env'].items() if k != 'CW_RUN_TOTAL'}
    if baseline['PATH'] != binding['trusted_PATH'] or any(not Path(p).is_absolute() for p in baseline['PATH'].split(':')):
        raise ValueError('trusted absolute PATH required')
    for key in ('TMPDIR', 'TMP', 'TEMP'):
        if key in baseline and not Path(baseline[key]).is_absolute():
            raise ValueError('absolute child temp required')
    for name in ('python', 'node', 'git'):
        runtime = binding['runtime_files'][name]
        if tokens['<ABSOLUTE_TRUSTED_' + name.upper() + '>'] != runtime['path']:
            raise ValueError('runtime token mismatch')
        Path(runtime['path']).relative_to(roots['runtime'])
        version = binding['runtime_versions'][name]
        expected_version = {'python': 'Python ' + binding['python_version'], 'node': 'v22.21.1', 'git': 'git version ' + binding['git_version']}[name]
        if version != expected_version or not binding['python_version'].startswith('3.12.'):
            raise ValueError('runtime version mismatch')
        native_receipt(binding, 'runtime/' + name, [runtime['path'], '--version'], roots['runtime'], (version + '\n').encode())
    native_receipt(binding, 'runtime/pytest', [binding['runtime_files']['python']['path'], '-I', '-B', '-m', 'pytest', '--version'], roots['runtime'], b'pytest 8.4.2\n')
    for slot in slots:
        if {k: v for k, v in slot['env'].items() if k != 'CW_RUN_TOTAL'} != baseline:
            raise ValueError('environment differs beyond CW_RUN_TOTAL')
        cwd = Path(slot['cwd'])
        cwd.relative_to(roots['ground_truth'] if slot['observer'] == 'ground_truth' else roots['pairs'])
        planned = next(s for s in contract['slots'] if s['id'] == slot['id'])
        fixture = planned['fixture']
        arm = slot['arm'] if slot['observer'] == 'ground_truth' else 'after'
        exact_file(cwd / fixture['repository_path'], fixture[arm])
        if slot['observer'] == 'ground_truth' and {str(p.relative_to(cwd)) for p in cwd.rglob('*') if not p.is_dir()} != {fixture['repository_path']}:
            raise ValueError('extra source-arm file')
        for index, query in enumerate(planned['git_queries']):
            native_receipt(binding, slot['id'] + '/' + str(index), [binding['runtime_files']['git']['path'], '-C', str(cwd), *query['args']], cwd, query['stdout'].encode())

if __name__ == '__main__':
    import sys
    raise SystemExit(main(*sys.argv[1:]))
