"""Issue #324: a multi-line pytest setting is read as pytest reads it.

`collection_settings` stopped a value's continuation at the first line that
held `=`, so a TOML array with `"--import-mode=importlib"` read as `[` and
an INI continuation that starts with `--cov=pkg` read as nothing. A selector
added after such a line passed with CI_WORKFLOW_TOUCHED at warn, where the
same edit to a one-line value blocked. An array whose first element sat on
the opening line was never continued at all, and an INI value continued
only when its first line was empty.

Now a TOML array runs to the line that closes it, and an INI value continues
over every indented line, as iniconfig reads it. A value that opens with a
quote is still read as a TOML string and never continued (#327).
"""
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.pytest_collection import _bracket_depth, collection_settings

PROD = {"app/__init__.py": b"", "app/billing.py": b"def total():\n    return 78.75\n"}
UNIT = b"from app.billing import total\n\n\ndef test_total():\n    assert total() == 78.75\n"
SLOW = (b"import pytest\nfrom app.billing import total\n\n\n@pytest.mark.slow\n"
        b"def test_slow():\n    assert total() == 78.75\n")
TREE = {**PROD, "tests/test_total.py": UNIT, "tests/test_slow.py": SLOW}
WORKFLOW = {".github/workflows/ci.yml": (
    b"name: ci\non: [pull_request]\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: pytest\n")}
SELECTOR = "CI configuration changed; test command weakened: resolved pytest collection option introduced: -m not slow"


def judge(before, after):
    before, after = {**WORKFLOW, **before}, {**WORKFLOW, **after}
    changes = [FileChange(p, "added" if p not in before else "deleted" if p not in after else "modified",
                          before.get(p), after.get(p))
               for p in sorted(before.keys() | after.keys()) if before.get(p) != after.get(p)]
    snapshot = {**TREE, **after}
    _ir, findings, verdict = analyze(changes, Config(), Contract(), [], datetime.date(2026, 10, 7),
                                     root_reader=snapshot.get, root_path_lister=lambda: sorted(snapshot),
                                     root_batch_reader=lambda paths: {p: snapshot.get(p) for p in paths})
    return verdict, [(f.severity, f.message) for f in findings if f.rule == "CI_WORKFLOW_TOUCHED"]


def pyproject(*elements, first_line=False):
    if first_line:
        body = f"addopts = [{elements[0]},\n" + "".join(f"    {e},\n" for e in elements[1:]) + "]\n"
    else:
        body = "addopts = [\n" + "".join(f"    {e},\n" for e in elements) + "]\n"
    return {"pyproject.toml": ("[tool.pytest.ini_options]\n" + body).encode()}


def setup_cfg(first, *lines):
    return {"setup.cfg": (f"[tool:pytest]\naddopts = {first}\n" + "".join(f"  {l}\n" for l in lines)).encode()}


# --- a selector added to a multi-line value -----------------------------------------------------

@pytest.mark.parametrize("before, after", [
    (pyproject('"-ra"', '"--import-mode=importlib"'),
     pyproject('"-ra"', '"--import-mode=importlib"', '"-m"', '"not slow"')),
    (pyproject('"-ra"', '"-q"', first_line=True), pyproject('"-ra"', '"-q"', '"-m"', '"not slow"', first_line=True)),
    (setup_cfg("", "--cov-report=term", "-rxXs"), setup_cfg("", "--cov-report=term", "-rxXs", "-m 'not slow'")),
    (setup_cfg("-ra", "--strict-markers"), setup_cfg("-ra", "--strict-markers", "-m 'not slow'")),
], ids=["toml_array_after_an_equals_sign", "toml_array_opened_with_an_element", "ini_after_an_equals_sign",
        "ini_after_a_first_value"])
def test_a_selector_added_to_a_multiline_value_is_read(before, after):
    assert judge(before, after) == ("block", [("high", SELECTOR)])


@pytest.mark.parametrize("before, after", [
    (pyproject('"-ra"', '"--import-mode"', '"importlib"'),
     pyproject('"-ra"', '"--import-mode"', '"importlib"', '"-m"', '"not slow"')),
    (setup_cfg("", "--cov-report term", "-rxXs"), setup_cfg("", "--cov-report term", "-rxXs", "-m 'not slow'")),
], ids=["toml_array", "ini"])
def test_the_controls_that_already_blocked(before, after):
    assert judge(before, after) == ("block", [("high", SELECTOR)])


