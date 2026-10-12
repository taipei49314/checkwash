"""One fixed, clean Action cost scenario; native step timing is collected separately."""
from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
TEMP = Path(os.environ["RUNNER_TEMP"]).resolve()
EVIDENCE = TEMP / "action-cost-evidence"
BASELINE = WORKSPACE / "baseline-中文"
BASE_SHA = "818dd6c389076569fb51558213bf570c9c9e8396"
ORDER = ("A1", "B1", "B2", "A2", "B3", "A3", "A4", "B4")


def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=60)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", "replace"))
    return result.stdout.decode("utf-8").strip()


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def package_digest(root):
    files = {path.relative_to(root / "src/checkwash").as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in (root / "src/checkwash").rglob("*")
             if path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}}
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def source(root, expected):
    if git(root, "rev-parse", "HEAD") != expected or git(root, "status", "--porcelain"):
        raise ValueError("source checkout is wrong or dirty")
    return {"commit": expected, "tree": git(root, "rev-parse", "HEAD^{tree}"),
            "package_tree": git(root, "rev-parse", "HEAD:src/checkwash"),
            "pyproject_blob": git(root, "rev-parse", "HEAD:pyproject.toml"),
            "source_digest": package_digest(root), "root": str(root),
            "version": tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"],
            "action_files": {name: hashlib.sha256((root / "action" / name).read_bytes()).hexdigest()
                             for name in ("action.yml", "secure.py", "post_review.py")
                             if (root / "action" / name).is_file()}}


def distribution():
    try:
        installed = importlib.metadata.distribution("checkwash")
    except importlib.metadata.PackageNotFoundError:
        return None
    return {"version": installed.version, "root": str(Path(installed.locate_file("checkwash")).resolve()),
            "direct_url": json.loads(installed.read_text("direct_url.json") or "{}")}


def prepare():
    if ROOT != WORKSPACE / "candidate-中文" or TEMP.is_relative_to(WORKSPACE):
        raise ValueError("unexpected trusted checkout or runner temporary path")
    EVIDENCE.mkdir()
    manifest = {"baseline": source(BASELINE, BASE_SHA), "candidate": source(ROOT, os.environ["CANDIDATE_SHA"]),
                "pr_head": os.environ["PR_HEAD_SHA"], "run_id": os.environ["GITHUB_RUN_ID"],
                "attempt": os.environ["GITHUB_RUN_ATTEMPT"], "system": os.environ["COST_SYSTEM"],
                "runner_image": os.environ.get("ImageOS"), "runner_image_version": os.environ.get("ImageVersion"),
                "python": str(Path(sys.executable).resolve()), "python_version": sys.version,
                "pip_version": importlib.metadata.version("pip"), "git_version": git(WORKSPACE, "--version"),
                "order": ORDER, "phase_times": "UNKNOWN", "origin_kind": "same-job local bare fixture"}
    if distribution() is not None:
        raise ValueError("unexpected preexisting checkwash in the setup-python environment")
    # Explicit path under the verified candidate; -I/-B exclude subject imports/caches.
    spec = importlib.util.spec_from_file_location("trusted_action_fixture", ROOT / "tools/action_security_qualification.py")
    if spec is None or spec.loader is None:
        raise ValueError("trusted fixture helper missing")
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    fixture.prepare("clean-pass")
    with (WORKSPACE / ".git/info/exclude").open("a", encoding="utf-8") as stream:
        stream.write("\nbaseline-中文/\n")
    origin = TEMP / "action-cost-origin.git"
    git(WORKSPACE, "clone", "--bare", str(WORKSPACE), str(origin))
    git(WORKSPACE, "remote", "add", "origin", origin.as_uri())
    # Preflight only; the original A composite still performs its own fetch.
    git(WORKSPACE, "fetch", "--quiet", "--deepen=200", "origin")
    manifest["fixture"] = json.loads((TEMP / "action-security-fixture.json").read_text(encoding="utf-8"))
    save(EVIDENCE / "manifest.json", manifest)


