"""Extra child diagnostic, never a replacement for the native CLI receipt.

Imports only the selected arm's qualified pyz. The one pass wrapper forwards
all arguments/return values/exceptions. It does not substitute any reader.
"""
import argparse
import ast
import hashlib
import json
import os
import resource
import subprocess
import sys
import time
import traceback
from pathlib import Path


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def exception_fact(error):
    frames = traceback.extract_tb(error.__traceback__)
    def rows(items):
        return [{"file": f.filename, "line": f.lineno, "function": f.name} for f in items]
    return {"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc(),
                "first_frames": rows(frames[:12]), "last_frames": rows(frames[-12:])}


def source_fact(repo, revision, path, dest):
    # This is a separate parse observation of a named blob, not proof that
    # stand-in requested/used this side. It runs after the diagnostic CLI.
    result = {"revision": revision, "path": path, "used_by_standin": "UNKNOWN",
                  "phase": "STANDALONE_SOURCE_PARSE", "nodes": None}
    commands = []
    def git(*args):
        argv = ["git", "-C", str(repo), *args]
        failure = None
        try:
            proc = subprocess.run(argv, capture_output=True, timeout=30, check=False)
            stdout, stderr, code = proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as error:
            stdout, stderr, code = error.stdout or b"", error.stderr or b"", None
            failure = "METADATA_GIT_TIMEOUT"
        prefix = dest.with_name(dest.name + f"-git-{len(commands):02d}")
        prefix.with_suffix(prefix.suffix + ".stdout").write_bytes(stdout)
        prefix.with_suffix(prefix.suffix + ".stderr").write_bytes(stderr)
        commands.append({"argv": argv, "exit_code": code, "failure": failure,
                             "raw_prefix": prefix.name, "stdout_sha256": sha(stdout), "stderr_sha256": sha(stderr)})
        if code != 0:
            raise RuntimeError("metadata Git command failed; see raw stderr")
        return stdout
    try:
        entry = git("ls-tree", "-z", revision, "--", path)
        if not entry:
            result["state"] = "ABSENT_AT_NAMED_REVISION"
            return result
        header, actual = entry[:-1].split(b"\t", 1)
        mode, kind, oid = header.decode("ascii").split()
        if actual.decode("utf-8") != path or kind != "blob":
            raise ValueError("named source is not the expected blob")
        result.update(mode=mode, oid=oid, bytes=int(git("cat-file", "-s", oid)))
        if mode not in ("100644", "100755") or result["bytes"] > 1_000_000:
            result["state"] = "METADATA_ONLY_NONREGULAR_OR_OVER_LIMIT"
            return result
        raw = git("cat-file", "blob", oid)
        if len(raw) != result["bytes"]:
            raise ValueError("metadata blob byte count changed")
        dest.write_bytes(raw)
        result.update(source_sha256=sha(raw), raw_source=dest.name)
        started = time.perf_counter()
        try:
            tree = ast.parse(raw.decode("utf-8"))
            result.update(state="PARSED", nodes=sum(1 for _ in ast.walk(tree)))
        except (SyntaxError, ValueError, RecursionError, MemoryError, UnicodeError) as error:
            result.update(state="PARSE_EXCEPTION", exception_type=type(error).__name__, message=str(error))
        finally:
            result["standalone_parse_count_seconds"] = time.perf_counter() - started
    except Exception as error:
        result.update(state="METADATA_ERROR", error=repr(error))
    finally:
        result["commands"] = commands
    return result