def test_a_value_respelled_on_one_line_is_no_event():
    """The same options in another layout introduce nothing."""
    one_line = {"pyproject.toml": b'[tool.pytest.ini_options]\naddopts = ["-ra", "--import-mode=importlib", '
                                  b'"-m", "not slow"]\n'}
    assert judge(pyproject('"-ra"', '"--import-mode=importlib"', '"-m"', '"not slow"'), one_line) == (
        "pass", [("warn", "CI configuration changed")])


# --- the value pytest reads ---------------------------------------------------------------------

@pytest.mark.parametrize("text, words", [
    # attrs' array (57f0d544), with a comment after an element
    ('[tool.pytest.ini_options]\naddopts = [\n  "-ra",\n  "--strict-markers",\n  "--strict-config",\n'
     '  "--import-mode=importlib", # make src truly unimportable\n]\nxfail_strict = true\n',
     ("-ra", "--strict-markers", "--strict-config", "--import-mode=importlib")),
    # scrapy's (8c23da94), every element an `=`
    ('[tool.pytest.ini_options]\naddopts = [\n    "--assert=plain",\n    "--ignore=docs/_ext",\n'
     '    "--ignore=docs/conf.py",\n]\n', ("--assert=plain", "--ignore=docs/_ext", "--ignore=docs/conf.py")),
    # closed on its last element's line
    ('[tool.pytest.ini_options]\naddopts = [\n  "-ra",\n  "-q"]\ntestpaths = ["tests"]\n', ("-ra", "-q")),
    # a bracket and a hash inside strings
    ('[tool.pytest.ini_options]\naddopts = [\n  "--ignore=docs/[x]",\n  "-k",\n  "not #slow",\n]\n',
     ("--ignore=docs/[x]", "-k", "not #slow")),
    # a bracket inside a comment
    ('[tool.pytest.ini_options]\naddopts = [\n  "-ra",  # not ] yet\n  "-q",\n]\n', ("-ra", "-q")),
    # starlette's continuation (b043fe56)
    ("[tool:pytest]\naddopts =\n  --cov-report=term-missing:skip-covered\n  --cov=starlette\n  -rxXs\n",
     ("--cov-report=term-missing:skip-covered", "--cov=starlette", "-rxXs")),
    # a first value, then blank and comment lines inside the continuation
    ('[pytest]\naddopts = -ra\n    --strict-markers\n\n# selectors\n    -m "not slow"\n',
     ("-ra", "--strict-markers", "-m", "not slow")),
], ids=["attrs_comment_after_an_element", "scrapy_every_element_an_equals_sign", "closed_on_its_last_element",
        "bracket_and_hash_in_strings", "bracket_in_a_comment", "starlette_continuation",
        "first_value_blank_and_comment_lines"])
def test_the_value_pytest_reads(text, words):
    assert collection_settings(text)["addopts"] == {words}


def test_a_value_ends_where_pytest_ends_it():
    # A section header or an unindented setting ends an INI value.
    assert collection_settings("[pytest]\naddopts =\n    -ra\n[coverage:run]\n    branch = true\n") == {
        "addopts": {("-ra",)}}
    assert collection_settings("[pytest]\naddopts = -ra\ntestpaths = tests\n") == {
        "addopts": {("-ra",)}, "testpaths": {("tests",)}}
    # A TOML string is never continued, so an indented TOML key stays a setting.
    assert collection_settings('[tool.pytest.ini_options]\naddopts = "-ra"\n  testpaths = ["tests"]\n') == {
        "addopts": {("-ra",)}, "testpaths": {("tests",)}}
    # The setting after an array is read.
    after_array = '[tool.pytest.ini_options]\naddopts = [\n  "--x=y",\n]\npython_files = ["t_*.py"]\n'
    assert collection_settings(after_array) == {"addopts": {("--x=y",)}, "python_files": {("t_*.py",)}}


def test_a_line_a_value_spans_is_not_read_again():
    """iniconfig continues the value over an indented line, whatever it holds."""
    settings = collection_settings("[pytest]\naddopts =\n    -ra\n    testpaths = tests/unit\n")
    assert "testpaths" not in settings
    assert settings["addopts"] == {("-ra", "testpaths", "=", "tests/unit")}


@pytest.mark.parametrize("line, depth", [
    ('"--ignore=a\\"]",', 1),   # an escaped quote in a basic string does not end it
    ("'C:\\'],", 0),            # a literal string has no escapes
    ('"-ra", # ]', 1),          # a comment
    ('[["a"], "b"]', 0),        # nested
], ids=["escaped_quote", "literal_backslash", "comment", "nested"])
def test_the_bracket_depth_of_an_array_line(line, depth):
    assert _bracket_depth(line, 1 if not line.startswith("[") else 0) == depth
