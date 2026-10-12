"""Capture four owned runtime/API pairs; no detector expectations are installed.

Only run by an ordinary hosted PR. All Checkwash invocations finish before any
owned subject code executes. Native pytest subprocesses then prove the intended
ground truth. Collector exit 0 means captured attempts, never engine PASS.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = Path(__file__).with_name("runtime_api_pairs.json")
TEMP = Path(os.environ["RUNNER_TEMP"]).resolve()
EVIDENCE = TEMP / "runtime-api-evidence"
REPOS = TEMP / "runtime-api-owned-repos"
IDS = ("RT-ITEM-NOOP", "RT-ITEM-DELEGATE", "RT-ASSERT-NOOP", "RT-ASSERT-DELEGATE")
PURPOSE = "DIAGNOSTIC_CAPTURE_NOT_DETECTOR_QUALIFICATION"


def save(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def environment():
    # Pin native runner behavior without changing the four subject source pairs.
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith(("PYTHON", "PYTEST", "GIT_"))}
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
    if len(data["cases"]) != 4 or set(found) != set(IDS) or data["pytest_version"] != "8.4.2":
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
    if set(files) != {"app.py", "tests/test_value.py", "conftest.py"}:
        raise ValueError("unexpected runtime reproduction source set")
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
    REPOS.mkdir()
    identity = {
        "purpose": PURPOSE, "detector_qualification": "NOT_EVALUATED",
        "candidate_sha": os.environ["CANDIDATE_SHA"], "pr_head_sha": os.environ["PR_HEAD_SHA"],
        "pr_base_sha": os.environ["PR_BASE_SHA"], "source_head": git(ROOT, "rev-parse", "HEAD"),
        "source_tree": git(ROOT, "rev-parse", "HEAD^{tree}"),
        "source_parents": git(ROOT, "rev-list", "--parents", "-n", "1", "HEAD"),
        "source_status": git(ROOT, "status", "--porcelain"),
        "engine_path": str(Path(checkwash.__file__).resolve()),
        "engine_version": checkwash.__version__, "engine_files": engine_manifest(),
        "run_id": os.environ["GITHUB_RUN_ID"], "attempt": os.environ["GITHUB_RUN_ATTEMPT"],
        "python": sys.version, "executable": str(Path(sys.executable).resolve()),
        "platform": platform.platform(), "image_os": os.environ.get("ImageOS"),
        "image_version": os.environ.get("ImageVersion"), "git_version": git(ROOT, "--version"),
        "pytest_version": importlib.metadata.version("pytest"),
        "installed_distributions": sorted((dist.metadata.get("Name", ""), dist.version)
                                          for dist in importlib.metadata.distributions()),
        "collector_sha256": digest(Path(__file__)), "cases_sha256": digest(CASES_PATH),
        "fixture_source_adjustment": "NONE",
        "policy": {"fail_on": "high", "task": None, "date": "2026-10-12",
                   "subject_config": "No .checkwash config, allowlist or TASK in either three-file tree"},
        "cases": {},
    }
    save(EVIDENCE / "binding.json", identity)
    if (identity["source_head"] != identity["candidate_sha"] or identity["source_status"]
            or Path(identity["engine_path"]) != (ROOT / "src/checkwash/__init__.py").resolve()
            or identity["pytest_version"] != "8.4.2"):
        raise ValueError("source/install/runner identity mismatch")
    (EVIDENCE / "runtime_api_pairs.json").write_bytes(CASES_PATH.read_bytes())
    for case_id, case in cases().items():
        repo, evidence = REPOS / case_id, EVIDENCE / case_id
        repo.mkdir()
        evidence.mkdir()
        git(repo, "init", "--object-format=sha1", "-b", "main")
        git(repo, "config", "user.name", "Owned runtime API reproduction")
        git(repo, "config", "user.email", "runtime-api@example.invalid")
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
                                     "paired_control": case["paired_control"]}
        save(EVIDENCE / "binding.json", identity)
    print("Four owned source pairs prepared; no runtime or detector result claimed.")


def invoke(case_id, label, command, cwd, refs):
    directory = EVIDENCE / case_id / label
    directory.mkdir()
    result = {"purpose": PURPOSE, "case": case_id, "label": label, "refs": refs,
              "argv": command, "cwd": str(cwd), "timeout_seconds": 30,
              "binding_sha256": digest(EVIDENCE / "binding.json"),
              "status": "NOT_STARTED", "returncode": None}
    stdout, stderr = b"", b""
    start = time.monotonic()
    try:
        proc = subprocess.run(command, cwd=cwd, env=environment(), capture_output=True, timeout=30)
        stdout, stderr = proc.stdout, proc.stderr
        result.update(status="EXITED", returncode=proc.returncode)
    except subprocess.TimeoutExpired as exc:
        stdout, stderr = exc.stdout or b"", exc.stderr or b""
        result.update(status="TIMEOUT", exception_type=type(exc).__name__)
    except OSError as exc:
        result.update(status="LAUNCH_FAILURE", exception_type=type(exc).__name__, message=str(exc))
    finally:
        result["elapsed_seconds"] = time.monotonic() - start
        (directory / "stdout.bin").write_bytes(stdout)
        (directory / "stderr.bin").write_bytes(stderr)
        result["stdout_sha256"], result["stderr_sha256"] = digest(directory / "stdout.bin"), digest(directory / "stderr.bin")
        save(directory / "process.json", result)
    return result


def capture():
    binding = read(EVIDENCE / "binding.json")
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
            payload = json.loads((directory / "stdout.bin").read_bytes())
            # Complete original JSON lives in stdout.bin; no finding projection or relabeling.
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
                raise ValueError("owned repository changed before native pytest")
            label = "pytest-" + side
            xml_path = EVIDENCE / case_id / label / "junit.xml"
            # No -I here: ordinary python -m pytest must import this owned app and
            # conftest through its normal cwd; no external plugin autoload.
            command = [sys.executable, "-B", "-X", "utf8", "-m", "pytest", "-q", "--tb=long",
                       "-p", "no:cacheprovider", "--confcutdir", str(repo),
                       "--rootdir", str(repo), "--junitxml", str(xml_path), "tests"]
            invoke(case_id, label, command, repo, refs)
            verify_tree(repo, refs[side], snapshot(all_cases[case_id], side))
            if git(repo, "status", "--porcelain"):
                raise ValueError("native pytest changed tracked or untracked subject files")
    if engine_manifest() != binding["engine_files"] or git(ROOT, "status", "--porcelain"):
        raise ValueError("trusted engine changed during reproduction")
    print("Twelve subprocess attempts captured. Checkwash verdicts are observations, not qualification.")


def validate():
    binding = read(EVIDENCE / "binding.json")
    if (binding["source_head"] != os.environ["CANDIDATE_SHA"] or binding["run_id"] != os.environ["GITHUB_RUN_ID"]
            or binding["attempt"] != os.environ["GITHUB_RUN_ATTEMPT"] or set(binding["cases"]) != set(IDS)
            or binding["collector_sha256"] != digest(Path(__file__)) or binding["cases_sha256"] != digest(CASES_PATH)):
        raise ValueError("receipt/source/run binding mismatch")
    failures, native, engine = [], [], []
    for case_id in IDS:
        refs = binding["cases"][case_id]["refs"]
        for label in ("checkwash", "pytest-before", "pytest-after"):
            directory = EVIDENCE / case_id / label
            process = read(directory / "process.json")
            if (process["case"] != case_id or process["label"] != label or process["refs"] != refs
                    or process["binding_sha256"] != digest(EVIDENCE / "binding.json")
                    or process["stdout_sha256"] != digest(directory / "stdout.bin")
                    or process["stderr_sha256"] != digest(directory / "stderr.bin")):
                raise ValueError("missing or mismatched original subprocess evidence")
            if label == "checkwash":
                engine.append({"case": case_id, "status": process["status"], "exit_code": process["returncode"],
                               "observed": str(directory / "observed.json")})
                continue  # Deliberately no current finding/severity/verdict expectation.
            expected_exit = 0 if label == "pytest-after" and case_id.endswith("-NOOP") else 1
            outcome = {"case": case_id, "side": label.removeprefix("pytest-"),
                       "expected_exit": expected_exit, "actual_exit": process["returncode"], "verified": False}
            try:
                document = ET.parse(directory / "junit.xml").getroot()
                suites = [document] if document.tag == "testsuite" else list(document.findall("testsuite"))
                testcases = [test for suite in suites for test in suite.findall("testcase")]
                actual = {name: sum(int(suite.get(name, "0")) for suite in suites)
                          for name in ("tests", "failures", "errors", "skipped")}
                outcome["junit"] = actual
                wanted = {"tests": 1, "failures": expected_exit, "errors": 0, "skipped": 0}
                if (process["status"] != "EXITED" or process["returncode"] != expected_exit
                        or actual != wanted or len(testcases) != 1 or testcases[0].get("name") != "test_value"):
                    raise ValueError("native test was absent, skipped, errored or did not have the intended outcome")
                if expected_exit:
                    failure = testcases[0].find("failure")
                    text = "" if failure is None else "".join(failure.itertext())
                    if "AssertionError" not in text and "assert 0 == 1" not in text:
                        raise ValueError("failure does not show the owned failing oracle")
                outcome["verified"] = True
            except (OSError, ValueError, ET.ParseError) as exc:
                outcome["error"] = type(exc).__name__ + ": " + str(exc)
                failures.append(case_id + "/" + label)
            native.append(outcome)
    save(EVIDENCE / "verification.json",
         {"purpose": PURPOSE, "native_ground_truth": native, "ground_truth_failures": failures,
          "checkwash_observations": engine, "detector_qualification": "NOT_EVALUATED",
          "checkwash_failure_or_timeout_is_not_pass": True})
    if failures:
        raise ValueError("owned ground truth NOT reproduced: " + ", ".join(failures))
    print("Eight native ground-truth outcomes verified. Four Checkwash observations remain unadjudicated.")


if __name__ == "__main__":
    {"prepare": prepare, "capture": capture, "validate": validate}[sys.argv[1]]()
