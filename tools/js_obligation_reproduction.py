"""Capture four owned JS pairs; no detector expectations are installed.

Only run by an ordinary hosted PR. All Checkwash invocations finish before any
owned subject code executes. Native Vitest subprocesses then prove the intended
ground truth. Collector exit 0 means captured attempts, never engine PASS.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
# Isolated Python omits the script directory. Add only this reviewed tools path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import owned_process_capture as process_capture

CASES_PATH = Path(__file__).with_name("js_obligation_pairs.json")
HELPER_PATH = Path(__file__).with_name("owned_process_capture.py")
TEMP = Path(os.environ["RUNNER_TEMP"]).resolve()
EVIDENCE = TEMP / "js-obligation-evidence"
REPOS = TEMP / "js-native" / "repos"
IDS = ("JS-CATCH-TAUTOLOGY", "JS-CATCH-RETHROW", "JS-EARLY-RETURN", "JS-RETURN-AFTER-ORACLE")
PURPOSE = "DIAGNOSTIC_CAPTURE_NOT_DETECTOR_QUALIFICATION"
NATIVE = TEMP / "js-native"
NODE = Path(os.environ["TRUSTED_NODE"])
NPM = Path(os.environ["TRUSTED_NPM"])
VITEST = NATIVE / "node_modules/vitest/vitest.mjs"
STREAM_LIMIT = 4_000_000
CONFIG_TEXT = ('export default { cacheDir: process.env.OWNED_VITE_CACHE, test: { '
               'include: ["value.test.ts"], environment: "node", pool: "forks", '
               'maxWorkers: 1, minWorkers: 1, fileParallelism: false, '
               'passWithNoTests: false, watch: false, reporters: ["json"] } };\n')


def save(path, data):
    process_capture.write(path, data)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def environment():
    # Pin native runner behavior without changing the four subject source pairs.
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith(("PYTHON", "PYTEST", "GIT_", "NODE_", "NPM_", "VITEST_", "VITE_"))}
    env.update(PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", CHECKWASH_TODAY="2026-10-12",
               NO_COLOR="1", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT="0")
    return env


def git(repo, *args, env=None):
    return subprocess.run(["git", "-C", str(repo), *args], env=env or environment(),
                          capture_output=True, check=True, timeout=30).stdout.decode("utf-8").strip()


def cases():
    data = read(CASES_PATH)
    found = {case["id"]: case for case in data["cases"]}
    if len(data["cases"]) != 4 or set(found) != set(IDS) or data["vitest_version"] != "3.2.4":
        raise ValueError("only the four fixed owned pairs and runner are permitted")
    return found


def snapshot(case, side):
    files = {name: text.encode("utf-8") for name, text in case["unchanged_context"].items()}
    for name, change in case["files"].items():
        text = change[side]
        if text is None:
            files.pop(name, None)
        else:
            files[name] = text.encode("utf-8")
    if set(files) != {"value.ts", "value.test.ts"}:
        raise ValueError("unexpected JS reproduction source set")
    return files


def verify_tree(repo, revision, expected):
    names = set(git(repo, "ls-tree", "-r", "--name-only", revision).splitlines())
    if names != set(expected):
        raise ValueError("Git source set differs from owned bytes")
    for name, raw in expected.items():
        result = subprocess.run(["git", "-C", str(repo), "show", revision + ":" + name],
                                env=environment(), capture_output=True, check=True, timeout=30)
        if result.stdout != raw:
            raise ValueError("Git source bytes differ from owned bytes")


def engine_manifest():
    directory = ROOT / "src/checkwash"
    return {path.relative_to(directory).as_posix(): digest(path)
            for path in sorted(directory.rglob("*")) if path.is_file()
            and "__pycache__" not in path.parts and path.suffix not in (".pyc", ".pyo")}


def prepare():
    import checkwash  # Trusted installed candidate only; no subject source exists yet.
    EVIDENCE.mkdir()
    if not NODE.is_absolute() or not NPM.is_absolute():
        raise ValueError("native Node and npm must be absolute trusted paths")
    REPOS.mkdir(parents=True)
    native_evidence = EVIDENCE / "native-install"
    native_evidence.mkdir()
    package = {"name": "owned-js-ground-truth", "private": True,
               "version": "0.0.0", "type": "module", "devDependencies": {"vitest": "3.2.4"}}
    save(NATIVE / "package.json", package)
    # npm rejects one real path loaded as both user and global config.
    # Use a separate owned empty global file; keep ambient config excluded.
    global_config = NATIVE / "empty-global.npmrc"
    global_config.write_bytes(b"")
    install_env = environment()
    install_env.update(NPM_CONFIG_USERCONFIG=os.devnull, NPM_CONFIG_GLOBALCONFIG=str(global_config),
                       NPM_CONFIG_CACHE=str(TEMP / "js-native-npm-cache"))
    argv = [str(NPM), "install", "--prefix", str(NATIVE), "--ignore-scripts",
            "--no-audit", "--no-fund", "--registry=https://registry.npmjs.org"]
    install = process_capture.capture(argv, TEMP, install_env, native_evidence / "install", 240, STREAM_LIMIT)
    save(native_evidence / "install.json", {"status": install["status"], "returncode": install["exit_code"],
         "argv": argv, "cwd": str(TEMP), "capture": install, "timeout_seconds": 240,
         "scripts": "DISABLED", "registry": "https://registry.npmjs.org"})
    for name in ("package.json", "package-lock.json"):
        if (NATIVE / name).exists():
            shutil.copyfile(NATIVE / name, native_evidence / name)
    if install["status"] != "EXITED" or install["exit_code"] != 0 or not install["capture_complete"]:
        raise ValueError("native runner dependency installation failed")
    installed = read(NATIVE / "node_modules/vitest/package.json")
    if installed["version"] != "3.2.4":
        raise ValueError("unexpected native runner version")
    shutil.copyfile(NATIVE / "node_modules/vitest/package.json", native_evidence / "vitest-package.json")
    config = NATIVE / "vitest.config.mjs"
    config.write_text(CONFIG_TEXT, encoding="utf-8")
    shutil.copyfile(config, native_evidence / config.name)
    identity = {
        "purpose": PURPOSE, "detector_qualification": "NOT_EVALUATED",
        "candidate_sha": os.environ["CANDIDATE_SHA"], "pr_head_sha": os.environ["PR_HEAD_SHA"],
        "pr_base_sha": os.environ["PR_BASE_SHA"], "source_head": git(ROOT, "rev-parse", "HEAD"),
        "source_tree": git(ROOT, "rev-parse", "HEAD^{tree}"),
        "source_commit_object": git(ROOT, "cat-file", "commit", "HEAD"),
        "source_status": git(ROOT, "status", "--porcelain"),
        "engine_path": str(Path(checkwash.__file__).resolve()),
        "engine_version": checkwash.__version__, "engine_files": engine_manifest(),
        "run_id": os.environ["GITHUB_RUN_ID"], "attempt": os.environ["GITHUB_RUN_ATTEMPT"],
        "event_name": os.environ["GITHUB_EVENT_NAME"],
        "python": sys.version, "executable": str(Path(sys.executable).resolve()),
        "platform": platform.platform(), "image_os": os.environ.get("ImageOS"),
        "image_version": os.environ.get("ImageVersion"), "git_version": git(ROOT, "--version"),
        "native": {"node": str(NODE), "node_realpath": str(NODE.resolve()),
                   "node_version": subprocess.run([str(NODE), "--version"], check=True,
                       capture_output=True, timeout=30, env=environment()).stdout.decode().strip(),
                   "npm": str(NPM), "vitest_version": installed["version"],
                   "vitest_entry": str(VITEST), "vitest_entry_sha256": digest(VITEST),
                   "config": str(config), "config_sha256": digest(config),
                   "lock_sha256": digest(NATIVE / "package-lock.json"),
                   "package_sha256": digest(NATIVE / "package.json"),
                   "vitest_package_sha256": digest(NATIVE / "node_modules/vitest/package.json")},
        "installed_distributions": sorted((dist.metadata.get("Name", ""), dist.version)
                                          for dist in importlib.metadata.distributions()),
        "collector_sha256": digest(Path(__file__)), "cases_sha256": digest(CASES_PATH),
        "capture_helper_sha256": digest(HELPER_PATH), "stream_limit_bytes": STREAM_LIMIT,
        "fixture_source_adjustment": "NONE",
        "policy": {"fail_on": "high", "task": None, "date": "2026-10-12",
                   "subject_config": "No .checkwash config, allowlist or TASK in either two-file tree"},
        "cases": {},
    }
    save(EVIDENCE / "binding.json", identity)
    if (identity["source_head"] != identity["candidate_sha"] or identity["source_status"]
            or Path(identity["engine_path"]) != (ROOT / "src/checkwash/__init__.py").resolve()
            or identity["native"]["vitest_version"] != "3.2.4"):
        raise ValueError("source/install/runner identity mismatch")
    (EVIDENCE / "js_obligation_pairs.json").write_bytes(CASES_PATH.read_bytes())
    for case_id, case in cases().items():
        repo, evidence = REPOS / case_id, EVIDENCE / case_id
        repo.mkdir()
        evidence.mkdir()
        git(repo, "init", "--object-format=sha1", "-b", "main")
        git(repo, "config", "user.name", "Owned JS obligation reproduction")
        git(repo, "config", "user.email", "js-obligation@example.invalid")
        git(repo, "config", "commit.gpgsign", "false")
        refs, hashes = {}, {}
        for index, side in enumerate(("before", "after")):
            files = snapshot(case, side)
            output = evidence / side
            output.mkdir()
            for name, raw in files.items():
                target = repo / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
                saved = output / name
                saved.parent.mkdir(parents=True, exist_ok=True)
                saved.write_bytes(raw)
            git(repo, "add", "--", ".")
            fixed = {**environment(), "GIT_AUTHOR_DATE": f"2000-01-01T00:00:0{index}+00:00",
                     "GIT_COMMITTER_DATE": f"2000-01-01T00:00:0{index}+00:00"}
            git(repo, "commit", "-m", case_id + " " + side, env=fixed)
            refs[side] = git(repo, "rev-parse", "HEAD")
            verify_tree(repo, refs[side], files)
            hashes[side] = {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()}
        raw_diff = subprocess.run(["git", "-C", str(repo), "diff", "--binary", refs["before"], refs["after"]],
                                  env=environment(), capture_output=True, check=True, timeout=30).stdout
        (evidence / "source.diff").write_bytes(raw_diff)
        identity["cases"][case_id] = {"refs": refs, "files": hashes, "repo": str(repo),
                                     "diff_sha256": digest(evidence / "source.diff"),
                                     "paired_control": case["paired_control"]}
        save(EVIDENCE / "binding.json", identity)
    print("Four owned source pairs prepared; no runtime or detector result claimed.")


def invoke(case_id, label, command, cwd, refs, extra_env=None):
    directory = EVIDENCE / case_id / label
    directory.mkdir()
    result = {"purpose": PURPOSE, "case": case_id, "label": label, "refs": refs,
              "argv": command, "cwd": str(cwd), "timeout_seconds": 30,
              "extra_env": extra_env or {},
              "binding_sha256": digest(EVIDENCE / "binding.json"),
              "sequence_index": IDS.index(case_id) if label == "checkwash" else 4 + 2 * IDS.index(case_id) + int(label == "vitest-after"),
              "started_unix": time.time(),
              "started_monotonic": time.monotonic(),
              "status": "NOT_STARTED", "returncode": None}
    save(directory / "process.json", result)
    observation = process_capture.capture(command, cwd, {**environment(), **(extra_env or {})},
                                          directory / "process", 30, STREAM_LIMIT)
    result.update(status=observation["status"], returncode=observation["exit_code"], capture=observation,
                  elapsed_seconds=observation["elapsed_seconds"], ended_unix=time.time(), ended_monotonic=time.monotonic())
    if label.startswith("vitest-"):
        result["report_sha256"] = digest(directory / "vitest.json") if (directory / "vitest.json").exists() else None
    save(directory / "process.json", result)
    if not observation["cleanup_complete"]:
        raise ValueError("process cleanup uncertain; no further source checkout or invocation")
    return result


def capture():
    binding = read(EVIDENCE / "binding.json")
    verify_bindings(binding)
    all_cases = cases()
    # Read-only engine analysis of all four pairs precedes ANY owned test execution.
    for case_id in IDS:
        row = binding["cases"][case_id]
        repo, refs = Path(row["repo"]), row["refs"]
        for side in ("before", "after"):
            verify_tree(repo, refs[side], snapshot(all_cases[case_id], side))
        if git(repo, "status", "--porcelain"):
            raise ValueError("owned repository changed before analysis")
        command = [sys.executable, "-I", "-B", "-X", "utf8", "-m", "checkwash", "check",
                   refs["before"] + "..." + refs["after"], "--repo", str(repo), "--format", "json", "--fail-on", "high"]
        record = invoke(case_id, "checkwash", command, TEMP, refs)
        directory = EVIDENCE / case_id / "checkwash"
        observed = {"detector_qualification": "NOT_EVALUATED", "process_status": record["status"],
                    "exit_code": record["returncode"], "json_state": "UNAVAILABLE",
                    "finding_labels": "NOT_ADJUDICATED"}
        try:
            payload = json.loads((directory / "process.stdout").read_bytes())
            # Original JSON lives in process.stdout; no finding projection or relabeling.
            observed.update(json_state="PARSED", report=payload)
        except (ValueError, UnicodeDecodeError) as exc:
            observed.update(json_state="INVALID_OR_ABSENT", json_error=type(exc).__name__)
        save(directory / "observed.json", observed)
    for case_id in IDS:
        row = binding["cases"][case_id]
        repo, refs = Path(row["repo"]), row["refs"]
        for side in ("before", "after"):
            git(repo, "checkout", "--detach", refs[side])
            verify_tree(repo, refs[side], snapshot(all_cases[case_id], side))
            if git(repo, "status", "--porcelain"):
                raise ValueError("owned repository changed before native Vitest")
            label = "vitest-" + side
            report = EVIDENCE / case_id / label / "vitest.json"
            # An actual pinned Vitest process resolves this owned pair's imports.
            # Trusted config/cache/runner remain outside the two-file Git tree.
            command = [str(NODE), str(VITEST), "run", "--root", str(repo), "--config",
                       binding["native"]["config"], "--outputFile", str(report)]
            invoke(case_id, label, command, repo, refs,
                   {"OWNED_VITE_CACHE": str(TEMP / "js-native-cache" / case_id / side)})
            verify_tree(repo, refs[side], snapshot(all_cases[case_id], side))
            if git(repo, "status", "--porcelain"):
                raise ValueError("native Vitest changed tracked or untracked subject files")
    if (digest(VITEST) != binding["native"]["vitest_entry_sha256"]
            or digest(Path(binding["native"]["config"])) != binding["native"]["config_sha256"]
            or digest(NATIVE / "package-lock.json") != binding["native"]["lock_sha256"]):
        raise ValueError("native runner identity changed during reproduction")
    if (engine_manifest() != binding["engine_files"] or git(ROOT, "status", "--porcelain")
            or git(ROOT, "rev-parse", "HEAD") != binding["source_head"]
            or git(ROOT, "rev-parse", "HEAD^{tree}") != binding["source_tree"]):
        raise ValueError("trusted engine changed during reproduction")
    print("Twelve subprocess attempts captured. Checkwash verdicts are observations, not qualification.")


def verify_capture(directory, prefix, record, argv, cwd, timeout):
    """Check the original capture sidecars/bytes without relabeling engine output."""
    observation = record["capture"]
    intent = read(directory / (prefix + ".intent.json"))
    terminal = read(directory / (prefix + ".observation.json"))
    if (record["argv"] != argv or record["cwd"] != str(cwd) or record["timeout_seconds"] != timeout
            or terminal != observation or intent["argv"] != argv or observation["argv"] != argv
            or intent["timeout_seconds"] != timeout or record["status"] != observation["status"]
            or record["returncode"] != observation["exit_code"]):
        raise ValueError("actual command/cwd/timeout/terminal binding differs")
    for name in ("spawned", "capture_complete", "cleanup_complete", "output_limit_observed"):
        if type(observation[name]) is not bool:
            raise ValueError("malformed capture flag")
    status, stop, code = observation["status"], observation["first_stop_reason"], observation["exit_code"]
    states = {"EXITED", "TIMEOUT", "OUTPUT_LIMIT", "CAPTURE_FAILED", "SPAWN_FAILED", "DEADLINE_NOT_LAUNCHED"}
    errors = observation["capture_errors"]
    if (status not in states or stop not in (states - {"EXITED"}) | {None}
            or type(errors) is not list or any(type(item) is not str for item in errors)
            or (code is not None and type(code) is not int)
            or observation["cleanup_complete"] != (not errors)
            or (stop is not None and stop != status)):
        raise ValueError("malformed or contradictory capture state")
    if observation["spawned"]:
        if (intent["state"] != "LAUNCHED" or intent["launch_executable"] != argv[0]
                or intent["executable"] != observation["executable"]
                or observation["executable"] != str(Path(argv[0]).resolve())
                or status in ("SPAWN_FAILED", "DEADLINE_NOT_LAUNCHED")):
            raise ValueError("actual launch executable/state differs")
    elif intent["state"] != "LAUNCH_INTENT" or code is not None or status not in ("SPAWN_FAILED", "DEADLINE_NOT_LAUNCHED") or stop != status:
        raise ValueError("unspawned capture has an invented product result")
    seconds = observation["elapsed_seconds"]
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
        raise ValueError("invalid capture duration")
    if (set(observation["streams"]) != {"stdout", "stderr"} or type(observation["output_limit_bytes"]) is not int
            or observation["output_limit_bytes"] != STREAM_LIMIT or (status == "TIMEOUT" and stop != "TIMEOUT")):
        raise ValueError("capture stream set/bound differs")
    raw, overflow, counters_complete = {}, False, True
    for name in ("stdout", "stderr"):
        row = observation["streams"][name]
        filename = prefix + "." + name
        raw[name] = (directory / filename).read_bytes()
        kept, seen = row["retained_bytes"], row["observed_bytes"]
        if (row["path"] != filename or intent["streams"][name] != filename
                or row["sha256"] != digest(directory / filename) or type(row["bytes"]) is not int or row["bytes"] != len(raw[name])
                or type(kept) is not int or kept != len(raw[name]) or kept > STREAM_LIMIT
                or (seen is not None and (type(seen) is not int or seen < kept))):
            raise ValueError("raw stream identity/counters differ")
        overflow |= seen is not None and seen > STREAM_LIMIT
        counters_complete &= seen == kept
    if observation["output_limit_observed"] != overflow or (status == "OUTPUT_LIMIT" and not overflow):
        raise ValueError("output-limit flag differs from raw counters")
    complete = (status == "EXITED" and observation["spawned"] and type(code) is int and stop is None
                and observation["cleanup_complete"] and not overflow and counters_complete)
    if observation["capture_complete"] != complete or (status == "EXITED" and not complete):
        raise ValueError("contradictory complete-capture claim")
    return raw


def verify_bindings(binding):
    if (binding["purpose"] != PURPOSE or binding["detector_qualification"] != "NOT_EVALUATED"
            or binding["event_name"] != "pull_request" or os.environ["GITHUB_EVENT_NAME"] != "pull_request"
            or any(not re.fullmatch(r"[0-9a-f]{40}", os.environ[name]) for name in ("CANDIDATE_SHA", "PR_HEAD_SHA", "PR_BASE_SHA"))
            or binding["candidate_sha"] != binding["source_head"] or binding["source_head"] != os.environ["CANDIDATE_SHA"]
            or binding["pr_head_sha"] != os.environ["PR_HEAD_SHA"] or binding["pr_base_sha"] != os.environ["PR_BASE_SHA"]
            or binding["run_id"] != os.environ["GITHUB_RUN_ID"] or binding["attempt"] != os.environ["GITHUB_RUN_ATTEMPT"]
            or binding["source_status"] or binding["executable"] != str(Path(sys.executable).resolve())
            or binding["engine_path"] != str((ROOT / "src/checkwash/__init__.py").resolve())
            or binding["collector_sha256"] != digest(Path(__file__)) or binding["cases_sha256"] != digest(CASES_PATH)
            or binding["capture_helper_sha256"] != digest(HELPER_PATH) or binding["stream_limit_bytes"] != STREAM_LIMIT
            or git(ROOT, "rev-parse", "HEAD") != binding["source_head"]
            or git(ROOT, "rev-parse", "HEAD^{tree}") != binding["source_tree"]
            or git(ROOT, "cat-file", "commit", "HEAD") != binding["source_commit_object"]
            or git(ROOT, "status", "--porcelain") or engine_manifest() != binding["engine_files"]):
        raise ValueError("source/event/run/helper binding mismatch")
    native = binding["native"]
    if (native["node"] != str(NODE) or native["node_realpath"] != str(NODE.resolve()) or native["npm"] != str(NPM)
            or native["vitest_entry"] != str(VITEST) or native["config"] != str(NATIVE / "vitest.config.mjs")
            or native["vitest_entry_sha256"] != digest(VITEST) or native["vitest_version"] != "3.2.4"
            or (NATIVE / "empty-global.npmrc").read_bytes() != b""
            or (NATIVE / "vitest.config.mjs").read_bytes() != CONFIG_TEXT.encode("utf-8")
            or read(NATIVE / "node_modules/vitest/package.json")["version"] != "3.2.4"):
        raise ValueError("native runner/config binding differs")
    for filename, field, live in (("vitest.config.mjs", "config_sha256", NATIVE / "vitest.config.mjs"),
                                  ("package-lock.json", "lock_sha256", NATIVE / "package-lock.json"),
                                  ("package.json", "package_sha256", NATIVE / "package.json"),
                                  ("vitest-package.json", "vitest_package_sha256", NATIVE / "node_modules/vitest/package.json")):
        if digest(live) != native[field] or digest(EVIDENCE / "native-install" / filename) != native[field]:
            raise ValueError("native installation evidence bytes differ")
    install = read(EVIDENCE / "native-install/install.json")
    argv = [str(NPM), "install", "--prefix", str(NATIVE), "--ignore-scripts", "--no-audit", "--no-fund",
            "--registry=https://registry.npmjs.org"]
    verify_capture(EVIDENCE / "native-install", "install", install, argv, TEMP, 240)
    if not install["capture"]["capture_complete"] or install["returncode"] != 0:
        raise ValueError("original native installation did not complete successfully")
    owned = cases()
    if set(binding["cases"]) != set(IDS) or (EVIDENCE / "js_obligation_pairs.json").read_bytes() != CASES_PATH.read_bytes():
        raise ValueError("owned case inventory differs")
    for case_id in IDS:
        row, case = binding["cases"][case_id], owned[case_id]
        repo = REPOS / case_id
        if (row["repo"] != str(repo) or set(row["refs"]) != {"before", "after"}
                or any(not re.fullmatch(r"[0-9a-f]{40}", sha) for sha in row["refs"].values())
                or row["paired_control"] != case["paired_control"]
                or git(repo, "rev-parse", row["refs"]["after"] + "^") != row["refs"]["before"]
                or git(repo, "rev-parse", "HEAD") != row["refs"]["after"] or git(repo, "status", "--porcelain")):
            raise ValueError("owned history path/refs/control differ")
        for side in ("before", "after"):
            files = snapshot(case, side)
            if row["files"][side] != {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()}:
                raise ValueError("owned source hash binding differs")
            verify_tree(repo, row["refs"][side], files)
            for name, raw in files.items():
                if (EVIDENCE / case_id / side / name).read_bytes() != raw:
                    raise ValueError("copied owned source evidence differs")
                if side == "after" and (repo / name).read_bytes() != raw:
                    raise ValueError("current owned worktree source bytes differ")
        if digest(EVIDENCE / case_id / "source.diff") != row["diff_sha256"]:
            raise ValueError("original owned diff bytes changed")


def validate():
    binding = read(EVIDENCE / "binding.json")
    verify_bindings(binding)
    failures, native, engine, timeline = [], [], [], []
    for case_id in IDS:
        refs = binding["cases"][case_id]["refs"]
        for label in ("checkwash", "vitest-before", "vitest-after"):
            directory = EVIDENCE / case_id / label
            process = read(directory / "process.json")
            if (process["case"] != case_id or process["label"] != label or process["refs"] != refs
                    or process["binding_sha256"] != digest(EVIDENCE / "binding.json")
                    or process["purpose"] != PURPOSE):
                raise ValueError("missing or mismatched original subprocess evidence")
            repo = REPOS / case_id
            if label == "checkwash":
                argv = [sys.executable, "-I", "-B", "-X", "utf8", "-m", "checkwash", "check",
                        refs["before"] + "..." + refs["after"], "--repo", str(repo), "--format", "json", "--fail-on", "high"]
                cwd, extra, index = TEMP, {}, IDS.index(case_id)
            else:
                side = label.removeprefix("vitest-")
                argv = [str(NODE), str(VITEST), "run", "--root", str(repo), "--config",
                        binding["native"]["config"], "--outputFile", str(directory / "vitest.json")]
                cwd, extra = repo, {"OWNED_VITE_CACHE": str(TEMP / "js-native-cache" / case_id / side)}
                index = 4 + 2 * IDS.index(case_id) + int(side == "after")
            if process["extra_env"] != extra or type(process["sequence_index"]) is not int or process["sequence_index"] != index:
                raise ValueError("cache environment or invocation sequence differs")
            raw = verify_capture(directory, "process", process, argv, cwd, 30)
            if not process["capture"]["cleanup_complete"] or process["elapsed_seconds"] != process["capture"]["elapsed_seconds"]:
                raise ValueError("uncertain cleanup or duration binding")
            start, end = process["started_monotonic"], process["ended_monotonic"]
            if any(type(value) not in (int, float) or not math.isfinite(value) or value < 0 for value in (start, end)) or end < start:
                raise ValueError("invalid invocation timing bounds")
            timeline.append({"index": index, "start": start, "end": end})
            if label == "checkwash":
                observed = read(directory / "observed.json")
                if (observed["detector_qualification"] != "NOT_EVALUATED" or observed["finding_labels"] != "NOT_ADJUDICATED"
                        or observed["process_status"] != process["status"] or observed["exit_code"] != process["returncode"]):
                    raise ValueError("Checkwash observation changes raw status")
                try:
                    payload = json.loads(raw["stdout"])
                except (ValueError, UnicodeDecodeError) as exc:
                    if observed["json_state"] != "INVALID_OR_ABSENT" or observed["json_error"] != type(exc).__name__:
                        raise ValueError("Checkwash JSON failure observation differs")
                else:
                    if observed["json_state"] != "PARSED" or observed["report"] != payload:
                        raise ValueError("Checkwash parsed observation differs from original bytes")
                engine.append({"case": case_id, "status": process["status"], "exit_code": process["returncode"],
                               "capture_complete": process["capture"]["capture_complete"],
                               "observed": str(directory / "observed.json")})
                continue  # Deliberately no current finding/severity/verdict expectation.
            expected_exit = 0 if label == "vitest-after" and case_id in (
                "JS-CATCH-TAUTOLOGY", "JS-EARLY-RETURN") else 1
            outcome = {"case": case_id, "side": label.removeprefix("vitest-"),
                       "expected_exit": expected_exit, "actual_exit": process["returncode"], "verified": False}
            try:
                if raw["stderr"]:
                    raise ValueError("native stderr is nonempty; no warning or global-error exemption")
                document = read(directory / "vitest.json")
                if process["report_sha256"] != digest(directory / "vitest.json"):
                    raise ValueError("native report changed after process-group cleanup")
                suites = document["testResults"]
                testcases = [test for suite in suites for test in suite["assertionResults"]]
                actual = {name: document[name] for name in (
                    "numTotalTests", "numFailedTests", "numPassedTests", "numPendingTests", "numTodoTests")}
                outcome["report_counts"] = actual
                outcome["report_sha256"] = digest(directory / "vitest.json")
                wanted = {"numTotalTests": 1, "numFailedTests": expected_exit,
                          "numPassedTests": 1 - expected_exit, "numPendingTests": 0, "numTodoTests": 0}
                if (process["status"] != "EXITED" or not process["capture"]["capture_complete"] or process["returncode"] != expected_exit
                        or any(type(value) is not int for value in actual.values())
                        or actual != wanted or len(testcases) != 1 or testcases[0]["title"] != "value"
                        or len(suites) != 1 or Path(suites[0]["name"]) != Path(binding["cases"][case_id]["repo"]) / "value.test.ts"
                        or suites[0]["message"] or document["success"] is not (expected_exit == 0)
                        or suites[0]["status"] != ("passed" if expected_exit == 0 else "failed")
                        or testcases[0]["status"] != ("passed" if expected_exit == 0 else "failed")):
                    raise ValueError("native test was absent, skipped, errored or did not have the intended outcome")
                if expected_exit:
                    text = "\n".join(testcases[0]["failureMessages"])
                    if "AssertionError" not in text or "expected +0 to be 1 // Object.is equality" not in text:
                        raise ValueError("failure does not show the owned failing oracle")
                elif testcases[0]["failureMessages"]:
                    raise ValueError("passing test unexpectedly carries failure messages")
                outcome["verified"] = True
            except (OSError, ValueError, KeyError, TypeError) as exc:
                outcome["error"] = type(exc).__name__ + ": " + str(exc)
                failures.append(case_id + "/" + label)
            native.append(outcome)
    timeline.sort(key=lambda row: row["index"])
    if ([row["index"] for row in timeline] != list(range(12))
            or any(a["end"] > b["start"] for a, b in zip(timeline, timeline[1:]))):
        raise ValueError("four Checkwash attempts did not precede eight isolated native attempts")
    save(EVIDENCE / "verification.json",
         {"purpose": PURPOSE, "native_ground_truth": native, "ground_truth_failures": failures,
          "checkwash_observations": engine, "detector_qualification": "NOT_EVALUATED",
          "invocation_timeline": timeline, "native_stderr_policy": "EMPTY_REQUIRED_NO_EXEMPTIONS",
          "checkwash_failure_or_timeout_is_not_pass": True})
    if failures:
        raise ValueError("owned ground truth NOT reproduced: " + ", ".join(failures))
    print("Eight native ground-truth outcomes verified. Four Checkwash observations remain unadjudicated.")


if __name__ == "__main__":
    {"prepare": prepare, "capture": capture, "validate": validate}[sys.argv[1]]()
