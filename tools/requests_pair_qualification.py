"""One fixed requests pair, one uninstrumented source CLI, one hosted run.

SOURCE_SHA and QUALIFICATION_HEAD_REF are deliberately unrendered. Capture
completion and the original native verdict remain separate in the receipt.
This file derives only the necessary machinery from the sealed #390 collector.
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
import tomllib


ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHA = "1ec9d1e06d24b6071474f6fd14603cf7087bce6f"
QUALIFICATION_HEAD_REF = "fix/requests-optional-probe-346-v1"
PARENT = "f8aa36b92d95e6d2f133489f39f9d5c2412f1bd9"
COMMIT = "4e383642a9ebb82a67eaeed199d0fbbb31991e3c"
PAIR = {"repository": "psf/requests", "ordinal": 2037, "parent": PARENT, "commit": COMMIT}
PAIR_TREES = {"base": "034ae7aca8cb624f7613b524f9c509e9415bb48a",
              "head": "510fec90002aa16b5e68d9383593e630cf4e34f7"}
OID = re.compile(r"[a-f0-9]{40}\Z")
STREAM_LIMIT = 4_000_000
CLI_TIMEOUT = 120
SETUP_TIMEOUT = 120
TOTAL_SECONDS = 900
FINDINGS_VERSION = 2
HELPERS = {
    "tools/r1_cost_capture.py": "668a5dc4d405e369c62819d3b7c462d3429abd0c20a0981e4e27901f683833e2",
    "tools/release_inventory.py": "efe46f1caeefa0db7afd7690759bf087c452e70ddfeab49453ff4b11ba17af5b",
    "tools/qualify_assertions.py": "8b06293aa3192c40cb555fee7bdc408dfcfbf20e8df1b4cd4dfead824c1a8995",
}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def git(repo, env, *args):
    result = subprocess.run(["git", "-c", "core.hooksPath=" + os.devnull, "-C", str(repo), *args], env=env,
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
    require(git(source, env, "rev-parse", "HEAD").decode().strip() == SOURCE_SHA, "source commit differs")
    require(not git(source, env, "status", "--porcelain", "--untracked-files=all"), "source checkout is not clean")
    _, proof = inventory.source_inventory(SOURCE_SHA)
    actual = set()
    for path in (source / "src").rglob("*"):
        require(not path.is_symlink(), "source contains an untracked/ignored symlink")
        if path.is_file():
            actual.add(path.relative_to(source / "src").as_posix())
    require(actual == set(proof) and proof, "complete source inventory differs")
    return proof


def run(source, output):
    require(sys.platform == "linux" and sys.version_info[:2] == (3, 12), "Ubuntu Python 3.12 only")
    source, output = source.resolve(), output.absolute()
    temporary_root = Path(os.environ["RUNNER_TEMP"]).resolve()
    require(not output.exists() and output.resolve().is_relative_to(temporary_root), "output must be fresh under runner temp")
    require(not output.resolve().is_relative_to(source) and not output.resolve().is_relative_to(ROOT), "output overlaps source")
    output.mkdir(parents=True)
    scratch = output.parent / (output.name + "-scratch")
    scratch.mkdir()
    for name in ("home", "tmp", "cwd"):
        (scratch / name).mkdir()
    env = {"PATH": os.environ["PATH"], "HOME": str(scratch / "home"), "TMPDIR": str(scratch / "tmp"),
           "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TZ": "UTC", "NO_COLOR": "1",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
           "GIT_OPTIONAL_LOCKS": "0"}
    original_environment = dict(os.environ)
    report = {"purpose": "REQUESTS_2037_SINGLE_SOURCE_CLI_QUALIFICATION", "state": "INCOMPLETE",
              "pair": PAIR, "source_commit": SOURCE_SHA, "qualification_head_ref": QUALIFICATION_HEAD_REF,
              "environment": env, "runtime": {"python": sys.version, "platform": platform.platform(),
              "launch_python": os.path.abspath(sys.executable), "resolved_python": str(Path(sys.executable).resolve())},
              "native": "NOT_ATTEMPTED", "failure": None, "cost_acceptance": "NOT_ADJUDICATED"}
    try:
        require(OID.fullmatch(SOURCE_SHA), "SOURCE_SHA is unrendered")
        require(QUALIFICATION_HEAD_REF != "QUALIFICATION_" + "HEAD_REF" and QUALIFICATION_HEAD_REF,
                "qualification head ref is unrendered")
        run_id, attempt, hosted = (original_environment[name] for name in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_SHA"))
        require(run_id.isdecimal() and attempt == "1" and OID.fullmatch(hosted), "invalid first-attempt hosted identity")
        require(original_environment["GITHUB_EVENT_NAME"] == "pull_request", "ordinary PR event required")
        require(git(ROOT, env, "rev-parse", "HEAD").decode().strip() == hosted, "qualification checkout differs from event")
        event = json.loads(Path(original_environment["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        require(event["action"] == "opened", "new PR opened event required")
        pr = event["pull_request"]
        require(pr["head"]["ref"] == QUALIFICATION_HEAD_REF and OID.fullmatch(pr["base"]["sha"])
                and OID.fullmatch(pr["head"]["sha"]), "qualification PR identity differs")
        headers = git(ROOT, env, "cat-file", "commit", hosted).split(b"\n\n", 1)[0].splitlines()
        parents = [line[7:].decode("ascii") for line in headers if line.startswith(b"parent ")]
        require(parents == [pr["base"]["sha"], pr["head"]["sha"]], "actual qualification merge parents differ")
        report["hosted"] = {"run_id": run_id, "attempt": attempt, "checkout": hosted,
                            "tree": git(ROOT, env, "rev-parse", "HEAD^{tree}").decode().strip(),
                            "pull_request": pr["number"], "base": pr["base"]["sha"], "head": pr["head"]["sha"],
                            "actual_parents": parents,
                            "image": {name: original_environment.get(name) for name in
                                      ("RUNNER_OS", "RUNNER_ARCH", "ImageOS", "ImageVersion")}}
        own_paths = ("tools/requests_pair_qualification.py", ".github/workflows/requests-pair-qualification.yml")
        report["qualification_files"] = {name: canonical_file(ROOT, hosted, name, env) for name in own_paths}
        require(not git(ROOT, env, "status", "--porcelain", "--untracked-files=all"), "qualification source is not clean")
        require(git(source, env, "rev-parse", "HEAD").decode().strip() == SOURCE_SHA, "pinned source checkout differs")
        report["source_tree"] = git(source, env, "rev-parse", "HEAD^{tree}").decode().strip()
        report["same_source"] = {}
        for name in ("src", "tests"):
            pinned = git(source, env, "rev-parse", SOURCE_SHA + ":" + name).decode().strip()
            current = git(ROOT, env, "rev-parse", hosted + ":" + name).decode().strip()
            require(pinned == current, "qualification-only child changed " + name)
            report["same_source"][name] = pinned
        source_project = canonical_file(source, SOURCE_SHA, "pyproject.toml", env)
        current_project = canonical_file(ROOT, hosted, "pyproject.toml", env)
        require(source_project == current_project, "qualification-only child changed pyproject.toml")
        report["same_source"]["pyproject.toml"] = source_project
        version = tomllib.loads((source / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
        require(type(version) is str and version, "static source version missing")
        engine = {"version": version, "findings_version": FINDINGS_VERSION}
        report["expected_envelope"] = engine
        report["original_helpers"] = {name: canonical_file(source, SOURCE_SHA, name, env) for name in HELPERS}
        require(all(report["original_helpers"][name]["sha256"] == expected for name, expected in HELPERS.items()),
                "existing sealed helper source changed")
        os.environ.clear()
        os.environ.update(env)
        capture = module_from(source / "tools/r1_cost_capture.py", "requests_existing_capture")
        inventory = module_from(source / "tools/release_inventory.py", "requests_existing_inventory")
        qualifier = module_from(source / "tools/qualify_assertions.py", "requests_existing_source_invocation")
        report["package_before"] = checked_source(source, env, inventory)
        (output / "raw").mkdir()
        deadline = time.monotonic() + TOTAL_SECONDS
        corpus = scratch / "requests.git"
        git_prefix = ["git", "-c", "core.hooksPath=" + os.devnull]
        setup = (
            git_prefix + ["init", "--bare", str(corpus)],
            git_prefix + ["-C", str(corpus), "remote", "add", "origin", "https://github.com/psf/requests.git"],
            git_prefix + ["-C", str(corpus), "fetch", "--no-tags", "--depth=2", "origin", COMMIT],
            git_prefix + ["--version"],
        )
        for index, command in enumerate(setup):
            observation = capture.capture(command, scratch / "cwd", env, output / "raw" / f"setup-{index}", SETUP_TIMEOUT, STREAM_LIMIT, deadline)
            capture.validate_capture(observation)
            require(observation["capture_complete"] and observation["cleanup_complete"] and observation["exit_code"] == 0,
                    "fixed pair setup failed")
        require(git(corpus, env, "rev-parse", "--is-bare-repository").strip() == b"true", "corpus is not bare")
        require(git(corpus, env, "rev-parse", COMMIT + "^@").decode().split() == [PARENT], "fixed commit parent differs")
        report["corpus_trees"] = {}
        labels = {}
        for label, revision in (("base", PARENT), ("head", COMMIT)):
            require(git(corpus, env, "rev-parse", revision + "^{commit}").decode().strip() == revision, "corpus revision differs")
            tree = git(corpus, env, "rev-parse", revision + "^{tree}").decode().strip()
            require(tree == PAIR_TREES[label], "original fixed pair tree differs")
            raw = git(corpus, env, "ls-tree", "-r", "-z", revision)
            with (output / (label + ".tree.z")).open("xb") as destination:
                destination.write(raw)
            report["corpus_trees"][label] = {"revision": revision, "tree": tree, "bytes": len(raw), "sha256": sha(raw)}
            short = git(corpus, env, "rev-parse", "--short", revision).decode().strip()
            require(len(short) >= 7 and revision.startswith(short)
                    and git(corpus, env, "rev-parse", short).decode().strip() == revision, "range label is not unique")
            labels[label] = short
        report["reported_labels"] = labels
        cli = ["check", PARENT + ".." + COMMIT, "--repo", str(corpus), "--format", "json"]
        interpreter = os.path.abspath(sys.executable)
        expected_package = {name: value["sha256"] for name, value in report["package_before"].items()}
        native = qualifier.invocation("source", source, None, [interpreter], expected_package, scratch / "cwd") + cli
        observation = capture.capture(native, scratch / "cwd", env, output / "raw" / "native", CLI_TIMEOUT, STREAM_LIMIT, deadline)
        report["native"] = observation
        capture.validate_capture(observation)
        require(observation["capture_complete"] and observation["cleanup_complete"], "native raw capture incomplete")
        payload = None
        try:
            payload = capture.decode((output / "raw" / "native.stdout").read_bytes())
        except (UnicodeError, ValueError) as error:
            report["payload_error"] = {"type": type(error).__name__, "reason": str(error)}
        outcome = capture.classify(observation, payload, PAIR, engine, labels)
        report["classification"] = outcome
        report["package_after"] = checked_source(source, env, inventory)
        require(report["package_before"] == report["package_after"], "source changed during native capture")
        require(outcome in ("ANALYZED_PASS", "ANALYZED_BLOCK"), "native analysis remains incomplete: " + outcome)
        report["state"] = "COMPLETE_ANALYSIS_NATIVE_VERDICT_RETAINED"
        # Keep the real 0/1 verdict in the job; never make a native block green.
        return observation["exit_code"]
    except Exception as error:
        report["failure"] = {"type": type(error).__name__, "reason": str(error)}
        return 2
    finally:
        os.environ.clear()
        os.environ.update(original_environment)
        with (output / "qualification.json").open("x", encoding="utf-8", newline="\n") as destination:
            json.dump(report, destination, sort_keys=True, indent=2, allow_nan=False)
            destination.write("\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    raise SystemExit(run(arguments.source, arguments.output))
