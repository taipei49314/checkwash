"""Changed test-shaped files outside the Python and JS/TS test parse gates (0.13, B6).

Covers PM-02 (inherited/mixin Python test classes), PM-03 (non-default Python
test filenames), and F-03/F-13 (non-default JS/TS test directories, suffixes,
Cypress, Jasmine, and Playwright layouts), together with channel routing and
machine-stdout invariance.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from checkwash.change import UnreadSide
from checkwash.frontends.javascript.coverage import CoverageGap
from checkwash.ir.model import IR
from checkwash.report.context import ReportContext
from checkwash.report.sarif import findings_to_sarif
from checkwash.report.term import render

ROOT = Path(__file__).resolve().parents[1]


def _git(repo: Path, *args: str) -> str:
    res = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return res.stdout.strip()


def _init_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "core.autocrlf", "false")
    for rel, content in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


def _commit(repo: Path, files: dict[str, str | None], msg: str = "head") -> None:
    for rel, content in files.items():
        target = repo / rel
        if content is None:
            _git(repo, "rm", "-q", rel)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="\n")
            _git(repo, "add", rel)
    _git(repo, "commit", "-q", "-m", msg)


def _run_cli(
    repo: Path,
    *args: str,
    stdin: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    env = {
        **os.environ,
        "PYTHONUTF8": "1",
        "NO_COLOR": "1",
        "GREENWASH_TODAY": "2026-11-15",
    }
    return subprocess.run(
        [sys.executable, "-m", "checkwash", *args, "--repo", str(repo)],
        input=stdin,
        env=env,
        capture_output=True,
        timeout=60,
    )


@pytest.mark.parametrize(
    ("rel", "base_body", "head_body"),
    [
        # PM-02: inherited/mixin Python test classes in uncollected modules
        (
            "tests/base.py",
            "class PricingChecks:\n    def test_total(self):\n        assert self.compute() == 97.2\n",
            "class PricingChecks:\n    def test_total(self):\n        assert self.compute() > 0\n",
        ),
        (
            "tests/cart_base.py",
            "import unittest\n\nclass CartBase(unittest.TestCase):\n    def test_cart(self):\n        self.assertEqual(1 + 1, 2)\n",
            "import unittest\n\nclass CartBase(unittest.TestCase):\n    @unittest.skip('later')\n    def test_cart(self):\n        self.assertEqual(1 + 1, 2)\n",
        ),
        # PM-03: non-default Python test filenames
        (
            "tests/pricing_tests.py",
            "def test_total():\n    assert 97.2 == 97.2\n",
            "def test_total():\n    assert 97.2 > 0\n",
        ),
        (
            "src/shopcart/tests.py",
            "import pytest\n\ndef test_total():\n    assert 97.2 == 97.2\n",
            "import pytest\n\n@pytest.mark.skip\ndef test_total():\n    assert 97.2 == 97.2\n",
        ),
        (
            "spec/pricing_spec.py",
            "def test_total():\n    assert 97.2 == 97.2\n",
            "def test_total():\n    pass\n",
        ),
        (
            "tests/testpricing.py",
            "def test_total():\n    assert 97.2 == 97.2\n",
            "def test_total():\n    assert True\n",
        ),
        (
            "tests/check_pricing.py",
            "def test_total():\n    assert 97.2 == 97.2\n",
            "def test_total():\n    assert True\n",
        ),
        (
            "unit_tests/pricing_tests.py",
            "def test_total():\n    assert 97.2 == 97.2\n",
            "def test_total():\n    assert True\n",
        ),
    ],
)
def test_python_unanalysed_test_files_emit_summary_note(
    tmp_path: Path, rel: str, base_body: str, head_body: str
) -> None:
    repo = _init_repo(
        tmp_path,
        {
            "src/shopcart/pricing.py": "def total():\n    return 97.2\n",
            rel: base_body,
        },
    )
    _commit(repo, {rel: head_body})
    res = _run_cli(repo, "check", "HEAD~1..HEAD")
    stdout = res.stdout.decode("utf-8")
    stderr = res.stderr.decode("utf-8")
    expected = f"analysis incomplete: 1 test-shaped file not analysed: {rel}"
    assert res.returncode == 0
    assert "checkwash: analysis incomplete; no known tampering pattern detected" in stdout
    assert f"! {expected}" in stdout
    assert f"checkwash: {expected}" in stderr


def test_python_role_override_and_deleted_django_tests_py_emit_note(tmp_path: Path) -> None:
    repo = _init_repo(
        tmp_path,
        {
            ".checkwash/config.toml": '[roles]\ntest = ["src/shopcart/tests.py"]\n',
            "src/shopcart/tests.py": "def test_discount():\n    assert 1 == 1\n",
        },
    )
    _commit(repo, {"src/shopcart/tests.py": None})
    res = _run_cli(repo, "check", "HEAD~1..HEAD")
    stdout = res.stdout.decode("utf-8")
    stderr = res.stderr.decode("utf-8")
    expected = "analysis incomplete: 1 test-shaped file not analysed: src/shopcart/tests.py"
    assert res.returncode == 0
    assert f"! {expected}" in stdout
    assert f"checkwash: {expected}" in stderr


@pytest.mark.parametrize(
    ("rel", "base_body", "head_body"),
    [
        # F-03: Jest / Mocha / node:test under tests/, *.unit.js, Jasmine spec/, Cypress *.cy.js, e2e/*.ts
        (
            "tests/billing.js",
            "test('adds tax', () => { expect(105.3).toBe(105.3); });\n",
            "test('adds tax', () => { expect(105.3).toBeDefined(); });\n",
        ),
        (
            "src/billing.unit.js",
            "test('adds tax', () => { expect(105.3).toBe(105.3); });\n",
            "test.skip('adds tax', () => { expect(105.3).toBe(105.3); });\n",
        ),
        (
            "spec/billingSpec.js",
            "it('adds tax', () => { expect(105.3).toBe(105.3); });\n",
            "xit('adds tax', () => { expect(105.3).toBe(105.3); });\n",
        ),
        (
            "cypress/e2e/invoice.cy.js",
            "describe('invoice', () => { it('shows total', () => { cy.visit('/'); }); });\n",
            "describe('invoice', () => { it.skip('shows total', () => { cy.visit('/'); }); });\n",
        ),
        (
            "e2e/invoice.ts",
            "test('shows total', () => { expect(105.3).toBe(105.3); });\n",
            "test('shows total', () => { expect(105.3).toBeDefined(); });\n",
        ),
        # F-13: Playwright layouts outside Jest's *.spec.* / *.test.* stems
        (
            "playwright/checkout.ts",
            "import { test, expect } from '@playwright/test';\ntest('checkout', async ({ page }) => { await expect(page).toHaveTitle('Shop'); });\n",
            "import { test, expect } from '@playwright/test';\ntest('checkout', async ({ page }) => {});\n",
        ),
        (
            "src/checkout.e2e-flow.ts",
            "import { test, expect } from '@playwright/test';\ntest('checkout', async () => { expect(1).toBe(1); });\n",
            "import { test } from '@playwright/test';\ntest('checkout', async () => {});\n",
        ),
        (
            "tests/dynamic_loop.js",
            "cases.forEach(({ name }) => { it(name, () => { expect(1).toBe(1); }); });\n",
            "cases.forEach(({ name }) => { it.skip(name, () => { expect(1).toBe(1); }); });\n",
        ),
    ],
)
def test_js_ts_unanalysed_test_files_emit_summary_note(
    tmp_path: Path, rel: str, base_body: str, head_body: str
) -> None:
    repo = _init_repo(
        tmp_path,
        {
            "package.json": '{"name": "demo", "private": true}\n',
            rel: base_body,
        },
    )
    _commit(repo, {rel: head_body})
    res = _run_cli(repo, "check", "HEAD~1..HEAD")
    stdout = res.stdout.decode("utf-8")
    stderr = res.stderr.decode("utf-8")
    expected = f"analysis incomplete: 1 test-shaped file not analysed: {rel}"
    assert res.returncode == 0
    assert "checkwash: analysis incomplete; no known tampering pattern detected" in stdout
    assert f"! {expected}" in stdout
    assert f"checkwash: {expected}" in stderr


def test_machine_stdout_channels_stay_unchanged(tmp_path: Path) -> None:
    repo = _init_repo(
        tmp_path,
        {
            "tests/base.py": "class PricingChecks:\n    def test_total(self):\n        assert self.total() == 97.2\n",
            "tests/billing.js": "test('adds tax', () => { expect(105.3).toBe(105.3); });\n",
        },
    )
    session_in = json.dumps(
        {"session_id": "s-b6", "hook_event_name": "SessionStart", "source": "startup"}
    ).encode("utf-8")
    assert _run_cli(repo, "hook", "session-start", stdin=session_in).returncode == 0

    _commit(
        repo,
        {
            "tests/base.py": "class PricingChecks:\n    def test_total(self):\n        assert self.total() > 0\n",
            "tests/billing.js": "test.skip('adds tax', () => { expect(105.3).toBe(105.3); });\n",
        },
    )
    expected_note = "analysis incomplete: 2 test-shaped files not analysed: tests/base.py, tests/billing.js"

    # 1. --format json: stdout unchanged; stderr carries the note
    cov_path = tmp_path / "cov.json"
    json_res = _run_cli(
        repo, "check", "HEAD~1..HEAD", "--format", "json", "--coverage-report", str(cov_path)
    )
    assert json_res.returncode == 0
    payload = json.loads(json_res.stdout.decode("utf-8"))
    assert set(payload) == {
        "checkwash_findings_version",
        "config_errors",
        "findings",
        "run",
        "skipped_files",
        "summary",
        "verdict",
    }
    assert payload["findings"] == []
    assert payload["verdict"] == "pass"
    assert "unanalysed" not in json_res.stdout.decode("utf-8")
    assert json_res.stderr.decode("utf-8").replace("\r\n", "\n") == f"checkwash: {expected_note}\n"

    # 2. --coverage-report: unchanged
    cov_payload = json.loads(cov_path.read_text(encoding="utf-8"))
    assert cov_payload["status"] == "no_known_gaps"
    assert cov_payload["files"] == []
    assert cov_payload["gaps"] == []

    # 3. --emit-ir: stdout unchanged; stderr carries the note
    ir_res = _run_cli(repo, "check", "HEAD~1..HEAD", "--emit-ir")
    assert ir_res.returncode == 0
    ir_payload = json.loads(ir_res.stdout.decode("utf-8"))
    assert "unanalysed" not in ir_res.stdout.decode("utf-8")
    assert len(ir_payload["files"]) == 2
    assert ir_res.stderr.decode("utf-8").replace("\r\n", "\n") == f"checkwash: {expected_note}\n"

    # 4. --format sarif: toolExecutionNotifications carries the warning
    sarif_res = _run_cli(repo, "check", "HEAD~1..HEAD", "--format", "sarif")
    assert sarif_res.returncode == 0
    sarif = json.loads(sarif_res.stdout.decode("utf-8"))
    inv = sarif["runs"][0]["invocations"][0]
    assert inv == {
        "executionSuccessful": True,
        "toolExecutionNotifications": [
            {"level": "warning", "message": {"text": expected_note}},
        ],
    }

    # 5. --format hook-json (including Stop-hook session window): stdout is "{}\n"
    (repo / "tests" / "pricing_tests.py").write_text(
        "def test_extra():\n    assert 1 > 0\n", encoding="utf-8", newline="\n"
    )
    stop_in = json.dumps(
        {"session_id": "s-b6", "hook_event_name": "Stop", "stop_hook_active": False}
    ).encode("utf-8")
    hook_res = _run_cli(
        repo, "check", "--format", "hook-json", "--hook-input", "stdin", stdin=stop_in
    )
    assert hook_res.returncode == 0
    assert hook_res.stdout == b"{}\n"

    # 6. hook pre-tool-use: stdout is "{}\n"
    pre_in = json.dumps(
        {
            "session_id": "s-b6",
            "hook_event_name": "PreToolUse",
            "tool_name": "Edit",
            "cwd": str(repo),
            "tool_input": {
                "file_path": str(repo / "tests" / "base.py"),
                "old_string": "assert self.total() > 0",
                "new_string": "assert True",
            },
        }
    ).encode("utf-8")
    pre_res = _run_cli(repo, "hook", "pre-tool-use", stdin=pre_in)
    assert pre_res.returncode == 0
    assert pre_res.stdout == b"{}\n"


def test_findings_coexist_with_unanalysed_note_without_switching_header(tmp_path: Path) -> None:
    repo = _init_repo(
        tmp_path,
        {
            "src/calc.py": "def compute():\n    return 10\n",
            "tests/test_real.py": "from calc import compute\n\ndef test_real():\n    assert compute() == 10\n",
            "tests/pricing_tests.py": "def test_other():\n    assert 20 == 20\n",
        },
    )
    _commit(
        repo,
        {
            "tests/test_real.py": "from calc import compute\n\ndef test_real():\n    assert compute() > 0\n",
            "tests/pricing_tests.py": "def test_other():\n    assert 20 > 0\n",
        },
    )
    res = _run_cli(repo, "check", "HEAD~1..HEAD")
    stdout = res.stdout.decode("utf-8")
    assert res.returncode == 1
    assert "1 finding(s) at or above high" in stdout
    assert "analysis incomplete; no known tampering pattern detected" not in stdout
    assert "! analysis incomplete: 1 test-shaped file not analysed: tests/pricing_tests.py" in stdout


def test_notification_ordering_and_truncation_across_term_and_sarif() -> None:
    ctx = ReportContext(
        coverage_gaps=[
            CoverageGap(
                path="test/a.test.js",
                side="after",
                line=3,
                column=5,
                callee="expect(...).toHaveText",
                reason="unmodelled matcher",
            )
        ],
        importer_gaps=[
            "analysis incomplete: search limit reached, so unchanged tests that import helpers were not read for their expected values"
        ],
        unanalysed_test_files=[
            "tests/e_tests.py",
            "tests/d_tests.py",
            "tests/c_tests.py",
            "tests/b_tests.py",
            "tests/a\x07_tests.py",
            "tests/f_tests.py",
        ],
    )
    unread = [UnreadSide(path="docs/huge.bin", side="head", size=1_500_000, limit=1_000_000)]
    ir = IR(base="base", head="head")

    term_out = render(ir, [], "pass", "high", context=ctx, unread=unread)
    expected_b6 = (
        "analysis incomplete: 6 test-shaped files not analysed: "
        "'tests/a\\x07_tests.py', tests/b_tests.py, tests/c_tests.py, tests/d_tests.py and 2 more"
    )
    cov_idx = term_out.index("! analysis incomplete: after test/a.test.js:3:5:")
    imp_idx = term_out.index("! analysis incomplete: search limit reached")
    b6_idx = term_out.index(f"! {expected_b6}")
    unr_idx = term_out.index(f"! {unread[0].note()}")
    assert cov_idx < imp_idx < b6_idx < unr_idx

    sarif = json.loads(findings_to_sarif(ir, [], context=ctx, unread=unread))
    notes = sarif["runs"][0]["invocations"][0]["toolExecutionNotifications"]
    assert [n["message"]["text"] for n in notes] == [
        ctx.coverage_gaps[0].message(),
        ctx.importer_gaps[0],
        expected_b6,
        unread[0].note(),
    ]
    assert notes[2] == {"level": "warning", "message": {"text": expected_b6}}


def test_controls_analysed_tests_pure_helpers_and_synthetic_renames_stay_quiet(
    tmp_path: Path,
) -> None:
    repo = _init_repo(
        tmp_path,
        {
            ".checkwash/config.toml": '[roles]\nguardrail = ["docs/policy_tests.py"]\n',
            "tests/test_collected.py": "def test_ok():\n    assert 1 == 1\n",
            "tests/helpers.py": "def make_cart():\n    return {'items': []}\n",
            "tests/testutils.py": "def build_fixture():\n    return 42\n",
            "tests/testing.py": "DEFAULT_TAX = 0.08\n",
            "tests/helper.js": "export function suite() { return /a/\n  .test('a'); }\n",
            "tests/__mocks__/api.js": "export const fetch = () => {};\n",
            "src/models.py": "class TestResult:\n    __test__ = False\n    code = 200\n",
            "jest.config.js": "module.exports = { testMatch: ['**/*.test.js'] };\n",
            "types/billing.spec.d.ts": "export interface BillingSpec { total: number; }\n",
            "venv/Lib/site-packages/pkg/foo_tests.py": "def test_vendored():\n    assert True\n",
            "docs/policy_tests.py": "POLICY = 1\n",
            "test/moved.js": "const x = 1;\n",
        },
    )
    _git(repo, "mv", "test/moved.js", "src/moved.js")
    _commit(
        repo,
        {
            "tests/test_collected.py": "def test_ok():\n    assert 1 == 1\n\ndef test_two():\n    assert 2 == 2\n",
            "tests/helpers.py": "def make_cart():\n    return {'items': [1]}\n",
            "tests/testutils.py": "def build_fixture():\n    return 43\n",
            "tests/testing.py": "DEFAULT_TAX = 0.09\n",
            "tests/helper.js": "export function suite() { return /b/\n  .test('b'); }\n",
            "tests/__mocks__/api.js": "export const fetch = () => null;\n",
            "src/models.py": "class TestResult:\n    __test__ = False\n    code = 201\n",
            "jest.config.js": "module.exports = { testMatch: ['**/*.spec.js'] };\n",
            "types/billing.spec.d.ts": "export interface BillingSpec { total: string; }\n",
            "venv/Lib/site-packages/pkg/foo_tests.py": "def test_vendored():\n    assert False\n",
            "docs/policy_tests.py": "POLICY = 2\n",
        },
    )
    res = _run_cli(repo, "check", "HEAD~1..HEAD")
    stdout = res.stdout.decode("utf-8")
    stderr = res.stderr.decode("utf-8")
    assert "test-shaped file" not in stdout
    assert "test-shaped file" not in stderr


def test_unparseable_judged_python_test_uses_unparseable_test_without_b6_duplicate(
    tmp_path: Path,
) -> None:
    repo = _init_repo(
        tmp_path,
        {"tests/base.py": "class PricingChecks:\n    def test_total(self):\n        assert 1 == 1\n"},
    )
    _commit(repo, {"tests/base.py": "def broken(:\n"})
    res = _run_cli(repo, "check", "HEAD~1..HEAD")
    stdout = res.stdout.decode("utf-8")
    stderr = res.stderr.decode("utf-8")
    assert "TEST_FILE_UNPARSEABLE" in stdout
    assert "test-shaped file" not in stdout
    assert "test-shaped file" not in stderr


def test_js_test_call_linear_time_on_large_masked_strings() -> None:
    from checkwash.unanalysed_tests import _js_side_has_tests

    payload = (
        ("function suite() { return 1; }\n" * 5000)
        + f'test("{"a" * 300_000}", () => {{ expect(1).toBe(1); }});\n'
    ).encode("utf-8")
    t0 = time.perf_counter()
    assert _js_side_has_tests(payload, in_js_test_dir=True) is True
    elapsed = time.perf_counter() - t0
    assert elapsed < 1.0, f"expected linear scan < 1.0s, took {elapsed:.3f}s"


def test_unsplit_renames_attribute_unanalysed_side_accurately(tmp_path: Path) -> None:
    repo = _init_repo(
        tmp_path,
        {
            "e2e/invoice.ts": "test('shows total', () => { expect(105.3).toBe(105.3); });\n",
            "spec/pricing_spec.py": "def test_total():\n    assert 97.2 == 97.2\n",
            "src/legacy.py": "VALUE = 1\n",
            "src/check_schema.py": "def validate_schema():\n    return True\n",
        },
    )
    (repo / "dist").mkdir(parents=True, exist_ok=True)
    _git(repo, "mv", "e2e/invoice.ts", "dist/invoice.ts")
    _git(repo, "mv", "spec/pricing_spec.py", "src/archive.txt")
    _git(repo, "mv", "src/legacy.py", "e2e/migrated.ts")
    (repo / "e2e" / "migrated.ts").write_text(
        "test('migrated', () => { expect(1).toBe(1); });\n",
        encoding="utf-8",
        newline="\n",
    )
    _git(repo, "add", "e2e/migrated.ts")
    (repo / "tests").mkdir(parents=True, exist_ok=True)
    _git(repo, "mv", "src/check_schema.py", "tests/helpers.py")
    _git(repo, "commit", "-q", "-m", "renames")

    res = _run_cli(repo, "check", "HEAD~1..HEAD")
    stdout = res.stdout.decode("utf-8")
    stderr = res.stderr.decode("utf-8")
    expected = (
        "analysis incomplete: 3 test-shaped files not analysed: "
        "e2e/invoice.ts, e2e/migrated.ts, spec/pricing_spec.py"
    )
    assert res.returncode == 0
    assert f"! {expected}" in stdout
    assert f"checkwash: {expected}" in stderr
    assert "src/archive.txt" not in stdout
    assert "tests/helpers.py" not in stdout
    assert "src/check_schema.py" not in stdout


def test_js_runner_names_inside_strings_and_prod_js_stay_quiet(tmp_path: Path) -> None:
    repo = _init_repo(
        tmp_path,
        {
            "tests/messages.ts": (
                "export const HELP = \"import { test } from '@playwright/test'; Deno.test('x')\";\n"
            ),
            "src/app.js": "export function render() { return 'ok'; }\n",
        },
    )
    _commit(
        repo,
        {
            "tests/messages.ts": (
                "export const HELP = \"require('mocha'); import 'cypress'; Deno.test('y')\";\n"
            ),
            "src/app.js": "export function render() { return 'updated'; }\n",
        },
    )
    res = _run_cli(repo, "check", "HEAD~1..HEAD")
    assert "test-shaped file" not in res.stdout.decode("utf-8")
    assert "test-shaped file" not in res.stderr.decode("utf-8")


def test_dunder_test_false_opts_out_helpers_but_keeps_pm02_mixins(tmp_path: Path) -> None:
    repo = _init_repo(
        tmp_path,
        {
            "tests/models.py": (
                "class TestResultFactory:\n"
                "    __test__ = False\n"
                "    code = 200\n"
                "    def test_payload(self):\n"
                "        return {'ok': 1}\n"
            ),
            "tests/support.py": "__test__ = False\n\ndef test_data():\n    return [1, 2]\n",
            "tests/abstract_base.py": (
                "class BasePricingChecks:\n"
                "    __test__ = False\n"
                "    def test_total(self):\n"
                "        assert self.compute() == 97.2\n"
            ),
        },
    )
    _commit(
        repo,
        {
            "tests/models.py": (
                "class TestResultFactory:\n"
                "    __test__ = False\n"
                "    code = 201\n"
                "    def test_payload(self):\n"
                "        return {'ok': 2}\n"
            ),
            "tests/support.py": "__test__ = False\n\ndef test_data():\n    return [1, 2, 3]\n",
            "tests/abstract_base.py": (
                "class BasePricingChecks:\n"
                "    __test__ = False\n"
                "    def test_total(self):\n"
                "        assert self.compute() > 0\n"
            ),
        },
    )
    res = _run_cli(repo, "check", "HEAD~1..HEAD")
    stdout = res.stdout.decode("utf-8")
    stderr = res.stderr.decode("utf-8")
    expected = "analysis incomplete: 1 test-shaped file not analysed: tests/abstract_base.py"
    assert f"! {expected}" in stdout
    assert f"checkwash: {expected}" in stderr
    assert "tests/models.py" not in stdout
    assert "tests/support.py" not in stdout


def test_bidi_format_characters_escaped_in_unanalysed_note() -> None:
    from checkwash.unanalysed_tests import unanalysed_test_note

    note = unanalysed_test_note(["tests/evil\u202epy.txt.py"])
    assert "\u202e" not in note
    assert "\\u202e" in note
