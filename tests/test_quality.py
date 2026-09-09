"""Behavioral quality tests use closed byte snapshots and no target execution."""
import copy
import datetime
import json

import pytest

from checkwash.quality.engine import analyze
from checkwash.quality.model import POLICY_PATH, ALLOW_PATH, digest
from checkwash.quality.policy import load_policy
from checkwash.quality.report import json_report, sarif
from checkwash.quality.snapshot import MappingSnapshot

TODAY = datetime.date(2026, 9, 9)


def profile(tool):
    row = {"id": tool + "-fixture", "tool": tool, "tool_version": "fixture",
           "rule_catalog": ["F401", "F821", "E711"], "default_rules": ["F401", "F821"],
           "default_excludes": ["build", "dist"], "preview_rules": []}
    row["digest"] = digest(row)
    return {row["id"]: row}


def policy(tool="coverage", mode="report", config="pyproject.toml"):
    return f'''schema_version = 1
mode = "{mode}"
[[targets]]
id = "main"
tool = "{tool}"
root = "."
config = "{config}"
profile = "{tool}-fixture"
paths = ["src/"]
'''.encode()


def scan(before, after, tool="coverage", mode="enforce", base_extra=None, head_extra=None):
    left = {POLICY_PATH: policy(tool, mode), "pyproject.toml": before.encode(), "src/code.py": b"x = 1\n"}
    right = {**left, "pyproject.toml": after.encode()}
    left.update(base_extra or {})
    right.update(head_extra or {})
    return analyze(MappingSnapshot(left), MappingSnapshot(right), today=TODAY, profiles=profile(tool))


def strong(payload):
    return [f for f in payload["findings"] if f["severity"] == "high"]


@pytest.mark.parametrize("before,after", [(n, n - 1) for n in range(1, 21)])
def test_coverage_integer_threshold_losses(before, after):
    p, code = scan(f"[tool.coverage.report]\nfail_under={before}", f"[tool.coverage.report]\nfail_under={after}")
    assert code == 1
    assert [f["rule"] for f in strong(p)] == ["QW_THRESHOLD_LOWERED"]


@pytest.mark.parametrize("before,after", [(n, n + 1) for n in range(20)])
def test_coverage_strengthening_never_creates_loss(before, after):
    p, code = scan(f"[tool.coverage.report]\nfail_under={before}", f"[tool.coverage.report]\nfail_under={after}")
    assert code == 0 and not strong(p)


@pytest.mark.parametrize("after", ["85.0", "85 # comment", "85\nprecision=0"])
def test_threshold_equivalent_spelling(after):
    p, code = scan("[tool.coverage.report]\nfail_under=85", "[tool.coverage.report]\nfail_under=" + after)
    assert code == 0 and not strong(p)


def test_deleted_threshold_uses_known_default():
    p, code = scan("[tool.coverage.report]\nfail_under=85", "[tool.coverage.report]\n")
    assert code == 1 and strong(p)[0]["after"]["data"] == "0"


@pytest.mark.parametrize("change", ["precision=2", "exclude_also=['.*']", "fail_under='${LIMIT}'"])
def test_unknown_context_never_passes_enforce(change):
    p, code = scan("[tool.coverage.report]\nfail_under=85", "[tool.coverage.report]\n" + change)
    assert code == 2
    assert p["verdict"] == "incomplete"


def test_scope_witness_uses_surviving_files_only():
    p, code = scan("[tool.coverage.report]\n", "[tool.coverage.report]\nomit=['src/code.py']")
    assert code == 1
    f = strong(p)[0]
    assert f["rule"] == "QW_SCOPE_NARROWED" and f["witnesses"]["paths"] == ["src/code.py"]


def test_report_high_is_visible_without_blocking():
    p, code = scan("[tool.coverage.report]\nfail_under=85", "[tool.coverage.report]\nfail_under=50", mode="report")
    assert code == 0 and p["verdict"] == "reported" and strong(p)


@pytest.mark.parametrize("code", ["F401", "F821", "E711"])
def test_ruff_lost_selected_rules(code):
    before = f'[tool.ruff.lint]\nselect=["{code}"]'
    p, status = scan(before, before + f'\nignore=["{code}"]', "ruff")
    assert status == 1 and strong(p)[0]["lost"] == [code]


def test_ruff_ignore_inactive_rule_does_not_remove_requirement():
    p, code = scan('[tool.ruff.lint]\nselect=["F401"]', '[tool.ruff.lint]\nselect=["F401"]\nignore=["E711"]', "ruff")
    assert code == 0 and not strong(p)


def test_ruff_specific_select_overrides_broad_ignore():
    p, code = scan('[tool.ruff.lint]\nselect=["F401"]', '[tool.ruff.lint]\nselect=["F401"]\nignore=["F"]', "ruff")
    assert code == 0 and not strong(p)


def test_ruff_gains_do_not_cancel_losses():
    p, code = scan('[tool.ruff.lint]\nselect=["F401"]', '[tool.ruff.lint]\nselect=["F821"]', "ruff")
    assert code == 1 and strong(p)[0]["lost"] == ["F401"] and strong(p)[0]["gained"] == ["F821"]


