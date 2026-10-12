"""Run the action wrapper in isolated processes against trusted Git fixtures."""
import json
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

import pytest

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "action/quality/run.py"


@pytest.fixture
def quality_runtime(tmp_path):
    """Offline runtime evidence only; hosted composites qualify pip/build."""
    runner = tmp_path / "runner"
    runner.mkdir()
    directory = runner / "runtime space 中文"
    directory.mkdir()
    environment = directory / "environment"
    flags = ["-I", "-B", "-X", "utf8"]
    made = subprocess.run([sys.executable, *flags, "-m", "venv", "--without-pip", str(environment)],
                          capture_output=True, timeout=120)
    assert made.returncode == 0, made.stderr
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    found = subprocess.run([str(python), *flags, "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
                           capture_output=True, timeout=30)
    assert found.returncode == 0, found.stderr
    site = Path(found.stdout.decode("utf-8").strip())
    shutil.copytree(ROOT / "src/checkwash", site / "checkwash",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    metadata = site / ("checkwash-" + version + ".dist-info")
    metadata.mkdir()
    (metadata / "METADATA").write_text("Metadata-Version: 2.1\nName: checkwash\nVersion: " + version + "\n", encoding="utf-8")
    return python, site, directory


@pytest.mark.parametrize("case,expected,analysis", [
    ("unchanged", 0, 0), ("report-loss", 0, 0), ("enforce-loss", 1, 1),
    ("enforce-incomplete", 2, 2), ("report-incomplete", 0, 0),
    ("require-enforce", 2, 0), ("missing-policy", 2, 0),
    ("bad-source", 2, 2), ("missing-ref", 2, 2),
    ("named-ref", 2, "unavailable"), ("outside-repo", 2, "unavailable"),
    ("nested-directory", 2, "unavailable"), ("invalid-boolean", 2, "unavailable"),
])
def test_action_preserves_review_results_and_rejects_bad_integration(tmp_path, quality_runtime, case, expected, analysis):
    workspace = tmp_path / "workspace"
    repo = workspace / "subject"
    repo.mkdir(parents=True)
    runner = tmp_path / "runner"
    runner.mkdir(exist_ok=True)
    marker = tmp_path / "SUBJECT_EXECUTED"
    hostile = "from pathlib import Path\nPath(" + repr(str(marker)) + ").write_text('executed')\n"
    (repo / "sitecustomize.py").write_text(hostile, encoding="utf-8")
    (repo / "checkwash").mkdir()
    (repo / "checkwash/__init__.py").write_text(hostile, encoding="utf-8")
    (repo / "checkwash/__main__.py").write_text(hostile, encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src/code.py").write_text("x = 1\n", encoding="utf-8")
    mode = "report" if case.startswith("report-") or case == "require-enforce" else "enforce"
    (repo / ".checkwash").mkdir()
    if case != "missing-policy":
        (repo / ".checkwash/quality.toml").write_text(
            'schema_version=1\nmode="' + mode + '"\n[[targets]]\nid="coverage"\ntool="coverage"\n'
            'root="."\nconfig="pyproject.toml"\nprofile="coverage-7.16.0-q1"\npaths=["src/"]\n', encoding="utf-8")
    config = '[tool.coverage.report]\nfail_under=85\n'
    (repo / "pyproject.toml").write_text(config, encoding="utf-8")
    def git(*args):
        result = subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
        return result.stdout.decode().strip()
    git("init")
    git("config", "user.name", "action-fixture")
    git("config", "user.email", "fixture@example.invalid")
    git("add", ".")
    git("commit", "-m", "trusted base")
    base = git("rev-parse", "HEAD")
    after = config if case == "unchanged" else config.replace("85", "50")
    if case.endswith("incomplete"):
        after += "exclude_also=['.*']\n"
    if case == "bad-source":
        after = "[invalid"
    (repo / "pyproject.toml").write_text(after, encoding="utf-8")
    git("add", ".")
    git("commit", "--allow-empty", "-m", "trusted head")
    head = git("rev-parse", "HEAD")
    env = {**os.environ, "GITHUB_WORKSPACE": str(workspace), "RUNNER_TEMP": str(runner),
           "GITHUB_OUTPUT": str(tmp_path / "output"), "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
           "CW_QUALITY_BASE": base, "CW_QUALITY_HEAD": head, "CW_QUALITY_REPOSITORY": "subject",
           "CW_QUALITY_REQUIRE_ENFORCE": "true" if case in {"require-enforce", "missing-policy"} else "false",
           "PYTHONPATH": str(repo), "CHECKWASH_TODAY": "2026-09-09"}
    if case == "missing-ref":
        env["CW_QUALITY_HEAD"] = "f" * 40
    elif case == "named-ref":
        env["CW_QUALITY_BASE"] = "HEAD~1"
    elif case == "outside-repo":
        env["CW_QUALITY_REPOSITORY"] = ".."
    elif case == "nested-directory":
        env["CW_QUALITY_REPOSITORY"] = "subject/src"
    elif case == "invalid-boolean":
        env["CW_QUALITY_REQUIRE_ENFORCE"] = "yes"
    python, _site, directory = quality_runtime
    env["CHECKWASH_RUNTIME_DIRECTORY"] = str(directory)
    proc = subprocess.run([str(python), "-I", "-B", "-X", "utf8", str(WRAPPER)], env=env, cwd=repo, capture_output=True, timeout=150)
    assert proc.returncode == expected, (proc.stdout, proc.stderr)
    output = dict(line.split("=", 1) for line in Path(env["GITHUB_OUTPUT"]).read_text(encoding="utf-8").splitlines())
    receipt = json.loads(Path(output["receipt_path"]).read_text(encoding="utf-8"))
    assert receipt["exit_code"] == expected and receipt["analysis_exit_code"] == analysis
    assert output["exit_code"] == str(expected) and output["analysis_exit_code"] == str(analysis)
    assert not marker.exists(), "Subject Python must never run, even through PYTHONPATH or sitecustomize"
    if analysis != "unavailable":
        report = json.loads(Path(output["report_path"]).read_text(encoding="utf-8"))
        assert report["analysis_status"] == output["analysis_status"]
        assert report["verdict"] == output["verdict"]
        if case in {"require-enforce", "missing-policy"}:
            assert receipt["integration_error"].startswith("BASE_MODE_NOT_ENFORCE")
            assert report["run"]["mode"] == "report"
    else:
        assert receipt["integration_error"] and output["report_path"] == ""


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def security_harness():
    return load_module("quality_security_harness", ROOT / "tools/quality_action_security.py")


def owned_review(tmp_path, quality_runtime, *, mode="enforce", unchanged=False, head_mode=None):
    python, site, directory = quality_runtime
    workspace = tmp_path / "workspace 中文"
    workspace.mkdir()
    repo = workspace / "subject space 中文"
    base, head = security_harness().history(repo, mode, unchanged=unchanged, head_mode=head_mode)
    env = {**os.environ, "GITHUB_WORKSPACE": str(workspace), "RUNNER_TEMP": str(directory.parent),
           "CHECKWASH_RUNTIME_DIRECTORY": str(directory), "GITHUB_OUTPUT": str(tmp_path / "output"),
           "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"), "CW_QUALITY_REPOSITORY": repo.name,
           "CW_QUALITY_BASE": base, "CW_QUALITY_HEAD": head, "CW_QUALITY_REQUIRE_ENFORCE": "false"}
    return python, site, repo, directory, env


def execute_review(python, repo, env):
    return subprocess.run([str(python), "-I", "-B", "-X", "utf8", str(WRAPPER)],
                          env=env, cwd=repo, capture_output=True, timeout=150)


def saved_receipt(env):
    paths = list(Path(env["RUNNER_TEMP"]).glob("checkwash-action-*/quality-report/action-receipt.json"))
    assert len(paths) == 1
    return json.loads(paths[0].read_text(encoding="utf-8")), paths[0]


@pytest.mark.parametrize("mode,unchanged,expected", [("enforce", True, 0), ("report", False, 0), ("enforce", False, 1)])
def test_quality_pollution_preserves_real_normal_report_and_enforce(tmp_path, quality_runtime, mode, unchanged, expected):
    python, _site, repo, directory, env = owned_review(tmp_path, quality_runtime, mode=mode, unchanged=unchanged)
    controls = tmp_path / "controls"
    controls.mkdir()
    dirty, fake, positive = security_harness().pollution(repo, controls)
    assert positive["module_returncode"] == 0 and positive["git_redirection_effective"]
    env.update(dirty)
    env["PATH"] = str(fake) + os.pathsep + env.get("PATH", "")
    result = execute_review(python, repo, env)
    assert result.returncode == expected, (result.stdout, result.stderr)
    receipt, _ = saved_receipt(env)
    assert (receipt["exit_code"], receipt["analysis_exit_code"]) == (expected, expected)
    report = json.loads(Path(receipt["report_path"]).read_text(encoding="utf-8"))
    assert report["analysis_status"] == "complete" and report["run"]["mode"] == mode
    high = [f for f in report["findings"] if f["rule"] == "QW_THRESHOLD_LOWERED" and f["severity"] == "high"]
    assert bool(high) is (not unchanged)
    assert receipt["requested_base"] == env["CW_QUALITY_BASE"]
    assert receipt["requested_head"] == env["CW_QUALITY_HEAD"]
    assert not (controls / "PROTECTED_CANARY_EXECUTED").exists()
    assert not (repo / "untrusted-install").exists()
    assert receipt["identity"]["isolated"] and receipt["identity"]["utf8"]
    assert receipt["identity"]["bytecode_writes_disabled"]


@pytest.mark.parametrize("base_mode,head_mode,required,expected,analysis", [
    ("enforce", "report", "false", 1, 1),
    ("report", "enforce", "false", 0, 0),
    ("report", "enforce", "true", 2, 0),
])
def test_quality_head_mode_cannot_replace_base_policy(tmp_path, quality_runtime, base_mode, head_mode, required, expected, analysis):
    python, _site, repo, _directory, env = owned_review(tmp_path, quality_runtime, mode=base_mode, head_mode=head_mode)
    env["CW_QUALITY_REQUIRE_ENFORCE"] = required
    result = execute_review(python, repo, env)
    assert result.returncode == expected, result.stderr
    receipt, _ = saved_receipt(env)
    assert receipt["analysis_exit_code"] == analysis and receipt["mode"] == base_mode
    report = json.loads(Path(receipt["report_path"]).read_text(encoding="utf-8"))
    assert report["run"]["mode"] == base_mode
    assert any(f["rule"] == "QW_THRESHOLD_LOWERED" and f["severity"] == "high" for f in report["findings"])


@pytest.mark.parametrize("damage", ["quality-source", "quality-resource", "missing", "cache", "loose-pyc", "runtime"])
def test_quality_rejects_runtime_tampering_before_import_and_saves_failure(tmp_path, quality_runtime, damage):
    python, site, repo, _directory, env = owned_review(tmp_path, quality_runtime)
    package = site / "checkwash"
    marker = tmp_path / "UNVERIFIED_IMPORT"
    if damage == "quality-source":
        (package / "quality/__init__.py").write_text(
            "from pathlib import Path\nPath(" + repr(str(marker)) + ").write_text('bad')\n", encoding="utf-8")
    elif damage == "quality-resource":
        resource = next((package / "quality").rglob("*.json"))
        resource.write_text("{}\n", encoding="utf-8")
    elif damage == "missing":
        (package / "quality/cli.py").unlink()
    elif damage == "cache":
        (package / "quality/__pycache__").mkdir()
        (package / "quality/__pycache__/payload.pyc").write_bytes(b"owned cache")
    elif damage == "loose-pyc":
        (package / "quality/payload.pyc").write_bytes(b"owned cache")
    else:
        env["CHECKWASH_RUNTIME_DIRECTORY"] = str(repo)
    result = execute_review(python, repo, env)
    assert result.returncode == 2, result.stderr
    receipt, receipt_path = saved_receipt(env)
    assert receipt["analysis_exit_code"] == "unavailable" and receipt["integration_error"]
    assert receipt["report_path"] == "" and not marker.exists()
    assert receipt_path.is_relative_to(Path(env["RUNNER_TEMP"]))
    assert not receipt_path.is_relative_to(repo)
    assert not (receipt_path.parent / "stdout.txt").exists()


@pytest.mark.parametrize("channel", ["GITHUB_STEP_SUMMARY", "GITHUB_OUTPUT"])
def test_quality_finalization_failure_retains_completed_analysis(tmp_path, quality_runtime, channel):
    python, _site, repo, directory, env = owned_review(tmp_path, quality_runtime)
    env[channel] = str(directory)  # A directory cannot be an append-only output file.
    result = execute_review(python, repo, env)
    assert result.returncode == 2, result.stderr
    receipt, _ = saved_receipt(env)
    assert receipt["exit_code"] == 2 and receipt["analysis_exit_code"] == 1
    assert receipt["integration_error"] and receipt["verdict"] == "block"
    assert json.loads(Path(receipt["report_path"]).read_text(encoding="utf-8"))["verdict"] == "block"


def test_quality_no_safe_directory_returns_two_without_outputs(tmp_path, quality_runtime):
    python, _site, repo, _directory, env = owned_review(tmp_path, quality_runtime)
    env["RUNNER_TEMP"] = str(repo)
    result = execute_review(python, repo, env)
    assert result.returncode == 2 and b"no outputs exported" in result.stderr
    assert not Path(env["GITHUB_OUTPUT"]).exists()
    assert not list(repo.glob("checkwash-action-*"))


@pytest.mark.parametrize("damage", ["receipt-write", "late-newline", "late-nul"])
def test_quality_finalize_never_exports_a_false_success(tmp_path, monkeypatch, damage):
    wrapper = load_module("quality_wrapper_finalize", WRAPPER)
    output = tmp_path / "report"
    output.mkdir()
    env = {"GITHUB_OUTPUT": str(tmp_path / "output"), "GITHUB_STEP_SUMMARY": str(tmp_path / "summary")}
    receipt = wrapper.new_receipt()
    receipt.update(exit_code=0, analysis_exit_code=0, analysis_status="complete", verdict="reported", mode="report", report_path="quality.json")
    if damage == "receipt-write":
        def fail_write(*_args):
            raise PermissionError("owned failure")
        monkeypatch.setattr(wrapper.secure, "save_json", fail_write)
    else:
        receipt["report_path"] += "\nexit_code=0" if damage == "late-newline" else "\0"
    assert wrapper.finalize(env, output, receipt) == 2
    assert receipt["analysis_exit_code"] == 0 and receipt["exit_code"] == 2
    assert not Path(env["GITHUB_OUTPUT"]).exists()
    if damage != "receipt-write":
        saved = json.loads((output / "action-receipt.json").read_text(encoding="utf-8"))
        assert saved["exit_code"] == 2 and saved["integration_error"]


def test_quality_invalid_json_retains_raw_bytes_and_spawn_environment(tmp_path, monkeypatch, capsys):
    wrapper = load_module("quality_wrapper_invalid", WRAPPER)
    repo = tmp_path / "subject"
    repo.mkdir()
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    output = tmp_path / "evidence"
    output.mkdir()
    env = {**os.environ, "GITHUB_WORKSPACE": str(repo), "CW_QUALITY_BASE": "a" * 40,
           "CW_QUALITY_HEAD": "b" * 40, "PIP_INDEX_URL": "http://127.0.0.1:9",
           "PYTHONPATH": str(repo), "GIT_DIR": str(repo), "QUALITY_FIXTURE_TOKEN": "fake"}
    monkeypatch.setattr(wrapper.secure, "runtime_directory", lambda _env: runtime)
    monkeypatch.setattr(wrapper.secure, "identity", lambda: {"owned_unit_stub": True})
    calls = []
    raw = b"::error::owned invalid JSON\n"
    def spawn(argv, **kwargs):
        calls.append((argv, kwargs))
        if "quality" in argv:
            return subprocess.CompletedProcess(argv, 0, raw, b"::add-mask::owned\n")
        return subprocess.CompletedProcess(argv, 0, (str(repo) + "\n").encode("utf-8"), b"")
    monkeypatch.setattr(wrapper.subprocess, "run", spawn)
    receipt = wrapper.review(env, output)
    assert receipt["exit_code"] == 2 and receipt["analysis_exit_code"] == "unavailable"
    assert receipt["subprocess_exit_code"] == 0 and receipt["integration_error"] == "Invalid quality JSON"
    assert (output / "stdout.txt").read_bytes() == raw
    assert b"::add-mask::" in (output / "stderr.txt").read_bytes()
    assert "::error::" not in capsys.readouterr().out
    assert len(calls) == 2
    for _argv, kwargs in calls:
        clean = kwargs["env"]
        assert not {"PYTHONPATH", "GIT_DIR", "QUALITY_FIXTURE_TOKEN", "PIP_INDEX_URL"} & clean.keys()
        assert clean["PIP_CONFIG_FILE"] == os.devnull
        assert kwargs["cwd"] == output
    assert Path(calls[0][0][0]).is_absolute()
    assert calls[1][0][:8] == [sys.executable, "-I", "-B", "-X", "utf8", "-m", "checkwash", "quality"]


@pytest.mark.parametrize("failure", ["timeout", "unexpected-exit", "stderr-write", "report-write"])
def test_quality_process_failures_keep_completed_analysis_distinct(tmp_path, monkeypatch, capsys, failure):
    wrapper = load_module("quality_wrapper_process_failure", WRAPPER)
    repo = tmp_path / "subject"
    repo.mkdir()
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    output = tmp_path / "evidence"
    output.mkdir()
    env = {**os.environ, "GITHUB_WORKSPACE": str(repo), "CW_QUALITY_BASE": "a" * 40,
           "CW_QUALITY_HEAD": "b" * 40}
    monkeypatch.setattr(wrapper.secure, "runtime_directory", lambda _env: runtime)
    monkeypatch.setattr(wrapper.secure, "identity", lambda: {"owned_unit_stub": True})
    raw = json.dumps({"checkwash_quality_version": 1, "analysis_status": "complete",
                      "verdict": "block", "run": {"mode": "enforce"}}).encode("utf-8")
    stderr = b"::error::owned raw stderr\n"
    def spawn(argv, **_kwargs):
        if "quality" not in argv:
            return subprocess.CompletedProcess(argv, 0, (str(repo) + "\n").encode("utf-8"), b"")
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, 120, output=b"::warning::partial", stderr=stderr)
        return subprocess.CompletedProcess(argv, 7 if failure == "unexpected-exit" else 1, raw, stderr)
    monkeypatch.setattr(wrapper.subprocess, "run", spawn)
    write_bytes = Path.write_bytes
    def controlled_write(path, data):
        denied = "stderr.txt" if failure == "stderr-write" else "quality.json"
        if failure in {"stderr-write", "report-write"} and path.name == denied:
            raise PermissionError("owned artifact write failure")
        return write_bytes(path, data)
    monkeypatch.setattr(Path, "write_bytes", controlled_write)
    receipt = wrapper.review(env, output)
    assert receipt["exit_code"] == 2 and receipt["integration_error"]
    assert capsys.readouterr().out == ""
    if failure == "timeout":
        assert receipt["analysis_exit_code"] == "unavailable" and "subprocess_exit_code" not in receipt
        assert (output / "stdout.txt").read_bytes() == b"::warning::partial"
        assert (output / "stderr.txt").read_bytes() == stderr
        assert receipt["report_path"] == ""
    elif failure == "unexpected-exit":
        assert receipt["analysis_exit_code"] == "unavailable" and receipt["subprocess_exit_code"] == 7
        assert (output / "stdout.txt").read_bytes() == raw and receipt["report_path"] == ""
    else:
        assert receipt["analysis_exit_code"] == 1 and receipt["subprocess_exit_code"] == 1
        assert receipt["analysis_status"] == "complete" and receipt["verdict"] == "block"
        assert (output / "stdout.txt").read_bytes() == raw
        if failure == "stderr-write":
            assert receipt["stream_write_errors"] == ["stderr.txt: PermissionError"]
            assert Path(receipt["report_path"]).read_bytes() == raw
        else:
            assert receipt["report_path"] == "" and (output / "stderr.txt").read_bytes() == stderr


def test_quality_installer_delegates_to_trusted_shared_file(tmp_path, monkeypatch):
    installer = load_module("quality_installer_adapter", ROOT / "action/quality/install.py")
    (tmp_path / "secure.py").write_text("raise RuntimeError('subject module imported')\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    shared = installer.shared_security()
    assert shared.ROOT == ROOT
    assert Path(shared.__file__).resolve() == ROOT / "action/secure.py"
    seen = []
    monkeypatch.setattr(shared, "install", lambda env: seen.append(env) or 0)
    monkeypatch.setattr(installer, "shared_security", lambda: shared)
    assert installer.main() == 0 and len(seen) == 1


@pytest.mark.parametrize("selection", ["missing", "explicit", "location"])
def test_quality_bootstrap_uses_trusted_python_and_real_script_file(tmp_path, selection):
    bash = shutil.which("bash")
    assert bash
    subject = tmp_path / "subject 中文"
    subject.mkdir()
    action = tmp_path / "action space 中文"
    action.mkdir()
    marker = tmp_path / "bootstrap.json"
    (action / "install.py").write_text(
        "import json, pathlib, sys\npathlib.Path(" + repr(str(marker)) + ").write_text("
        "json.dumps([sys.executable, sys.flags.isolated, sys.flags.utf8_mode, sys.dont_write_bytecode]))\n", encoding="utf-8")
    fake_marker = tmp_path / "AMBIENT_PYTHON"
    fake = subject / "python"
    fake.write_text("#!/bin/sh\nprintf bad > '" + fake_marker.as_posix() + "'\n", encoding="utf-8")
    fake.chmod(0o755)
    python = Path(sys.executable).absolute()
    location = python.parent if os.name == "nt" else python.parent.parent
    env = {**os.environ, "CW_REQUESTED_PYTHON": str(python) if selection == "explicit" else "",
           "CW_PYTHON_LOCATION": str(location) if selection == "location" else "",
           "GITHUB_WORKSPACE": str(subject), "CW_ACTION_PATH": str(action),
           "RUNNER_OS": "Windows" if os.name == "nt" else "Linux", "PYTHONUTF8": "0",
           "PATH": str(subject) + os.pathsep + os.environ.get("PATH", "")}
    metadata = (ROOT / "action/quality/action.yml").read_text(encoding="utf-8")
    block = metadata.split("      run: |\n", 1)[1].split("    - id: review\n", 1)[0]
    script = tmp_path / "bootstrap.sh"
    script.write_text("\n".join(line.removeprefix("        ") for line in block.splitlines()) + "\n", encoding="utf-8", newline="\n")
    result = subprocess.run([bash, "--noprofile", "--norc", "-e", "-o", "pipefail", script.as_posix()],
                            cwd=subject, env=env, capture_output=True, timeout=30)
    assert not fake_marker.exists()
    if selection == "missing":
        assert result.returncode == 2 and not marker.exists(), result.stderr
    else:
        assert result.returncode == 0, result.stderr
        executable, isolated, utf8, no_bytecode = json.loads(marker.read_text(encoding="utf-8"))
        assert Path(executable).resolve() == python.resolve()
        assert isolated == 1 and utf8 == 1 and no_bytecode is True


@pytest.fixture
def quality_qualification_evidence(tmp_path, monkeypatch):
    qualifier = security_harness()
    monkeypatch.setenv("CANDIDATE_SHA", "a" * 40)
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    for case, (code, analysis) in qualifier.CASES.items():
        for system in qualifier.SYSTEMS:
            directory = tmp_path / (case + "-" + system)
            directory.mkdir()
            controls = {"module_returncode": 0, "modules": ["sitecustomize", "pip", "checkwash", "hatchling", "secure"],
                        "path_controls": ["checkwash", "git", "pip", "python"], "git_redirection_effective": True}
            fixture = {"case": case, "base": "b" * 40, "head": "c" * 40, "candidate_sha": "a" * 40,
                       "controls": None if case == "missing-ref" else controls}
            identity = {"isolated": True, "utf8": True, "bytecode_writes_disabled": True,
                        "source_digest": "d" * 64, "source_root": "/trusted/source", "version": "0.7.0",
                        "base_python": "/trusted/python"}
            mode = "report" if case in {"report-loss", "missing-ref"} else "enforce"
            status = "error" if case == "missing-ref" else "complete"
            verdict = {"unchanged-enforce": "no_blocking_finding", "report-loss": "reported",
                       "enforce-loss": "block", "missing-ref": "error"}[case]
            receipt = {"checkwash_quality_action_version": 1, "exit_code": code, "analysis_exit_code": analysis,
                       "subprocess_exit_code": analysis,
                       "analysis_status": status, "verdict": verdict, "mode": mode, "identity": identity,
                       "report_path": "/original/quality.json", "receipt_path": "/original/action-receipt.json",
                       "integration_error": None, "ci_execution_verified": False, "branch_protection_verified": False,
                       "requested_base": fixture["base"], "requested_head": fixture["head"]}
            report = {"checkwash_quality_version": 1, "analysis_status": status, "verdict": verdict,
                      "run": {"base": "HEAD" if case == "missing-ref" else fixture["base"],
                              "head": "worktree" if case == "missing-ref" else fixture["head"], "mode": mode},
                      "findings": [] if case in {"missing-ref", "unchanged-enforce"} else
                          [{"rule": "QW_THRESHOLD_LOWERED", "severity": "high", "allowlisted": False}],
                      "diagnostics": [{"kind": "error"}] if case == "missing-ref" else [],
                      "summary": {"blocking_findings": 0 if case == "unchanged-enforce" else 1}}
            data = {"case": case, "system": system, "candidate_sha": "a" * 40, "expected_candidate_sha": "a" * 40,
                    "run_id": "123", "attempt": "1", "fixture": fixture, "canary_executed": False,
                    "untrusted_install_created": False, "step_outcome": "success" if code == 0 else "failure",
                    "receipts": ["action-receipt.json"], "identities": ["identity.json"], "install_reports": ["install-report.json"],
                    "action_outputs": {name: str(receipt[name]) for name in qualifier.OUTPUT_KEYS},
                    "source_digest": identity["source_digest"], "source_root": identity["source_root"],
                    "source_version": identity["version"], "trusted_python": identity["base_python"],
                    "source_uri": "file:///trusted/source"}
            install = {"pip_version": "22.3.1", "install": [{"metadata": {"name": "checkwash", "version": "0.7.0"},
                        "download_info": {"url": data["source_uri"]}}]}
            for name, payload in (("case.json", data), ("fixture.json", fixture), ("action-receipt.json", receipt),
                                  ("identity.json", identity), ("install-report.json", install), ("quality.json", report),
                                  ("stdout.txt", report)):
                qualifier.write_json(directory / name, payload)
            if case != "missing-ref":
                for name, values in (("positive-module.txt", controls["modules"]), ("positive-path.txt", controls["path_controls"])):
                    (directory / name).write_text("\n".join(values) + "\n", encoding="utf-8")
    return qualifier, tmp_path


def test_quality_qualification_accepts_original_error_report_and_all_cases(quality_qualification_evidence):
    qualifier, directory = quality_qualification_evidence
    qualifier.validate(directory)


@pytest.mark.parametrize("damage", ["missing-case", "duplicate-case", "candidate", "run", "attempt", "fixture-case",
                                    "requested-base", "requested-head", "identity", "installer-source", "output", "step",
                                    "analysis-exit", "canary", "finding-removed", "control", "raw-report",
                                    "error-report-refs", "error-report-mode", "no-report", "receipt-version", "raw-process-code"])
def test_quality_qualification_rejects_missing_or_misbound_original_evidence(quality_qualification_evidence, damage):
    qualifier, directory = quality_qualification_evidence
    case_name = "missing-ref" if damage.startswith("error-report") else "report-loss"
    case = directory / (case_name + "-ubuntu-latest")
    data_path, receipt_path, report_path = case / "case.json", case / "action-receipt.json", case / "quality.json"
    data = json.loads(data_path.read_text(encoding="utf-8"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if damage == "missing-case":
        data_path.unlink()
    elif damage == "duplicate-case":
        shutil.copytree(case, directory / "duplicate")
    elif damage == "no-report":
        report_path.unlink()
    else:
        if damage in {"candidate", "run", "attempt"}:
            data[{"candidate": "candidate_sha", "run": "run_id", "attempt": "attempt"}[damage]] = "wrong"
        elif damage == "fixture-case":
            data["fixture"]["case"] = "unchanged-enforce"
        elif damage in {"requested-base", "requested-head"}:
            receipt[damage.replace("-", "_")] = "0" * 40
        elif damage == "identity":
            receipt["identity"]["source_digest"] = "0" * 64
        elif damage == "installer-source":
            install = json.loads((case / "install-report.json").read_text(encoding="utf-8"))
            install["install"][0]["download_info"]["url"] = "file:///subject"
            qualifier.write_json(case / "install-report.json", install)
        elif damage == "output":
            data["action_outputs"]["analysis_exit_code"] = "unavailable"
        elif damage == "step":
            data["step_outcome"] = "failure"
        elif damage == "analysis-exit":
            receipt["analysis_exit_code"] = "unavailable"
        elif damage == "receipt-version":
            receipt["checkwash_quality_action_version"] = 2
        elif damage == "raw-process-code":
            receipt["subprocess_exit_code"] = 7
        elif damage == "canary":
            data["canary_executed"] = True
        elif damage == "control":
            (case / "positive-path.txt").write_text("\n", encoding="utf-8")
        elif damage == "raw-report":
            (case / "stdout.txt").write_text("{}\n", encoding="utf-8")
        else:
            if damage == "finding-removed":
                report["findings"] = []
            elif damage == "error-report-refs":
                report["run"]["head"] = data["fixture"]["head"]
            else:
                report["run"]["mode"] = "enforce"
            qualifier.write_json(report_path, report)
            qualifier.write_json(case / "stdout.txt", report)
        qualifier.write_json(data_path, data)
        qualifier.write_json(receipt_path, receipt)
    with pytest.raises((ValueError, OSError)):
        qualifier.validate(directory)
