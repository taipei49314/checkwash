"""Five fixed hosted static observations; source-only draft, never product import."""
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

REFS = {"baseline": "744496a73fd61bd5c3175c527f3da68a4c4fe989",
        "candidate": "c33f61bc37387196a1f158233024ef38d417029c"}
CANDIDATE_PACKAGE_TREE = "6169701104ec4611532be61911e9e310cfe0fb7d"
ACQUISITION_PERMITTED = True
COMMON = ["src/checkwash/frontends/python/standin_installations.py"]
NEW = "tests/test_standin_literal_binding_batches.py"
WORKFLOW = ".github/workflows/standin-batch-static-floor.yml"
PINS = {"ruff": "0.16.6", "mypy": "2.3.1"}
ROOT = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
OUT = ROOT / "standin-batch-static-evidence"
OUT.mkdir(exist_ok=True)
manifest = {"status": "RAW_NATIVE_NOT_STATIC_FLOOR_ADJUDICATION", "refs": REFS,
            "run_id": os.environ["GITHUB_RUN_ID"], "attempt": os.environ["GITHUB_RUN_ATTEMPT"],
            "diagnostic_checkout": os.environ["DIAGNOSTIC_SHA"],
            "pr_head": os.environ["PR_HEAD_SHA"], "python": sys.version,
            "workflow_ref": os.environ["GITHUB_WORKFLOW_REF"],
            "workflow_sha": os.environ["GITHUB_WORKFLOW_SHA"],
            "repository": os.environ["GITHUB_REPOSITORY"], "job": os.environ["GITHUB_JOB"],
            "executable": sys.executable, "platform": platform.platform(),
            "commands": [], "subjects": {}, "expected_batches": [
                {"side": side, "scope": scope, "tool": tool, "state": "NOT_ATTEMPTED"}
                for side, scope in (("baseline", "common"), ("candidate", "common"),
                                    ("candidate", "candidate_only")) for tool in PINS
                if scope != "candidate_only" or tool == "ruff"]}
result_exit = 0


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save():
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def capture(name, argv, cwd, env, timeout=180):
    """Qualified maintenance pattern: full streams, signed native exit, explicit errors."""
    row = {"name": name, "argv": argv, "cwd": str(cwd), "timeout_seconds": timeout,
           "environment_sha256": digest(json.dumps(env, sort_keys=True).encode()),
           "environment_keys": sorted(env)}
    manifest["commands"].append(row)
    save()
    started = time.monotonic()
    try:
        run = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, timeout=timeout)
        stdout, stderr = run.stdout, run.stderr
        row["exit"] = run.returncode
    except subprocess.TimeoutExpired as error:
        stdout, stderr = error.stdout or b"", error.stderr or b""
        row.update(exit=None, capture_error="TimeoutExpired", streams_complete=False)
    except OSError as error:
        stdout, stderr = b"", str(error).encode()
        row.update(exit=None, capture_error=type(error).__name__, streams_complete=False)
    for stream, raw in (("stdout", stdout), ("stderr", stderr)):
        path = OUT / (name + "." + stream)
        path.write_bytes(raw)
        row[stream] = {"path": path.name, "bytes": len(raw), "sha256": digest(raw)}
    row["elapsed_seconds"] = time.monotonic() - started
    row.setdefault("streams_complete", True)
    save()
    return row, stdout


def git(repo, *args):
    run = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=60)
    if run.returncode:
        (OUT / "failed-git.stdout").write_bytes(run.stdout)
        (OUT / "failed-git.stderr").write_bytes(run.stderr)
        manifest["failed_git"] = {"argv": run.args, "cwd": str(ROOT), "exit": run.returncode}
        raise RuntimeError("source identity Git command failed")
    return run.stdout


def bind(repo, expected):
    head = git(repo, "rev-parse", "HEAD").decode().strip()
    if head != expected or git(repo, "status", "--porcelain"):
        raise RuntimeError("checkout identity/cleanliness differs")
    entries = {}
    for item in git(repo, "ls-tree", "-r", "-z", "HEAD").split(b"\0"):
        if item:
            meta, path = item.split(b"\t", 1)
            entries[path.decode()] = meta.decode().split()
    return {"head": head, "tree": git(repo, "rev-parse", "HEAD^{tree}").decode().strip(),
            "paths": {}}, entries