def before(trial):
    index = ORDER.index(trial)
    if index and not (EVIDENCE / (ORDER[index - 1] + ".json")).is_file():
        raise ValueError("prior trial evidence missing")
    if (EVIDENCE / (trial + ".json")).exists():
        raise ValueError("duplicate trial")
    previous = distribution()
    if previous:
        # Only this job's prior A installation may be removed. No cache purge.
        if unquote(previous["direct_url"].get("url", "")) != unquote(BASELINE.as_uri()):
            raise ValueError("refusing to remove a package outside this benchmark installation")
        subprocess.run([sys.executable, "-I", "-m", "pip", "uninstall", "-y", "checkwash"], check=True, timeout=120)
    if distribution() is not None:
        raise ValueError("ambient package reset failed")
    if Path(shutil.which("python") or "").resolve() != Path(sys.executable).resolve():
        raise ValueError("old Action would use a different ambient Python")
    manifest = json.loads((EVIDENCE / "manifest.json").read_text(encoding="utf-8"))
    if (git(WORKSPACE, "rev-parse", "HEAD") != manifest["fixture"]["head"]
            or git(WORKSPACE, "status", "--porcelain")):
        raise ValueError("fixture changed between trials")
    save(EVIDENCE / (trial + "-before.json"), {"trial": trial, "ambient_package_absent": True,
                                             "removed_prior_install": previous})


def capture(trial):
    manifest = json.loads((EVIDENCE / "manifest.json").read_text(encoding="utf-8"))
    row = {"trial": trial, "index": ORDER.index(trial), "outcome": os.environ["ACTION_OUTCOME"],
           "run_id": manifest["run_id"], "attempt": manifest["attempt"], "system": manifest["system"],
           "source": manifest["baseline" if trial.startswith("A") else "candidate"],
           "fixture": manifest["fixture"], "phase_times": "UNKNOWN"}
    complete = False
    try:
        if not (EVIDENCE / (trial + "-before.json")).is_file():
            raise ValueError("trial preparation receipt missing")
        if trial.startswith("A"):
            row["installed"] = distribution()
            row["analysis_exit_code"] = "unavailable: original composite has no receipt"
            installed = row["installed"]
            complete = bool(installed and installed["version"] == row["source"]["version"]
                            and unquote(installed["direct_url"].get("url", "")) == unquote(BASELINE.as_uri()))
        else:
            receipt = Path(os.environ.get("COST_RECEIPT_PATH", "")).resolve()
            if receipt.name != "check-receipt.json" or not receipt.is_relative_to(TEMP):
                raise ValueError("candidate receipt absent or outside runner temporary directory")
            dest = EVIDENCE / trial
            dest.mkdir()
            for name in ("check-receipt.json", "identity.json", "install-report.json",
                         "install-stdout.txt", "install-stderr.txt", "stdout.txt", "stderr.txt"):
                shutil.copyfile(receipt.parent / name, dest / name)
            result = json.loads((dest / "check-receipt.json").read_text(encoding="utf-8"))
            identity = json.loads((dest / "identity.json").read_text(encoding="utf-8"))
            row["receipt"] = trial + "/check-receipt.json"
            complete = (result["identity"] == identity and result["exit_code"] == result["analysis_exit_code"] == 0
                        and result["error"] is None and result["base"] == row["fixture"]["base"]
                        and result["head"] == row["fixture"]["head"] and result["fail_on"] == "high"
                        and identity["source_root"] == str(ROOT) and identity["source_digest"] == row["source"]["source_digest"]
                        and identity["version"] == row["source"]["version"] and identity["base_python"] == manifest["python"]
                        and identity["isolated"] and identity["utf8"] and identity["bytecode_writes_disabled"])
        if row["outcome"] != "success" or not complete:
            raise ValueError("actual normal composite or its evidence did not pass")
    except Exception as exc:
        row["evidence_error"] = type(exc).__name__ + ": " + str(exc)
        raise
    finally:
        save(EVIDENCE / (trial + ".json"), row)


def finish():
    manifest = json.loads((EVIDENCE / "manifest.json").read_text(encoding="utf-8"))
    for trial in ORDER:
        row = json.loads((EVIDENCE / (trial + ".json")).read_text(encoding="utf-8"))
        if row["outcome"] != "success" or row.get("evidence_error"):
            raise ValueError("incomplete normal-case run")
    source(BASELINE, BASE_SHA)
    source(ROOT, manifest["candidate"]["commit"])
    print("Eight actual normal composites completed; native elapsed is collected separately; phase costs UNKNOWN.")


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "prepare":
        prepare()
    elif mode == "before":
        before(sys.argv[2])
    elif mode == "capture":
        capture(sys.argv[2])
    elif mode == "finish":
        finish()
    else:
        raise ValueError("unknown fixed-scenario mode")
