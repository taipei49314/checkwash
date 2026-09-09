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
