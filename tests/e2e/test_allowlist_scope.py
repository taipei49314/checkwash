"""Real commits prove scope, base-side use and legacy-key retirement together."""

import hashlib
import json
import os
import subprocess
import sys

import pytest

SCENARIOS = [
    (
        "AGENTS.md", "GUARDRAIL_TOUCHED", "critical",
        b"# Policy\nRun tests.\n", b"# Policy\nRun tests and lint.\n", b"# Policy\nSkip tests.\n",
    ),
    (
        ".github/workflows/test.yml", "CI_WORKFLOW_TOUCHED", "high",
        b"name: Tests\non: push\njobs:\n  test:\n    steps:\n      - uses: actions/setup-python@v5\n        with:\n          python-version: '3.11'\n      - run: pytest\n",
        b"name: Tests\non: push\njobs:\n  test:\n    steps:\n      - uses: actions/setup-python@v5\n        with:\n          python-version: '3.12'\n      - run: pytest\n",
        b"name: Tests\non: push\njobs:\n  test:\n    steps:\n      - uses: actions/setup-python@v5\n        with:\n          python-version: '3.12'\n      - run: pytest || true\n",
    ),
]


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout.decode().strip()


def _write(repo, path, data):
    file = repo / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(data)


def _commit(repo, *paths):
    _git(repo, "add", "--", *paths)
    _git(repo, "commit", "-m", "scenario step")
    return _git(repo, "rev-parse", "HEAD")


def _cli(repo, *args):
    return subprocess.run(
        [sys.executable, "-m", "checkwash", *args, "--repo", str(repo)],
        capture_output=True,
        env={**os.environ, "GREENWASH_TODAY": "2026-09-06", "PYTHONUTF8": "1", "NO_COLOR": "1"},
    )


def _check(repo, rule, rev=None, *, extra=()):
    result = _cli(repo, "check", *([rev] if rev else []), "--format", "json", *extra)
    assert result.returncode in (0, 1), result.stderr.decode()
    payload = json.loads(result.stdout)
    return result, payload, next(f for f in payload["findings"] if f["rule"] == rule)


def _legacy(rule, path):
    digest = hashlib.sha256(f"{rule}/{path}//{path}".encode()).hexdigest()[:12]
    return f"{rule}/{path}/-/{digest}"


def _ledger(key, declared_rule=None):
    return (
        "[[allow]]\n"
        f"fingerprint = {json.dumps(key)}\n"
        f"rule = {json.dumps(declared_rule if declared_rule is not None else key.split('/', 1)[0])}\n"
        'reason = "reviewed previous change"\nauthor = "reviewer"\n'
        'created = "2026-09-02"\nexpires = "2026-12-01"\n'
    ).encode()


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.name", "scope-test")
    _git(tmp_path, "config", "user.email", "scope@example.invalid")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    _write(tmp_path, "README.md", b"scenario\n")
    _commit(tmp_path, "README.md")
    return tmp_path