def main():
    parser = argparse.ArgumentParser()
    for name in ("artifact", "artifact-sha", "engine-sha", "repo", "base", "head", "path", "output", "run", "attempt"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    output = Path(args.output)
    artifact = Path(args.artifact).resolve(strict=True)
    receipt = {"purpose": "INSTRUMENTED_DIAGNOSTIC_NOT_NATIVE_COST_OR_QUALIFICATION",
                   "engine_sha": args.engine_sha, "artifact_sha256": args.artifact_sha,
                   "run_id": args.run, "attempt": args.attempt, "base": args.base, "head": args.head,
                   "python": sys.version, "executable": sys.executable, "sources": [],
                   "complete": False, "recorder_errors": [],
                   "standin": {"state": "NOT_REACHED", "elapsed_seconds": None,
                               "step_observation": {"state": "NOT_OBSERVED"}},
                   "cli_exit": None, "first_failure_phase": "UNKNOWN", "exception": None}
    save(output, receipt)
    code = 2
    started = time.perf_counter()
    try:
        if sha(artifact.read_bytes()) != args.artifact_sha:
            raise ValueError("qualified artifact bytes changed")
        sys.path.insert(0, str(artifact))
        import checkwash
        from checkwash import cli, engine
        if not str(checkwash.__file__).startswith(str(artifact) + "/checkwash/"):
            raise ValueError("diagnostic imported a different package")
        receipt["package_path"] = str(checkwash.__file__)
        original = engine.installation_events
        def measured(*a, **kw):
            phase = receipt["standin"]
            phase.update(state="ENTERED", elapsed_seconds=None)
            entered = time.perf_counter()
            try:
                result = original(*a, **kw)
                phase.update(state="RETURNED", event_count=len(result))
                return result
            except BaseException as error:
                phase.update(state="RAISED", exception=exception_fact(error))
                try:
                    # Only an original exception triggers this metadata read.
                    # No _step wrapper, retry, reader or product limit change.
                    import importlib.util
                    import zipfile
                    observer_path = Path(__file__).with_name("standin_step_observation.py")
                    spec = importlib.util.spec_from_file_location("standin_step_observation", observer_path)
                    observer = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(observer)
                    with zipfile.ZipFile(artifact) as archive:
                        source = archive.read("checkwash/frontends/python/standin_installations.py")
                    phase["step_observation"] = observer.observe(error, original, source)
                    phase["step_observation"]["observer_sha256"] = sha(observer_path.read_bytes())
                except BaseException as observation_error:
                    phase["step_observation"] = {"state": "OBSERVER_FAILED", "type": type(observation_error).__name__}
                    receipt["recorder_errors"].append("step_metadata: " + type(observation_error).__name__)
                raise
            finally:
                phase["elapsed_seconds"] = time.perf_counter() - entered
                try:
                    save(output, receipt)
                except OSError as error:
                    # Do not replace the original engine exception/return with
                    # an instrumentation write failure. Mark it incomplete.
                    receipt["recorder_errors"].append(repr(error))
        engine.installation_events = measured
        parsed = cli.build_parser().parse_args([
            "check", args.base + ".." + args.head, "--repo", args.repo,
            "--fail-on", "high", "--format", "json"])
        code = cli._cmd_check(parsed)
        phase = "STANDIN" if receipt["standin"]["state"] == "RAISED" else None if code in (0, 1) else "UNKNOWN"
        receipt.update(cli_exit=code, first_failure_phase=phase)
    except BaseException as error:
        receipt["exception"] = exception_fact(error)
        receipt["first_failure_phase"] = "STANDIN" if receipt["standin"]["state"] == "RAISED" else "UNKNOWN"
        code = 2
    finally:
        receipt["diagnostic_cli_seconds"] = time.perf_counter() - started
        # Subsequent metadata Git commands have their own raw receipts. Do not
        # count them as Git work performed by this extra instrumented CLI.
        os.environ.pop("GIT_TRACE2_EVENT", None)
        receipt["git_trace_scope"] = "EXTRA_INSTRUMENTED_CLI_ONLY_NOT_PRIMARY_OR_METADATA_PARSE"
        # Same arm/runtime but a different measurement phase; exclude these
        # parse observations from diagnostic_cli_seconds and stand-in span.
        for side, revision in (("before", args.base), ("after", args.head)):
            result = source_fact(args.repo, revision, args.path, output.with_name(output.stem + "-" + side + ".source"))
            receipt["sources"].append(dict(named_side=side, **result))
        usage = resource.getrusage(resource.RUSAGE_SELF)
        receipt["process_usage"] = {"ru_maxrss": usage.ru_maxrss, "ru_maxrss_unit": "KiB on Linux",
            "user_seconds": usage.ru_utime, "system_seconds": usage.ru_stime,
            "scope": "whole diagnostic child including standalone parses; not pass-only or total Git memory"}
        receipt["complete"] = not receipt["recorder_errors"] and all(s["state"] != "METADATA_ERROR" for s in receipt["sources"])
        receipt["diagnostic_cli_outcome_exit"] = code
        if not receipt["complete"]:
            code = 2
        receipt["exit_code"] = code
        save(output, receipt)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
