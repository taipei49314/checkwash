"""Onboarding never grants policy authority or executes the subject tools."""
import datetime
import json
import subprocess
from types import SimpleNamespace

import pytest

from checkwash.cli import main
from checkwash.quality.cli import run
from checkwash.quality.model import POLICY_PATH, QualityError
from checkwash.quality.policy import load_policy
from checkwash.quality.setup import draft, doctor, inferred_paths, render
from checkwash.quality.snapshot import MappingSnapshot

TODAY = datetime.date(2026, 9, 9)
CONFIG = b'[tool.coverage.report]\nfail_under=85\n[tool.ruff.lint]\nselect=["F401"]\n[tool.mypy]\ndisallow_untyped_defs=true\n'


def source():
    return {"pyproject.toml": CONFIG, "src/code.py": b"x = 1\n"}


def configured():
    files = source()
    result, code = draft(MappingSnapshot(files))
    assert code == 0
    files[POLICY_PATH] = result["policy_toml"].encode()
    return files


def codes(result):
    return {d["code"] for d in result["diagnostics"]}


def test_draft_roundtrips_three_models_without_modifying_sources():
    files = source()
    snapshot = MappingSnapshot(files)
    result, code = draft(snapshot)
    mode, targets = load_policy(result["policy_toml"].encode())
    assert code == 0 and mode == "report"
    assert [t.tool for t in targets] == ["coverage", "mypy", "ruff"]
    assert all(t.paths == ["src/"] and t.config == "auto" for t in targets)
    assert all(t["version_selection"] == "requires_review" for t in result["targets"])
    assert snapshot.files == files and POLICY_PATH not in files
    assert result["authority"] == "advisory_only" and not result["tool_versions_verified"]


def test_inference_omits_transient_directories_only_in_draft():
    files = {p: b"" for p in ["src/a.py", "src/b.pyi", "tests/a.py", "app.py", ".venv/a.py", "build/a.py", "node_modules/a.py"]}
    assert inferred_paths(MappingSnapshot(files), ".") == ["app.py", "src/", "tests/"]
    result, _ = draft(MappingSnapshot({**files, "pyproject.toml": CONFIG}), paths=["build/"])
    assert result["targets"][0]["paths"] == ["build/"]  # Explicit source ownership wins.


def test_monorepo_draft_stays_inside_requested_root():
    files = {"packages/a/pyproject.toml": CONFIG, "packages/a/src/code.py": b"", "packages/b/src/code.py": b""}
    result, code = draft(MappingSnapshot(files), root="packages/a", tools=["coverage"])
    assert code == 0 and len(result["targets"]) == 1
    assert result["targets"][0]["paths"] == ["packages/a/src/"]
    assert result["targets"][0]["selected_config"] == "packages/a/pyproject.toml"


@pytest.mark.parametrize("path", ["../src/", "/src/", "src\\a.py", "src/*.py", "src/[a].py", "outside/a.py"])
def test_invalid_or_outside_draft_paths_are_rejected(path):
    files = {"pkg/pyproject.toml": CONFIG, "pkg/src/code.py": b""}
    with pytest.raises(QualityError):
        draft(MappingSnapshot(files), root="pkg", paths=[path])


def test_unicode_paths_roundtrip_and_cannot_control_terminal():
    files = {"pyproject.toml": CONFIG, "程式/🐍\u202e.py": b""}
    result, code = draft(MappingSnapshot(files), paths=["程式/🐍\u202e.py"])
    assert code == 0
    assert load_policy(result["policy_toml"].encode())[1][0].paths == ["程式/🐍\u202e.py"]
    assert "\u202e" not in render(result, "term")


def test_existing_policy_is_never_overwritten():
    files = configured()
    snapshot = MappingSnapshot(files)
    with pytest.raises(QualityError, match="already exists"):
        draft(snapshot)
    assert snapshot.files == files


def test_explicit_missing_tool_prevents_partial_draft():
    result, code = draft(MappingSnapshot({"pyproject.toml": b"[tool.mypy]\n", "src/a.py": b""}), tools=["coverage", "mypy"])
    assert code == 2 and "policy_toml" not in result
    assert "CONTEXT_UNRESOLVED" in codes(result)


def test_no_configuration_is_not_an_invented_default_target():
    result, code = draft(MappingSnapshot({"src/a.py": b""}))
    assert code == 2 and "NO_BASE_TARGETS" in codes(result)


def test_no_sources_requires_explicit_scope():
    with pytest.raises(QualityError, match="No Python"):
        draft(MappingSnapshot({"pyproject.toml": CONFIG}))


def test_missing_packaged_model_cannot_be_guessed():
    with pytest.raises(QualityError, match="exactly one"):
        draft(MappingSnapshot(source()), profiles={})


def test_malformed_source_does_not_produce_partial_policy():
    with pytest.raises(QualityError):
        draft(MappingSnapshot({**source(), "pyproject.toml": b"[invalid"}))


