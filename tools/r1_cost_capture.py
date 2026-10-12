"""Ubuntu-only extraction of the reviewed v070 raw capture/classifier.

Source common.py SHA256 9125fe06d3c8ddae2fcf469fc8efa81055a2150dee0e93ccda3e8d7d884a1ac1.
No EC loader, approval, baseline, artifact or dispatch logic is imported.
Windows is deliberately rejected. Launch paths preserve venv symlinks; the
resolved executable is recorded separately and never substituted into argv[0].
"""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import shutil
import subprocess
import threading
import time

HASH = re.compile(r"[0-9a-f]{64}\Z")


def facts():
    return {"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

def unique_object(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON key: " + key)
        result[key] = value
    return result


def decode(raw):
    def reject(value):
        raise ValueError("nonfinite JSON value: " + value)
    return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique_object, parse_constant=reject)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def relative(root, spelling):
    if (not isinstance(spelling, str) or "\\" in spelling or ":" in spelling
            or Path(spelling).is_absolute() or ".." in Path(spelling).parts):
        raise ValueError("invalid relative path")
    path = root.joinpath(spelling).resolve()
    if not path.is_relative_to(root.resolve()) or path == root.resolve():
        raise ValueError("path escaped root")
    return path


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
        raise RuntimeError('R1 cost capture supports Ubuntu/POSIX only')
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


def validate_capture(observation):
    """Check the full recorded capture schema before accepting raw results."""
    states = {"EXITED", "TIMEOUT", "OUTPUT_LIMIT", "CAPTURE_FAILED", "SPAWN_FAILED", "DEADLINE_NOT_LAUNCHED"}
    for name in ("spawned", "capture_complete", "cleanup_complete", "output_limit_observed"):
        if type(observation[name]) is not bool:
            raise ValueError("capture flag must be boolean: " + name)
    status, stop, code = observation["status"], observation["first_stop_reason"], observation["exit_code"]
    errors = observation["capture_errors"]
    if (status not in states or stop not in states - {"EXITED"} | {None}
            or not isinstance(errors, list) or any(not isinstance(value, str) for value in errors)
            or (code is not None and type(code) is not int)):
        raise ValueError("invalid capture state/exit/errors")
    seconds = observation["elapsed_seconds"]
    if type(seconds) not in (int, float) or seconds < 0 or not math.isfinite(seconds):
        raise ValueError("invalid process elapsed time")
    if observation["cleanup_complete"] != (not errors):
        raise ValueError("contradictory cleanup/error state")
    if stop is not None and status != stop:
        raise ValueError("first stopping cause differs from terminal status")
    if status in ("SPAWN_FAILED", "DEADLINE_NOT_LAUNCHED") and observation["spawned"]:
        raise ValueError("a refused launch cannot have spawned")
    if status in ("SPAWN_FAILED", "DEADLINE_NOT_LAUNCHED") and stop != status:
        raise ValueError("unspawned capture lost its stopping cause")
    if not observation["spawned"] and (code is not None or status not in ("SPAWN_FAILED", "DEADLINE_NOT_LAUNCHED")):
        raise ValueError("unspawned capture has terminal product state")
    if status == "OUTPUT_LIMIT" and not observation["output_limit_observed"]:
        raise ValueError("unproved output limit")
    if set(observation["streams"]) != {"stdout", "stderr"}:
        raise ValueError("incomplete capture streams")
    overflow = False
    limit = observation["output_limit_bytes"]
    if type(limit) is not int or limit <= 0:
        raise ValueError("invalid stream limit")
    for stream in observation["streams"].values():
        if not isinstance(stream["path"], str):
            raise ValueError("invalid stream path")
        kept, observed = stream["retained_bytes"], stream["observed_bytes"]
        if (type(kept) is not int or kept < 0 or type(stream["bytes"]) is not int or kept != stream["bytes"]
                or (observed is not None and (type(observed) is not int or observed < kept))
                or not isinstance(stream["sha256"], str) or not HASH.fullmatch(stream["sha256"])):
            raise ValueError("invalid/unknown stream accounting")
        if kept > limit:
            raise ValueError("retained stream exceeds limit")
        overflow |= observed is not None and observed > limit
    if observation["output_limit_observed"] != overflow:
        raise ValueError("overflow flag contradicts retained counters")
    complete = (status == "EXITED" and observation["spawned"] and type(code) is int and stop is None
                and observation["cleanup_complete"] and not errors and not overflow
                and all(stream["observed_bytes"] == stream["retained_bytes"] for stream in observation["streams"].values()))
    if observation["capture_complete"] != complete or (status == "EXITED" and not complete):
        raise ValueError("contradictory complete-capture claim")


def classify(observation, payload, member, engine, labels=None):
    try:
        validate_capture(observation)
    except (KeyError, TypeError, ValueError):
        return "INVALID_CAPTURE_ENVELOPE"
    if observation["status"] != "EXITED":
        return observation["status"]
    if not observation["capture_complete"]:
        return "CAPTURE_FAILED"
    if observation["exit_code"] == 2:
        return "PRODUCT_ERROR_WITH_VERDICT" if isinstance(payload, dict) and "verdict" in payload else "PRODUCT_ERROR_EXIT"
    if observation["exit_code"] not in (0, 1):
        return "UNEXPECTED_PRODUCT_EXIT"
    if not isinstance(payload, dict):
        return "INVALID_JSON_ENVELOPE"
    run = payload.get("run", {})
    if not isinstance(run, dict) or not all(isinstance(run.get(name), str) for name in ("base", "head")):
        return "INVALID_RANGE_ENVELOPE"
    # Bind the formatter's labels to exact prelaunch rev-parse --short values,
    # each separately resolved back to its unique full frozen commit.
    labels = labels if labels is not None else member.get("reported_labels", {})
    if not all(isinstance(labels.get(name), str) and len(labels[name]) >= 7 and full.startswith(labels[name])
               for name, full in (("base", member["parent"]), ("head", member["commit"]))):
        return "INVALID_LABEL_BINDING"
    if not all(run[name] == labels[name] for name in ("base", "head")):
        return "RANGE_MISMATCH"
    if run.get("checkwash_version") != engine["version"] or payload.get("checkwash_findings_version") != engine["findings_version"] or type(payload.get("checkwash_findings_version")) is not int:
        return "VERSION_MISMATCH"
    if not isinstance(payload.get("findings"), list) or payload.get("verdict") not in ("pass", "block"):
        return "INVALID_VERDICT_ENVELOPE"
    if observation["exit_code"] != (1 if payload["verdict"] == "block" else 0):
        return "EXIT_VERDICT_MISMATCH"
    severities = dict(critical=0, high=0, warn=0, info=0)
    for finding in payload["findings"]:
        if (not isinstance(finding, dict) or not all(isinstance(finding.get(key), str) for key in
                ("rule", "severity", "path", "message", "fingerprint"))
                or finding["severity"] not in severities or type(finding.get("allowlisted")) is not bool
                or "unit" not in finding or not (finding["unit"] is None or isinstance(finding["unit"], str))
                or not all(isinstance(finding.get(key), list) and all(isinstance(value, str) for value in finding[key])
                           for key in ("escalators", "deescalators"))):
            return "INVALID_FINDING_ENVELOPE"
        for key in ("before", "after"):
            if key not in finding:
                return "INVALID_FINDING_ENVELOPE"
            evidence = finding[key]
            if evidence is not None and (not isinstance(evidence, dict) or not isinstance(evidence.get("text"), str)
                    or not isinstance(evidence.get("span"), list) or len(evidence["span"]) != 2
                    or any(type(value) is not int for value in evidence["span"])):
                return "INVALID_FINDING_ENVELOPE"
        severities[finding["severity"]] += 1
    if payload.get("summary") != severities or any(type(value) is not int for value in payload["summary"].values()):
        return "INVALID_FINDING_ENVELOPE"
    if not all(isinstance(payload.get(key), list) and all(isinstance(value, str) for value in payload[key])
               for key in ("config_errors", "skipped_files")):
        return "INVALID_DIAGNOSTIC_ENVELOPE"
    if payload.get("config_errors"):
        return "CONFIG_DIAGNOSTICS_" + payload["verdict"].upper()
    if payload.get("skipped_files"):
        return "ANALYZED_WITH_SKIPS_" + payload["verdict"].upper()
    if observation["streams"]["stderr"]["bytes"]:
        return "ANALYZED_WITH_STDERR_" + payload["verdict"].upper()
    return "ANALYZED_" + payload["verdict"].upper()
