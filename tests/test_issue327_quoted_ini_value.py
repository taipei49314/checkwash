"""Issue #327: a quoted INI value is continued, as iniconfig continues it.

`collection_settings` serves INI and TOML files alike and read a value's kind
from its first line alone: one that opened with a quote was a TOML string,
never continued. In an INI file the quote is part of the value, and
iniconfig continues it over the indented lines after it, so a selector
added beneath `addopts = "-ra"` in `setup.cfg` or `pytest.ini` ran
(`['-ra', '-m', 'not slow']`) and passed with CI_WORKFLOW_TOUCHED at warn.

Now the section decides too: `[tool:pytest]`, which only `setup.cfg` holds,
is INI; `[tool.pytest.ini_options]`, which only `pyproject.toml` holds, is
TOML; and in `[pytest]`, INI in `pytest.ini` and `tox.ini` but TOML in
`pytest.toml`, a quoted value continues up to a line that reads as a TOML
setting.
"""
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.pytest_collection import _TOML_SETTING, collection_settings

PROD = {"app/__init__.py": b"", "app/billing.py": b"def total():\n    return 78.75\n"}
UNIT = b"from app.billing import total\n\n\ndef test_total():\n    assert total() == 78.75\n"
SLOW = (b"import pytest\nfrom app.billing import total\n\n\n@pytest.mark.slow\n"
        b"def test_slow():\n    assert total() == 78.75\n")
TREE = {**PROD, "tests/test_total.py": UNIT, "tests/test_slow.py": SLOW}
SELECTOR = "CI configuration changed; test command weakened: resolved pytest collection option introduced: -m not slow"


def judge(path, before, after):
    snapshot = {**TREE, path: after}
    changes = [FileChange(path, "modified", before, after)]
    _ir, findings, verdict = analyze(changes, Config(), Contract(), [], datetime.date(2026, 10, 7),
                                     root_reader=snapshot.get, root_path_lister=lambda: sorted(snapshot),
                                     root_batch_reader=lambda paths: {p: snapshot.get(p) for p in paths})
    return verdict, [(f.severity, f.message) for f in findings if f.rule == "CI_WORKFLOW_TOUCHED"]


# --- the issue's rows ---------------------------------------------------------------------------

@pytest.mark.parametrize("path, before, after", [
    ("setup.cfg", b'[tool:pytest]\naddopts = "-ra"\n', b'[tool:pytest]\naddopts = "-ra"\n    -m "not slow"\n'),
    ("pytest.ini", b"[pytest]\naddopts = '-ra'\n", b"[pytest]\naddopts = '-ra'\n    -m 'not slow'\n"),
    ("tox.ini", b'[pytest]\naddopts = "-ra"\n', b'[pytest]\naddopts = "-ra"\n    -m "not slow"\n'),
    ("setup.cfg", b'[tool:pytest]\naddopts = "-ra"\n', b'[tool:pytest]\naddopts = "-ra" -m "not slow"\n'),
], ids=["Q1_setup_cfg", "Q2_pytest_ini", "tox_ini", "Q3_control_one_line"])
def test_a_selector_beneath_a_quoted_value_is_read(path, before, after):
    assert judge(path, before, after) == ("block", [("high", SELECTOR)])


def test_a_quoted_value_respelled_on_one_line_is_no_event():
    before = b'[tool:pytest]\naddopts = "-ra"\n    -m "not slow"\n'
    after = b'[tool:pytest]\naddopts = "-ra" -m "not slow"\n'
    assert judge("setup.cfg", before, after) == ("pass", [("warn", "CI configuration changed")])


# --- the value pytest reads ---------------------------------------------------------------------

@pytest.mark.parametrize("text, settings", [
    # INI: iniconfig continues a quoted value like any other, whatever its lines hold
    ('[tool:pytest]\naddopts = "-ra"\n    -m "not slow"\n', {"addopts": {("-ra", "-m", "not slow")}}),
    ('[tool:pytest]\naddopts = "-ra"\n    testpaths = tests\n', {"addopts": {("-ra", "testpaths", "=", "tests")}}),
    ("[pytest]\naddopts = '-ra'\n\n# selectors\n    -q\n", {"addopts": {("-ra", "-q")}}),
    ('[pytest]\naddopts = "-ra"\n    --deselect="tests/a.py::t"\n', {"addopts": {("-ra", "--deselect=tests/a.py::t")}}),
    # `[pytest]` in pytest.toml: an indented key after a string is a setting
    ('[pytest]\naddopts = "-ra"\n  testpaths = ["tests"]\n', {"addopts": {("-ra",)}, "testpaths": {("tests",)}}),
    # TOML: a string is never continued
    ('[tool.pytest.ini_options]\naddopts = "-ra"\n  testpaths = ["tests"]\n',
     {"addopts": {("-ra",)}, "testpaths": {("tests",)}}),
    ('[tool.pytest.ini_options]\naddopts = "-ra"\n  "-q"\n', {"addopts": {("-ra",)}}),
], ids=["tool_pytest_option", "tool_pytest_setting_shaped_line", "pytest_blank_and_comment_lines",
        "pytest_option_with_a_quoted_value", "pytest_toml_key", "toml_key", "toml_string_never_continued"])
def test_the_value_pytest_reads(text, settings):
    assert collection_settings(text) == settings


@pytest.mark.parametrize("line, toml", [
    ("  testpaths = tests", True),
    ('python_files="t_*.py"', True),
    ('  "testpaths" = ["tests"]', True),
    ("  tool.pytest = 1", True),
    ('    -m "not slow"', False),
    ('    --deselect="tests/a.py::t"', False),
    ("    tests/unit", False),
    ("    -ra", False),
], ids=["bare_key", "no_spaces", "quoted_key", "dotted_key", "option", "option_with_equals", "path", "flag"])
def test_a_line_that_reads_as_a_toml_setting(line, toml):
    assert bool(_TOML_SETTING.match(line)) is toml
