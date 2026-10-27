"""Unknown namespaces are visible without breaking newer-engine exemptions."""

from checkwash.cli import main
from checkwash.doctor import collect
from checkwash.allowlist import active_fingerprints, load_allowlist
import datetime


def test_future_key_is_preserved_but_writer_and_doctor_explain_matching(tmp_path, capsys):
    key = "FUTURE_CHECK_RULE/tests/test_api.py/test_api/0123456789ab"
    assert main(["allow", key, "--reason", "newer CI", "--repo", str(tmp_path)]) == 0
    output = capsys.readouterr()
    assert "recorded exemption" in output.out
    assert "warning:" in output.err
    assert "not recognized" in output.err and "version" in output.err
    ledger = tmp_path / ".greenwash/allow.toml"
    entries, error = load_allowlist(ledger.read_bytes())
    assert error is None and entries[0].fingerprint == key
    # Preserve the existing read-side compatibility contract.
    assert key in active_fingerprints(entries, datetime.date.today())
    notes = collect(tmp_path)
    warning = next(note for note in notes if "unrecognized" in note.title)
    assert key in warning.detail and "matching finding" in warning.detail
    summary = next(note for note in notes if "expiry is capped" in note.title)
    assert "eligibility" in summary.detail


def test_known_legacy_namespace_has_no_unknown_warning(tmp_path, capsys):
    assert main(["allow", "BROAD_EXCEPT_ADDED/tests/test_api.py/test_api/0123456789ab",
                 "--reason", "reviewed", "--repo", str(tmp_path)]) == 0
    assert "not recognized" not in capsys.readouterr().err


def test_unknown_key_control_characters_are_visible_only_in_diagnostics(tmp_path, capsys):
    key = "FUTURE_CHECK_RULE/tests/test.py/test_api/line\n\x1b[31m\u202e"
    assert main(["allow", key, "--reason", "newer CI", "--repo", str(tmp_path)]) == 0
    warning = capsys.readouterr().err
    assert "\x1b" not in warning and "\u202e" not in warning
    assert r"\n\x1b[31m\u202e" in warning
    entries, error = load_allowlist((tmp_path / ".greenwash/allow.toml").read_bytes())
    assert error is None and entries[0].fingerprint == key
