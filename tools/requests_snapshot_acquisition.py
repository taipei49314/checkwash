"""Acquire only requests ordinal 2037 on the already-qualified 30cf source.

Capture completion is evidence acquisition, never an engine PASS. No repository
test code is executed. The native child always precedes the diagnostic child.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
ENGINE = "30cfb8bd39aa702aae0d59bde1d1400654137bad"
ENGINE_TREE = "47560377419edd2dd8e73b3c077a50e5a396c04a"
SOURCE_TREE = "531870030a23838b060cd555be7e9af51e8a4688"
PARENT = "f8aa36b92d95e6d2f133489f39f9d5c2412f1bd9"
COMMIT = "4e383642a9ebb82a67eaeed199d0fbbb31991e3c"
PAIR = {"repository": "psf/requests", "ordinal": 2037, "parent": PARENT, "commit": COMMIT}
OID = re.compile(r"[a-f0-9]{40}\Z")
STREAM_LIMIT = 4_000_000
CLI_TIMEOUT = 120
TOTAL_SECONDS = 900
OBSERVER_LIMIT = 8_000_000


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def git(repo, env, *args):
    result = subprocess.run(["git", "-C", str(repo), *args], env=env,
                            capture_output=True, timeout=120, check=False)
    require(result.returncode == 0, "source/pair Git identity command failed: " + repr(args))
    return result.stdout


def module_from(path, name):
    specification = importlib.util.spec_from_file_location(name, path)
    require(specification is not None and specification.loader is not None, "module loader unavailable")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def canonical_file(repo, commit, relative, env):
    path = repo / relative
    require(path.is_file() and not path.is_symlink(), "required source file is not regular")
    raw = git(repo, env, "cat-file", "blob", commit + ":" + relative)
    require(path.read_bytes() == raw, "source file differs from immutable Git blob: " + relative)
    return {"sha256": sha(raw), "bytes": len(raw),
            "git_blob": git(repo, env, "rev-parse", commit + ":" + relative).decode().strip()}


def checked_source(source, env, inventory):
    require(git(source, env, "rev-parse", "HEAD").decode().strip() == ENGINE, "engine commit differs")
    require(git(source, env, "rev-parse", "HEAD^{tree}").decode().strip() == ENGINE_TREE, "engine tree differs")
    require(git(source, env, "rev-parse", "HEAD:src").decode().strip() == SOURCE_TREE, "source tree differs")
    require(not git(source, env, "status", "--porcelain", "--untracked-files=all"), "engine checkout is not clean")
    # Existing source_inventory performs Git blob framing and byte comparisons.
    _, proof = inventory.source_inventory(ENGINE)
    actual = set()
    for path in (source / "src").rglob("*"):
        require(not path.is_symlink(), "source contains an untracked/ignored symlink")
        if path.is_file():
            actual.add(path.relative_to(source / "src").as_posix())
    require(actual == set(proof) and len(proof) == 200, "source package inventory differs")
    return proof


def observer_receipt(raw, decode, expected_exit):
    require(len(raw) <= OBSERVER_LIMIT, "observer receipt exceeds its declared bound")
    report = decode(raw)
    require(type(report) is dict and report.get("purpose") == "REQUESTS_2037_METADATA_DIAGNOSTIC_NOT_A_VERDICT",
            "observer purpose differs")
    require(report.get("expected_engine_commit") == ENGINE and report.get("pair") == PAIR, "observer source/pair differs")
    require(type(report.get("engine_exit")) is int and report["engine_exit"] == expected_exit, "observer exit differs")
    require(report.get("instrumentation_complete") is True and report.get("instrumentation_errors") == [],
            "observer explicitly incomplete")
    calls = report.get("calls")
    require(type(calls) is list and type(report.get("calls_started")) is int
            and type(report.get("calls_recorded")) is int
            and report["calls_started"] == report["calls_recorded"] == len(calls), "observer call accounting differs")
    for index, call in enumerate(calls, 1):
        require(type(call) is dict and type(call.get("call")) is int and call["call"] == index, "observer call order differs")
        require(call.get("outcome") in ("RETURNED", "RAISED"), "unknown original call outcome")
        requested = call.get("requested_paths")
        if call.get("requested_state") == "UNKNOWN_BEFORE_SELECTION":
            require(requested is None and call["outcome"] == "RAISED", "unknown selection became data")
        else:
            expected_state = "COMPLETE_FROM_RESULT_KEYS" if call["outcome"] == "RETURNED" else "COMPLETE_FROM_ORIGINAL_SELECTED"
            require(call.get("requested_state") == expected_state and type(requested) is list
                    and all(type(path) is str for path in requested)
                    and requested == sorted(set(requested)), "requested-set accounting differs")
        resolved = call.get("resolved_revision")
        require(resolved in (None, PARENT, COMMIT), "observer resolved an unrelated revision")
        expected_side = "BASE" if resolved == PARENT else "HEAD" if resolved == COMMIT else "OTHER_OR_UNRESOLVED"
        require(call.get("side") == expected_side, "observer side differs from frozen revision")
    return report


def run(source, output):
    require(sys.platform == "linux" and sys.version_info[:2] == (3, 12), "proposal is Ubuntu Python 3.12 only")
    source, output = source.resolve(), output.absolute()
    temporary_root = Path(os.environ["RUNNER_TEMP"]).resolve()
    require(not output.exists() and output.resolve().is_relative_to(temporary_root), "output must be fresh under runner temp")
    require(not output.resolve().is_relative_to(source) and not output.resolve().is_relative_to(ROOT), "output overlaps source")
    output.mkdir(parents=True)
    scratch = output.parent / (output.name + "-scratch")
    scratch.mkdir()
    for name in ("home", "tmp", "cwd"):
        (scratch / name).mkdir()
    # Same explicit environment for both children; no token or arbitrary runner
    # variable is inherited. PATH comes from trusted setup-python/hosted setup.
    env = {"PATH": os.environ["PATH"], "HOME": str(scratch / "home"), "TMPDIR": str(scratch / "tmp"),
           "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TZ": "UTC", "NO_COLOR": "1",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
           "GIT_OPTIONAL_LOCKS": "0"}
    # Also isolate the existing inventory helper's inherited Git environment.
    original_environment = dict(os.environ)
    report = {"purpose": "REQUESTS_2037_ACQUISITION_NOT_PRODUCT_QUALIFICATION", "state": "INCOMPLETE",
              "pair": PAIR, "engine_commit": ENGINE, "engine_tree": ENGINE_TREE, "source_tree": SOURCE_TREE,
              "environment": env, "runtime": {"python": sys.version, "platform": platform.platform(),
              "launch_python": os.path.abspath(sys.executable), "resolved_python": str(Path(sys.executable).resolve())},
              "arms": {"native": "NOT_ATTEMPTED", "diagnostic": "NOT_ATTEMPTED"}, "failure": None}
    capture = None
    try:
        run_id, attempt, hosted = (original_environment[name] for name in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_SHA"))
        require(run_id.isdecimal() and attempt.isdecimal() and OID.fullmatch(hosted), "invalid hosted run identity")
        require(git(ROOT, env, "rev-parse", "HEAD").decode().strip() == hosted, "diagnostic checkout differs from event")
        event = json.loads(Path(original_environment["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        pr = event["pull_request"]
        require(pr["base"]["sha"] == ENGINE and OID.fullmatch(pr["head"]["sha"]), "diagnostic PR must have exact 30cf base")
        headers = git(ROOT, env, "cat-file", "commit", hosted).split(b"\n\n", 1)[0].splitlines()
        parents = [line[7:].decode("ascii") for line in headers if line.startswith(b"parent ")]
        require(parents == [ENGINE, pr["head"]["sha"]], "actual diagnostic merge parents differ")
        report["hosted"] = {"run_id": run_id, "attempt": attempt, "checkout": hosted,
                            "tree": git(ROOT, env, "rev-parse", "HEAD^{tree}").decode().strip(),
                            "pull_request": pr["number"], "base": pr["base"]["sha"], "head": pr["head"]["sha"],
                            "actual_parents": parents,
                            "image": {name: original_environment.get(name) for name in
                                      ("RUNNER_OS", "RUNNER_ARCH", "ImageOS", "ImageVersion")}}
        own_paths = ("tools/requests_snapshot_acquisition.py", "tools/requests_snapshot_trace.py",
                     "tests/test_requests_snapshot_trace.py", ".github/workflows/requests-snapshot-diagnostic.yml")
        report["diagnostic_files"] = {name: canonical_file(ROOT, hosted, name, env) for name in own_paths}
        require(not git(ROOT, env, "status", "--porcelain", "--untracked-files=all"), "diagnostic source is not clean")
        helpers = ("tools/r1_cost_capture.py", "tools/release_inventory.py", "tools/qualify_assertions.py")
        report["original_helpers"] = {name: canonical_file(source, ENGINE, name, env) for name in helpers}
        os.environ.clear()
        os.environ.update(env)
        capture = module_from(source / helpers[0], "requests_original_capture")
        inventory = module_from(source / helpers[1], "requests_original_inventory")
        qualifier = module_from(source / helpers[2], "requests_original_source_invocation")
        report["package_before"] = checked_source(source, env, inventory)
        (output / "raw").mkdir()
        deadline = time.monotonic() + TOTAL_SECONDS
        corpus = scratch / "requests.git"
        setup = (
            ["git", "init", "--bare", str(corpus)],
            ["git", "-C", str(corpus), "remote", "add", "origin", "https://github.com/psf/requests.git"],
            ["git", "-C", str(corpus), "fetch", "--no-tags", "--depth=2", "origin", COMMIT],
            ["git", "--version"],
        )
        for index, command in enumerate(setup):
            observation = capture.capture(command, scratch / "cwd", env, output / "raw" / f"setup-{index}", 180, STREAM_LIMIT, deadline)
            capture.validate_capture(observation)
            require(observation["capture_complete"] and observation["exit_code"] == 0, "fixed corpus setup failed")
        require(git(corpus, env, "rev-parse", "--is-bare-repository").strip() == b"true", "corpus is not bare")
        require(git(corpus, env, "rev-parse", COMMIT + "^@").decode().split() == [PARENT], "fixed commit parent differs")
        report["corpus_trees"] = {}
        for label, revision in (("base", PARENT), ("head", COMMIT)):
            require(git(corpus, env, "rev-parse", revision + "^{commit}").decode().strip() == revision, "corpus revision differs")
            raw = git(corpus, env, "ls-tree", "-r", "-z", revision)
            (output / (label + ".tree.z")).write_bytes(raw)
            report["corpus_trees"][label] = {"revision": revision, "tree": git(corpus, env, "rev-parse", revision + "^{tree}").decode().strip(),
                                             "bytes": len(raw), "sha256": sha(raw)}
        cli = ["check", PARENT + ".." + COMMIT, "--repo", str(corpus), "--format", "json"]
        interpreter = os.path.abspath(sys.executable)  # Preserve virtualenv launch spelling.
        expected_package = {name: value["sha256"] for name, value in report["package_before"].items()}
        native = qualifier.invocation("source", source, None, [interpreter], expected_package, scratch / "cwd") + cli
        observer_path = ROOT / "tools" / "requests_snapshot_trace.py"
        receipt_path = output / "observer.json"
        bootstrap = ("import importlib.util, sys; s=importlib.util.spec_from_file_location('requests_snapshot_observer', "
                     + repr(str(observer_path)) + "); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
                     + "raise SystemExit(m.run(" + repr(str(source)) + ", " + repr(str(receipt_path)) + ", sys.argv[1:]))")
        diagnostic = [interpreter, "-I", "-B", "-c", bootstrap, *cli]
        for arm, command in (("native", native), ("diagnostic", diagnostic)):
            observation = capture.capture(command, scratch / "cwd", env, output / "raw" / arm, CLI_TIMEOUT, STREAM_LIMIT, deadline)
            report["arms"][arm] = observation
            capture.validate_capture(observation)
            require(observation["capture_complete"] and observation["cleanup_complete"], arm + " raw capture incomplete")
        native_result, diagnostic_result = report["arms"]["native"], report["arms"]["diagnostic"]
        equality = {"exit": native_result["exit_code"] == diagnostic_result["exit_code"]}
        for stream in ("stdout", "stderr"):
            equality[stream] = (output / "raw" / ("native." + stream)).read_bytes() == (output / "raw" / ("diagnostic." + stream)).read_bytes()
        report["native_diagnostic_equal"] = equality
        require(all(equality.values()), "diagnostic changed original exit or raw output; no causal attribution")
        require(receipt_path.is_file() and not receipt_path.is_symlink(), "final observer receipt missing")
        raw_observer = receipt_path.read_bytes()
        observed = observer_receipt(raw_observer, capture.decode, diagnostic_result["exit_code"])
        report["observer"] = {"path": "observer.json", "bytes": len(raw_observer), "sha256": sha(raw_observer),
                              "calls": len(observed["calls"]), "target_called": bool(observed["calls"])}
        report["package_after"] = checked_source(source, env, inventory)
        require(report["package_before"] == report["package_after"], "engine source changed during capture")
        report["state"] = "ACQUIRED_EQUAL_RAW_NOT_A_PRODUCT_PASS"
        return 0
    except Exception as error:
        report["failure"] = {"type": type(error).__name__, "reason": str(error)}
        return 2
    finally:
        os.environ.clear()
        os.environ.update(original_environment)
        # Raw files are never replaced or removed; a failed final write leaves a
        # native failing outer process and no claim of complete acquisition.
        with (output / "acquisition.json").open("x", encoding="utf-8", newline="\n") as destination:
            json.dump(report, destination, sort_keys=True, indent=2, allow_nan=False)
            destination.write("\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    raise SystemExit(run(arguments.engine, arguments.output))
