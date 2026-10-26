"""Per-commit sweep diagnostics preserve accounting and avoid copying secrets."""

import datetime
import importlib
import json
from types import SimpleNamespace

import pytest

from checkwash import __version__
from checkwash.change import SourceOverLimit, UnreadSide
from checkwash.gitio.git import GitError


SWEEP = importlib.import_module("checkwash.sweep")
COMMIT = "1" * 40
PARENT = "a" * 40
NEXT = "2" * 40
TODAY = datetime.date(2026, 10, 26)


def _empty_analysis(*args, **kwargs):
    return SimpleNamespace(globals=SimpleNamespace(prod_opaque_change=False), files=[]), [], "pass"


def _inputs(monkeypatch, config=None, allow=None, commits=(COMMIT,)):
    """Exercise real config/allow parsers without unrelated Git/process I/O."""
    monkeypatch.setattr(SWEEP, "_commit_list", lambda *args: list(commits))
    monkeypatch.setattr("checkwash.gitio.git.read_commit_parents", lambda *args: [PARENT])
    monkeypatch.setattr(SWEEP, "list_range_changes", lambda *args: [])
    monkeypatch.setattr(SWEEP, "read_base_config_file", lambda repo, parent, name:
                        (".greenwash/" + name, config if name == "config.toml" else allow))
    monkeypatch.setattr(SWEEP, "read_base_file", lambda *args: None)
    snapshot = SimpleNamespace(read=lambda path: None, search=lambda needles: [],
                               list_paths=lambda: [], read_many=lambda paths: {})
    monkeypatch.setattr(SWEEP, "GitSnapshot", lambda *args, **kwargs: snapshot)
    monkeypatch.setattr(SWEEP, "analyze", _empty_analysis)


def _run():
    return SWEEP.sweep("unused-synthetic", COMMIT, 2, TODAY)


@pytest.mark.parametrize("name,data,kind,phase", [
    ("config", b"[broken\n", "config_parse_error", "load_config"),
    ("allow", b"[broken\n", "allow_parse_error", "load_allowlist"),
])
def test_parse_diagnostic_names_exact_commit_parent_and_existing_fallback(monkeypatch, name, data, kind, phase):
    _inputs(monkeypatch, **{name: data})
    result = _run()
    payload = json.loads(result.to_json())
    assert (result.commits, result.errors, result.skipped, result.blocked) == (1, 0, 0, 0)
    event, = payload["commit_diagnostics"]
    assert (event["commit"], event["parent"], event["kind"], event["phase"]) == (COMMIT, PARENT, kind, phase)
    assert event["path"] == f".greenwash/{name}.toml"
    assert (event["line"], event["column"]) == (1, 8)
    assert "exception_type" not in event
    assert ("defaults are in effect" if name == "config" else "no exemptions are active") in event["message"]


def test_value_warnings_keep_safe_fields_and_never_echo_supplied_values(monkeypatch):
    config = b'''[roles]
"synthetic_private_role" = ["*"]
test = 7
[gate]
fail_on = "https://synthetic-user:synthetic-password@example.invalid/?token=synthetic-token"
on_engine_error = "synthetic-secret"
[detectors]
disable = 7
'''
    _inputs(monkeypatch, config=config, allow=b"[broken\n")
    result = _run()
    encoded = result.to_json()
    events = json.loads(encoded)["commit_diagnostics"]
    warnings = [event for event in events if event["kind"] == "config_warning"]
    assert len(warnings) == 5
    assert {event["field"] for event in warnings} == {"roles", "gate.fail_on", "gate.on_engine_error", "detectors.disable"}
    assert all(event["commit"] == COMMIT and event["parent"] == PARENT for event in events)
    assert all(event["phase"] == "load_config" for event in warnings)
    assert events[-1]["kind"] == "allow_parse_error"
    assert (result.commits, result.errors) == (1, 0)
    for private in ("synthetic_private_role", "synthetic-user", "synthetic-password", "synthetic-token", "synthetic-secret"):
        assert private not in encoded


def test_analysis_exception_does_not_enter_analysed_denominator_or_echo_its_text(monkeypatch):
    _inputs(monkeypatch, commits=(COMMIT, NEXT))

    def analyze(*args, **kwargs):
        if kwargs["head_label"] == NEXT:
            raise RuntimeError("https://user:synthetic-password@example.invalid/\n\x1b[2J token=synthetic-token")
        return _empty_analysis()

    monkeypatch.setattr(SWEEP, "analyze", analyze)
    result = _run()
    encoded = result.to_json()
    event, = json.loads(encoded)["commit_diagnostics"]
    assert (result.commits, result.errors, result.skipped, result.blocked) == (1, 1, 0, 0)
    assert (event["commit"], event["parent"], event["phase"], event["kind"], event["exception_type"]) == (
        NEXT, PARENT, "analyze", "analysis_exception", "RuntimeError")
    assert "omitted" in event["message"]
    assert "synthetic-password" not in encoded and "synthetic-token" not in encoded
    assert "\x1b" not in encoded


