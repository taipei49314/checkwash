"""End-to-end: real git repo, real subprocesses, both range and worktree modes.

Running the CLI twice in separate processes also verifies determinism under
different PYTHONHASHSEED values (each process gets a fresh random seed).
"""

import json
import os
import subprocess
import sys
import textwrap

import pytest

_ENV = {**os.environ, "GREENWASH_TODAY": "2026-01-01", "NO_COLOR": "1"}


def _git(repo, *args):
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
    )


def _greenwash(repo, *args):
    return subprocess.run(
        [sys.executable, "-m", "greenwash", *args, "--repo", str(repo)],
        capture_output=True,
        text=True,
        env=_ENV,
    )


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.name", "e2e")
    _git(tmp_path, "config", "user.email", "e2e@example.invalid")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    (tmp_path / "billing.py").write_text(
        "def compute_invoice_total(items):\n    return round(sum(items), 2)\n",
        encoding="utf-8",
    )
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_billing.py").write_text(
        textwrap.dedent(
            """\
            from billing import compute_invoice_total


            def test_invoice_total():
                total = compute_invoice_total([10.5, 94.8])
                assert total == 105.3
            """
        ),
        encoding="utf-8",
    )
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "base")
    return tmp_path


def _weaken(repo):
    test_file = repo / "tests" / "test_billing.py"
    content = test_file.read_text(encoding="utf-8")
    test_file.write_text(
        content.replace("assert total == 105.3", "assert total > 0"), encoding="utf-8"
    )


def test_range_mode_blocks_weakened_assert(repo):
    _weaken(repo)
    _git(repo, "commit", "-am", "agent fix")
    result = _greenwash(repo, "check", "HEAD~1..HEAD", "--format", "json")
    assert result.returncode == 1, result.stderr
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "block"
    rules = [f["rule"] for f in payload["findings"]]
    assert "ASSERT_WEAKENED" in rules
    finding = next(f for f in payload["findings"] if f["rule"] == "ASSERT_WEAKENED")
    assert finding["severity"] == "high"
    assert "NO_PROD_CHANGE_IN_DIFF" in finding["escalators"]
    assert finding["before"]["text"] == "assert total == 105.3"
    assert finding["after"]["text"] == "assert total > 0"


def test_worktree_mode_blocks_uncommitted_weakening(repo):
    _weaken(repo)
    result = _greenwash(repo, "check", "--format", "json")
    assert result.returncode == 1, result.stderr
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "block"


def test_sarif_format_is_github_code_scanning_subset(repo):
    _weaken(repo)
    _git(repo, "commit", "-am", "agent fix")
    result = _greenwash(repo, "check", "HEAD~1..HEAD", "--format", "sarif")
    assert result.returncode == 1, result.stderr
    payload = json.loads(result.stdout)
    assert payload["version"] == "2.1.0"
    assert payload["$schema"].endswith("sarif-2.1.0.json")
    run = payload["runs"][0]
    assert run["tool"]["driver"]["name"] == "greenwash"
    assert "ASSERT_WEAKENED" in [rule["id"] for rule in run["tool"]["driver"]["rules"]]
    hit = next(item for item in run["results"] if item["ruleId"] == "ASSERT_WEAKENED")
    assert hit["level"] == "error"
    assert hit["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == (
        "tests/test_billing.py"
    )
    assert hit["locations"][0]["physicalLocation"]["region"]["startLine"] == 1
    assert hit["partialFingerprints"]["greenwash/v1"]
    again = _greenwash(repo, "check", "HEAD~1..HEAD", "--format", "sarif")
    assert again.stdout == result.stdout


