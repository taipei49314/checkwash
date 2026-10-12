"""Four CLI captures and four real hosted companion cells for two owned CI pairs.

This tool does not execute or emulate a workflow. GitHub Actions executes three
literal test steps; a fourth companion deliberately contains no such step.
Only ordinary hosted PR jobs may invoke this diagnostic. No detector labels.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import owned_process_capture as capture_tool

TEMP = Path(os.environ["RUNNER_TEMP"]).resolve()
EVIDENCE = TEMP / "ci-obligation-evidence"
SUBJECT = TEMP / "ci-owned/subject"
CATALOG = ROOT / "tools/ci_obligation_pairs.json"
IDS = ("CI-LAST-STEP-REMOVED", "CI-STEP-MOVED")
PURPOSE = "DIAGNOSTIC_CAPTURE_NOT_DETECTOR_QUALIFICATION"
LIMIT = 4_000_000
HELPER_SHA256 = "017d3c0dafb7ac0bf71bec8d514baccc791e03073ed1f86b1ef0018232bfc643"
TOOL_PATHS = ("tools/ci_obligation_pairs.json", "tools/ci_obligation_reproduction.py",
              "tools/ci_obligation_pytest.py", "tools/ci_obligation_validate.py", "tools/owned_process_capture.py",
              ".github/workflows/ci-obligation-reproduction.yml")
EVENT_KEYS = ("CANDIDATE_SHA", "PR_HEAD_SHA", "PR_BASE_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT")
_git_index = 0


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, value):
    capture_tool.write(path, value)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def environment():
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith(("PYTHON", "PYTEST", "GIT_"))
           and not key.upper().endswith("_TOKEN")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT="0", CHECKWASH_TODAY="2026-10-12", NO_COLOR="1")
    return env


def git(repo, *args, extra=None):
    global _git_index
    _git_index += 1
    directory = EVIDENCE / "git"
    directory.mkdir(exist_ok=True)
    prefix = directory / f"call-{_git_index:04d}-{os.getpid()}"
    argv = [shutil.which("git"), "-C", str(repo), *args]
    result = capture_tool.capture(argv, TEMP, environment() | (extra or {}), prefix, 30, LIMIT)
    if result["status"] != "EXITED" or not result["capture_complete"] or result["exit_code"] != 0:
        raise ValueError("Git failed; original streams and state retained")
    return prefix.with_suffix(".stdout").read_bytes()


def text_git(repo, *args):
    return git(repo, *args).decode("utf-8").strip()


def catalog():
    data = read(CATALOG)
    if (data["version"] != 1 or data["pytest_version"] != "8.4.2"
            or data["python_minor"] != [3, 12]
            or [row["id"] for row in data["cases"]] != list(IDS)
            or set(data["augmentation"]["files"]) != {"app.py", "tests/test_value.py"}):
        raise ValueError("unexpected owned catalog")
    return data


def snapshot(case_id, side, augmented):
    data = catalog()
    case, = [row for row in data["cases"] if row["id"] == case_id]
    files = dict(case["unchanged_context"])
    files.update({name: sides[side] for name, sides in case["files"].items() if sides[side] is not None})
    if augmented:
        if set(files) & set(data["augmentation"]["files"]):
            raise ValueError("augmentation would overwrite original source")
        files.update(data["augmentation"]["files"])
    expected = {".github/workflows/ci.yml"}
    if case_id == IDS[1] and side == "after":
        expected.add("scripts/test.sh")
    if augmented:
        expected.update(("app.py", "tests/test_value.py"))
    if set(files) != expected:
        raise ValueError("unexpected input path or policy file")
    return {name: value.encode("utf-8") for name, value in files.items()}


def hashes(files):
    return {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()}


def engine_files():
    result = {}
    def fail(error):
        raise error
    for directory, folders, filenames in os.walk(ROOT / "src/checkwash", onerror=fail):
        folders[:] = sorted(name for name in folders if name != "__pycache__")
        for name in sorted(filenames):
            path = Path(directory) / name
            if path.suffix not in {".pyc", ".pyo"}:
                result[path.relative_to(ROOT).as_posix()] = digest(path)
    return result


def identity():
    observed = {key: os.environ[key] for key in EVENT_KEYS}
    if (os.environ["GITHUB_EVENT_NAME"] != "pull_request" or sys.version_info[:2] != (3, 12)
            or digest(ROOT / "tools/owned_process_capture.py") != HELPER_SHA256
            or any(not re.fullmatch(r"[0-9a-f]{40}", observed[key]) for key in EVENT_KEYS[:3])):
        raise ValueError("ordinary PR / fixed Python / exact SHA required")
    observed.update(purpose=PURPOSE, candidate_sha=observed["CANDIDATE_SHA"],
                    pr_head_sha=observed["PR_HEAD_SHA"], pr_base_sha=observed["PR_BASE_SHA"],
                    run_id=observed["GITHUB_RUN_ID"], attempt=observed["GITHUB_RUN_ATTEMPT"],
                    source_head=text_git(ROOT, "rev-parse", "HEAD"),
                    source_tree=text_git(ROOT, "rev-parse", "HEAD^{tree}"),
                    source_status=text_git(ROOT, "status", "--porcelain"),
                    source_commit=text_git(ROOT, "cat-file", "commit", "HEAD"),
                    tools={name: digest(ROOT / name) for name in TOOL_PATHS},
                    engine_files=engine_files(), executable=str(Path(sys.executable).absolute()),
                    executable_realpath=str(Path(sys.executable).resolve()),
                    python=sys.version, platform=platform.platform(),
                    image_os=os.environ.get("ImageOS"), image_version=os.environ.get("ImageVersion"))
    save(EVIDENCE / "identity.json", observed)
    if observed["source_head"] != observed["candidate_sha"] or observed["source_status"]:
        raise ValueError("candidate checkout identity/cleanliness mismatch")
    return observed


def native_addopts():
    return ('-p ci_obligation_pytest -p no:cacheprovider '
            f'-c "{TEMP / "ci-native-empty.ini"}" '
            f'--rootdir="{SUBJECT}" --junitxml="{EVIDENCE / "native.xml"}"')


def verify_tree(repo, revision, expected):
    if set(text_git(repo, "ls-tree", "-r", "--name-only", revision).splitlines()) != set(expected):
        raise ValueError("owned Git file set differs")
    for name, raw in expected.items():
        if git(repo, "show", revision + ":" + name) != raw:
            raise ValueError("owned Git file bytes differ")


def make_repo(repo, case_id, augmented, directory):
    repo.mkdir(parents=True)
    directory.mkdir(parents=True)
    git(repo, "init", "--object-format=sha1", "-b", "main")
    git(repo, "config", "user.name", "Owned CI observation")
    git(repo, "config", "user.email", "ci-obligation@example.invalid")
    git(repo, "config", "commit.gpgsign", "false")
    git(repo, "config", "core.autocrlf", "false")
    refs, sides = {}, {}
    for side in ("before", "after"):
        files = snapshot(case_id, side, augmented)
        if side == "after":
            for name in set(snapshot(case_id, "before", augmented)) - set(files):
                (repo / name).unlink()
        for name, raw in files.items():
            path = repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            archived = directory / side / name
            archived.parent.mkdir(parents=True, exist_ok=True)
            archived.write_bytes(raw)
        git(repo, "add", "--all")
        git(repo, "commit", "-m", case_id + " " + side,
            extra={"GIT_AUTHOR_DATE": "2026-10-12T00:00:00Z", "GIT_COMMITTER_DATE": "2026-10-12T00:00:00Z"})
        refs[side] = text_git(repo, "rev-parse", "HEAD")
        verify_tree(repo, refs[side], files)
        sides[side] = {"files": hashes(files), "tree": text_git(repo, "rev-parse", "HEAD^{tree}")}
    (directory / "original.diff").write_bytes(git(repo, "diff", "--binary", refs["before"], refs["after"]))
    return {"case": case_id, "augmented": augmented, "repo": str(repo), "refs": refs, "sides": sides}


def verify_source(binding):
    if (text_git(ROOT, "rev-parse", "HEAD") != binding["source_head"]
            or text_git(ROOT, "rev-parse", "HEAD^{tree}") != binding["source_tree"]
            or text_git(ROOT, "status", "--porcelain")
            or engine_files() != binding["engine_files"]
            or {name: digest(ROOT / name) for name in TOOL_PATHS} != binding["tools"]):
        raise ValueError("candidate source changed during observation")


def engine():
    EVIDENCE.mkdir()
    binding = identity()
    import checkwash  # Before any owned subject exists or runs.
    if Path(checkwash.__file__).resolve() != (ROOT / "src/checkwash/__init__.py").resolve():
        raise ValueError("installed engine is not exact checkout")
    binding.update(engine_version=checkwash.__version__, engine_path=str(Path(checkwash.__file__).resolve()),
                   policy={"fail_on": "high", "task": None, "date": "2026-10-12",
                           "config_and_allowlist": "ABSENT_BY_EXACT_TREE_IN_BOTH_ARMS"}, inputs={})
    for augmented in (False, True):
        variant = "augmented" if augmented else "original"
        for case_id in IDS:
            label = variant + "--" + case_id
            binding["inputs"][label] = make_repo(TEMP / "ci-engine" / label, case_id, augmented,
                                                EVIDENCE / "inputs" / label)
    save(EVIDENCE / "binding.json", binding)
    (EVIDENCE / CATALOG.name).write_bytes(CATALOG.read_bytes())
    ledger = []
    for index, (label, fixture) in enumerate(binding["inputs"].items()):
        directory = EVIDENCE / "observations" / label
        directory.mkdir(parents=True)
        refs = fixture["refs"]
        argv = [sys.executable, "-I", "-B", "-X", "utf8", "-m", "checkwash", "check",
                refs["before"] + "..." + refs["after"], "--format", "json", "--fail-on", "high"]
        started = time.monotonic()
        process = capture_tool.capture(argv, Path(fixture["repo"]), environment(), directory / "process", 30, LIMIT)
        row = {"index": index, "label": label, "case": fixture["case"], "augmented": fixture["augmented"],
               "refs": refs, "argv": argv, "cwd": fixture["repo"], "timeout_seconds": 30,
               "binding_sha256": digest(EVIDENCE / "binding.json"), "capture": process,
               "started_monotonic": started, "ended_monotonic": time.monotonic()}
        raw = (directory / "process.stdout").read_bytes()
        try:
            row["report"] = json.loads(raw)
            row["json_status"] = "PARSED"
        except (ValueError, UnicodeDecodeError) as error:
            row.update(report=None, json_status="INVALID_OR_ABSENT", json_error=type(error).__name__)
        save(directory / "receipt.json", row)
        ledger.append({"label": label, "receipt_sha256": digest(directory / "receipt.json")})
        save(EVIDENCE / "ledger.json", ledger)
        if not process["cleanup_complete"]:
            raise ValueError("process cleanup uncertain; no subsequent invocation")
        if text_git(Path(fixture["repo"]), "status", "--porcelain"):
            raise ValueError("analysis modified the owned repository")
    verify_source(binding)
    save(EVIDENCE / "capture-complete.json", {"purpose": PURPOSE, "attempts": len(ledger),
         "engine_results": "UNADJUDICATED_NOT_ASSUMED_PASS", "native_subject_executions": 0})


def native_prepare():
    EVIDENCE.mkdir()
    binding = identity()
    case_id, side = os.environ["OWNED_CASE"], os.environ["OWNED_SIDE"]
    if case_id not in IDS or side not in {"before", "after"}:
        raise ValueError("unknown native cell")
    fixture = make_repo(SUBJECT, case_id, True, EVIDENCE / "input")
    git(SUBJECT, "checkout", "--detach", fixture["refs"][side])
    expected = snapshot(case_id, side, True)
    verify_tree(SUBJECT, fixture["refs"][side], expected)
    command = None if (case_id, side) == (IDS[0], "after") else (
        "bash scripts/test.sh" if (case_id, side) == (IDS[1], "after") else "python -m pytest tests")
    workflow = expected[".github/workflows/ci.yml"].decode()
    actual_lines = [line.removeprefix("      - run: ") for line in workflow.splitlines() if line.startswith("      - run: ")]
    if actual_lines != ([] if command is None else [command]) or os.environ["OWNED_COMMAND"] != (command or "NOT_INVOKED"):
        raise ValueError("companion command is not the original owned run body")
    if importlib.metadata.version("pytest") != "8.4.2" or Path(shutil.which("python")).resolve() != Path(sys.executable).resolve():
        raise ValueError("native command's Python/pytest identity differs")
    if os.environ["NATIVE_ADDOPTS"] != (native_addopts() if command is not None else "NOT_INVOKED"):
        raise ValueError("native reporting configuration differs")
    config = TEMP / "ci-native-empty.ini"
    config.write_bytes(b"[pytest]\n")
    binding.update(case=case_id, side=side, fixture=fixture, native_command=command,
                   native_cwd=str(SUBJECT), pytest_version=importlib.metadata.version("pytest"),
                   pytest_path=str(Path(importlib.metadata.distribution("pytest").locate_file("pytest/__init__.py")).resolve()),
                   shell="GitHub Ubuntu unspecified shell; original literal run body",
                   report_configuration="EXTERNAL_PLUGIN_AND_JUNIT_ONLY", config_sha256=digest(config),
                   native_addopts=os.environ["NATIVE_ADDOPTS"],
                   expected_pythonpath=str(ROOT / "tools"), native_os_exit_code=None)
    save(EVIDENCE / "binding.json", binding)
    if (EVIDENCE / "native.xml").exists() or (EVIDENCE / "native-pytest.json").exists():
        raise ValueError("native evidence already exists before actual step")


def native_finish():
    binding = read(EVIDENCE / "binding.json")
    # Save raw step outcome/report identities before attempting validation.
    row = {"purpose": PURPOSE, "binding_sha256": digest(EVIDENCE / "binding.json"),
           "case": binding["case"], "side": binding["side"],
           "native_outcome": os.environ["NATIVE_OUTCOME"], "os_process_exit_code": None,
           "stdout_stderr": "ORIGINAL_GITHUB_JOB_LOG_REQUIRED_SEPARATION_UNAVAILABLE",
           "reports": {name: digest(EVIDENCE / name) if (EVIDENCE / name).is_file() else None
                       for name in ("native.xml", "native-pytest.json")}}
    save(EVIDENCE / "native-step.json", row)
    verify_source(binding)
    fixture = binding["fixture"]
    if (text_git(SUBJECT, "rev-parse", "HEAD") != fixture["refs"][binding["side"]]
            or text_git(SUBJECT, "status", "--porcelain")
            or (TEMP / "ci-native-empty.ini").read_bytes() != b"[pytest]\n"):
        raise ValueError("native execution changed source/config identity")
    expected = snapshot(binding["case"], binding["side"], True)
    for name, raw in expected.items():
        if (SUBJECT / name).read_bytes() != raw:
            raise ValueError("native source bytes changed")


def outcomes():
    EVIDENCE.mkdir(exist_ok=True)
    save(EVIDENCE / "step-outcomes.json", {"purpose": PURPOSE,
         "event": {key: os.environ[key] for key in EVENT_KEYS},
         "steps": json.loads(os.environ["STEP_OUTCOMES"]),
         "role": os.environ["OWNED_ROLE"]})


if __name__ == "__main__":
    command = sys.argv[1]
    try:
        {"engine": engine, "native-prepare": native_prepare,
         "native-finish": native_finish, "outcomes": outcomes}[command]()
    except Exception as error:
        EVIDENCE.mkdir(exist_ok=True)
        save(EVIDENCE / ("failure-" + command + ".json"), {"purpose": PURPOSE,
             "status": "INCOMPLETE_NOT_PASS", "error": type(error).__name__, "detail": str(error)})
        raise
