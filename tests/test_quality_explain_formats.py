"""Rule help honors its selected format without becoming a review result."""
import datetime
import json
from types import SimpleNamespace

import pytest

from checkwash.cli import main
from checkwash.quality.cli import run
from checkwash.quality.model import RULES

TODAY = datetime.date(2026, 10, 26)


@pytest.mark.parametrize("rule", RULES)
@pytest.mark.parametrize("format", ["term", "json", "sarif"])
def test_explain_formats_describe_the_same_rule_without_analysis(rule, format, monkeypatch):
    def no_repository(*args, **kwargs):
        pytest.fail("Rule explanation must not inspect a repository")

    monkeypatch.setattr("checkwash.quality.cli.Snapshot", no_repository)
    args = SimpleNamespace(range="explain", rule=rule, format=format, repo="missing-repository",
                           root=None, paths=None, tool=None, details=False)
    text, code = run(args, TODAY)
    assert code == 0
    if format == "term":
        assert text.startswith(rule + ": ")
        assert text.endswith("See docs/quality.md for the support matrix and base-only exemptions.\n")
    elif format == "json":
        result = json.loads(text)
        assert result["operation"] == "explain" and result["authority"] == "advisory_only"
        assert result["rule"] == rule and result["description"]
        assert result["documentation"] == "docs/quality.md"
        assert "verdict" not in result and "findings" not in result
    else:
        result = json.loads(text)
        assert result["version"] == "2.1.0"
        run_result = result["runs"][0]
        assert run_result["results"] == [] and "invocations" not in run_result
        descriptor = run_result["tool"]["driver"]["rules"][0]
        assert descriptor["id"] == rule and descriptor["fullDescription"]["text"]


@pytest.mark.parametrize("format", ["json", "sarif"])
def test_cli_explain_machine_output_ignores_repo_option(format, capsys, monkeypatch):
    def no_repository(*args, **kwargs):
        pytest.fail("Rule explanation must not ask Git to locate a repository")

    monkeypatch.setattr("checkwash.cli._reroot", no_repository)
    assert main(["quality", "explain", "QW_THRESHOLD_LOWERED", "--format", format,
                 "--repo", "missing-repository"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out)