@pytest.mark.parametrize("setting", ['preview=true', 'lint.per-file-ignores={"src/code.py"=["F401"]}', 'lint.ignore=["UNKNOWN123"]'])
def test_ruff_unsupported_context_is_incomplete(setting):
    p, code = scan('[tool.ruff]\n', '[tool.ruff]\n' + setting, "ruff")
    assert code == 2 and p["verdict"] == "incomplete"


@pytest.mark.parametrize("flag", ["disallow_untyped_defs", "check_untyped_defs", "disallow_incomplete_defs", "warn_return_any", "strict_optional"])
def test_mypy_required_flag_loss(flag):
    p, code = scan(f'[tool.mypy]\n{flag}=true', f'[tool.mypy]\n{flag}=false', "mypy")
    assert code == 1 and strong(p)[0]["dimension"] == "mypy." + flag


@pytest.mark.parametrize("flag", ["ignore_errors", "ignore_missing_imports"])
def test_mypy_suppression_direction(flag):
    p, code = scan(f'[tool.mypy]\n{flag}=false', f'[tool.mypy]\n{flag}=true', "mypy")
    assert code == 1 and strong(p)


def test_mypy_error_code_enable_precedence():
    p, code = scan('[tool.mypy]\n', '[tool.mypy]\ndisable_error_code=["assignment"]\nenable_error_code=["assignment"]', "mypy")
    assert code == 0 and not strong(p)


def test_mypy_inline_context_prevents_global_claim():
    p, code = scan('[tool.mypy]\n', '[tool.mypy]\nignore_errors=true', "mypy", base_extra={"src/code.py": b"# mypy: ignore-errors\nx=1"}, head_extra={"src/code.py": b"# mypy: ignore-errors\nx=1"})
    assert code == 2 and not strong(p)


def test_head_cannot_switch_enforcement_mode():
    p, code = scan("[tool.coverage.report]\nfail_under=85", "[tool.coverage.report]\nfail_under=50", head_extra={POLICY_PATH: policy(mode="report")})
    assert code == 1 and p["run"]["mode"] == "enforce"
    assert any(f["severity"] == "critical" for f in p["findings"])


def allow_entry(fingerprint):
    return f'''[[allow]]
fingerprint="{fingerprint}"
rule="QW_THRESHOLD_LOWERED"
target_id="main"
reason="Approved synthetic threshold migration"
author="fixture-reviewer"
created="2026-09-01"
expires="2026-10-01"
'''.encode()


def test_exemption_is_bound_to_both_sides_and_base_policy():
    before, after = "[tool.coverage.report]\nfail_under=85", "[tool.coverage.report]\nfail_under=50"
    p, _ = scan(before, after)
    allowance = allow_entry(strong(p)[0]["fingerprint"])
    p, code = scan(before, after, head_extra={ALLOW_PATH: allowance})
    assert code == 1 and not strong(p)[0]["allowlisted"]
    p, code = scan(before, after, base_extra={ALLOW_PATH: allowance}, head_extra={ALLOW_PATH: allowance})
    assert code == 0 and strong(p)[0]["allowlisted"]
    p, code = scan(before, after.replace("50", "40"), base_extra={ALLOW_PATH: allowance}, head_extra={ALLOW_PATH: allowance})
    assert code == 1 and not strong(p)[0]["allowlisted"]


@pytest.mark.parametrize("setting", ['mode="oops"', 'schema_version=2', 'unknown=true'])
def test_invalid_base_policy_is_error(setting):
    data = policy().decode()
    if setting.startswith("mode"):
        data = data.replace('mode = "report"', setting)
    elif setting.startswith("schema"):
        data = data.replace("schema_version = 1", setting)
    else:
        data = setting + "\n" + data
    with pytest.raises(Exception) as caught:
        load_policy(data.encode())
    assert caught.value.code == "POLICY_INVALID"


def test_discovery_has_no_completeness_claim():
    p, code = analyze(MappingSnapshot({}), MappingSnapshot({"pyproject.toml": b"[tool.coverage.report]\nfail_under=50"}), today=TODAY)
    assert code == 0 and p["verdict"] == "incomplete" and p["run"]["discovery"]
    assert not strong(p)


def test_machine_report_is_deterministic_and_separate():
    p, _ = scan("[tool.coverage.report]\nfail_under=85", "[tool.coverage.report]\nfail_under=50")
    assert json_report(p) == json_report(copy.deepcopy(p))
    assert "checkwash_findings_version" not in p
    assert json.loads(sarif(p))["runs"][0]["tool"]["driver"]["name"] == "checkwash-quality"


def test_ruff_extend_parent_loss_is_visible_when_child_unchanged():
    config = '[tool.ruff]\nextend="parent.toml"'
    p, code = scan(config, config, "ruff",
                   base_extra={"parent.toml": b'[lint]\nselect=["F401"]'},
                   head_extra={"parent.toml": b'[lint]\nselect=[]'})
    assert code == 1 and strong(p)[0]["lost"] == ["F401"]


