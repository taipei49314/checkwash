"""Fixed Quality Action ABBA/BAAB cost capture; native step timing is external.

Three hosted OSes, four fresh installations per arm, one unchanged enforce fixture.
No local execution, pollution, baseline patch, package-cache purge or timing claim.
A retains its original pip/cache/bytecode behavior; B retains fixed-index,
no-cache/no-compile behavior and identity checks. Network/build dependency and
cache effects remain part of whole-composite elapsed, not isolated wrapper cost.
All install/analysis phase times remain UNKNOWN. Four observations per arm are
descriptive, not a statistical or general repository-performance guarantee.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
TEMP = Path(os.environ["RUNNER_TEMP"]).resolve()
BASELINE = WORKSPACE / "baseline-中文"
BASE_SHA = "17f4d11fe0f7c9a821f6385e9ef531cd100d1408"
EVIDENCE = TEMP / "quality-action-cost-evidence"
ORDER = ("A1", "B1", "B2", "A2", "B3", "A3", "A4", "B4")
KEYS = ("exit_code", "analysis_exit_code", "analysis_status", "verdict", "report_path", "receipt_path")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError("trusted metadata/fixture helper missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Reuse existing file/Git metadata, never its main-Action prepare/reset/capture.
common = load("quality_cost_common", ROOT / "tools/action_cost.py")
fixture = load("quality_cost_fixture", ROOT / "tools/quality_action_security.py")
secure = load("quality_cost_metadata", ROOT / "action/secure.py")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def source(root, sha):
    result = common.source(root, sha)
    result["quality_action_files"] = {
        name: hashlib.sha256((root / "action/quality" / name).read_bytes()).hexdigest()
        for name in ("action.yml", "install.py", "run.py")
    }
    return result


def temporary_directories():
    return {str(path.resolve()) for prefix in ("checkwash-quality-venv-", "checkwash-quality-report-", "checkwash-action-")
            for path in TEMP.glob(prefix + "*") if path.is_dir()}


def prepare():
    if ROOT != WORKSPACE / "candidate-中文" or TEMP.is_relative_to(WORKSPACE):
        raise ValueError("unexpected trusted checkout or runner temporary directory")
    EVIDENCE.mkdir()
    baseline = source(BASELINE, BASE_SHA)
    candidate = source(ROOT, os.environ["CANDIDATE_SHA"])
    for key in ("package_tree", "pyproject_blob", "source_digest", "version"):
        if baseline[key] != candidate[key]:
            raise ValueError("engine/package changed; this fixed wrapper-cost comparison is inapplicable")
    # Only history is reused. prepare() would introduce pollution and is NOT called.
    repo = WORKSPACE / fixture.SUBJECT_DIRECTORY
    base, head = fixture.history(repo, "enforce", unchanged=True)
    manifest = {
        "purpose": "OWNED_NORMAL_COST_NOT_RELEASE_QUALIFICATION",
        "baseline": baseline, "candidate": candidate, "order": ORDER,
        "run_id": os.environ["GITHUB_RUN_ID"], "attempt": os.environ["GITHUB_RUN_ATTEMPT"],
        "pr_head": os.environ["PR_HEAD_SHA"], "system": os.environ["COST_SYSTEM"],
        "python": str(Path(sys.executable).resolve()), "python_version": sys.version,
        "pip_version": importlib.metadata.version("pip"), "git_version": common.git(ROOT, "--version"),
        "runner_image": os.environ.get("ImageOS"), "runner_image_version": os.environ.get("ImageVersion"),
        "fixture": {"case": "unchanged-enforce", "base": base, "head": head,
                    "repository": fixture.SUBJECT_DIRECTORY, "tree": common.git(repo, "rev-parse", "HEAD^{tree}")},
        "phase_times": "UNKNOWN", "native_step_elapsed": "COLLECT_SEPARATELY_FROM_THIS_RUN_ATTEMPT",
        "observations_per_arm": 4, "pollution": False,
        "cache_policy": "No benchmark purge; original A cache behavior and candidate B no-cache-dir preserved",
        "cost_scope": "Whole actual composite including fresh venv/pip/network/build/identity/analysis/output",
    }
    common.save(EVIDENCE / "manifest.json", manifest)
    secure.output_values(os.environ["GITHUB_OUTPUT"],
                         {"base": base, "head": head, "repository": fixture.SUBJECT_DIRECTORY})


def before(trial):
    manifest = read(EVIDENCE / "manifest.json")
    index = ORDER.index(trial)
    if index:
        previous = read(EVIDENCE / (ORDER[index - 1] + ".json"))
        if previous["outcome"] != "success" or previous.get("evidence_error"):
            raise ValueError("previous trial did not qualify as a normal cost observation")
    if (EVIDENCE / (trial + "-before.json")).exists():
        raise ValueError("duplicate trial")
    # A's ORIGINAL composite resolves python through PATH. Check the clean
    # setup-python selection without replacing that command or its environment.
    python = shutil.which("python")
    git = shutil.which("git")
    if (not python or not git or Path(python).resolve() != Path(sys.executable).resolve()
            or Path(python).resolve().is_relative_to(WORKSPACE)
            or Path(git).resolve().is_relative_to(WORKSPACE)):
        raise ValueError("original Action ambient Python/Git is not trusted runner tooling")
    repo = WORKSPACE / manifest["fixture"]["repository"]
    if (common.git(repo, "rev-parse", "HEAD") != manifest["fixture"]["head"]
            or common.git(repo, "rev-parse", "HEAD^{tree}") != manifest["fixture"]["tree"]
            or common.git(repo, "status", "--porcelain")):
        raise ValueError("owned fixture changed")
    source(BASELINE, BASE_SHA)
    source(ROOT, manifest["candidate"]["commit"])
    common.save(EVIDENCE / (trial + "-before.json"),
                {"trial": trial, "temporary_directories": sorted(temporary_directories()),
                 "ambient_python": python, "ambient_git": git, "no_install_or_reset_performed": True})


def installed_readback(venv, expected, dest):
    # Read the already-created environment only. Do not run its interpreter,
    # re-install it, invoke candidate identity() on A, or import Checkwash.
    sites = [path for pattern in ("Lib/site-packages", "lib/python*/site-packages")
             for path in venv.glob(pattern) if path.is_dir()]
    if len(sites) != 1:
        raise ValueError("one original runtime site-packages directory required")
    packages = [dist for dist in importlib.metadata.distributions(path=[str(sites[0])])
                if dist.metadata.get("Name", "").lower() == "checkwash"]
    if len(packages) != 1:
        raise ValueError("one installed Checkwash distribution required")
    distribution = packages[0]
    package_root = Path(distribution.locate_file("checkwash")).resolve()
    if package_root != (sites[0] / "checkwash").resolve():
        raise ValueError("installed metadata points elsewhere")
    direct_text = distribution.read_text("direct_url.json")
    metadata_text = distribution.read_text("METADATA")
    if direct_text is None or metadata_text is None:
        raise ValueError("installed origin/version metadata unavailable")
    (dest / "installed-direct_url.json").write_text(direct_text, encoding="utf-8")
    (dest / "installed-METADATA.txt").write_text(metadata_text, encoding="utf-8")
    shutil.copyfile(venv / "pyvenv.cfg", dest / "pyvenv.cfg")
    direct = json.loads(direct_text)
    files = secure.source_manifest(package_root)  # baseline bytecode remains permitted
    expected_files = secure.source_manifest(Path(expected["root"]) / "src/checkwash")
    if (distribution.version != expected["version"] or files != expected_files
            or unquote(direct.get("url", "")) != unquote(Path(expected["root"]).as_uri())):
        raise ValueError("original installed package differs from its pinned source")
    common.save(dest / "installed-files.json", files)
    return {"kind": "POST_STEP_FILE_READBACK_NOT_ACTION_ISSUED_IDENTITY",
            "venv": str(venv), "package_root": str(package_root),
            "version": distribution.version, "direct_url": direct,
            "source_digest": secure.manifest_digest(files), "files": len(files)}


def capture(trial):
    manifest = read(EVIDENCE / "manifest.json")
    expected = manifest["baseline" if trial.startswith("A") else "candidate"]
    row = {"trial": trial, "index": ORDER.index(trial), "outcome": os.environ["ACTION_OUTCOME"],
           "run_id": manifest["run_id"], "attempt": manifest["attempt"], "system": manifest["system"],
           "source": expected, "fixture": manifest["fixture"], "phase_times": "UNKNOWN"}
    dest = EVIDENCE / trial
    dest.mkdir()
    try:
        prior = read(EVIDENCE / (trial + "-before.json"))
        new = sorted(temporary_directories() - set(prior["temporary_directories"]))
        row["new_temporary_directories"] = new
        # Preserve available original evidence even if installation/review failed.
        for index, name in enumerate(new):
            for offset, directory in enumerate((Path(name), Path(name) / "quality-report")):
                copied = dest / f"raw-{index}-{offset}"
                for filename in ("action-receipt.json", "quality.json", "stdout.txt", "stderr.txt",
                                 "identity.json", "install-report.json", "install-stdout.txt", "install-stderr.txt"):
                    if (directory / filename).is_file():
                        copied.mkdir(exist_ok=True)
                        shutil.copyfile(directory / filename, copied / filename)
        outputs = json.loads(os.environ.get("COST_OUTPUTS", "{}"))
        row["action_outputs"] = outputs
        if set(outputs) != set(KEYS):
            raise ValueError("all six actual composite outputs required")
        receipt_path, report_path = (Path(outputs[key]).resolve(strict=True) for key in ("receipt_path", "report_path"))
        if (receipt_path.name != "action-receipt.json" or report_path.name != "quality.json"
                or receipt_path.parent != report_path.parent
                or not any(receipt_path.is_relative_to(Path(path)) for path in new)):
            raise ValueError("outputs do not name this invocation's private reports")
        receipt = read(receipt_path)
        raw = report_path.read_bytes()
        shutil.copyfile(receipt_path, dest / "action-receipt.json")
        (dest / "quality.json").write_bytes(raw)
        report = json.loads(raw)
        if (receipt.get("checkwash_quality_action_version") != 1
                or any(outputs[key] != str(receipt[key]) for key in KEYS)
                or (receipt["exit_code"], receipt["analysis_exit_code"]) != (0, 0)
                or receipt["integration_error"] is not None
                or receipt["ci_execution_verified"] or receipt["branch_protection_verified"]
                or receipt["analysis_status"] != "complete" or receipt["verdict"] != "no_blocking_finding"
                or receipt["mode"] != "enforce" or row["outcome"] != "success"):
            raise ValueError("original normal composite outputs/receipt did not pass")
        if (report["checkwash_quality_version"] != 1 or report["analysis_status"] != "complete"
                or report["verdict"] != "no_blocking_finding" or report["run"]["mode"] != "enforce"
                or report["run"]["base"] != row["fixture"]["base"] or report["run"]["head"] != row["fixture"]["head"]
                or report["findings"] or report["summary"]["blocking_findings"] != 0):
            raise ValueError("owned unchanged enforce report did not remain normal")
        if trial.startswith("A"):
            venvs = [Path(path) for path in new if Path(path).name.startswith("checkwash-quality-venv-")]
            if len(new) != 2 or len(venvs) != 1 or not receipt_path.parent.name.startswith("checkwash-quality-report-"):
                raise ValueError("one fresh original venv and report directory required")
        else:
            installs = [Path(path) for path in new if (Path(path) / "identity.json").is_file()]
            if len(new) != 2 or len(installs) != 1:
                raise ValueError("one fresh candidate installation and separate report required")
            installation = installs[0]
            venvs = [installation / "environment"]
            identity = read(installation / "identity.json")
            installed = read(installation / "install-report.json")
            row["candidate_identity"] = identity
            if (receipt.get("identity") != identity or receipt.get("subprocess_exit_code") != 0
                    or receipt.get("requested_base") != row["fixture"]["base"]
                    or receipt.get("requested_head") != row["fixture"]["head"]
                    or identity["source_root"] != str(ROOT) or identity["source_digest"] != expected["source_digest"]
                    or identity["version"] != expected["version"] or identity["base_python"] != manifest["python"]
                    or not all(identity[key] for key in ("isolated", "utf8", "bytecode_writes_disabled"))
                    or raw != (report_path.parent / "stdout.txt").read_bytes()):
                raise ValueError("candidate runtime/stream identity mismatch")
            if not installed.get("pip_version") or len(installed.get("install", [])) != 1:
                raise ValueError("candidate pip receipt incomplete")
            package = installed["install"][0]
            if (package.get("metadata", {}).get("name") != "checkwash"
                    or package.get("metadata", {}).get("version") != expected["version"]
                    or unquote(package.get("download_info", {}).get("url", "")) != unquote(ROOT.as_uri())):
                raise ValueError("candidate pip installed a different source")
        row["installed_readback"] = installed_readback(venvs[0], expected, dest)
        if not trial.startswith("A") and row["installed_readback"]["package_root"] != row["candidate_identity"]["package_root"]:
            raise ValueError("candidate receipt and installed readback point to different packages")
        row["report_sha256"] = hashlib.sha256(raw).hexdigest()
        if trial != "A1" and raw != (EVIDENCE / "A1/quality.json").read_bytes():
            raise ValueError("original quality JSON bytes differ across normal trials")
    except Exception as exc:
        row["evidence_error"] = type(exc).__name__ + ": " + str(exc)
        raise
    finally:
        common.save(EVIDENCE / (trial + ".json"), row)


def finish():
    manifest = read(EVIDENCE / "manifest.json")
    for index, trial in enumerate(ORDER):
        row = read(EVIDENCE / (trial + ".json"))
        if (row["outcome"] != "success" or row.get("evidence_error")
                or row["run_id"] != manifest["run_id"] or row["attempt"] != manifest["attempt"]
                or row["trial"] != trial or row["index"] != index or row["system"] != manifest["system"]
                or row["source"] != manifest["baseline" if trial.startswith("A") else "candidate"]
                or row["fixture"] != manifest["fixture"]):
            raise ValueError("incomplete eight-trial normal cost evidence")
    repo = WORKSPACE / manifest["fixture"]["repository"]
    if (common.git(repo, "rev-parse", "HEAD") != manifest["fixture"]["head"]
            or common.git(repo, "rev-parse", "HEAD^{tree}") != manifest["fixture"]["tree"]
            or common.git(repo, "status", "--porcelain")):
        raise ValueError("owned fixture changed after the final trial")
    source(BASELINE, BASE_SHA)
    source(ROOT, manifest["candidate"]["commit"])
    print("Eight original normal quality composites preserved; collect native step timestamps separately.")
    print("Whole-composite observations only; install/analysis phase costs UNKNOWN; four observations per arm.")


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