def test_parent_read_failure_does_not_reuse_the_previous_commits_parent(monkeypatch):
    _inputs(monkeypatch, commits=(COMMIT, NEXT))

    def parents(repo, commit):
        if commit == NEXT:
            raise GitError("synthetic private remote failure")
        return [PARENT]

    monkeypatch.setattr("checkwash.gitio.git.read_commit_parents", parents)
    result = _run()
    event, = json.loads(result.to_json())["commit_diagnostics"]
    assert (result.commits, result.errors, result.skipped) == (1, 1, 0)
    assert event["commit"] == NEXT
    assert (event["phase"], event["exception_type"]) == ("read_commit", "GitError")
    assert "parent" not in event


def test_diagnostics_do_not_read_more_source_or_call_exception_string(monkeypatch):
    _inputs(monkeypatch)
    requests = []

    class UnprintableError(Exception):
        def __str__(self):
            raise AssertionError("diagnostics must not inspect arbitrary exception text")

    def read(repo, parent, name):
        requests.append(name)
        raise UnprintableError()

    monkeypatch.setattr(SWEEP, "read_base_config_file", read)
    result = _run()
    event, = json.loads(result.to_json())["commit_diagnostics"]
    assert requests == ["config.toml"]
    assert (result.commits, result.errors) == (0, 1)
    assert (event["phase"], event["exception_type"]) == ("load_config", "UnprintableError")


def test_source_limit_refusal_stays_an_error_without_retrying_the_read(monkeypatch):
    _inputs(monkeypatch)
    requests = []

    def read(repo, parent, name):
        requests.append(name)
        raise SourceOverLimit(UnreadSide(".greenwash/config.toml", "base", 1_000_001, 1_000_000))

    monkeypatch.setattr(SWEEP, "read_base_config_file", read)
    result = _run()
    event, = json.loads(result.to_json())["commit_diagnostics"]
    assert requests == ["config.toml"]
    assert (result.commits, result.errors) == (0, 1)
    assert event["exception_type"] == "SourceOverLimit"
    assert event["phase"] == "load_config"


def test_missing_parser_position_is_not_invented(monkeypatch):
    _inputs(monkeypatch, config=b"value = [")
    event, = json.loads(_run().to_json())["commit_diagnostics"]
    assert "line" not in event and "column" not in event


def test_real_root_stays_a_skip_without_a_diagnostic(monkeypatch):
    _inputs(monkeypatch)
    monkeypatch.setattr("checkwash.gitio.git.read_commit_parents", lambda *args: [])
    result = _run()
    assert (result.commits, result.errors, result.skipped) == (0, 0, 1)
    assert "commit_diagnostics" not in json.loads(result.to_json())


def test_no_diagnostic_keeps_the_existing_json_bytes(monkeypatch):
    _inputs(monkeypatch)
    encoded = _run().to_json()
    expected = '''{
  "block_rate": 0.0,
  "blocked_commits": [],
  "commits_analysed": 1,
  "commits_blocked": 0,
  "commits_skipped_no_parent": 0,
  "commits_touching_tests": 0,
  "commits_with_opaque_prod_change": 0,
  "corpus": {
    "checkwash_version": "%s",
    "newest_commit": "%s",
    "oldest_commit": "%s"
  },
  "engine_errors": 0,
  "findings_by_rule": {},
  "merge_commits": "excluded (rev-list --no-merges); a merge gate sees them too"
}
''' % (__version__, COMMIT, COMMIT)
    assert encoded == expected


def test_json_escapes_a_diagnostics_control_characters():
    result = SWEEP.SweepResult()
    result.commit_diagnostics.append({"commit": COMMIT, "phase": "analyze", "kind": "analysis_exception",
                                      "message": 'synthetic "quoted"\n\x1b[2J', "exception_type": "RuntimeError"})
    encoded = result.to_json()
    assert "\x1b" not in encoded
    assert "\\u001b" in encoded and "\\n" in encoded
    assert json.loads(encoded)["commit_diagnostics"][0]["message"] == 'synthetic "quoted"\n\x1b[2J'
