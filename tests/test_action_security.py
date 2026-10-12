"""Action process boundary regressions; no subject code is executed by the judge.

The offline private environment here tests runtime isolation. Actual pip install
and composite behavior are qualified separately by action-security.yml.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

import pytest


ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "action" / "secure.py"
SPEC = importlib.util.spec_from_file_location("secure_action", DRIVER)
assert SPEC and SPEC.loader
secure = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(secure)


def run_python(python, *args, cwd, env):
    return subprocess.run([str(python), "-I", "-B", "-X", "utf8", *map(str, args)],
                          cwd=cwd, env=env, capture_output=True, timeout=120)


@pytest.fixture
def runtime(tmp_path):
    runner = tmp_path / "runner space 稽核"
    runner.mkdir()
    directory = runner / "checkwash-action-test"
    directory.mkdir()
    environment = directory / "environment"
    made = run_python(sys.executable, "-m", "venv", "--without-pip", environment,
                      cwd=runner, env=dict(os.environ))
    assert made.returncode == 0, made.stderr
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    found = run_python(python, "-c", "import sysconfig; print(sysconfig.get_path('purelib'))",
                       cwd=runner, env=dict(os.environ))
    assert found.returncode == 0, found.stderr
    site = Path(found.stdout.decode("utf-8").strip())
    shutil.copytree(ROOT / "src/checkwash", site / "checkwash",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    metadata = site / ("checkwash-" + version + ".dist-info")
    metadata.mkdir()
    (metadata / "METADATA").write_text("Metadata-Version: 2.1\nName: checkwash\nVersion: " + version + "\n",
                                      encoding="utf-8")
    subject = tmp_path / "subject 中文"
    subject.mkdir()
    env = {**os.environ, "GITHUB_WORKSPACE": str(subject), "RUNNER_TEMP": str(runner),
           "CHECKWASH_RUNTIME_DIRECTORY": str(directory), "CHECKWASH_BASE": "HEAD~1",
           "CHECKWASH_FAIL_ON": "high", "GITHUB_OUTPUT": str(directory / "outputs"),
           "GITHUB_STEP_SUMMARY": str(directory / "summary"), "CHECKWASH_TODAY": "2026-10-12"}
    return python, site, subject, directory, env


def git(repo, *args):
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True, timeout=30)
    return result.stdout.decode("utf-8").strip()


def subject_history(repo, case="block"):
    git(repo, "init")
    git(repo, "config", "user.name", "action-fixture")
    git(repo, "config", "user.email", "action-fixture@example.invalid")
    (repo / "tests").mkdir()
    (repo / "calculator.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (repo / "tests/test_calculator.py").write_text(
        "from calculator import add\n\ndef test_total():\n    assert add(2, 3) == 5\n", encoding="utf-8")
    if case in {"bad-policy", "base-policy"}:
        (repo / ".checkwash").mkdir()
        policy = "[invalid" if case == "bad-policy" else (
            '[gate]\nfail_on = "critical"\n[detectors]\ndisable = ["ASSERT_REMOVED", "TEST_DISABLED"]\n')
        (repo / ".checkwash/config.toml").write_text(policy, encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    base = git(repo, "rev-parse", "HEAD")
    if case in {"block", "head-policy", "base-policy"}:
        (repo / "tests/test_calculator.py").write_text(
            "from calculator import add\n\ndef test_total():\n    pass\n", encoding="utf-8")
    elif case == "repair":
        (repo / "calculator.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    if case == "head-policy":
        (repo / ".checkwash").mkdir()
        (repo / ".checkwash/config.toml").write_text(
            '[gate]\nfail_on = "critical"\n[detectors]\ndisable = ["ASSERT_REMOVED", "TEST_DISABLED"]\n', encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "--allow-empty", "-m", "head")
    return base, git(repo, "rev-parse", "HEAD")


@pytest.mark.parametrize("case,expected", [("block", 1), ("repair", 0), ("unchanged", 0),
                                          ("bad-policy", 0), ("head-policy", 1), ("base-policy", 0)])
def test_private_runtime_preserves_real_engine_verdicts(runtime, case, expected):
    python, _site, repo, directory, env = runtime
    base, head = subject_history(repo, case)
    result = run_python(python, DRIVER, "check", cwd=repo, env=env)
    assert result.returncode == expected, (result.stdout, result.stderr)
    receipt = json.loads((directory / "check-receipt.json").read_text(encoding="utf-8"))
    assert receipt["analysis_exit_code"] == receipt["exit_code"] == expected
    assert receipt["base"] == base and receipt["head"] == head
    assert receipt["identity"]["isolated"] and receipt["identity"]["utf8"]
    if case in {"block", "head-policy"}:
        assert b"ASSERT_REMOVED" in (directory / "stdout.txt").read_bytes()
    if case == "base-policy":
        assert b"ASSERT_REMOVED" not in (directory / "stdout.txt").read_bytes()
    if case == "bad-policy":
        assert b"could not be parsed" in (directory / "stderr.txt").read_bytes()
    assert not list((_site / "checkwash").rglob("*.pyc"))


@pytest.mark.parametrize("pollution", ["modules", "path", "python", "pip", "combined"])
def test_subject_pollution_cannot_replace_real_engine(runtime, pollution):
    python, _site, repo, directory, env = runtime
    subject_history(repo)
    marker = directory / "SUBJECT_EXECUTED"
    hostile = "from pathlib import Path\nPath(" + repr(str(marker)) + ").write_text('executed')\n"
    if pollution in {"modules", "python", "combined"}:
        for name in ("pip", "checkwash", "hatchling"):
            (repo / name).mkdir()
            for file in ("__init__.py", "__main__.py"):
                (repo / name / file).write_text(hostile, encoding="utf-8")
        (repo / "sitecustomize.py").write_text(hostile, encoding="utf-8")
        # Prove the canary actually fires in an explicitly vulnerable import.
        vulnerable_env = {**os.environ, "PYTHONPATH": str(repo)}
        vulnerable = subprocess.run([str(python), "-B", "-c", "import checkwash"],
                                    cwd=repo, env=vulnerable_env, capture_output=True, timeout=30)
        assert vulnerable.returncode == 0 and marker.exists(), vulnerable.stderr
        marker.unlink()
        vulnerable_pip = subprocess.run([str(python), "-B", "-m", "pip", "--version"],
                                        cwd=repo, env=vulnerable_env, capture_output=True, timeout=30)
        assert vulnerable_pip.returncode == 0 and marker.exists(), vulnerable_pip.stderr
        marker.unlink()
        env.update(PYTHONPATH=str(repo), PYTHONHOME=str(repo / "nonexistent"), PYTHONUTF8="0",
                   PYTHONIOENCODING="cp950", PYTHONUSERBASE=str(repo))
    if pollution in {"path", "combined"}:
        fake = repo / "fake-bin"
        fake.mkdir()
        script = "#!/bin/sh\nprintf executed > '" + marker.as_posix().replace("'", "'\\''") + "'\nexit 0\n"
        for name in ("python", "checkwash", "git", "pip"):
            (fake / name).write_text(script, encoding="utf-8")
            (fake / name).chmod(0o755)
            (fake / (name + ".cmd")).write_text('@echo off\r\necho executed>"%CHECKWASH_CANARY_PATH%"\r\n', encoding="ascii")
        env["PATH"] = str(fake) + os.pathsep + env.get("PATH", "")
        env["CHECKWASH_CANARY_PATH"] = str(marker)
        # An ordinary PATH lookup really would choose this canary executable.
        if os.name == "nt":
            vulnerable_path = subprocess.run([os.environ["COMSPEC"], "/d", "/c", "git"],
                                             cwd=repo, env=env, capture_output=True, timeout=30)
        else:
            vulnerable_path = subprocess.run(["git"], cwd=repo, env=env, capture_output=True, timeout=30)
        assert vulnerable_path.returncode == 0 and marker.exists(), vulnerable_path.stderr
        marker.unlink()
    if pollution in {"pip", "combined"}:
        config = repo / "pip.ini"
        config.write_text("[global]\nindex-url = http://127.0.0.1:9/untrusted\n", encoding="utf-8")
        env.update(PIP_CONFIG_FILE=str(config), PIP_INDEX_URL="http://127.0.0.1:9/untrusted",
                   PIP_FIND_LINKS=str(repo), PIP_TARGET=str(repo / "installed"), PIP_PREFIX=str(repo),
                   PIP_CONSTRAINT=str(repo / "missing-constraint"))
    result = run_python(python, DRIVER, "check", cwd=repo, env=env)
    assert result.returncode == 1, (result.stdout, result.stderr)
    assert not marker.exists()
    assert b"ASSERT_REMOVED" in (directory / "stdout.txt").read_bytes()


@pytest.mark.parametrize("side", ["base", "head"])
def test_matching_allowlist_is_effective_only_on_base(runtime, side):
    python, _site, repo, directory, env = runtime
    base, head = subject_history(repo)
    clean = secure.child_environment(env, directory)
    original = run_python(python, "-m", "checkwash", "check", base + "..." + head,
                          "--repo", repo, "--format", "json", cwd=directory, env=clean)
    assert original.returncode == 1, original.stderr
    finding = next(item for item in json.loads(original.stdout)["findings"] if item["rule"] == "ASSERT_REMOVED")
    exemption = (
        '[[allow]]\nfingerprint = "' + finding["fingerprint"] + '"\nrule = "ASSERT_REMOVED"\n'
        'reason = "reviewed qualification control"\nauthor = "qualification"\n'
        'created = "2026-10-12"\nexpires = "2026-10-13"\n')
    weakened = (repo / "tests/test_calculator.py").read_text(encoding="utf-8")
    if side == "base":
        git(repo, "checkout", "--detach", base)
    (repo / ".checkwash").mkdir()
    (repo / ".checkwash/allow.toml").write_text(exemption, encoding="utf-8")
    git(repo, "add", ".checkwash/allow.toml")
    git(repo, "commit", "-m", "reviewed exemption")
    if side == "base":
        base = git(repo, "rev-parse", "HEAD")
        (repo / "tests/test_calculator.py").write_text(weakened, encoding="utf-8")
        git(repo, "add", "tests/test_calculator.py")
        git(repo, "commit", "-m", "head weakening")
    env["CHECKWASH_BASE"] = base
    result = run_python(python, DRIVER, "check", cwd=repo, env=env)
    assert result.returncode == (0 if side == "base" else 1), (result.stdout, result.stderr)
    receipt = json.loads((directory / "check-receipt.json").read_text(encoding="utf-8"))
    reviewed = run_python(python, "-m", "checkwash", "check", receipt["base"] + "..." + receipt["head"],
                          "--repo", repo, "--format", "json", cwd=directory, env=clean)
    matching = next(item for item in json.loads(reviewed.stdout)["findings"] if item["rule"] == "ASSERT_REMOVED")
    assert matching["fingerprint"] == finding["fingerprint"]
    assert matching["allowlisted"] is (side == "base")


def test_clean_environment_is_carried_to_build_children(tmp_path):
    env = {**os.environ, "PATH": str(tmp_path), "PIP_FIND_LINKS": str(tmp_path),
           "PIP_CONFIG_FILE": str(tmp_path / "pip.ini"), "PIP_CONSTRAINT": "evil",
           "PYTHONPATH": str(tmp_path), "PYTHONHOME": str(tmp_path),
           "PYTHONUSERBASE": str(tmp_path), "GH_TOKEN": "test-token", "GITHUB_TOKEN": "test-token",
           "ACTIONS_RUNTIME_TOKEN": "test-token",
           "BASH_ENV": str(tmp_path / "startup.sh"), "GIT_CONFIG_COUNT": "1"}
    clean = secure.child_environment(env, tmp_path)
    assert clean["PIP_CONFIG_FILE"] == os.devnull
    assert not any(key.startswith("PYTHON") for key in clean)
    assert {key for key in clean if key.startswith("PIP_")} == {"PIP_CONFIG_FILE"}
    assert not {"GH_TOKEN", "GITHUB_TOKEN", "ACTIONS_RUNTIME_TOKEN", "BASH_ENV", "GIT_CONFIG_COUNT"} & clean.keys()
    assert str(tmp_path) not in clean["PATH"].split(os.pathsep)


def qualification_module():
    specification = importlib.util.spec_from_file_location(
        "action_qualification", ROOT / "tools/action_security_qualification.py")
    assert specification and specification.loader
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


@pytest.fixture
def qualification_evidence(tmp_path, monkeypatch):
    qualifier = qualification_module()
    monkeypatch.setenv("CANDIDATE_SHA", "a" * 40)
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    for case, (exit_code, analysis_code) in qualifier.CASES.items():
        for system in qualifier.SYSTEMS:
            directory = tmp_path / (case + "-" + system)
            directory.mkdir()
            metadata = {"case": case, "system": system, "candidate_sha": "a" * 40,
                        "run_id": "123", "attempt": "1", "canary_executed": False,
                        "untrusted_install_created": False, "receipts": ["check-receipt.json"],
                        "step_outcome": "success" if exit_code == 0 else "failure",
                        "source_root": "/trusted/source", "source_digest": "d" * 64,
                        "source_version": "0.7.0", "trusted_python": "/trusted/python",
                        "expected_base": "b" * 40, "expected_head": "c" * 40}
            identity = {"isolated": True, "utf8": True, "bytecode_writes_disabled": True,
                        "source_root": metadata["source_root"], "source_digest": metadata["source_digest"],
                        "version": metadata["source_version"], "base_python": metadata["trusted_python"]}
            receipt = {"exit_code": exit_code, "analysis_exit_code": analysis_code, "identity": identity,
                       "error": "missing ref" if analysis_code == "unavailable" else None}
            if analysis_code != "unavailable":
                receipt.update(base=metadata["expected_base"], head=metadata["expected_head"])
            for name, data in (("case.json", metadata), ("check-receipt.json", receipt),
                               ("install-report.json", {"pip_version": "22.3.1", "install": [{}]})):
                (directory / name).write_text(json.dumps(data), encoding="utf-8")
            (directory / "stdout.txt").write_text("ASSERT_REMOVED" if analysis_code == 1 else "", encoding="utf-8")
    return qualifier, tmp_path


def test_qualification_accepts_complete_original_outcomes(qualification_evidence):
    qualifier, directory = qualification_evidence
    qualifier.validate(directory)


@pytest.mark.parametrize("damage", ["missing-case", "duplicate-case", "candidate", "run", "attempt",
                                    "source", "interpreter", "base", "head", "step", "exit", "canary", "no-receipt"])
def test_qualification_rejects_missing_or_misbound_evidence(qualification_evidence, damage):
    qualifier, directory = qualification_evidence
    case = directory / "clean-block-ubuntu-latest"
    metadata_path = case / "case.json"
    receipt_path = case / "check-receipt.json"
    metadata = json.loads(metadata_path.read_text())
    receipt = json.loads(receipt_path.read_text())
    if damage == "missing-case":
        metadata_path.unlink()
    elif damage == "duplicate-case":
        shutil.copytree(case, directory / "duplicate")
    else:
        if damage == "candidate":
            metadata["candidate_sha"] = "0" * 40
        elif damage == "run":
            metadata["run_id"] = "456"
        elif damage == "attempt":
            metadata["attempt"] = "2"
        elif damage == "source":
            receipt["identity"]["source_digest"] = "0" * 64
        elif damage == "interpreter":
            receipt["identity"]["base_python"] = "/subject/python"
        elif damage in {"base", "head"}:
            receipt[damage] = "0" * 40
        elif damage == "step":
            metadata["step_outcome"] = "success"
        elif damage == "exit":
            receipt["analysis_exit_code"] = 0
        elif damage == "canary":
            metadata["canary_executed"] = True
        else:
            metadata["receipts"] = []
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ValueError):
        qualifier.validate(directory)


@pytest.mark.parametrize("damage", ["source", "extra", "missing", "metadata", "cache", "loose-pyc"])
def test_identity_rejects_tampering_before_import(runtime, damage):
    python, site, repo, directory, env = runtime
    marker = directory / "IMPORTED_UNVERIFIED_PACKAGE"
    package = site / "checkwash"
    if damage == "source":
        (package / "__init__.py").write_text(
            "from pathlib import Path\nPath(" + repr(str(marker)) + ").write_text('bad')\n", encoding="utf-8")
    elif damage == "extra":
        (package / "injected.py").write_text("raise RuntimeError('injected')\n", encoding="utf-8")
    elif damage == "missing":
        (package / "cli.py").unlink()
    elif damage == "metadata":
        next(site.glob("checkwash-*.dist-info/METADATA")).write_text(
            "Metadata-Version: 2.1\nName: checkwash\nVersion: 99.0.0\n", encoding="utf-8")
    elif damage == "cache":
        (package / "__pycache__").mkdir()
        (package / "__pycache__/__init__.cpython-312.pyc").write_bytes(b"cached payload")
    else:
        (package / "injected.pyc").write_bytes(b"cached payload")
    result = run_python(python, DRIVER, "identity", cwd=repo, env=env)
    assert result.returncode == 2, result.stdout
    assert not marker.exists()


def test_missing_ref_is_error_not_pass(runtime):
    python, _site, repo, directory, env = runtime
    subject_history(repo)
    env["CHECKWASH_BASE"] = "f" * 40
    result = run_python(python, DRIVER, "check", cwd=repo, env=env)
    assert result.returncode == 2
    receipt = json.loads((directory / "check-receipt.json").read_text(encoding="utf-8"))
    assert receipt["analysis_exit_code"] == "unavailable" and receipt["error"]


def test_summary_failure_does_not_swallow_block(runtime):
    python, _site, repo, directory, env = runtime
    subject_history(repo)
    env["GITHUB_STEP_SUMMARY"] = str(directory)  # Opening a directory must fail.
    result = run_python(python, DRIVER, "check", cwd=repo, env=env)
    assert result.returncode == 2
    receipt = json.loads((directory / "check-receipt.json").read_text(encoding="utf-8"))
    assert receipt["analysis_exit_code"] == 1 and receipt["exit_code"] == 2


def test_output_newlines_cannot_add_workflow_outputs(tmp_path):
    output = tmp_path / "output"
    with pytest.raises(ValueError):
        secure.output_values(str(output), {"path": "valid\nexit_code=0"})
    assert not output.exists()


def test_identity_does_not_silently_skip_unreadable_subdirectory(tmp_path, monkeypatch):
    package = tmp_path / "checkwash"
    package.mkdir()
    def unreadable_walk(_root, *, followlinks, onerror):
        onerror(PermissionError("fixture subdirectory cannot be read"))
    monkeypatch.setattr(secure.os, "walk", unreadable_walk)
    with pytest.raises(PermissionError):
        secure.source_manifest(package)


def test_raw_subject_log_is_inside_stop_commands(capsysbinary):
    payload = b"::error::subject text\n::add-mask::hidden\n"
    secure.safe_log(payload)
    output = capsysbinary.readouterr().out
    first, remainder = output.split(b"\n", 1)
    assert first.startswith(b"::stop-commands::checkwash-")
    token = first.removeprefix(b"::stop-commands::")
    assert remainder == payload + b"::" + token + b"::\n"


def test_comment_keeps_tokens_out_of_engine_and_requires_explicit_token(runtime, monkeypatch):
    python, _site, repo, directory, env = runtime
    env.pop("GH_TOKEN", None)
    result = run_python(python, DRIVER, "comment", cwd=repo, env=env)
    assert result.returncode == 0 and b"comment-pr skipped" in result.stdout

    # The real comment path is exercised with owned data and process boundaries
    # mocked below; no second environment, engine, network or review is started.
    dummy = "owned-comment-test-token"
    env.update(GH_TOKEN=dummy, GITHUB_TOKEN="not-for-helper",
               ACTIONS_RUNTIME_TOKEN="not-for-helper", GH_REPO="owner/repo", PR_NUMBER="7")
    (directory / "check-receipt.json").write_text(json.dumps({
        "analysis_exit_code": 0, "error": None, "base": "a" * 40,
        "head": "b" * 40, "fail_on": "high",
    }), encoding="utf-8")
    monkeypatch.setattr(secure, "runtime_directory", lambda _env: directory)
    monkeypatch.setattr(secure, "identity", lambda: {})
    calls = []

    def fake_run(argv, **kwargs):
        # comment adds the helper token after the engine call. Snapshot the
        # environment at each call, rather than retaining that mutable dict.
        calls.append((list(argv), dict(kwargs["env"]), kwargs["cwd"]))
        return subprocess.CompletedProcess(argv, 0, b'{"findings":[]}', b"")

    monkeypatch.setattr(secure.subprocess, "run", fake_run)
    assert secure.comment(env) == 0
    assert len(calls) == 2
    engine, helper = calls
    assert engine[0] == [secure.sys.executable, "-I", "-B", "-X", "utf8", "-m", "checkwash", "check",
                         "a" * 40 + "..." + "b" * 40, "--repo", str(repo.resolve()),
                         "--fail-on", "high", "--format", "json"]
    assert not any(key.upper().endswith("_TOKEN") for key in engine[1])
    assert helper[0] == [secure.sys.executable, "-I", "-B", "-X", "utf8",
                         str(secure.ROOT / "action/post_review.py"), str(directory / "findings.json")]
    assert {key: value for key, value in helper[1].items()
            if key.upper().endswith("_TOKEN")} == {"GH_TOKEN": dummy}
    assert helper[1]["GH_REPO"] == "owner/repo" and helper[1]["PR_NUMBER"] == "7"
    assert engine[2] == helper[2] == directory


def bootstrap_script():
    action = (ROOT / "action/action.yml").read_text(encoding="utf-8")
    block = action.split("      run: |\n", 1)[1].split("    - id: check\n", 1)[0]
    return "\n".join(line.removeprefix("        ") for line in block.splitlines())


def run_bootstrap(bash, directory, *, cwd, env):
    # Actions invokes a temporary script file. Passing the whole shell source
    # through `-c` adds a Windows command-line quoting boundary absent there.
    script = directory / "bootstrap.sh"
    script.write_text(bootstrap_script() + "\n", encoding="utf-8", newline="\n")
    return subprocess.run([bash, "--noprofile", "--norc", "-e", "-o", "pipefail", script.as_posix()],
                          cwd=cwd, env=env, capture_output=True, timeout=30)


def test_bootstrap_does_not_fall_back_to_ambient_python(tmp_path):
    bash = shutil.which("bash")
    assert bash, "supported Action runners must provide Bash"
    subject = tmp_path / "subject"
    subject.mkdir()
    marker = tmp_path / "AMBIENT_PYTHON"
    fake = subject / "python"
    fake.write_text("#!/bin/sh\nprintf bad > '" + marker.as_posix() + "'\n", encoding="utf-8")
    fake.chmod(0o755)
    env = {**os.environ, "PATH": str(subject) + os.pathsep + os.environ.get("PATH", ""),
           "CW_REQUESTED_PYTHON": "", "CW_PYTHON_LOCATION": "", "GITHUB_WORKSPACE": str(subject),
           "CW_ACTION_PATH": str(ROOT / "action"), "RUNNER_OS": "Windows" if os.name == "nt" else "Linux"}
    result = run_bootstrap(bash, tmp_path, cwd=subject, env=env)
    assert result.returncode == 2 and not marker.exists(), result.stderr


@pytest.mark.parametrize("explicit", [False, True])
def test_bootstrap_uses_trusted_interpreter_with_spaces_and_unicode(tmp_path, explicit):
    bash = shutil.which("bash")
    assert bash
    subject = tmp_path / "subject 稽核"
    subject.mkdir()
    action = tmp_path / "trusted action 中文"
    action.mkdir()
    marker = tmp_path / "bootstrap.json"
    (action / "secure.py").write_text(
        "import json, pathlib, sys\npathlib.Path(" + repr(str(marker)) + ").write_text("
        "json.dumps([sys.executable, sys.flags.isolated, sys.flags.utf8_mode, sys.argv[1:]]))\n",
        encoding="utf-8")
    python = Path(sys.executable).absolute()
    location = python.parent if os.name == "nt" else python.parent.parent
    env = {**os.environ, "CW_REQUESTED_PYTHON": str(python) if explicit else "",
           "CW_PYTHON_LOCATION": str(location), "GITHUB_WORKSPACE": str(subject),
           "CW_ACTION_PATH": str(action), "RUNNER_OS": "Windows" if os.name == "nt" else "Linux",
           "PYTHONPATH": str(subject), "PYTHONUTF8": "0"}
    result = run_bootstrap(bash, tmp_path, cwd=subject, env=env)
    assert result.returncode == 0, result.stderr
    executable, isolated, utf8, args = json.loads(marker.read_text())
    assert Path(executable).resolve() == python.resolve()
    assert isolated == 1 and utf8 == 1 and args == ["install"]
