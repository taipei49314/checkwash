"""Capture the unchanged, fixed 60-case verifier on ordinary hosted Ubuntu CI.

No new oracle classifier or verdict comparison. The verifier's native exit,
including incomplete-cohort exit 2, remains the job exit.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import traceback

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
INPUTS = HERE / "refactor_qualification_inputs.json"
LABELS = ("before_good_pass", "before_bug_fail", "after_good_pass", "after_bug_fail")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
                    encoding="utf-8")


def git(*args):
    proc = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True,
                          timeout=30, env=dict(os.environ, GIT_NO_LAZY_FETCH="1"))
    require(proc.returncode == 0, f"git {args!r}: exit {proc.returncode}: {proc.stderr!r}")
    return proc.stdout


def source_state():
    # Preserve observed identity before any comparison, including dirty status.
    return dict(commit=git("rev-parse", "HEAD").decode().strip(),
                tree=git("rev-parse", "HEAD^{tree}").decode().strip(),
                worktree_status=git("status", "--porcelain", "--untracked-files=all").decode())


def check_fixed_inputs(fixed):
    require(len(fixed["members"]) == 60 and len(set(fixed["members"])) == 60,
            "the original 60 unique members are required")
    cases = ROOT / "benchmarks/refactors/cases"
    require(sorted(p.name for p in cases.iterdir() if p.is_dir()) == fixed["members"],
            "missing or unexpected original case directory")
    require(git("rev-parse", "HEAD:benchmarks/refactors/cases").decode().strip()
            == fixed["cases_tree"], "fixed case tree changed")
    # Tree equality binds original membership/contents; compare working bytes
    # too, rather than relying on Git's text-normalizing dirty check.
    for entry in git("ls-tree", "-r", "-z", "HEAD:benchmarks/refactors/cases").split(b"\0"):
        if not entry:
            continue
        header, raw_path = entry.split(b"\t", 1)
        mode, kind, oid = header.split()
        path = cases / raw_path.decode("utf-8")
        require(mode in (b"100644", b"100755") and kind == b"blob" and not path.is_symlink(),
                f"non-regular case entry: {raw_path!r}")
        data = path.read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        require(blob == oid.decode(), f"working bytes differ: {raw_path!r}")
    for key in ("expected", "verifier"):
        item = fixed[key]
        path = ROOT / item["path"]
        require(git("rev-parse", "HEAD:" + item["path"]).decode().strip() == item["git_blob"]
                and path.stat().st_size == item["bytes"] and sha(path) == item["sha256"],
                f"fixed {key} bytes changed")
    expected = json.loads((ROOT / fixed["expected"]["path"]).read_text(encoding="utf-8"))
    require(sorted(expected["cases"]) == fixed["members"], "expected membership mismatch")


def receipt_binding(receipt, fixed, state):
    """Accounting only: retain verifier semantics, including invalid cases."""
    require(receipt["source"] == state, "verifier source identity differs")
    require(receipt["expected_case_count"] == 60, "verifier denominator differs")
    require(receipt["inputs"]["expected_sha256"] == fixed["expected"]["sha256"]
            and receipt["inputs"]["verifier_sha256"] == fixed["verifier"]["sha256"],
            "verifier input identity differs")
    require(receipt["inputs_unchanged"] is True, "verifier inputs changed")
    rows = receipt["cases"]
    require(len(rows) == 60 and sorted(row["case"] for row in rows) == fixed["members"],
            "missing/duplicate/unexpected receipt member")
    # This is deliberately not a new JUnit oracle or an FP decision.
    retained = sum(len(row["observations"]) for row in rows)
    complete_cells = all(set(row["observations"]) == set(LABELS) for row in rows)
    return dict(retained_observations=retained, all_240_cells_present=complete_cells,
                verifier_status=receipt["status"], verifier_summary=receipt["summary"],
                semantic_adjudication="PENDING", distribution="source",
                wheel_pyz_qualification="NOT_RUN_BY_THIS_JOB")


def main():
    require(sys.platform.startswith("linux"), "Ubuntu/POSIX hosted capture only")
    require(os.environ.get("GITHUB_EVENT_NAME") == "pull_request", "ordinary PR only")
    out = Path(os.environ["REFACTOR_OUTPUT"]).absolute()
    require(not out.exists(), "new output directory required")
    require(not out.is_relative_to(ROOT), "output must be outside source checkout")
    out.mkdir(parents=True)
    record = dict(status="NOT_STARTED", native_exit=None, source_before=None, source_after=None,
                  error=None, runtime_qualification="NOT_ESTABLISHED")
    save(out / "capture.json", record)
    try:
        expected = {key: os.environ[key] for key in
                    ("CANDIDATE_SHA", "PR_HEAD_SHA", "PR_BASE_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT")}
        require(all(re.fullmatch(r"[0-9a-f]{40}", expected[key]) for key in
                    ("CANDIDATE_SHA", "PR_HEAD_SHA", "PR_BASE_SHA")), "full event SHA required")
        require(all(re.fullmatch(r"[1-9][0-9]*", expected[key]) for key in
                    ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT")), "run/attempt required")
        record["event"] = expected
        state = source_state()
        record["source_before"] = state
        save(out / "capture.json", record)
        require(state["commit"] == expected["CANDIDATE_SHA"] and state["worktree_status"] == "",
                "expected clean checkout required")
        fixed = json.loads(INPUTS.read_text(encoding="utf-8"))
        check_fixed_inputs(fixed)
        record["fixed_inputs"] = fixed
        record["harness"] = {name: sha(HERE / name) for name in
                              (Path(__file__).name, INPUTS.name, "owned_process_capture.py")}
        record["python"] = dict(version=sys.version, launch=sys.executable,
                                resolved=str(Path(sys.executable).resolve()))
        helper = HERE / "owned_process_capture.py"
        spec = importlib.util.spec_from_file_location("refactor_owned_capture", helper)
        cap = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cap)
        receipt_path = out / "refactor-receipt.json"
        argv = [sys.executable, "-I", "-B", "-X", "utf8", str(ROOT / fixed["verifier"]["path"]),
                "--output", str(receipt_path)]
        env = {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR") if key in os.environ}
        env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
                   GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_NO_LAZY_FETCH="1")
        record.update(status="RUNNING", command=argv, cwd=str(ROOT), env=env,
                      timeout_seconds=1800, output_limit_per_stream_bytes=16000000)
        save(out / "capture.json", record)
        observed = cap.capture(argv, str(ROOT), env, out / "verifier", 1800, 16000000)
        record["observation"] = observed
        record["native_exit"] = observed["exit_code"]
        save(out / "capture.json", record)
        require(observed["capture_complete"] is True and observed["cleanup_complete"] is True,
                "incomplete outer process capture/cleanup")
        require(observed["exit_code"] in (0, 2), "unexpected verifier exit; raw evidence retained")
        state_after = source_state()
        record["source_after"] = state_after
        save(out / "capture.json", record)
        require(state_after == state, "source changed during capture")
        check_fixed_inputs(fixed)
        require(receipt_path.is_file() and receipt_path.stat().st_size <= 32000000,
                "missing or oversized verifier receipt")
        record["receipt"] = dict(path=receipt_path.name, bytes=receipt_path.stat().st_size,
                                 sha256=sha(receipt_path))
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        record["accounting"] = receipt_binding(receipt, fixed, state)
        require((observed["exit_code"] == 0) == (receipt["status"] == "complete"),
                "exit/receipt status mismatch")
        record["status"] = "VERIFIER_RETURNED_WITH_BOUND_RECEIPT"
        # Never turn native incomplete-cohort exit 2 into successful qualification.
        return observed["exit_code"]
    except Exception:
        record["status"] = "CAPTURE_INCOMPLETE"
        record["error"] = traceback.format_exc()
        return 2
    finally:
        save(out / "capture.json", record)
        files = {p.name: dict(bytes=p.stat().st_size, sha256=sha(p))
                 for p in sorted(out.iterdir()) if p.is_file() and p.name != "file-manifest.json"}
        save(out / "file-manifest.json", files)


if __name__ == "__main__":
    raise SystemExit(main())
