"""Restricted TASK syntax is visible without changing the parsed contract."""
from dataclasses import asdict
import json
import subprocess

import pytest

import checkwash.contract as contract_module
from checkwash.cli import main

CANONICAL = "---\ncheckwash:\n  oracle_freeze: true\n  scope:\n    allow:\n      - tests/**\n---\n"
BAD = (
    ("bom", "\ufeff" + CANONICAL, False, [], False),
    ("comment", CANONICAL.replace("true", "true # freeze"), True, ["tests/**"], False),
    ("quoted", CANONICAL.replace("true", '"true"'), True, ["tests/**"], False),
    ("flow", CANONICAL.replace("    allow:\n      - tests/**", "    allow: [tests/**]"), True, [], True),
    ("unclosed", CANONICAL.rsplit("---", 1)[0], False, [], False),
    ("block-comment", CANONICAL.replace("checkwash:", "checkwash: # policy"), True, [], False),
)


@pytest.mark.parametrize("name,text,present,scope,freeze", BAD)
def test_unsupported_syntax_has_nonmutating_diagnostics(name, text, present, scope, freeze):
    before = asdict(contract_module.parse_contract(text))
    diagnostic = getattr(contract_module, "contract_diagnostics", lambda value: [])
    messages = diagnostic(text)
    assert messages, name
    assert all("TASK syntax" in message and "\n" not in message and "\x1b" not in message for message in messages)
    assert asdict(contract_module.parse_contract(text)) == before
    assert (before["present"], before["scope_allow"], before["oracle_freeze"]) == (present, scope, freeze)


@pytest.mark.parametrize("text", (None, "", "Plain task instructions", CANONICAL,
                                  CANONICAL.replace("checkwash:", "greenwash:"),
                                  CANONICAL.replace("true", "FALSE").replace("\n", "\r\n")))
def test_supported_or_absent_metadata_has_no_syntax_warning(text):
    diagnostic = getattr(contract_module, "contract_diagnostics", lambda value: [])
    assert diagnostic(text) == []


@pytest.mark.parametrize("format", ("term", "json", "sarif", "hook-json"))
def test_cli_task_diagnostic_keeps_existing_exit_and_payload(tmp_path, capsys, format):
    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)
    git("init")
    git("config", "user.name", "TASK syntax fixture")
    git("config", "user.email", "fixture@example.invalid")
    (tmp_path / "test_api.py").write_text("def test_api():\n    assert api() == 1\n", encoding="utf-8")
    (tmp_path / "TASK.md").write_text(CANONICAL.replace("true", "true # frozen"), encoding="utf-8")
    git("add", ".")
    git("-c", "commit.gpgsign=false", "commit", "-m", "trusted baseline")
    (tmp_path / "test_api.py").write_text("def test_api():\n    assert api() > 0\n", encoding="utf-8")
    assert main(["check", "--repo", str(tmp_path), "--task", str(tmp_path / "TASK.md"), "--format", format]) == (0 if format == "hook-json" else 1)
    output = capsys.readouterr()
    assert "TASK syntax" in output.err
    assert "BASE" in output.err and "TASK.md" in output.err
    if format == "json":
        payload = json.loads(output.out)
        assert payload["checkwash_findings_version"] == 2 and payload["verdict"] == "block"
        assert payload["config_errors"] == []
        assert any(f["rule"] == "ASSERT_WEAKENED" and "ORACLE_FREEZE" not in f["escalators"] for f in payload["findings"])
    elif format == "sarif":
        assert json.loads(output.out)["version"] == "2.1.0"
    elif format == "hook-json":
        assert json.loads(output.out)["decision"] == "block"
