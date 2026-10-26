"""Init guidance remains a valid advisory draft and gives actionable prerequisites."""
import json
import tomllib

import pytest

from checkwash.quality.model import POLICY_PATH
from checkwash.quality.policy import load_policy
from checkwash.quality.setup import draft, render
from checkwash.quality.snapshot import MappingSnapshot


def source():
    return {"pyproject.toml": b"[tool.coverage.report]\nfail_under=85\n", "src/api.py": b"value = 1\n"}


@pytest.mark.parametrize("format", ["term", "json"])
def test_init_draft_explains_save_review_install_without_writing(format):
    original = source()
    snapshot = MappingSnapshot(original)
    result, code = draft(snapshot, tools=["coverage"])
    assert code == 0
    text = render(result, format)
    if format == "json":
        payload = json.loads(text)
        assert payload["checkwash_quality_setup_version"] == 1
        assert payload["authority"] == "advisory_only" and "verdict" not in payload
        text = payload["policy_toml"]
    assert "quality-draft.toml" in text and POLICY_PATH in text and "UTF-8" in text
    assert "no file was written" in text
    parsed = tomllib.loads(text)
    assert parsed["mode"] == "report"
    assert load_policy(text.encode("utf-8"))[0] == "report"
    assert snapshot.files == original and POLICY_PATH not in snapshot.files


@pytest.mark.parametrize("requested", [None, ["coverage"]])
def test_init_missing_configuration_gives_prerequisites_instead_of_an_init_loop(requested):
    result, code = draft(MappingSnapshot({"src/api.py": b"value = 1\n"}), tools=requested)
    assert code == 2 and "policy_toml" not in result
    assert result["authority"] == "advisory_only" and "verdict" not in result
    for issue in result["diagnostics"]:
        assert "configuration" in issue["remediation"]
        assert "--root" in issue["remediation"]
        assert not issue["remediation"].startswith("Generate a draft with checkwash quality init")


def test_init_missing_one_requested_tool_still_produces_no_partial_draft():
    result, code = draft(MappingSnapshot(source()), tools=["coverage", "mypy"])
    assert code == 2 and "policy_toml" not in result
    issue = next(row for row in result["diagnostics"] if row["code"] == "CONTEXT_UNRESOLVED")
    assert "every requested tool" in issue["remediation"]
    assert "--tool" in issue["remediation"]
    assert "No partial" in issue["remediation"]
