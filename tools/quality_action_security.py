"""Owned hosted quality-Action fixtures; no subject quality tools are executed."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import tomllib
from urllib.parse import unquote

CASES = {"unchanged-enforce": (0, 0), "report-loss": (0, 0),
         "enforce-loss": (1, 1), "missing-ref": (2, 2)}
SYSTEMS = {"ubuntu-latest", "windows-latest", "macos-latest"}
CANDIDATE_DIRECTORY = "candidate-中文"
SUBJECT_DIRECTORY = "quality subject 中文"
OUTPUT_KEYS = ("exit_code", "analysis_exit_code", "analysis_status", "verdict", "report_path", "receipt_path")


def security():
    path = Path(__file__).resolve().parents[1] / "action/secure.py"
    spec = importlib.util.spec_from_file_location("quality_qualification_security", path)
    if spec is None or spec.loader is None:
        raise ValueError("security helper missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(repo, *args, env=None):
    # prepare starts clean; capture passes the shared sanitized environment.
    executable = shutil.which("git", path=(env or os.environ).get("PATH"))
    if not executable:
        raise ValueError("Git unavailable")
    proc = subprocess.run([executable, "-C", str(repo), *args], env=env,
                          capture_output=True, check=True, timeout=30)
    return proc.stdout.decode("utf-8").strip()


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def append(path, values):
    security().output_values(path, values)


def history(repo, mode, unchanged=False, head_mode=None):
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src/code.py").write_text("x = 1\n", encoding="utf-8")
    (repo / ".checkwash").mkdir()
    policy = ('schema_version=1\nmode="' + mode + '"\n[[targets]]\nid="coverage"\ntool="coverage"\n'
              'root="."\nconfig="pyproject.toml"\nprofile="coverage-7.16.0-q1"\npaths=["src/"]\n')
    (repo / ".checkwash/quality.toml").write_text(policy, encoding="utf-8")
    git(repo, "init")
    git(repo, "config", "user.name", "Owned quality qualification")
    git(repo, "config", "user.email", "qualification@example.invalid")
    revisions = []
    for index, threshold in enumerate((85, 85 if unchanged else 50)):
        (repo / "pyproject.toml").write_text(f"[tool.coverage.report]\nfail_under={threshold}\n", encoding="utf-8")
        if index and head_mode:
            (repo / ".checkwash/quality.toml").write_text(policy.replace('mode="' + mode + '"', 'mode="' + head_mode + '"'), encoding="utf-8")
        git(repo, "add", ".")
        git(repo, "commit", "--allow-empty", "-m", "owned fixture " + str(index))
        revisions.append(git(repo, "rev-parse", "HEAD"))
    return revisions


def pollution(repo, temporary):
    """Activate harmless controls separately, then return protected-run env."""
    positive = temporary / "positive-module.txt"
    protected = temporary / "PROTECTED_CANARY_EXECUTED"
    for name in ("pip", "checkwash", "hatchling"):
        package = repo / name
        package.mkdir()
        payload = ("import os\nfrom pathlib import Path\nwith Path(os.environ['CW_CANARY_MARKER']).open('a', encoding='utf-8') as stream:\n"
                   "    stream.write(" + repr(name + "\n") + ")\n")
        (package / "__init__.py").write_text(payload, encoding="utf-8")
        (package / "__main__.py").write_text(payload, encoding="utf-8")
    for name in ("sitecustomize", "secure"):
        payload = ("import os\nfrom pathlib import Path\nwith Path(os.environ['CW_CANARY_MARKER']).open('a', encoding='utf-8') as stream:\n"
                   "    stream.write(" + repr(name + "\n") + ")\n")
        (repo / (name + ".py")).write_text(payload, encoding="utf-8")
    control_env = {**os.environ, "PYTHONPATH": str(repo), "CW_CANARY_MARKER": str(positive)}
    for key in list(control_env):
        if key.startswith("PYTHON") and key != "PYTHONPATH":
            del control_env[key]
    control = subprocess.run([sys.executable, "-c", "import pip, checkwash, hatchling, secure"],
                             cwd=temporary, env=control_env, capture_output=True, timeout=30)
    (temporary / "positive-module-stdout.txt").write_bytes(control.stdout)
    (temporary / "positive-module-stderr.txt").write_bytes(control.stderr)
    expected_modules = {"sitecustomize", "pip", "checkwash", "hatchling", "secure"}
    observed = set(positive.read_text(encoding="utf-8").splitlines()) if positive.exists() else set()
    if control.returncode != 0 or observed != expected_modules:
        raise ValueError("module canary positive control failed")

    fake = repo / "fake-bin"
    fake.mkdir()
    bash = shutil.which("bash")
    if not bash:
        raise ValueError("Bash is required for the actual composite fixture")
    positive_path = temporary / "positive-path.txt"
    for name in ("python", "pip", "checkwash", "git"):
        script = fake / name
        script.write_text('#!/bin/sh\nprintf "%s\\n" "' + name + '" >> "$CW_CANARY_MARKER"\n', encoding="utf-8", newline="\n")
        script.chmod(0o755)
        (fake / (name + ".cmd")).write_text('@echo off\r\necho ' + name + '>>"%CW_CANARY_MARKER%"\r\n', encoding="utf-8")
        run = subprocess.run([bash, "--noprofile", "--norc", script.as_posix()],
                             env={**os.environ, "CW_CANARY_MARKER": positive_path.as_posix()}, capture_output=True, timeout=30)
        (temporary / ("positive-path-" + name + "-stdout.txt")).write_bytes(run.stdout)
        (temporary / ("positive-path-" + name + "-stderr.txt")).write_bytes(run.stderr)
        if run.returncode:
            raise ValueError("PATH canary positive control failed")
    if set(positive_path.read_text(encoding="utf-8").splitlines()) != {"python", "pip", "checkwash", "git"}:
        raise ValueError("PATH canary receipts missing")

    decoy = temporary / "decoy git 中文"
    history(decoy, "report", unchanged=True)
    git_env = {**os.environ, "GIT_DIR": str(decoy / ".git"), "GIT_WORK_TREE": str(decoy)}
    if Path(git(repo, "rev-parse", "--show-toplevel", env=git_env)).resolve() != decoy.resolve():
        raise ValueError("Git environment positive control failed")
    config = repo / "pip.ini"
    config.write_text("[global]\nindex-url=http://127.0.0.1:9/owned-unused\n", encoding="utf-8")
    with (repo / "pyproject.toml").open("a", encoding="utf-8") as stream:
        stream.write('\n[build-system]\nrequires=[]\nbuild-backend="hatchling"\nbackend-path=["."]\n')
    dirty = {"PYTHONPATH": str(repo), "PYTHONHOME": str(repo / "invalid-home"),
             "PYTHONUTF8": "0", "PYTHONIOENCODING": "cp950", "PYTHONUSERBASE": str(repo),
             "PIP_CONFIG_FILE": str(config), "PIP_INDEX_URL": "http://127.0.0.1:9/owned-unused",
             "PIP_FIND_LINKS": str(repo), "PIP_TARGET": str(repo / "untrusted-install"),
             "PIP_PREFIX": str(repo), "PIP_CONSTRAINT": str(repo / "missing-constraints"),
             "GIT_DIR": str(decoy / ".git"), "GIT_WORK_TREE": str(decoy),
             "CW_CANARY_MARKER": protected.as_posix(), "QUALITY_FIXTURE_TOKEN": "owned-nonsecret-token"}
    return dirty, fake, {"module_returncode": control.returncode, "modules": sorted(observed),
                         "path_controls": ["checkwash", "git", "pip", "python"],
                         "git_redirection_effective": True}


def prepare(case):
    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
    temporary = Path(os.environ["RUNNER_TEMP"])
    control_directory = temporary / "quality controls 中文"
    control_directory.mkdir()
    repo = workspace / SUBJECT_DIRECTORY
    base, head = history(repo, "report" if case == "report-loss" else "enforce", unchanged=case == "unchanged-enforce")
    controls = None
    # Pollution on normal/report/block: it must not manufacture a refusal or
    # erase the report-mode high finding as a way to avoid executing canaries.
    if case != "missing-ref":
        dirty, fake, controls = pollution(repo, control_directory)
        append(os.environ["GITHUB_ENV"], dirty)
        with open(os.environ["GITHUB_PATH"], "a", encoding="utf-8", newline="\n") as stream:
            stream.write(str(fake) + "\n")
    if case == "missing-ref":
        missing = "f" * 40
        try:
            git(repo, "cat-file", "-e", missing + "^{commit}")
        except subprocess.CalledProcessError:
            head = missing
        else:
            raise ValueError("owned missing ref unexpectedly exists")
    source = workspace / CANDIDATE_DIRECTORY
    fixture = {"case": case, "base": base, "head": head, "controls": controls,
               "candidate_sha": git(source, "rev-parse", "HEAD"), "prepared_at": time.time()}
    write_json(temporary / "quality-security-fixture.json", fixture)
    append(os.environ["GITHUB_OUTPUT"], {"base": base, "head": head, "repository": SUBJECT_DIRECTORY})


def capture(case, system):
    temporary = Path(os.environ["RUNNER_TEMP"])
    fixture = json.loads((temporary / "quality-security-fixture.json").read_text(encoding="utf-8"))
    output = Path(os.environ["EVIDENCE_ROOT"])
    output.mkdir(exist_ok=True)
    receipts, identities, installs = [], [], []
    for number, directory in enumerate(sorted(temporary.glob("checkwash-action-*"))):
        if not directory.is_dir():
            continue
        dest = output / str(number)
        dest.mkdir()
        for name in ("identity.json", "install-report.json", "install-stdout.txt", "install-stderr.txt"):
            if (directory / name).is_file():
                shutil.copyfile(directory / name, dest / name)
                if name == "identity.json":
                    identities.append(str(number) + "/" + name)
                if name == "install-report.json":
                    installs.append(str(number) + "/" + name)
        review = directory / "quality-report"
        if review.is_dir():
            for name in ("action-receipt.json", "quality.json", "stdout.txt", "stderr.txt"):
                if (review / name).is_file():
                    shutil.copyfile(review / name, dest / name)
            if (review / "action-receipt.json").is_file():
                receipts.append(str(number) + "/action-receipt.json")
    shared = security()
    clean = shared.child_environment(dict(os.environ), temporary)
    source = Path(os.environ["GITHUB_WORKSPACE"]) / CANDIDATE_DIRECTORY
    metadata = {"case": case, "system": system, "candidate_sha": git(source, "rev-parse", "HEAD", env=clean),
                "expected_candidate_sha": os.environ["CANDIDATE_SHA"],
                "run_id": os.environ["GITHUB_RUN_ID"], "attempt": os.environ["GITHUB_RUN_ATTEMPT"],
                "step_outcome": os.environ["ACTION_OUTCOME"], "receipts": receipts,
                "identities": identities, "install_reports": installs,
                "action_outputs": {key: os.environ.get("ACTION_" + key.upper(), "") for key in OUTPUT_KEYS},
                "source_root": str(source.resolve()), "source_uri": source.resolve().as_uri(),
                "source_digest": shared.manifest_digest(shared.source_manifest(source / "src/checkwash")),
                "source_version": tomllib.loads((source / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"],
                "trusted_python": str(Path(sys.executable).resolve()), "python_version": sys.version,
                "fixture": fixture,
                "canary_executed": (temporary / "quality controls 中文" / "PROTECTED_CANARY_EXECUTED").exists(),
                "untrusted_install_created": (Path(os.environ["GITHUB_WORKSPACE"]) / SUBJECT_DIRECTORY / "untrusted-install").exists(),
                "runner_image": os.environ.get("ImageOS"), "runner_image_version": os.environ.get("ImageVersion"),
                "prepare_to_capture_seconds": time.time() - fixture["prepared_at"],
                "install_seconds": None, "analysis_seconds": None}
    write_json(output / "case.json", metadata)
    shutil.copyfile(temporary / "quality-security-fixture.json", output / "fixture.json")
    for path in (temporary / "quality controls 中文").glob("positive-*.txt"):
        shutil.copyfile(path, output / path.name)


def validate(root):
    found = {}
    for metadata_path in root.rglob("case.json"):
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
        key = (data["case"], data["system"])
        if key in found or key[0] not in CASES or key[1] not in SYSTEMS:
            raise ValueError("duplicate or unexpected quality case")
        found[key] = data
        if (data["fixture"]["case"] != key[0] or data["candidate_sha"] != os.environ["CANDIDATE_SHA"] or data["expected_candidate_sha"] != data["candidate_sha"]
                or data["fixture"]["candidate_sha"] != data["candidate_sha"]
                or data["run_id"] != os.environ["GITHUB_RUN_ID"] or data["attempt"] != os.environ["GITHUB_RUN_ATTEMPT"]
                or data["canary_executed"] or data["untrusted_install_created"]):
            raise ValueError("source/run/canary evidence mismatch")
        if json.loads((metadata_path.parent / "fixture.json").read_text(encoding="utf-8")) != data["fixture"]:
            raise ValueError("fixture receipt changed")
        if any(len(data[name]) != 1 for name in ("receipts", "identities", "install_reports")):
            raise ValueError("one actual receipt, identity and install report required")
        receipt_path = metadata_path.parent / data["receipts"][0]
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        expected_exit, expected_analysis = CASES[key[0]]
        if receipt.get("checkwash_quality_action_version") != 1 or receipt.get("subprocess_exit_code") != expected_analysis:
            raise ValueError("Action receipt version or original process exit changed")
        if (receipt["exit_code"], receipt["analysis_exit_code"]) != (expected_exit, expected_analysis):
            raise ValueError("quality exit contract changed")
        if (receipt.get("requested_base") != data["fixture"]["base"]
                or receipt.get("requested_head") != data["fixture"]["head"]):
            raise ValueError("requested fixture refs mismatched")
        if receipt["integration_error"] is not None or receipt["ci_execution_verified"] or receipt["branch_protection_verified"]:
            raise ValueError("integration/verification flags changed")
        if data["step_outcome"] != ("success" if expected_exit == 0 else "failure"):
            raise ValueError("native composite failure was swallowed")
        if any(data["action_outputs"].get(name) != str(receipt[name]) for name in OUTPUT_KEYS):
            raise ValueError("six Action outputs differ from original receipt")
        identity = receipt["identity"]
        installed_identity = json.loads((metadata_path.parent / data["identities"][0]).read_text(encoding="utf-8"))
        if (identity != installed_identity or not identity["isolated"] or not identity["utf8"]
                or not identity["bytecode_writes_disabled"] or identity["source_digest"] != data["source_digest"]
                or identity["source_root"] != data["source_root"] or identity["version"] != data["source_version"]
                or identity["base_python"] != data["trusted_python"]):
            raise ValueError("runtime content/interpreter identity mismatch")
        installed = json.loads((metadata_path.parent / data["install_reports"][0]).read_text(encoding="utf-8"))
        if not installed.get("pip_version") or len(installed.get("install", [])) != 1:
            raise ValueError("actual pip installation evidence missing")
        package = installed["install"][0]
        if (package.get("metadata", {}).get("name") != "checkwash"
                or package.get("metadata", {}).get("version") != data["source_version"]
                or unquote(package.get("download_info", {}).get("url", "")) != unquote(data["source_uri"])):
            raise ValueError("pip installed a different source/package")
        raw = (receipt_path.parent / "quality.json").read_bytes()
        if raw != (receipt_path.parent / "stdout.txt").read_bytes():
            raise ValueError("original quality JSON bytes changed")
        report = json.loads(raw)
        if (report["checkwash_quality_version"] != 1 or report["analysis_status"] != receipt["analysis_status"]
                or report["verdict"] != receipt["verdict"] or report["run"]["mode"] != receipt["mode"]):
            raise ValueError("original quality report fields changed")
        if key[0] == "missing-ref":
            if (report["analysis_status"] != "error" or report["verdict"] != "error"
                    or report["run"]["base"] != "HEAD" or report["run"]["head"] != "worktree"
                    or report["run"]["mode"] != "report"
                    or not any(item["kind"] == "error" for item in report["diagnostics"])):
                raise ValueError("missing ref lost the engine's unresolved error report")
        else:
            controls = data["fixture"]["controls"]
            if (controls["module_returncode"] != 0 or not controls["git_redirection_effective"]
                    or set(controls["modules"]) != {"sitecustomize", "pip", "checkwash", "hatchling", "secure"}
                    or set(controls["path_controls"]) != {"python", "pip", "checkwash", "git"}):
                raise ValueError("pollution positive controls missing")
            for name, expected in (("positive-module.txt", controls["modules"]), ("positive-path.txt", controls["path_controls"])):
                if set((metadata_path.parent / name).read_text(encoding="utf-8").splitlines()) != set(expected):
                    raise ValueError("raw positive control receipt missing")
            if (report["run"]["base"] != data["fixture"]["base"] or report["run"]["head"] != data["fixture"]["head"]
                    or report["analysis_status"] != "complete"):
                raise ValueError("resolved owned history changed")
            if key[0] == "unchanged-enforce":
                if (report["run"]["mode"] != "enforce" or report["verdict"] != "no_blocking_finding"
                        or report["findings"] or report["summary"]["blocking_findings"] != 0):
                    raise ValueError("normal enforced change did not pass")
            else:
                mode = "report" if key[0] == "report-loss" else "enforce"
                verdict = "reported" if mode == "report" else "block"
                if (report["run"]["mode"] != mode or report["verdict"] != verdict
                        or not any(f["rule"] == "QW_THRESHOLD_LOWERED" and f["severity"] == "high" and not f["allowlisted"]
                                   for f in report["findings"])):
                    raise ValueError("real threshold loss was erased or relabeled")
    if found.keys() != {(case, system) for case in CASES for system in SYSTEMS}:
        raise ValueError("quality qualification cases missing")
    print("All", len(found), "actual quality composites retained their original expected outcomes.")
    print("Expected native failure jobs remain failed; this is the independent qualification.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "capture", "validate"))
    parser.add_argument("--case", choices=CASES)
    parser.add_argument("--system", choices=sorted(SYSTEMS))
    parser.add_argument("--root", type=Path)
    args = parser.parse_args()
    if args.mode == "prepare":
        try:
            prepare(args.case)
        except Exception as exc:
            output = Path(os.environ["EVIDENCE_ROOT"])
            output.mkdir(exist_ok=True)
            write_json(output / "prepare-failure.json", {"case": args.case, "error": type(exc).__name__})
            for path in (Path(os.environ["RUNNER_TEMP"]) / "quality controls 中文").glob("positive-*.txt"):
                shutil.copyfile(path, output / path.name)
            raise
    elif args.mode == "capture":
        capture(args.case, args.system)
    else:
        validate(args.root)


if __name__ == "__main__":
    main()