def source(repo, path, entries):
    entry = entries.get(path)
    if entry is None:
        return {"state": "NOT_IN_SUBJECT_TREE"}
    mode, kind, blob = entry
    if kind != "blob" or mode not in ("100644", "100755"):
        raise RuntimeError("diagnostic source is nonregular")
    raw = (repo / path).read_bytes()
    if raw != git(repo, "show", "HEAD:" + path):
        raise RuntimeError("checkout source differs from blob")
    exported = OUT / "source-exports" / repo.name / path
    exported.parent.mkdir(parents=True, exist_ok=True)
    exported.write_bytes(raw)
    return {"state": "SELECTED", "blob": blob, "bytes": len(raw), "sha256": digest(raw),
            "raw_source": exported.relative_to(OUT).as_posix()}


try:
    if (not ACQUISITION_PERMITTED
            or len(REFS["candidate"]) != 40
            or any(char not in "0123456789abcdef" for char in REFS["candidate"])
            or len(CANDIDATE_PACKAGE_TREE) != 40
            or any(char not in "0123456789abcdef" for char in CANDIDATE_PACKAGE_TREE)):
        raise RuntimeError("BLOCKED: literal-batch source/package identity not frozen for acquisition")
    if sys.implementation.name != "cpython" or sys.version_info[:2] != (3, 12):
        raise RuntimeError("requires CPython3.12")
    diagnostic = ROOT / "diagnostic"
    manifest["diagnostic"], diagnostic_entries = bind(diagnostic, manifest["diagnostic_checkout"])
    for path in (WORKFLOW, "tools/standin_batch_static_floor.py"):
        manifest["diagnostic"]["paths"][path] = source(diagnostic, path, diagnostic_entries)
    if any(row["state"] != "SELECTED" for row in manifest["diagnostic"]["paths"].values()):
        raise RuntimeError("diagnostic workflow/collector absent")
    candidate_repo = ROOT / "candidate"
    preflight, candidate_entries = bind(candidate_repo, REFS["candidate"])
    preflight["package_tree"] = git(candidate_repo, "rev-parse", "HEAD:src/checkwash").decode().strip()
    preflight["package_files"] = sum(path.startswith("src/checkwash/") for path in candidate_entries)
    manifest["candidate_preflight"] = preflight
    if preflight["package_files"] != 209 or preflight["package_tree"] != CANDIDATE_PACKAGE_TREE:
        raise RuntimeError("fixed candidate package identity differs before acquisition")
    save()
    tool_root = Path(os.environ["RUNNER_TEMP"]) / "standin-batch-static-tools"
    python = str(tool_root / "bin/python")
    install = [
        ("venv", [sys.executable, "-I", "-B", "-m", "venv", str(tool_root)]),
        ("pip", [python, "-I", "-B", "-m", "pip", "install", "--report",
                 str(OUT / "install.json"), *[name + "==" + version for name, version in PINS.items()]]),
        ("freeze", [python, "-I", "-B", "-m", "pip", "freeze", "--all"]),
        ("versions", [python, "-I", "-B", "-c", "import importlib.metadata,json,sys; "
                      "print(json.dumps({'python':sys.version,'executable':sys.executable,"
                      "'ruff':importlib.metadata.version('ruff'),'mypy':importlib.metadata.version('mypy')}))"]),
    ]
    for name, argv in install:
        row, raw = capture("install-" + name, argv, ROOT, dict(os.environ))
        if row["exit"] != 0:
            raise RuntimeError("tool installation or receipt failed")
        if name == "versions":
            manifest["tools"] = json.loads(raw)
            if any(manifest["tools"][name] != version for name, version in PINS.items()):
                raise RuntimeError("installed tool versions differ")
    manifest["install_report"] = {"bytes": (OUT / "install.json").stat().st_size,
                                  "sha256": digest((OUT / "install.json").read_bytes())}
    for side, ref in REFS.items():
        repo = ROOT / side
        observed, entries = bind(repo, ref)
        manifest["subjects"][side] = observed
        observed["package_tree"] = git(repo, "rev-parse", "HEAD:src/checkwash").decode().strip()
        observed["package_files"] = sum(path.startswith("src/checkwash/") for path in entries)
        if side == "candidate" and (observed["package_files"] != 209 or observed["package_tree"] !=
                                    CANDIDATE_PACKAGE_TREE):
            raise RuntimeError("fixed candidate package identity differs")
        for path in COMMON + [NEW]:
            if side == "baseline" and path == NEW:
                if path in entries or (repo / path).exists() or (repo / path).is_symlink():
                    raise RuntimeError("new test unexpectedly exists at baseline")
                observed["paths"][path] = {"state": "ABSENT_NOT_COMPARABLE"}
            else:
                observed["paths"][path] = source(repo, path, entries)
                if observed["paths"][path]["state"] != "SELECTED":
                    raise RuntimeError("selected critical source absent")
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("RUFF_", "MYPY_", "PYTHON"))}
        env.update(MYPYPATH=str(repo / "src"), NO_COLOR="1")
        observed["effective_environment"] = {key: env.get(key) for key in
                                             ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "MYPYPATH", "NO_COLOR")}
        options = {
            "ruff": ["check", "--isolated", "--target-version", "py311", "--no-cache",
                     "--cache-dir", str(Path(os.environ["RUNNER_TEMP"]) / ("maintenance-ruff-" + side)),
                     "--output-format", "json"],
            "mypy": ["--config-file=", "--python-version", "3.12", "--no-incremental",
                     "--cache-dir", str(Path(os.environ["RUNNER_TEMP"]) / ("maintenance-mypy-" + side)),
                     "--output", "json", "--no-error-summary"],
        }
        scopes = {"common": COMMON, **({"candidate_only": [NEW]} if side == "candidate" else {})}
        for scope, paths in scopes.items():
            for tool, flags in options.items():
                if scope == "candidate_only" and tool != "ruff":
                    continue
                slot = next(item for item in manifest["expected_batches"] if
                            (item["side"], item["scope"], item["tool"]) == (side, scope, tool))
                row, raw = capture(side + "-" + scope + "-" + tool,
                                   [python, "-I", "-B", "-m", tool, *flags, *paths], repo, env)
                slot["state"] = "CAPTURE_ERROR" if "capture_error" in row else "NATIVE_CAPTURED"
                row.update(side=side, scope=scope, tool=tool, selected_paths=paths)
                result_exit = max(result_exit, 0 if row["exit"] == 0 else 1 if row["exit"] == 1 else 2)
                try:
                    diagnostics = json.loads(raw) if tool == "ruff" else [json.loads(line) for line in raw.splitlines() if line.strip()]
                    if not isinstance(diagnostics, list) or any(not isinstance(item, dict) for item in diagnostics):
                        raise ValueError("native diagnostic format differs")
                    if row["exit"] == 1 and not diagnostics:
                        raise ValueError("native failure has no diagnostic occurrences")
                    row["diagnostics"] = diagnostics  # all occurrences, no scope filtering or deduplication
                    row["diagnostic_sources"] = {}
                    for item in diagnostics:
                        path = item.get("filename", item.get("file", ""))
                        resolved = Path(path) if Path(path).is_absolute() else repo / path
                        relative = resolved.resolve().relative_to(repo).as_posix() if resolved.resolve().is_relative_to(repo) else None
                        row["diagnostic_sources"][path] = source(repo, relative, entries) if relative else {"state": "OUTSIDE_SUBJECT_TREE"}
                except (ValueError, TypeError, OSError) as error:
                    row["diagnostic_capture_error"] = str(error)
                    slot["state"] = "CAPTURE_ERROR"
                    result_exit = 2
                save()
        if git(repo, "status", "--porcelain"):
            raise RuntimeError("static tools changed subject checkout")
except Exception as error:
    manifest["capture_error"] = {"type": type(error).__name__, "message": str(error)}
    if isinstance(error, subprocess.TimeoutExpired):
        (OUT / "failed-git.stdout").write_bytes(error.stdout or b"")
        (OUT / "failed-git.stderr").write_bytes(error.stderr or b"")
        manifest["failed_git"] = {"argv": error.cmd, "exit": None, "timeout": 60}
    result_exit = 2
finally:
    manifest["collector_exit"] = result_exit
    save()
raise SystemExit(result_exit)
