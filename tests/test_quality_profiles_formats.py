"""Bare profiles keeps JSON compatibility; explicit terminal output is human-readable."""
import json

import pytest

from checkwash.cli import main
from checkwash.quality.model import QualityError
from checkwash.quality.profiles import available


@pytest.mark.parametrize("details", [False, True])
def test_bare_profiles_preserves_explicit_json_output(details, capsys):
    suffix = ["--details"] if details else []
    assert main(["quality", "profiles", *suffix]) == 0
    default = capsys.readouterr()
    assert main(["quality", "profiles", *suffix, "--format", "json"]) == 0
    explicit = capsys.readouterr()
    assert default.out == explicit.out and default.err == explicit.err == ""
    profiles = json.loads(default.out)["profiles"]
    assert {row["id"] for row in profiles} == set(available())
    if details:
        assert all("supported_keys" in row and "qualification_receipt" in row for row in profiles)


def test_explicit_term_profiles_lists_versions_digests_and_boundaries(capsys):
    assert main(["quality", "profiles", "--format", "term"]) == 0
    captured = capsys.readouterr()
    assert captured.err == "" and captured.out.startswith("Checkwash quality profiles")
    for profile in available().values():
        for key in ("id", "tool", "tool_version", "digest", "scope"):
            assert str(profile[key]) in captured.out
    assert "not verified" in captured.out


def test_explicit_term_profile_details_keep_metadata_visible_and_quote_controls(capsys, monkeypatch):
    rows = available()
    profile = dict(next(iter(rows.values())))
    profile["extra_context"] = "line\n\x1b[31m\u202e"
    monkeypatch.setattr("checkwash.quality.cli.available", lambda: {profile["id"]: profile})
    assert main(["quality", "profiles", "--details", "--format", "term"]) == 0
    text = capsys.readouterr().out
    assert text.startswith("Checkwash quality profiles")
    assert "supported_keys" in text and "qualification_receipt" in text
    assert "extra_context" in text and "\x1b" not in text and "\u202e" not in text
    assert r"\n\u001b[31m\u202e" in text or r"\n\u001b[31m\u202e" in text.replace("\\\\", "\\")


@pytest.mark.parametrize("format", ["term", "json"])
def test_profiles_catalog_error_honors_selected_format(format, capsys, monkeypatch):
    def broken():
        raise QualityError("UNKNOWN_PROFILE", "Packaged model unavailable")

    monkeypatch.setattr("checkwash.quality.cli.available", broken)
    assert main(["quality", "profiles", "--format", format]) == 2
    captured = capsys.readouterr()
    if format == "term":
        assert captured.out.startswith("error: UNKNOWN_PROFILE:")
    else:
        assert json.loads(captured.out) == {"error": "UNKNOWN_PROFILE", "message": "Packaged model unavailable"}
