"""Ruff ignore-file diagnostics identify the unchanged qualification boundary."""

import datetime

import pytest

from checkwash.quality.engine import analyze
from checkwash.quality.model import POLICY_PATH, Target
from checkwash.quality.profiles import available
from checkwash.quality.ruff_adapter import ruff
from checkwash.quality.snapshot import MappingSnapshot


TODAY = datetime.date(2026, 10, 26)


def _profile():
    return next(row for row in available().values() if row["tool"] == "ruff")


def _files():
    return {"pyproject.toml": b'[tool.ruff.lint]\nselect=["F401"]\n',
            "src/code.py": b"x = 1\n"}


def _resolve(files, side="base"):
    profile = _profile()
    target = Target("main", "ruff", ".", "pyproject.toml", profile["id"], ["src/"])
    return ruff(MappingSnapshot(files), target, side, profile), profile


@pytest.mark.parametrize("path", [".gitignore", "nested/.ignore"])
@pytest.mark.parametrize("side", ["base", "head"])
@pytest.mark.parametrize("contents", [b"*.generated.py\n", b"# comment only\n"], ids=["pattern", "comment"])
def test_nonempty_ignore_names_input_side_profile_and_safe_next_step(path, side, contents):
    resolved, profile = _resolve({**_files(), path: contents}, side)
    code, message, dimensions = resolved.problems[0]
    assert code == "CONTEXT_UNRESOLVED" and dimensions == ["ruff.scope"]
    assert "ruff.scope" not in resolved.values
    assert resolved.values["ruff.lint.rules"] == ["F401"]
    assert repr(path) in message and repr(side) in message
    assert repr(profile["id"]) in message
    assert "discovery and matching" in message and "not qualified" in message
    assert "checkwash quality profiles --details" in message
    assert "checkwash quality explain QW_ANALYSIS_INCOMPLETE" in message
    assert "retain" in message and "request qualification" in message
    assert "remove" not in message.lower() and "delete" not in message.lower()


def test_ignore_input_uses_repr_instead_of_terminal_controls():
    path = "nested\u202e\x1b[2J/.ignore"
    resolved, _ = _resolve({**_files(), path: b"# comment\n"}, "head")
    message = resolved.problems[0][1]
    assert repr(path) in message
    assert "\u202e" not in message and "\x1b" not in message
    assert "\\u202e" in message and "\\x1b" in message


@pytest.mark.parametrize("path", [".gitignore", "nested/.ignore"])
@pytest.mark.parametrize("contents", [b"", b" \t\r\n"], ids=["empty", "whitespace"])
def test_empty_ignore_keeps_qualified_scope(path, contents):
    resolved, _ = _resolve({**_files(), path: contents})
    assert resolved.problems == []
    assert resolved.values["ruff.scope"] == ["src/code.py"]
    assert resolved.values["ruff.lint.rules"] == ["F401"]


def test_absent_ignore_does_not_create_an_incomplete_scope():
    resolved, _ = _resolve(_files())
    assert resolved.problems == []
    assert resolved.values["ruff.scope"] == ["src/code.py"]


@pytest.mark.parametrize("mode,expected_exit", [("report", 0), ("enforce", 2)])
def test_ignore_diagnostic_keeps_incomplete_exit_and_independent_rule_finding(mode, expected_exit):
    profile = _profile()
    policy = f'''schema_version=1
mode="{mode}"
[[targets]]
id="main"
tool="ruff"
root="."
config="pyproject.toml"
profile="{profile['id']}"
paths=["src/"]
'''.encode()
    before = {**_files(), POLICY_PATH: policy, ".gitignore": b"# comment only\n"}
    after = {**before, "pyproject.toml": b'[tool.ruff.lint]\nselect=[]\n'}
    payload, code = analyze(MappingSnapshot(before), MappingSnapshot(after), today=TODAY)
    assert code == expected_exit and payload["verdict"] == "incomplete"
    assert payload["analysis_status"] == "partial"
    assert payload["targets"][0]["unsupported_dimensions"] == ["ruff.scope"]
    disabled, = [finding for finding in payload["findings"] if finding["rule"] == "QW_RULE_DISABLED"]
    assert disabled["severity"] == "high" and disabled["lost"] == ["F401"]
    assert disabled["fingerprint"].startswith("QW_RULE_DISABLED/main/q1:")
    assert len([finding for finding in payload["findings"] if finding["rule"] == "QW_ANALYSIS_INCOMPLETE"]) == 2
