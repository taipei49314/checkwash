"""Input table evidence is about the same callable on both sides."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from test_issue_expectation_families import run


PRODUCTION = "def first(xs):\n    return xs[0]\ndef last(xs):\n    return xs[-1]\n"


def source(row="([42, 0], 42)", call="first(xs)", *, prefix="", binding="", args="xs, expected"):
    return (
        "import pytest\nfrom app.prod import first, last\n" + prefix
        + '@pytest.mark.parametrize("xs,expected", [' + row + "])\n"
        + "def test_value(" + args + "):\n" + binding
        + "    assert " + call + " == expected\n"
    )


def input_findings(before, after):
    return [f for f in run(before, after, PRODUCTION)[1] if f.rule == "SUBJECT_INPUT_CHANGED"]


@pytest.mark.parametrize("before_call,after_call", [
    ("first(xs)", "last(xs)"),
    ("subject.first(xs)", "subject.last(xs)"),
    ("first(xs)", "xs[-1]"),
    ("first(xs)", "first(xs, 0)"),
    ("first(xs=xs)", "first(values=xs)"),
])
def test_changed_callable_or_call_shape_is_not_same_subject_evidence(before_call, after_call):
    assert not input_findings(
        source(call=before_call), source("([0, 42], 42)", after_call),
    )


@pytest.mark.parametrize("provider", ["local", "fixture", "constant"])
def test_changed_named_provider_withholds_table_evidence(provider):
    options = {
        "local": ({"binding": "    subject = first\n"}, {"binding": "    subject = last\n"}),
        "fixture": (
            {"prefix": "@pytest.fixture\ndef subject():\n    return first\n", "args": "xs, expected, subject"},
            {"prefix": "@pytest.fixture\ndef subject():\n    return last\n", "args": "xs, expected, subject"},
        ),
        "constant": ({"prefix": "subject = first\n"}, {"prefix": "subject = last\n"}),
    }
    before, after = options[provider]
    assert not input_findings(
        source(call="subject(xs)", **before), source("([0, 42], 42)", "subject(xs)", **after),
    )


@pytest.mark.parametrize("kwargs", [
    {},
    {"call": "subject(xs)", "binding": "    subject = first\n"},
    {"call": "subject(xs)", "prefix": "@pytest.fixture\ndef subject():\n    return first\n", "args": "xs, expected, subject"},
])
def test_unchanged_provider_still_detects_rewritten_input(kwargs):
    findings = input_findings(source(**kwargs), source("([0, 42], 42)", **kwargs))
    assert len(findings) == 1 and findings[0].severity == "high"


def test_reformatted_callable_retains_table_evidence():
    assert input_findings(source(), source("([0, 42], 42)", "(first)(xs)"))


@pytest.mark.parametrize("prefix", ["", "    assert 1 == 1\n"])
def test_same_unit_bindings_do_not_hide_a_changed_reaching_provider(prefix):
    before = source(call="subject(xs)", binding=prefix + "    subject = first\n")
    before += "    subject = last\n"
    after = source("([0, 42], 42)", "subject(xs)",
                   binding=prefix + "    subject = first\n    subject = last\n")
    assert not input_findings(before, after)


def test_changed_first_assertion_does_not_hide_an_unchanged_provider_later():
    before = source() + "    assert last(xs) == expected\n"
    after = source("([0, 42], 42)", "last(xs)") + "    assert last(xs) == expected\n"
    assert input_findings(before, after)


def test_reorder_and_addition_do_not_invent_a_rewritten_input():
    before = source("([42, 0], 42), ([7, 0], 7)")
    after = source("([7, 0], 7), ([42, 0], 42), ([9, 0], 9)")
    assert not input_findings(before, after)


def test_changed_callee_and_matching_data_pass_real_pytest_and_cli(tmp_path):
    package = tmp_path / "src" / "app"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "prod.py").write_text(PRODUCTION, encoding="utf-8")
    (tmp_path / "pytest.ini").write_text("[pytest]\npythonpath = src\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONDONTWRITEBYTECODE="1")
    env.pop("PYTHONPATH", None)

    def command(*args, environment=env):
        result = subprocess.run(args, cwd=tmp_path, env=environment, capture_output=True,
                                text=True, encoding="utf-8", timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout

    command("git", "init", "-q")
    command("git", "config", "user.name", "Regression")
    command("git", "config", "user.email", "regression@example.invalid")
    for text in (source(), source("([0, 42], 42)", "last(xs)")):
        (tests / "test_case.py").write_text(text, encoding="utf-8")
        output = command(sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests")
        assert "1 passed" in output
        command("git", "add", "src", "tests", "pytest.ini")
        command("git", "-c", "commit.gpgsign=false", "commit", "-qm", "case")
    src = str(Path(__file__).resolve().parents[1] / "src")
    report = json.loads(command(sys.executable, "-m", "checkwash", "check", "HEAD~1..HEAD",
                                "--format", "json", environment=dict(env, PYTHONPATH=src)))
    assert report["verdict"] == "pass" and report["findings"] == []
