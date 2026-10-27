"""Authority readers refuse recognized policies the subset cannot apply."""
from dataclasses import asdict
import json
import subprocess

import pytest

from checkwash.change import EngineError
from checkwash.cli import main
from checkwash.contract import load_contract, parse_contract


CANONICAL = "---\ncheckwash:\n  oracle_freeze: true\n  scope:\n    allow:\n      - tests/**\n---\n"


@pytest.mark.parametrize("text", [
    "\ufeff" + CANONICAL,
    CANONICAL.replace("true", "true # freeze"),
    CANONICAL.replace("true", '"true"'),
    CANONICAL.replace("    allow:\n      - tests/**", "    allow: [tests/**]"),
    CANONICAL.rsplit("---", 1)[0],
    CANONICAL.replace("checkwash:", "checkwash: # policy"),
    CANONICAL.replace("checkwash:", "  checkwash:"),
    CANONICAL.replace("tests/**", "tests/** # review"),
    CANONICAL.replace("scope:", "scop:"),
    CANONICAL.replace("    allow:", "  allow:"),
    CANONICAL.replace("      - tests/**", "    - tests/**"),
    CANONICAL.replace("oracle_freeze: true", "oracle_freeze: true\n  oracle_freeze: false"),
    CANONICAL.replace("---\n", "---\n", 1).replace("\n---\n", "\ngreenwash:\n  oracle_freeze: false\n---\n"),
    CANONICAL.replace("      - tests/**", "      - 'tests/**"),
    CANONICAL.replace("  oracle_freeze:", "oracle_freeze:"),
    CANONICAL.replace("  scope:", "    scope:"),
    CANONICAL.replace("    allow:", "    deny:"),
    CANONICAL.replace("checkwash:", '"checkwash":'),
    CANONICAL.replace("checkwash:", "'greenwash':"),
    CANONICAL.replace("checkwash:", "checkwash :"),
    CANONICAL.replace("checkwash:", "\tcheckwash:"),
    CANONICAL.replace("\n", "\r"),
    "\x00".join(CANONICAL),
])
def test_invalid_recognized_policy_is_not_authority(text):
    with pytest.raises(EngineError, match="invalid TASK contract.*TASK syntax"):
        load_contract(text)


@pytest.mark.parametrize("text", [
    None, "", "Plain task instructions", CANONICAL,
    CANONICAL.replace("checkwash:", "greenwash:"),
    CANONICAL.replace("true", "FALSE").replace("\n", "\r\n"),
    CANONICAL.replace("tests/**", "'tests/hash # review/**'"),
    CANONICAL.replace("checkwash:", "title: Task\ncheckwash:"),
    CANONICAL.replace("  scope:", "  intent: keep behavior\n  scope:"),
    "---\ncheckwash:\n  scope:\n    allow:\n---\n",  # Existing empty-scope meaning.
    "---\ntitle: Task\nmetadata:\n  owner: Example\n---\n",  # Unrelated metadata.
])
def test_canonical_or_absent_policy_retains_historical_contract(text):
    assert asdict(load_contract(text)) == asdict(parse_contract(text))


def test_refusal_names_source_without_echoing_task_values():
    with pytest.raises(EngineError) as error:
        load_contract(CANONICAL.replace("true", '"\x1b[31m"'), source="--task 'TASK.md' (BASE)")
    assert "--task 'TASK.md' (BASE)" in str(error.value)
    assert "\x1b" not in str(error.value)
    assert "No TASK policy was applied" in str(error.value)


@pytest.mark.parametrize("base_valid", [False, True])
def test_native_head_cannot_choose_whether_base_task_is_valid(tmp_path, capsys, base_valid):
    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)
    git("init")
    git("config", "user.name", "synthetic")
    git("config", "user.email", "fixture@example.invalid")
    git("config", "commit.gpgsign", "false")
    invalid = CANONICAL.replace("true", '"true"')
    task = tmp_path / "TASK.md"
    task.write_text(CANONICAL if base_valid else invalid, encoding="utf-8")
    test = tmp_path / "test_api.py"
    test.write_text("def test_api():\n    assert api() == 1\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-m", "base")
    task.write_text(invalid if base_valid else CANONICAL, encoding="utf-8")
    test.write_text("def test_api():\n    assert api() > 0\n", encoding="utf-8")
    code = main(["check", "--repo", str(tmp_path), "--task", "TASK.md", "--format", "json"])
    output = capsys.readouterr()
    if base_valid:
        assert code == 1
        payload = json.loads(output.out)
        assert payload["config_errors"] == []
        assert any(f["rule"] == "ASSERT_WEAKENED" and "ORACLE_FREEZE" in f["escalators"]
                   for f in payload["findings"])
    else:
        assert code == 2 and output.out == ""
        assert "invalid TASK contract" in output.err and "BASE" in output.err
