"""#424 Q8 on GitHub-hosted CI: a throwaway reproduction. Do not merge.

Owner ruling on #424, 2026-10-18 (issuecomment-6248631489), item 2: the
function-level `test_x.__test__ = False` is reproduced in a throwaway draft
pull request on GitHub-hosted CI, as #485 and #486 checked #479. The run uses
real pytest and checkwash on the issue's base file with a function-level
`test_total.__test__ = False` appended, and records what each reports. The pull
request is closed unmerged once the result is recorded.

The issue's base test file is kept as the issue gives it. `app/billing.py`
rounds the total, so the base test fails, and the appended line would take a
failing test out of the run, which is the case #424 describes.

Each test pins what reading the source predicts. A pass means exactly that was
observed; a failure's message records what was observed instead.

- pytest collects a function only while `getattr(obj, "__test__", True)` holds
  (`_pytest/python.py`, `pytest_pycollect_makeitem`, read in pytest 9.1.1), so
  after the appended line pytest has nothing to run: exit 5, "no tests ran".
- checkwash's Python frontend reads `__test__ = False` only when it is assigned
  to the plain name at module or class scope (`frontends/python/frontend.py`,
  `_test_attr_disabled`), and the #424 rebinding walk resolves an attribute
  target only to a class (`frontends/python/rebindings.py`, `_Walk.resolve`).
  The resolved collection inventory does read the function-level form, but
  only when the diff changes the root pytest configuration
  (`collection_inventory.py`), and this diff has none. So checkwash is
  expected to report nothing: exit 0, verdict pass, no finding.

Two controls check the harness itself: pytest runs the base test and it fails,
and checkwash, through the same two-commit repository, blocks the
module-level `__test__ = False` that it does read.
"""

import json
import os
import subprocess
import sys

import pytest

# The issue's base file, `tests/test_billing.py`, as #424 gives it.
BASE = (
    "from app.billing import total\n"
    "\n"
    "def test_total():\n"
    "    assert total([50.0, 28.75]) == 78.75\n"
)
# Q8: the function-level attribute, appended.
FUNCTION_LEVEL = BASE + "\ntest_total.__test__ = False\n"
# Control: the module-level attribute, which the frontend reads.
MODULE_LEVEL = BASE + "\n__test__ = False\n"
# round(78.75) is 79, so the base test fails.
BILLING = "def total(items):\n    return round(sum(items))\n"


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _project(root, test_source):
    _write(root / "app" / "__init__.py", "")
    _write(root / "app" / "billing.py", BILLING)
    _write(root / "tests" / "test_billing.py", test_source)


def _record(result):
    return (
        f"exit {result.returncode}\n--- stdout ---\n{result.stdout}"
        f"\n--- stderr ---\n{result.stderr}"
    )


def _pytest(root):
    env = {**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONUTF8": "1"}
    env.pop("PYTEST_ADDOPTS", None)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-rA", "-p", "no:cacheprovider", "tests"],
        cwd=root, env=env, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=120,
    )


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _checkwash(root, head_source):
    """Commit the base, then `head_source`, and run `checkwash check HEAD~1..HEAD`."""
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.name", "e2e")
    _git(root, "config", "user.email", "e2e@example.invalid")
    _git(root, "config", "commit.gpgsign", "false")
    _project(root, BASE)
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "base")
    _write(root / "tests" / "test_billing.py", head_source)
    _git(root, "commit", "-am", "head")
    result = subprocess.run(
        [sys.executable, "-m", "checkwash", "check", "HEAD~1..HEAD", "--format", "json"],
        cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={**os.environ, "CHECKWASH_TODAY": "2026-10-19", "NO_COLOR": "1", "PYTHONUTF8": "1"},
        timeout=300,
    )
    return result, _record(result)


def _payload(result, record):
    try:
        return json.loads(result.stdout)
    except ValueError:
        pytest.fail("checkwash printed no JSON\n" + record)


def test_q8_control_pytest_runs_the_base_test(tmp_path):
    _project(tmp_path, BASE)
    result = _pytest(tmp_path)
    record = _record(result)
    assert result.returncode == pytest.ExitCode.TESTS_FAILED, record
    assert "test_billing.py::test_total" in result.stdout, record
    assert "1 failed" in result.stdout, record


def test_q8_pytest_does_not_collect_the_function_level_attribute(tmp_path):
    _project(tmp_path, FUNCTION_LEVEL)
    result = _pytest(tmp_path)
    record = _record(result)
    assert result.returncode == pytest.ExitCode.NO_TESTS_COLLECTED, record
    assert "no tests ran" in result.stdout, record


def test_q8_control_checkwash_blocks_the_module_level_attribute(tmp_path):
    result, record = _checkwash(tmp_path, MODULE_LEVEL)
    assert result.returncode == 1, record
    payload = _payload(result, record)
    assert payload["verdict"] == "block", record
    assert any(
        finding["rule"] == "TEST_DISABLED" and finding["severity"] == "high"
        for finding in payload["findings"]
    ), record


def test_q8_checkwash_reports_nothing_for_the_function_level_attribute(tmp_path):
    result, record = _checkwash(tmp_path, FUNCTION_LEVEL)
    assert result.returncode == 0, record
    payload = _payload(result, record)
    assert payload["verdict"] == "pass", record
    assert payload["findings"] == [], record
