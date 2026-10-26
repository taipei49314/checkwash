"""Quality keys must not appear successfully recorded in check's ledger."""

import pytest

from checkwash.cli import main
from checkwash.findings import make_fingerprint
from checkwash.quality.model import RULES


@pytest.mark.parametrize("rule", RULES)
@pytest.mark.parametrize("existing", (False, True))
def test_allow_quality_key_does_not_write_check_ledger(tmp_path, capsys, rule, existing):
    ledger = tmp_path / ".checkwash" / "allow.toml"
    original = b"# reviewed check exemptions\n"
    if existing:
        ledger.parent.mkdir()
        ledger.write_bytes(original)
    key = rule + "/coverage-main/q1:" + "a" * 64
    code = main(["allow", key, "--reason", "reviewed", "--repo", str(tmp_path)])
    output = capsys.readouterr()
    assert code == 2
    assert output.out == ""
    assert ".checkwash/quality-allow.toml" in output.err
    assert "target_id" in output.err
    assert "recorded" not in output.err
    assert ledger.read_bytes() == original if existing else not ledger.exists()
    assert not (tmp_path / ".greenwash").exists()


def test_allow_check_key_still_records(tmp_path, capsys):
    key = make_fingerprint("BROAD_EXCEPT_ADDED", "tests/test_api.py", "test_api", "except Exception:")
    assert main(["allow", key, "--reason", "reviewed", "--repo", str(tmp_path)]) == 0
    assert "recorded exemption" in capsys.readouterr().out
    assert key in (tmp_path / ".greenwash" / "allow.toml").read_text(encoding="utf-8")


def test_allow_future_namespace_keeps_existing_compatibility(tmp_path, capsys):
    key = "FUTURE_CHECK_RULE/tests/test_api.py/test_api/0123456789ab"
    assert main(["allow", key, "--reason", "newer CI", "--repo", str(tmp_path)]) == 0
    assert "recorded exemption" in capsys.readouterr().out
    assert key in (tmp_path / ".greenwash" / "allow.toml").read_text(encoding="utf-8")
