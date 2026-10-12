"""Owned Ubuntu subprocess evidence, extracted from the reviewed R1 capture.

No engine classifier, cohort, artifact qualification or scheduler is imported.
The absolute launch path preserves venv identity; resolution is evidence only.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import threading
import time


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
    intent = dict(argv=argv, streams={name: path.name for name, path in files.items()},
                  state="LAUNCH_INTENT", timeout_seconds=timeout, utc=facts()["utc"])
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
                sizes[name] = dict(observed_bytes=observed, retained_bytes=kept)

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
                                         stderr=subprocess.PIPE, start_new_session=True)
                spawned = True
                intent.update(state="LAUNCHED", executable=executable, launch_executable=actual[0])
                write(prefix.with_suffix(".intent.json"), intent)
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
                **sizes.get(name, dict(observed_bytes=None if spawned else 0, retained_bytes=path.stat().st_size)))
        except OSError as error:
            failures.append("retained stream identity unknown: " + repr(error))
            streams[name] = dict(path=path.name, sha256=None, bytes=None, observed_bytes=None, retained_bytes=None)
    status = first_stop or ("CAPTURE_FAILED" if failures else "OUTPUT_LIMIT" if overflow.is_set() else "EXITED")
    observation = dict(argv=argv, executable=executable, spawned=spawned, exit_code=exit_code,
                output_limit_bytes=limit,
                elapsed_seconds=time.perf_counter() - started, first_stop_reason=first_stop,
                output_limit_observed=overflow.is_set(), cleanup_complete=not failures,
                status=status, capture_complete=status == "EXITED" and not failures,
                capture_errors=failures, streams=streams)
    write(prefix.with_suffix(".observation.json"), observation)
    return observation