@pytest.mark.parametrize("legacy", [False, True])
def test_parser_approval_cannot_hide_a_later_parser_regression(repo, legacy):
    path, rule = "tests/test_api.py", "TEST_FILE_UNPARSEABLE"
    _write(repo, path, b"VALUE = (\n")
    _commit(repo, path)
    _write(repo, path, b"VALUE = (\n# known unsupported file\n")
    _, _, first = _check(repo, rule)
    key = _legacy(rule, path) if legacy else first["fingerprint"]
    _write(repo, ".greenwash/allow.toml", _ledger(key, "ASSERT_REMOVED" if legacy else None))
    _commit(repo, ".greenwash/allow.toml")
    _, _, exact = _check(repo, rule)
    assert exact["allowlisted"] is (not legacy)
    _commit(repo, path)
    _write(repo, path, b"VALUE = 5\nassert VALUE == 5\n")
    _commit(repo, path)
    _write(repo, path, b"VALUE = (\nassert VALUE == 5\n")
    _commit(repo, path)
    result, payload, later = _check(repo, rule, "HEAD~1..HEAD")
    assert result.returncode == 1 and payload["verdict"] == "block"
    assert later["severity"] == "high" and not later["allowlisted"]
    assert later["fingerprint"] != key
    assert [f["rule"] for f in payload["findings"]] == [rule]
    if legacy:
        assert b"retired" in result.stderr and key.encode() in result.stderr
        refused = _cli(repo, "allow", key, "--reason", "retired parser key")
        assert refused.returncode == 2


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("changed_context", ["contract", "content"])
def test_scope_approval_cannot_cross_content_or_base_contract(repo, legacy, changed_context):
    path, rule = "auth.py", "SCOPE_DRIFT"
    contract = b'---\ncheckwash:\n  scope:\n    allow:\n      - "billing.py"\n---\n'
    _write(repo, "TASK.md", contract)
    _write(repo, path, b'def authorize(token):\n    return token == "expected"\n')
    _commit(repo, "TASK.md", path)
    _write(repo, path, b'def authorize(token):\n    return bool(token) and token == "expected"\n')
    extra = ("--task", str(repo / "TASK.md"))
    _, _, first = _check(repo, rule, extra=extra)
    key = _legacy(rule, path) if legacy else first["fingerprint"]
    _write(repo, ".greenwash/allow.toml", _ledger(key, "ASSERT_REMOVED" if legacy else None))
    _commit(repo, ".greenwash/allow.toml")
    _, _, exact = _check(repo, rule, extra=extra)
    assert exact["allowlisted"] is (not legacy)
    if changed_context == "contract":
        _write(repo, "TASK.md", contract.replace(b"billing.py", b"docs/**"))
        _commit(repo, "TASK.md")  # the exact same auth content pair, new trusted contract
    else:
        _write(repo, path, b"def authorize(token):\n    return True\n")
    _commit(repo, path)
    result, payload, later = _check(repo, rule, "HEAD~1..HEAD", extra=extra)
    assert result.returncode == 1 and payload["verdict"] == "block"
    assert later["severity"] == "high" and not later["allowlisted"]
    assert later["fingerprint"] != key
    if legacy:
        assert b"retired" in result.stderr and key.encode() in result.stderr
        assert _cli(repo, "allow", key, "--reason", "retired scope key").returncode == 2


@pytest.mark.parametrize("scenario", SCENARIOS, ids=["guardrail", "ci"])
@pytest.mark.parametrize("directory", [".checkwash", ".greenwash"])
@pytest.mark.parametrize("spoof_rule", [False, True])
def test_retired_base_exemption_cannot_allow_later_content(repo, scenario, directory, spoof_rule):
    path, rule, severity, before, _honest, attack = scenario
    _write(repo, path, before)
    _commit(repo, path)
    ledger = f"{directory}/allow.toml"
    key = _legacy(rule, path)
    _write(repo, ledger, b"\xef\xbb\xbf" + _ledger(key, "ASSERT_REMOVED" if spoof_rule else None))
    _commit(repo, ledger)
    _write(repo, path, attack)
    _commit(repo, path)
    result, payload, hit = _check(repo, rule, "HEAD~1...HEAD")
    assert result.returncode == 1 and payload["verdict"] == "block"
    assert hit["severity"] == severity and hit["allowlisted"] is False
    assert hit["fingerprint"] != key
    assert b"ignored exemption" in result.stderr and b"retired" in result.stderr
    assert ledger.encode() in result.stderr and key.encode() in result.stderr
    assert payload["config_errors"] == []  # migration advice is not a parse failure


@pytest.mark.parametrize("scenario", SCENARIOS, ids=["guardrail", "ci"])
def test_approved_exact_change_survives_unrelated_commit_but_not_next_change(repo, scenario):
    path, rule, severity, before, honest, attack = scenario
    _write(repo, path, before)
    _commit(repo, path)
    _write(repo, path, honest)
    _result, _payload, proposed = _check(repo, rule)
    key = proposed["fingerprint"]
    allow = _cli(repo, "allow", key, "--reason", "reviewed exact change")
    assert allow.returncode == 0, allow.stderr.decode()
    _commit(repo, ".greenwash/allow.toml")  # the target modification stays uncommitted
    _write(repo, "README.md", b"unrelated documentation\n")
    _commit(repo, "README.md")
    result, payload, exact = _check(repo, rule)
    assert result.returncode == 0 and payload["verdict"] == "pass"
    assert exact["fingerprint"] == key and exact["allowlisted"] is True
    _commit(repo, path)
    result, _payload, exact = _check(repo, rule, "HEAD~1..HEAD")
    assert result.returncode == 0 and exact["allowlisted"] is True
    _write(repo, path, attack)
    _commit(repo, path)
    result, payload, later = _check(repo, rule, "HEAD~1...HEAD")
    assert result.returncode == 1 and payload["verdict"] == "block"
    assert later["severity"] == severity and later["allowlisted"] is False
    assert later["fingerprint"] != key