def test_ruff_child_reset_discards_parent_selection():
    config = '[tool.ruff]\nextend="parent.toml"\n[tool.ruff.lint]\nselect=["F821"]'
    p, code = scan(config, config, "ruff",
                   base_extra={"parent.toml": b'[lint]\nselect=["F401"]'},
                   head_extra={"parent.toml": b'[lint]\nselect=[]'})
    assert code == 0 and not strong(p)


def test_ruff_extend_cycle_is_incomplete():
    config = '[tool.ruff]\nextend="parent.toml"'
    extra = {"parent.toml": b'extend="pyproject.toml"'}
    p, code = scan(config, config, "ruff", base_extra=extra, head_extra=extra)
    assert code == 2 and any(d["code"] == "INHERITANCE_CYCLE" for d in p["diagnostics"])


def test_ruff_broad_ignore_can_remove_default_rules():
    p, code = scan('[tool.ruff.lint]', '[tool.ruff.lint]\nignore=["F"]', "ruff")
    assert code == 1 and strong(p)[0]["lost"] == ["F401", "F821"]


def test_known_strict_expansion_can_be_preserved_explicitly():
    profiles = profile("mypy")
    profiles["mypy-fixture"].update(strict_expansion={"disallow_untyped_defs": True}, mypy_defaults={"disallow_untyped_defs": False})
    left = {POLICY_PATH: policy("mypy", "enforce"), "pyproject.toml": b'[tool.mypy]\nstrict=true'}
    right = {**left, "pyproject.toml": b'[tool.mypy]\nstrict=false\ndisallow_untyped_defs=true'}
    p, code = analyze(MappingSnapshot(left), MappingSnapshot(right), today=TODAY, profiles=profiles)
    assert code == 0 and not strong(p)


def test_unknown_strict_expansion_is_not_treated_as_empty():
    p, code = scan('[tool.mypy]\nstrict=true', '[tool.mypy]\nstrict=false', "mypy")
    assert code == 2 and not strong(p)


def test_nested_ruff_override_removes_only_its_domain():
    root = '[tool.ruff.lint]\nselect=["F401"]'
    base = {POLICY_PATH: policy("ruff", "enforce", "auto"), "pyproject.toml": root.encode(),
            "src/one.py": b"import os", "src/private/two.py": b"import os"}
    head = {**base, "src/private/ruff.toml": b'[lint]\nselect=[]'}
    p, code = analyze(MappingSnapshot(base), MappingSnapshot(head), today=TODAY, profiles=profile("ruff"))
    assert code == 1
    assert [f["dimension"] for f in strong(p)] == ["ruff.lint.rules@src/private/two.py"]


def test_scope_change_without_witness_is_still_visible():
    p, code = scan("[tool.coverage.report]", "[tool.coverage.report]\nomit=['src/future/**']")
    assert code == 0 and not strong(p)
    assert any(f["event_kind"] == "scope_without_witness" for f in p["findings"])


def test_mypy_implicit_reexport_has_permissive_direction():
    profiles = profile("mypy")
    profiles["mypy-fixture"]["mypy_defaults"] = {"implicit_reexport": True}
    left = {POLICY_PATH: policy("mypy", "enforce"), "pyproject.toml": b'[tool.mypy]\nimplicit_reexport=false'}
    right = {**left, "pyproject.toml": b'[tool.mypy]\nimplicit_reexport=true'}
    p, code = analyze(MappingSnapshot(left), MappingSnapshot(right), today=TODAY, profiles=profiles)
    assert code == 1 and strong(p)[0]["dimension"] == "mypy.implicit_reexport"


def test_snapshot_failure_before_policy_never_becomes_report_pass(monkeypatch):
    from argparse import Namespace
    from checkwash.quality import cli
    from checkwash.quality.model import QualityError
    def fail(*args):
        raise QualityError("RESOURCE_LIMIT", "Fixture inventory limit")
    monkeypatch.setattr(cli, "Snapshot", fail)
    text, code = cli.run(Namespace(range=None, rule=None, repo=".", format="json"), TODAY)
    assert code == 2 and json.loads(text)["verdict"] == "error"


def test_real_worktree_cli_preserves_uncommitted_quality_change(tmp_path, monkeypatch):
    import subprocess
    from argparse import Namespace
    from checkwash.quality import cli, engine
    monkeypatch.setattr(engine, "load_profile", lambda name, tool: profile(tool)[name])
    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)
    git("init")
    git("config", "user.name", "quality-fixture")
    git("config", "user.email", "quality@example.invalid")
    (tmp_path / ".checkwash").mkdir()
    (tmp_path / POLICY_PATH).write_bytes(policy(mode="enforce"))
    config = tmp_path / "pyproject.toml"
    config.write_bytes(b"[tool.coverage.report]\nfail_under=85\n")
    git("add", ".")
    git("commit", "-m", "base")
    config.write_bytes(b"[tool.coverage.report]\nfail_under=50\n")
    text, code = cli.run(Namespace(range=None, rule=None, repo=str(tmp_path), format="json"), TODAY)
    report = json.loads(text)
    assert code == 1 and strong(report)[0]["before"]["data"] == "85"
    assert config.read_bytes().endswith(b"fail_under=50\n")
