"""Direct asserted-call replacement with literal expectation retained (#132 C1)."""
import datetime
import os
import subprocess
import sys

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze

PREFIX = "from app.billing import total\n"
BASE = PREFIX + "def test_total():\n    assert total([1, 2]) == 3\n"


def judge(before, after, extra=None):
    changes = [FileChange("tests/test_billing.py", "modified", before.encode(), after.encode())]
    sources = {"app/__init__.py": b"", "app/billing.py": b"def total(values):\n    return 0\n",
               "tests/test_billing.py": after.encode(), **(extra or {})}
    return analyze(changes, Config(), Contract(), [], datetime.date(2026, 9, 21),
                   root_reader=sources.get, root_path_lister=lambda: sorted(sources),
                   root_batch_reader=lambda paths: {p: sources.get(p) for p in paths})[1]


@pytest.mark.parametrize("setup,callee", [
    ("", "sum"),
    ("import builtins\n", "builtins.sum"),
    ("from builtins import sum as standin\n", "standin"),
    ("def standin(values):\n    return sum(values)\n", "standin"),
    ("def standin(values):\n    return 3\n", "standin"),
    ("standin = lambda values: 3\n", "standin"),
    ("from unittest.mock import Mock\nstandin = Mock(return_value=3)\n", "standin"),
    ("import unittest.mock as mock\nstandin = mock.MagicMock(return_value=3)\n", "standin"),
])
def test_exact_subject_builtin_local_stub_and_mock_matrix(setup, callee):
    after = PREFIX + setup + "def test_total():\n    assert " + callee + "([1, 2]) == 3\n"
    hits = [f for f in judge(BASE, after) if f.rule == "TEST_PATCHES_SUBJECT"]
    assert len(hits) == 1 and hits[0].severity == "high"
    assert "app.billing.total" in hits[0].message


@pytest.mark.parametrize("setup", [
    "    def standin(values):\n        return 3\n",
    "    standin = lambda values: 3\n",
    "    standin = Mock(return_value=3)\n",
])
def test_function_local_standin_is_resolved_at_the_oracle(setup):
    after = PREFIX + "from unittest.mock import Mock\ndef test_total():\n" + setup + "    assert standin([1, 2]) == 3\n"
    assert any(f.rule == "TEST_PATCHES_SUBJECT" for f in judge(BASE, after))


@pytest.mark.parametrize("before,after", [
    (BASE, PREFIX + "def standin(values):\n    return total(values)\ndef test_total():\n    assert standin([1, 2]) == 3\n"),
    (BASE, "from app.billing import total as renamed\ndef test_total():\n    assert renamed([1, 2]) == 3\n"),
    (BASE, PREFIX + "def test_total():\n    nearby = sum([1, 2])\n    assert total([1, 2]) == 3\n"),
    (PREFIX + "def test_total():\n    assert total([1, 2]) == sum([1, 2])\n",
     PREFIX + "def test_total():\n    assert total([1, 2]) == max([1, 2])\n"),
    ("from external.billing import total\ndef test_total():\n    assert total([1, 2]) == 3\n",
     "from external.billing import total\ndef test_total():\n    assert sum([1, 2]) == 3\n"),
    ("import time\ndef test_total():\n    assert time.time() == 3\n",
     "import time\ndef test_total():\n    assert max() == 3\n"),
    (BASE, PREFIX + "sum = total\ndef test_total():\n    assert sum([1, 2]) == 3\n"),
    (BASE, PREFIX + "from unittest.mock import Mock\nstandin = Mock(wraps=total)\ndef test_total():\n    assert standin([1, 2]) == 3\n"),
])
def test_honest_helpers_aliases_expected_side_and_unrelated_calls_do_not_install_subject(before, after):
    assert not [f for f in judge(before, after) if f.rule == "TEST_PATCHES_SUBJECT"]


def test_input_or_answer_change_alone_is_not_direct_callable_replacement():
    assert not [f for f in judge(BASE, BASE.replace("[1, 2]", "[3]")) if f.rule == "TEST_PATCHES_SUBJECT"]
    assert not [f for f in judge(BASE, BASE.replace("== 3", "== 4")) if f.rule == "TEST_PATCHES_SUBJECT"]


@pytest.mark.parametrize('hops', [1, 2])
def test_replacement_cannot_hide_behind_local_result_aliases(hops):
    assignment = '    got = total([1, 2])\n'
    if hops == 2:
        assignment += '    result = got\n'
    name = 'got' if hops == 1 else 'result'
    before = PREFIX + 'def test_total():\n' + assignment + f'    assert {name} == 3\n'
    after = before.replace('= total(', '= sum(')
    assert any(f.rule == 'TEST_PATCHES_SUBJECT' and f.severity == 'high' for f in judge(before, after))


def test_same_production_call_moved_to_a_result_local_is_not_a_standin():
    after = PREFIX + 'def test_total():\n    got = total([1, 2])\n    assert got == 3\n'
    assert not [f for f in judge(BASE, after) if f.rule == 'TEST_PATCHES_SUBJECT']


def test_callable_parameter_named_like_builtin_cannot_prove_a_pure_standin():
    before = PREFIX + 'def test_total():\n    assert total(total) == 3\n'
    after = PREFIX + 'def standin(sum):\n    return sum([1, 2])\ndef test_total():\n    assert standin(total) == 3\n'
    assert not [f for f in judge(before, after) if f.rule == 'TEST_PATCHES_SUBJECT']


def test_unknown_local_result_rebinding_cannot_reuse_an_earlier_call():
    before = PREFIX + 'def test_total():\n    got = total([1, 2])\n    got = unknown()\n    assert got == 3\n'
    after = before.replace('= total(', '= sum(')
    assert not [f for f in judge(before, after) if f.rule == 'TEST_PATCHES_SUBJECT']


@pytest.mark.parametrize("setup,callee", [
    ("", "sum"), ("def standin(values):\n    return 3\n", "standin"),
    ("from unittest.mock import Mock\nstandin = Mock(return_value=3)\n", "standin"),
])
def test_real_pytest_subject_replacement_masks_bug_and_is_blocked(tmp_path, setup, callee):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_bytes(b"")
    (tmp_path / "app" / "billing.py").write_text("def total(values):\n    return 0\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    test = tmp_path / "tests" / "test_billing.py"
    test.write_text(BASE, encoding="utf-8")
    env = {**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONPATH": ""}
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"]
    before = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert before.returncode == 1, before.stdout + before.stderr
    after_source = PREFIX + setup + "def test_total():\n    assert " + callee + "([1, 2]) == 3\n"
    test.write_text(after_source, encoding="utf-8")
    after = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert after.returncode == 0, after.stdout + after.stderr
    assert any(f.rule == "TEST_PATCHES_SUBJECT" and f.severity == "high" for f in judge(BASE, after_source))