def test_doctor_configured_is_advice_not_a_review_verdict():
    files = configured()
    result, code = doctor(MappingSnapshot(files), head_policy=files[POLICY_PATH], head_revision="a" * 40, today=TODAY)
    assert code == 0 and result["state"] == "configured"
    assert result["analysis_status"] == "complete" and "verdict" not in result
    assert all(t["tracked_source_files"] == 1 for t in result["targets"])
    assert not result["ci_execution_verified"] and not result["branch_protection_verified"]
    assert not result["tool_versions_verified"]


@pytest.mark.parametrize("head_policy,head_revision,expected", [(None, "a" * 40, "POLICY_NOT_IN_HEAD"), (None, None, "HEAD_UNAVAILABLE")])
def test_doctor_explains_uncommitted_or_unborn_policy(head_policy, head_revision, expected):
    result, code = doctor(MappingSnapshot(configured()), head_policy=head_policy, head_revision=head_revision, today=TODAY)
    assert code == 2 and expected in codes(result)


@pytest.mark.parametrize("extra", [b"[tool.mypy.overrides]\nignore_errors=true\n", b"[tool.coverage.run]\nplugins=['unknown']\n", b"[tool.ruff]\npreview=true\n"])
def test_doctor_keeps_unsupported_context_visible_in_report_mode(extra):
    files = configured()
    files["pyproject.toml"] += extra
    result, code = doctor(MappingSnapshot(files), head_policy=files[POLICY_PATH], head_revision="a" * 40, today=TODAY)
    assert code == 2 and result["state"] == "needs_attention"
    assert result["analysis_status"] != "complete" and result["diagnostics"]
    assert all(issue["remediation"] for issue in result["diagnostics"])


def test_doctor_rejects_empty_tracked_source_universe():
    files = configured()
    snapshot = MappingSnapshot(files)
    snapshot.tracked.remove("src/code.py")
    result, code = doctor(snapshot, head_policy=files[POLICY_PATH], head_revision="a" * 40, today=TODAY)
    assert code == 2 and "NO_TRACKED_SOURCES" in codes(result)


def test_doctor_without_policy_explains_next_command():
    result, code = doctor(MappingSnapshot(source()), today=TODAY)
    assert code == 2 and "NO_BASE_TARGETS" in codes(result)
    assert "quality init" in render(result, "term")


@pytest.mark.parametrize("command,flags", [("doctor", {"root": "."}), ("profiles", {"paths": ["src/"]}),
                                          ("HEAD..HEAD", {"tool": ["mypy"]}), (None, {"details": True}),
                                          ("init", {"details": True}), ("init", {"format": "sarif"}),
                                          ("doctor", {"rule": "extra"})])
def test_setup_flags_never_silently_change_review_behavior(command, flags):
    args = SimpleNamespace(range=command, rule=None, format="json", repo=".", root=None, paths=None, tool=None, details=False)
    for key, value in flags.items():
        setattr(args, key, value)
    text, code = run(args, TODAY)
    assert code == 2 and text.startswith("error:")


def test_profiles_details_include_receipts_and_settings(capsys):
    assert main(["quality", "profiles", "--details"]) == 0
    rows = json.loads(capsys.readouterr().out)["profiles"]
    assert len(rows) == 3
    assert all(row["supported_keys"] and row["qualification_receipt"] and row["digest"] for row in rows)


def test_setup_errors_keep_machine_contract(monkeypatch):
    import checkwash.quality.cli as cli
    def fail(*args, **kwargs):
        raise QualityError("SOURCE_INVALID", "bad source", kind="error")
    monkeypatch.setattr(cli, "Snapshot", fail)
    text, code = run(SimpleNamespace(range="doctor", rule=None, format="json", repo="."), TODAY)
    result = json.loads(text)
    assert code == 2 and result["state"] == "error"
    assert result["authority"] == "advisory_only" and codes(result) == {"SOURCE_INVALID"}


def test_cli_draft_install_commit_doctor_lifecycle(tmp_path, capsys):
    def git(*args):
        return subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)
    git("init")
    git("config", "user.name", "setup-fixture")
    git("config", "user.email", "fixture@example.invalid")
    (tmp_path / "pyproject.toml").write_bytes(CONFIG)
    (tmp_path / "src").mkdir()
    (tmp_path / "src/code.py").write_text("x = 1\n", encoding="utf-8")
    args = ["--repo", str(tmp_path), "--format", "json"]
    assert main(["quality", "init", *args]) == 0
    draft_result = json.loads(capsys.readouterr().out)
    assert not (tmp_path / POLICY_PATH).exists()
    (tmp_path / ".checkwash").mkdir()
    (tmp_path / POLICY_PATH).write_text(draft_result["policy_toml"], encoding="utf-8")
    assert main(["quality", "doctor", *args]) == 2
    assert "HEAD_UNAVAILABLE" in codes(json.loads(capsys.readouterr().out))
    git("add", ".")
    git("commit", "-m", "reviewed synthetic policy")
    assert main(["quality", "doctor", *args]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "configured"
    before = (tmp_path / POLICY_PATH).read_bytes()
    assert main(["quality", "init", *args]) == 2
    assert "POLICY_INVALID" in codes(json.loads(capsys.readouterr().out))
    assert (tmp_path / POLICY_PATH).read_bytes() == before
