"""A receipt must fail on escapes, false positives, and same-version stale builds."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import venv
import zipapp
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("qualify_assertions", ROOT / "tools/qualify_assertions.py")
QUALIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(QUALIFY)


CASES = [
    {"id": "loss", "path": "test_owned.js", "before": "EXACT\n", "after": "LOSS\n",
     "verdict": "block", "rule": "ASSERT_WEAKENED", "severity": "high", "kind": "weakening"},
    {"id": "control", "path": "test_owned.js", "before": "EXACT\n", "after": "EXACT // comment\n",
     "verdict": "pass", "rule": None, "severity": None, "kind": "preserving"},
]


def fake_source(tmp_path, *, detect=True, preserve=True, severity="high", block_exit=1):
    """An owned process-level fault injector; never imports the real detector."""
    source = tmp_path / "source"
    package = source / "src/checkwash"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('__version__ = "0.4.0"\n', encoding="utf-8")
    (package / "cli.py").write_text(f'''
import json
from pathlib import Path
import subprocess
import sys

def main():
    if sys.argv[1:] == ["--version"]:
        print("checkwash 0.4.0")
        return 0
    selected = sys.argv[2]
    if selected.startswith("MISSING_"):
        print("checkwash engine error: unknown ref", file=sys.stderr)
        return 2
    # Reading both commits ensures fixtures really exist in git history.
    if selected != "HEAD..HEAD":
        before = subprocess.check_output(["git", "show", "HEAD~1:test_owned.js"], text=True)
        after = subprocess.check_output(["git", "show", "HEAD:test_owned.js"], text=True)
        assert before == "EXACT\\n"
        assert after == Path("test_owned.js").read_text()
    else:
        after = ""
    block = ({detect!r} and after == "LOSS\\n") or (not {preserve!r} and "comment" in after)
    findings = [{{"rule": "ASSERT_WEAKENED", "severity": {severity!r}, "path": "test_owned.js"}}] if block else []
    print(json.dumps({{"verdict": "block" if block else "pass", "findings": findings,
        "run": {{"checkwash_version": "0.4.0"}}, "config_errors": [], "skipped_files": []}}))
    return {block_exit!r} if block else 0

def entry():
    raise SystemExit(main())
''', encoding="utf-8")
    (source / "pyproject.toml").write_text('[project]\nname="checkwash"\nversion="0.4.0"\n', encoding="utf-8")
    QUALIFY.git(source, "init", "-b", "main")
    QUALIFY.git(source, "add", ".")
    QUALIFY.git(source, "commit", "-m", "owned test engine")
    return source


def qualify_fake(tmp_path, **fault):
    source = fake_source(tmp_path, **fault)
    artifact = tmp_path / "checkwash.pyz"
    zipapp.create_archive(source / "src", artifact, main="checkwash.cli:entry")
    return QUALIFY.qualify(source=source, distribution="pyz", artifact=artifact,
                           command=[sys.executable], cases=CASES)


def test_real_commits_and_repeat_receipts_are_deterministic(tmp_path):
    first = qualify_fake(tmp_path)
    source = tmp_path / "source"
    second = QUALIFY.qualify(source=source, distribution="pyz", artifact=tmp_path / "checkwash.pyz",
                             command=[sys.executable], cases=CASES)
    assert first == second
    assert first["status"] == "passed"
    assert first["summary"] == {"total": 2, "executed": 2, "failed": 0}
    assert first["source_commit"] == QUALIFY.git(source, "rev-parse", "HEAD")
    assert len(first["artifact_sha256"]) == len(first["source_package_sha256"]) == 64


@pytest.mark.parametrize("fault,case_id,error", [
    ({"detect": False}, "loss", "missing ASSERT_WEAKENED/high"),
    ({"preserve": False}, "control", "preserving control produced findings"),
    ({"severity": "warn"}, "loss", "missing ASSERT_WEAKENED/high"),
    ({"block_exit": 0}, "loss", "exit 0; expected 1"),
])
def test_fault_injection_cannot_produce_passing_receipts(tmp_path, fault, case_id, error):
    receipt = qualify_fake(tmp_path, **fault)
    assert receipt["status"] == "failed"
    observation = next(row for row in receipt["cases"] if row["id"] == case_id)
    assert any(error in message for message in observation["errors"])


def test_same_version_stale_artifact_is_rejected_before_running(tmp_path):
    source = fake_source(tmp_path)
    artifact = tmp_path / "checkwash.pyz"
    zipapp.create_archive(source / "src", artifact, main="checkwash.cli:entry")
    with (source / "src/checkwash/cli.py").open("a", encoding="utf-8") as stream:
        stream.write("\n# Candidate source differs, version deliberately does not.\n")
    receipt = QUALIFY.qualify(source=source, distribution="pyz", artifact=artifact,
                             command=[sys.executable], cases=CASES)
    assert receipt["status"] == "failed"
    assert receipt["summary"]["executed"] == 0
    assert receipt["source_package_dirty"] is True
    assert any("artifact does not match source package" in error for error in receipt["errors"])
    output = tmp_path / "receipt.json"
    result = subprocess.run([
        sys.executable, str(ROOT / "tools/qualify_assertions.py"),
        "--source-root", str(source), "--distribution", "pyz", "--artifact", str(artifact),
        "--output", str(output),
    ], capture_output=True, text=True)
    assert result.returncode == 1, result.stdout + result.stderr
    assert json.loads(output.read_text())["status"] == "failed"


def test_matching_wheel_cannot_mask_a_different_installed_package(tmp_path):
    source = fake_source(tmp_path)
    artifact = tmp_path / "owned.whl"
    with zipfile.ZipFile(artifact, "w") as archive:
        for path in (source / "src").rglob("*.py"):
            archive.write(path, path.relative_to(source / "src").as_posix())
    runtime = tmp_path / "runtime"
    venv.EnvBuilder(with_pip=False).create(runtime)
    python = runtime / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    result = subprocess.run([str(python), "-I", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
                            capture_output=True, text=True, check=True)
    package = Path(result.stdout.strip()) / "checkwash"
    package.mkdir()
    (package / "__init__.py").write_text('__version__ = "0.4.0"\n', encoding="utf-8")
    (package / "cli.py").write_text("# stale runtime with the same advertised version\n", encoding="utf-8")
    receipt = QUALIFY.qualify(source=source, distribution="wheel", artifact=artifact,
                             command=[str(python), "-I", "-m", "checkwash"], cases=CASES)
    assert receipt["status"] == "failed"
    assert any("loaded wheel does not match source package" in error for error in receipt["errors"])


def test_venv_interpreter_path_is_not_dereferenced(tmp_path, monkeypatch):
    """Resolving a POSIX venv symlink silently switches to the base interpreter."""
    source = fake_source(tmp_path)
    artifact = tmp_path / "owned.whl"
    expected = QUALIFY.package_files(source / "src/checkwash")
    with zipfile.ZipFile(artifact, "w") as archive:
        for path in (source / "src").rglob("*.py"):
            archive.write(path, path.relative_to(source / "src").as_posix())
    runtime = tmp_path / "runtime"
    executable = runtime / "bin/python"
    executable.parent.mkdir(parents=True)
    executable.touch()
    package = runtime / "lib/checkwash"
    package.mkdir(parents=True)
    for path in (source / "src/checkwash").glob("*.py"):
        (package / path.name).write_bytes(path.read_bytes())
    captured = []
    original_resolve = Path.resolve

    def resolve(path, *args, **kwargs):
        if path == executable:
            return Path(sys.executable).absolute()
        return original_resolve(path, *args, **kwargs)

    def probe(command, cwd):
        captured.append(command)
        assert command[0] == str(executable.absolute())
        return subprocess.CompletedProcess(command, 0, json.dumps({
            "package": str(package / "__init__.py"), "prefix": str(runtime), "base": str(tmp_path / "base"),
        }), "")

    monkeypatch.setattr(Path, "resolve", resolve)
    monkeypatch.setattr(QUALIFY, "run", probe)
    actual = QUALIFY.invocation("wheel", source, artifact, [str(executable)], expected, tmp_path)
    assert captured and actual[0] == os.path.abspath(executable)


def test_pythonpath_cannot_replace_the_selected_distribution(tmp_path, monkeypatch):
    poison = tmp_path / "poison"
    (poison / "checkwash").mkdir(parents=True)
    (poison / "checkwash/__init__.py").write_text("raise RuntimeError('PYTHONPATH poison')\n", encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(poison))
    receipt = qualify_fake(tmp_path)
    assert receipt["status"] == "passed", receipt


@pytest.mark.parametrize("payload", [
    [], {"verdict": "pass", "findings": {}},
    {"verdict": "pass", "findings": [], "config_errors": ["bad config"], "skipped_files": []},
    {"verdict": "pass", "findings": [], "config_errors": [], "skipped_files": ["test_owned.js"]},
])
def test_incomplete_reports_are_not_preserving_success(payload):
    result = subprocess.CompletedProcess([], 0, json.dumps(payload), "")
    assert QUALIFY.observe(result, CASES[1])["status"] == "failed"


@pytest.mark.parametrize("extra", [
    {"rule": "ASSERT_REMOVED", "severity": "critical", "path": "wrong.test.js"},
    {"rule": "ASSERT_WEAKENED", "severity": "high", "path": "test_owned.js"},
])
def test_extra_or_duplicate_findings_cannot_hide_behind_expected_block(extra):
    payload = {"verdict": "block", "config_errors": [], "skipped_files": [], "findings": [
        {"rule": "ASSERT_WEAKENED", "severity": "high", "path": "test_owned.js"}, extra,
    ]}
    result = subprocess.CompletedProcess([], 1, json.dumps(payload), "")
    observation = QUALIFY.observe(result, CASES[0])
    assert observation["status"] == "failed"
    assert "blocking case produced extra or duplicate findings" in observation["errors"]


def test_actual_source_and_zipapp_use_the_same_contract_cases(tmp_path):
    contract_spec = importlib.util.spec_from_file_location("assertion_contract", ROOT / "tools/assertion_contract.py")
    contract = importlib.util.module_from_spec(contract_spec)
    contract_spec.loader.exec_module(contract)
    all_cases = contract.mutation_cases()
    # Smoke one Node loss and one passing control; hosted qualification runs all.
    cases = [next(row for row in all_cases if row["verdict"] == verdict and "node" in row["id"])
             for verdict in ("block", "pass")]
    source = QUALIFY.qualify(source=ROOT, distribution="source", command=[sys.executable], cases=cases)
    artifact = tmp_path / "checkwash.pyz"
    zipapp.create_archive(ROOT / "src", artifact, main="checkwash.zipapp_entry:run", compressed=True)
    pyz = QUALIFY.qualify(source=ROOT, distribution="pyz", artifact=artifact,
                         command=[sys.executable], cases=cases)
    assert source["status"] == pyz["status"] == "passed", (source, pyz)
    assert source["cases"] == pyz["cases"]