def test_sarif_pass_is_empty_results(repo):
    (repo / "notes.md").write_text("release notes\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "docs")
    result = _greenwash(repo, "check", "HEAD~1..HEAD", "--format", "sarif")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["runs"][0]["results"] == []
    assert payload["runs"][0]["tool"]["driver"]["rules"] == []


def test_clean_range_passes(repo):
    (repo / "notes.md").write_text("release notes\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "docs")
    result = _greenwash(repo, "check", "HEAD~1..HEAD", "--format", "json")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["verdict"] == "pass"


def test_cross_process_byte_identical(repo):
    _weaken(repo)
    _git(repo, "commit", "-am", "agent fix")
    a = _greenwash(repo, "check", "HEAD~1..HEAD", "--format", "json")
    b = _greenwash(repo, "check", "HEAD~1..HEAD", "--format", "json")
    assert a.stdout == b.stdout
    assert a.stdout


def test_term_report_renders(repo):
    _weaken(repo)
    result = _greenwash(repo, "check")
    assert result.returncode == 1
    assert "ASSERT_WEAKENED" in result.stdout
    assert "allow_cap=180d" in result.stdout
    assert "commit .greenwash/allow.toml" in result.stdout
    assert "greenwash allow" in result.stdout
    assert "why high:" in result.stdout
    assert "no de-escalator applied" in result.stdout
    assert "next: fix the code" in result.stdout


def test_term_header_counts_findings_at_active_threshold(repo):
    guardrail = repo / ".claude" / "settings.json"
    guardrail.parent.mkdir()
    guardrail.write_text("{}\n", encoding="utf-8")

    high = _greenwash(repo, "check", "--fail-on", "high")
    assert high.returncode == 0, high.stderr
    assert "greenwash: 1 finding(s), none at or above high" in high.stdout
    assert "verdict=pass" in high.stdout

    warn = _greenwash(repo, "check", "--fail-on", "warn")
    assert warn.returncode == 1, warn.stderr
    assert "greenwash: 1 finding(s) at or above warn" in warn.stdout
    assert "verdict=block" in warn.stdout


def test_allow_roundtrip(repo):
    _weaken(repo)
    first = _greenwash(repo, "check", "--format", "json")
    fingerprint = json.loads(first.stdout)["findings"][0]["fingerprint"]

    allow = _greenwash(repo, "allow", fingerprint, "--reason", "reviewed: issue 482")
    assert allow.returncode == 0, allow.stderr
    # Only the exemption goes through review/commit; the weakened test stays
    # in the worktree. Exemptions are honoured from the BASE side (SPEC §6).
    _git(repo, "add", ".greenwash")
    _git(repo, "commit", "-m", "record exemption")

    result = _greenwash(repo, "check", "--format", "json")
    assert result.returncode == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "pass"
    assert any(f["allowlisted"] for f in payload["findings"])


def test_engine_error_exit_code(tmp_path):
    result = _greenwash(tmp_path, "check", "HEAD~1..HEAD", "--format", "json")
    assert result.returncode == 2


def test_hook_json_blocks_with_reason(repo):
    guardrail = repo / ".claude" / "settings.json"
    guardrail.parent.mkdir()
    guardrail.write_text("{}\n", encoding="utf-8")
    warn = _greenwash(
        repo,
        "check",
        "--fail-on",
        "warn",
        "--format",
        "hook-json",
    )
    assert warn.returncode == 0, warn.stderr
    warn_payload = json.loads(warn.stdout)
    assert warn_payload["decision"] == "block"
    assert "1 finding(s) blocking" in warn_payload["reason"]
    assert "GUARDRAIL_TOUCHED" in warn_payload["reason"]

    guardrail.unlink()
    guardrail.parent.rmdir()
    _weaken(repo)
    result = _greenwash(repo, "check", "--format", "hook-json")
    # Stop-hook protocol: decision travels in JSON, exit stays 0.
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["decision"] == "block"
    assert "ASSERT_WEAKENED" in payload["reason"]
    assert "greenwash allow" in payload["reason"]


def test_hook_json_clean_is_empty_object(repo):
    result = _greenwash(repo, "check", "--format", "hook-json")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {}


def test_hook_install_merges_existing_settings(repo):
    claude_dir = repo / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text(
        '{"permissions": {"allow": ["Bash(pytest:*)"]}}', encoding="utf-8"
    )
    result = _greenwash(repo, "hook", "install", "--agent", "claude-code")
    assert result.returncode == 0, result.stderr
    settings = json.loads((claude_dir / "settings.json").read_text(encoding="utf-8"))
    assert settings["permissions"]["allow"] == ["Bash(pytest:*)"]  # preserved
    commands = [
        h["command"]
        for entry in settings["hooks"]["Stop"]
        for h in entry["hooks"]
    ]
    assert "greenwash check --format hook-json" in commands
    # idempotent
    again = _greenwash(repo, "hook", "install", "--agent", "claude-code")
    assert again.returncode == 0
    settings2 = json.loads((claude_dir / "settings.json").read_text(encoding="utf-8"))
    assert settings2 == settings


def _greenwash_cp1252(repo, *args):
    # Forces the legacy-locale pipe encoding that crashed the term report
    # (confirmed red-team finding): exit codes must survive cp1252.
    env = {**_ENV, "PYTHONIOENCODING": "cp1252", "PYTHONUTF8": "0"}
    return subprocess.run(
        [sys.executable, "-m", "greenwash", *args, "--repo", str(repo)],
        capture_output=True,
        env=env,
    )


def test_cp1252_pipe_clean_diff_exits_zero(repo):
    (repo / "notes.md").write_text("notes\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "docs")
    result = _greenwash_cp1252(repo, "check", "HEAD~1..HEAD")
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert b"greenwash" in result.stdout


def test_cp1252_pipe_block_exits_one(repo):
    _weaken(repo)
    result = _greenwash_cp1252(repo, "check")
    assert result.returncode == 1, result.stderr.decode("utf-8", "replace")
    assert b"ASSERT_WEAKENED" in result.stdout


def test_rename_test_file_out_of_tests_blocks(repo):
    # git mv tests/test_billing.py legacy_billing.py laundered TEST_DISABLED
    # with zero findings (confirmed red-team bypass).
    _git(repo, "mv", "tests/test_billing.py", "legacy_billing.py")
    _git(repo, "commit", "-m", "archive tests")
    result = _greenwash(repo, "check", "HEAD~1..HEAD", "--format", "json")
    assert result.returncode == 1, result.stdout
    payload = json.loads(result.stdout)
    disabled = [f for f in payload["findings"] if f["rule"] == "TEST_DISABLED"]
    assert disabled and disabled[0]["severity"] == "high"
    assert "NO_PROD_CHANGE_IN_DIFF" in disabled[0]["escalators"]


def test_rename_test_file_to_uncollected_name_blocks(repo):
    _git(repo, "mv", "tests/test_billing.py", "tests/billing_checks.py")
    _git(repo, "commit", "-m", "reorganize")
    result = _greenwash(repo, "check", "HEAD~1..HEAD", "--format", "json")
    assert result.returncode == 1, result.stdout
    payload = json.loads(result.stdout)
    assert any(f["rule"] == "TEST_DISABLED" for f in payload["findings"])


def test_rename_test_file_to_collected_name_is_benign(repo):
    _git(repo, "mv", "tests/test_billing.py", "tests/test_invoices.py")
    _git(repo, "commit", "-m", "rename test module")
    result = _greenwash(repo, "check", "HEAD~1..HEAD", "--format", "json")
    assert result.returncode == 0, result.stdout
    assert json.loads(result.stdout)["verdict"] == "pass"


def test_worktree_mode_catches_plain_mv_relocation(repo):
    # The round-1 rename fix only covered range mode; hook mode (the primary
    # integration) still laundered it (confirmed red-team finding).
    (repo / "attic").mkdir()
    os.replace(repo / "tests" / "test_billing.py", repo / "attic" / "legacy.py")
    result = _greenwash(repo, "check", "--format", "json")
    assert result.returncode == 1, result.stdout
    payload = json.loads(result.stdout)
    disabled = [f for f in payload["findings"] if f["rule"] == "TEST_DISABLED"]
    assert disabled and disabled[0]["severity"] == "high"


def test_worktree_case_only_rename_is_visible(repo):
    # On a case-insensitive volume the deleted path used to be read back off
    # disk as the renamed file's bytes and dropped as unchanged.
    os.replace(repo / "tests" / "test_billing.py", repo / "tests" / "Billing_Checks.py")
    result = _greenwash(repo, "check", "--format", "json")
    assert result.returncode == 1, result.stdout
    payload = json.loads(result.stdout)
    assert any(f["rule"] == "TEST_DISABLED" for f in payload["findings"])


def test_three_dot_range_uses_merge_base(repo):
    # A...B means merge-base(A,B)..B. Downgrading it to two dots pulled base
    # branch prod commits in and disarmed E1 (confirmed red-team finding).
    _git(repo, "checkout", "-q", "-b", "feat")
    _weaken(repo)
    _git(repo, "commit", "-am", "weaken assertion")
    _git(repo, "checkout", "-q", "main")
    (repo / "discount.py").write_text("def discount(x):\n    return x * 9 // 10\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "main: add discount")

    three = _greenwash(repo, "check", "main...feat", "--format", "json")
    assert three.returncode == 1, three.stdout
    payload = json.loads(three.stdout)
    weakened = [f for f in payload["findings"] if f["rule"] == "ASSERT_WEAKENED"]
    assert weakened and weakened[0]["severity"] == "high"
    assert "NO_PROD_CHANGE_IN_DIFF" in weakened[0]["escalators"]


def test_json_is_utf8_regardless_of_locale(repo):
    test_file = repo / "tests" / "test_billing.py"
    test_file.write_text(
        "from billing import compute_invoice_total\n\n\n"
        "def test_invoice_total():\n"
        '    assert compute_invoice_total([1]) == "發票總額"\n',
        encoding="utf-8",
    )
    _git(repo, "commit", "-am", "non-ascii expectation")
    test_file.write_text(
        "from billing import compute_invoice_total\n\n\n"
        "def test_invoice_total():\n"
        "    assert compute_invoice_total([1]) is not None\n",
        encoding="utf-8",
    )
    _git(repo, "commit", "-am", "weaken")
    result = _greenwash_cp1252(repo, "check", "HEAD~1..HEAD", "--format", "json")
    assert result.returncode == 1
    payload = json.loads(result.stdout.decode("utf-8"))  # must be valid UTF-8
    assert "發票總額" in json.dumps(payload, ensure_ascii=False)


def test_recursion_bomb_is_engine_error_not_block(repo):
    (repo / "tests" / "test_deep.py").write_text(
        "def test_deep():\n    assert " + "1+" * 20000 + "1\n", encoding="utf-8"
    )
    result = _greenwash(repo, "check", "--format", "json")
    # Either parsed fine or degraded visibly — but never a bogus "block",
    # and never an unhandled traceback.
    assert result.returncode in (0, 2), result.stdout
    assert "Traceback" not in result.stderr


def test_malformed_config_is_reported_not_swallowed(repo):
    cfg = repo / ".greenwash"
    cfg.mkdir()
    (cfg / "config.toml").write_text('[gate]\nfail_on = "warn"\n[roles\n', encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "add config")
    _weaken(repo)
    result = _greenwash(repo, "check", "--format", "json")
    payload = json.loads(result.stdout)
    assert payload["config_errors"], "a config that failed to parse must be surfaced"
    assert "config.toml" in result.stderr


def test_allow_reason_with_backslash_stays_valid_toml(repo):
    _weaken(repo)
    first = _greenwash(repo, "check", "--format", "json")
    fingerprint = json.loads(first.stdout)["findings"][0]["fingerprint"]
    allow = _greenwash(
        repo, "allow", fingerprint, "--reason", r"see notes in C:\Users\bob\review.md"
    )
    assert allow.returncode == 0, allow.stderr
    import tomllib

    data = (repo / ".greenwash" / "allow.toml").read_bytes()
    parsed = tomllib.loads(data.decode("utf-8"))
    assert parsed["allow"][0]["reason"] == r"see notes in C:\Users\bob\review.md"


def _add_compat_gate(repo):
    """Base: a compat module + a test importing it. Diff: only the marker."""
    (repo / "compat_helpers.py").write_text(
        'import sys\n\nWIN = sys.platform.startswith("win")\n', encoding="utf-8"
    )
    test_file = repo / "tests" / "test_billing.py"
    test_file.write_text(
        textwrap.dedent(
            """\
            import pytest

            from billing import compute_invoice_total
            from compat_helpers import WIN


            def test_invoice_total():
                total = compute_invoice_total([10.5, 94.8])
                assert total == 105.3
            """
        ),
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "add compat helper")
    test_file.write_text(
        test_file.read_text(encoding="utf-8").replace(
            "def test_invoice_total():",
            '@pytest.mark.skipif(WIN, reason="pipe pager path")\ndef test_invoice_total():',
        ),
        encoding="utf-8",
    )


def test_range_mode_resolves_compat_constant_from_unchanged_file(repo):
    # The constant's module is not in the diff at all: D6 must read it from
    # the head revision (click b761eda, the FP the sweep adjudication found).
    _add_compat_gate(repo)
    _git(repo, "commit", "-am", "skip pager test on windows")
    result = _greenwash(repo, "check", "HEAD~1..HEAD", "--format", "json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "pass"
    finding = next(f for f in payload["findings"] if f["rule"] == "TEST_DISABLED")
    assert finding["severity"] == "warn"
    assert "COMPAT_GATE" in finding["deescalators"]


def test_worktree_mode_resolves_compat_constant_from_disk(repo):
    _add_compat_gate(repo)
    result = _greenwash(repo, "check", "--format", "json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "pass"
    finding = next(f for f in payload["findings"] if f["rule"] == "TEST_DISABLED")
    assert "COMPAT_GATE" in finding["deescalators"]


def test_rename_into_prod_earns_no_opaque_exemption(repo):
    """THREATMODEL 79 — a rename cannot invent pre-existing production.

    Rename folding keeps the *old* blob as the before side while the role
    comes from the *new* path, so `docs/rules.md` moved to `app/rules.csv`
    read as a modified production file that had in fact never existed. The
    diff manufactured the very unreadability it was then credited for. Only a
    real `git mv` exercises this — a .gwcase fixture has no rename status —
    so this is pinned here rather than in tests/cases/.
    """
    docs = repo / "docs"
    docs.mkdir()
    (docs / "rules.md").write_text("# Rules\n\n| code | value |\n| a | 1 |\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "add rules doc")

    app = repo / "app"
    app.mkdir()
    _git(repo, "mv", "docs/rules.md", "app/rules.csv")
    (app / "rules.csv").write_text("# Rules\n\n| code | value |\n| a | 9 |\n", encoding="utf-8")
    test_file = repo / "tests" / "test_billing.py"
    test_file.write_text(
        test_file.read_text(encoding="utf-8").replace("== 105.3", "> 0"), encoding="utf-8"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "weaken the oracle behind a renamed doc")

    result = _greenwash(repo, "check", "HEAD~1..HEAD", "--format", "json")
    assert result.returncode == 1, result.stdout
    payload = json.loads(result.stdout)
    weakened = [f for f in payload["findings"] if f["rule"] == "ASSERT_WEAKENED"]
    assert weakened and weakened[0]["severity"] == "high", payload["findings"]
    assert "REPAIR_EVIDENCE" not in weakened[0]["deescalators"]