@pytest.mark.parametrize("scenario", SCENARIOS, ids=["guardrail", "ci"])
def test_same_base_different_change_needs_a_new_approval(repo, scenario):
    path, rule, severity, before, honest, attack = scenario
    _write(repo, path, before)
    _commit(repo, path)
    _write(repo, path, honest)
    _result, _payload, proposed = _check(repo, rule)
    key = proposed["fingerprint"]
    assert _cli(repo, "allow", key, "--reason", "reviewed exact change").returncode == 0
    _commit(repo, ".greenwash/allow.toml")
    _write(repo, path, attack)
    result, payload, hit = _check(repo, rule)
    assert result.returncode == 1 and payload["verdict"] == "block"
    assert hit["fingerprint"] != key and hit["allowlisted"] is False
    assert hit["severity"] == severity


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("rule,path", [(item[1], item[0]) for item in SCENARIOS])
def test_allow_refuses_retired_key_without_creating_or_modifying_a_ledger(repo, existing, rule, path):
    ledger = repo / ".greenwash" / "allow.toml"
    original = b"# keep this byte for byte\n"
    if existing:
        _write(repo, ".greenwash/allow.toml", original)
    result = _cli(repo, "allow", _legacy(rule, path), "--reason", "old command copied from report")
    assert result.returncode == 2
    assert b"retired" in result.stderr and b"Re-run" in result.stderr
    assert ledger.read_bytes() == original if existing else not ledger.exists()


def test_removing_a_retired_base_entry_is_still_a_guardrail_change(repo):
    ledger = ".greenwash/allow.toml"
    _write(repo, ledger, _ledger(_legacy("GUARDRAIL_TOUCHED", "AGENTS.md")))
    _commit(repo, ledger)
    _write(repo, ledger, b"# obsolete approval removed\n")
    _commit(repo, ledger)
    result, payload, hit = _check(repo, "GUARDRAIL_TOUCHED", "HEAD~1..HEAD")
    assert result.returncode == 1 and payload["verdict"] == "block"
    assert hit["path"] == ledger and hit["severity"] == "critical"
    assert not any(f["rule"] == "EXEMPTION_ADDED" for f in payload["findings"])


def test_legacy_directory_does_not_override_preferred_base_ledger(repo):
    path, rule, _severity, before, honest, _attack = SCENARIOS[0]
    _write(repo, path, before)
    _commit(repo, path)
    _write(repo, path, honest)
    _result, _payload, proposed = _check(repo, rule)
    _write(repo, ".greenwash/allow.toml", _ledger(proposed["fingerprint"]))
    _write(repo, ".checkwash/allow.toml", _ledger(_legacy(rule, path)))
    _commit(repo, ".greenwash/allow.toml", ".checkwash/allow.toml")
    result, payload, hit = _check(repo, rule)
    assert result.returncode == 1 and payload["verdict"] == "block"
    assert hit["allowlisted"] is False


def test_doctor_reports_retired_keys_without_counting_them_active(repo):
    ledger = ".checkwash/allow.toml"
    key = _legacy("GUARDRAIL_TOUCHED", "AGENTS.md")
    _write(repo, ledger, _ledger(key))
    result = _cli(repo, "doctor")
    assert result.returncode == 1
    assert b"0 active today" in result.stdout
    assert b"1 retired fingerprint(s)" in result.stdout
    assert b"retired or invalid exemptions are ignored" in result.stdout
    assert key.encode() in result.stdout and ledger.encode() in result.stdout
    assert b"Re-run" in result.stdout and b"cannot be migrated" in result.stdout


def test_real_git_rename_has_the_same_identity_in_worktree_and_range(repo):
    _write(repo, "AGENTS.md", b"# Policy\nRun tests.\n")
    _commit(repo, "AGENTS.md")
    _git(repo, "mv", "AGENTS.md", "CLAUDE.md")
    result, _payload, worktree = _check(repo, "GUARDRAIL_TOUCHED")
    assert result.returncode == 1 and worktree["path"] == "CLAUDE.md"
    _git(repo, "commit", "-m", "rename policy file")
    result, _payload, committed = _check(repo, "GUARDRAIL_TOUCHED", "HEAD~1..HEAD")
    assert result.returncode == 1
    assert committed["fingerprint"] == worktree["fingerprint"]
