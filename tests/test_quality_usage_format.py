"""Usage failures remain machine-readable in requested quality formats."""

import datetime
import json
from types import SimpleNamespace

import pytest

from checkwash.quality.cli import run


@pytest.mark.parametrize("command,flags", [
    ("doctor", {"root": "."}),
    ("init", {"rule": "extra"}),
    ("profiles", {"rule": "extra"}),
    ("explain", {"rule": "unknown"}),
])
@pytest.mark.parametrize("format", ("json", "sarif"))
def test_quality_usage_error_is_machine_readable(command, flags, format):
    args = SimpleNamespace(range=command, rule=None, format=format, repo=".",
                           root=None, paths=None, tool=None, details=False)
    vars(args).update(flags)
    text, code = run(args, datetime.date(2026, 10, 26))
    assert code == 2
    payload = json.loads(text)
    if format == "json" and command in {"init", "doctor"}:
        assert payload["checkwash_quality_setup_version"] == 1
        assert payload["state"] == "error" and payload["authority"] == "advisory_only"
        assert "verdict" not in payload
        assert payload["diagnostics"][0]["code"] == "POLICY_INVALID"
    elif format == "json":
        assert payload["checkwash_quality_version"] == 1
        assert payload["analysis_status"] == payload["verdict"] == "error"
        assert payload["diagnostics"][0]["kind"] == "error"
    else:
        assert payload["version"] == "2.1.0"
        invocation = payload["runs"][0]["invocations"][0]
        assert invocation["executionSuccessful"] is False
        assert invocation["toolExecutionNotifications"][0]["level"] == "error"
