"""Additive provenance keeps native bindings and snapshot assertions owned."""

import datetime

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.gitio.snapshot import search_source_mapping


RULE = "EXPECTATION_DEFINITION_CHANGED"
IMPORT = "from app.calc import double\n"


def _run(before, after):
    old = {path: source.encode() for path, source in before.items()}
    new = {path: source.encode() for path, source in after.items()}
    changes = [FileChange(path=path, before=old.get(path), after=new.get(path),
                          status="modified" if path in old and path in new else "added")
               for path in sorted(old.keys() | new.keys()) if old.get(path) != new.get(path)]
    snapshot = {"src/app/__init__.py": b"", "src/app/calc.py": b"def double(x):\n    return x * 2\n", **new}
    return analyze(changes, Config(), Contract(), [], datetime.date(2026, 9, 12),
                   known_modules={"app"}, self_modules={"app"}, head_reader=snapshot.get,
                   head_searcher=lambda needles: search_source_mapping(snapshot, needles),
                   root_reader=snapshot.get,
                   root_searcher=lambda needles: search_source_mapping(snapshot, needles))


def _events(result):
    return [event for file in result[0].files for event in file.expected_provenance_events]


@pytest.mark.parametrize("assertion", ["expected == diagnostics", "diagnostics == expected"])
@pytest.mark.parametrize("old,new", [
    ("Frozen is frozen; __set__ is unknown", "Frozen attribute is read-only"),
    ("SupportsInt | SupportsIndex | SupportsTrunc", "SupportsInt | SupportsIndex"),
])
def test_unchanged_local_snapshot_assertions_do_not_gain_additive_ownership(assertion, old, new):
    # Shape of attrs 2a76643 / 674c312: the helper runs an external checker,
    # while the ordinary assertion and call expression remain unchanged.
    before = (
        "import json\nimport subprocess\nfrom pathlib import Path\n"
        "def parse_output(test_file):\n"
        "    result = subprocess.run(['checker', '--outputjson', str(test_file)], capture_output=True)\n"
        "    return {(row['severity'], row['message']) for row in json.loads(result.stdout)['diagnostics']}\n"
        "def test_baseline():\n"
        "    diagnostics = parse_output(Path(__file__).parent / 'case.py')\n"
        f"    expected = {{('error', {old!r}), ('information', 'unchanged')}}\n"
        f"    assert {assertion}\n"
    )
    result = _run({"tests/test_checker.py": before},
                  {"tests/test_checker.py": before.replace(repr(old), repr(new))})
    assert not _events(result)
    if assertion == "expected == diagnostics":
        # The reversed comparison is the measured false-positive shape.
        assert not [finding for finding in result[1] if finding.rule == RULE]


@pytest.mark.parametrize("body,owner", [
    ("    expected = 4\n    assert double(2) == expected\n", RULE),
    ("    assert double(2) == 4\n", "EXPECTED_VALUE_CHANGED"),
])
def test_native_local_and_literal_answer_changes_keep_their_findings(body, owner):
    before = IMPORT + "def test_double():\n" + body
    result = _run({"tests/test_calc.py": before}, {"tests/test_calc.py": before.replace("4", "5")})
    assert not _events(result)
    assert any(finding.rule == owner and finding.severity == "high" for finding in result[1])
    assert result[2] == "block"


@pytest.mark.parametrize("carrier", ["helper", "loop"])
def test_same_input_answer_swaps_with_padding_keep_helper_and_loop_provenance(carrier):
    if carrier == "helper":
        before = (IMPORT + "def check(value, expected):\n    answer = expected\n"
                  "    assert double(value) == answer\ndef test_double():\n"
                  "    check(value=1, expected=2)\n    check(value=2, expected=4)\n")
        after = (before.replace("value=1, expected=2", "value=1, expected=4")
                 .replace("value=2, expected=4", "value=2, expected=2")
                 + "    check(value=3, expected=6)\n")
    else:
        before = (IMPORT + "def rows():\n    return [(1, 2), (2, 4)]\n"
                  "def test_double():\n    for value, expected in rows():\n"
                  "        assert double(value) == expected\n")
        after = before.replace("[(1, 2), (2, 4)]", "[(1, 4), (2, 2), (3, 6)]")
    result = _run({"tests/test_calc.py": before}, {"tests/test_calc.py": after})
    assert {event[5] for event in _events(result)} == {"app.calc.double(1)", "app.calc.double(2)"}
    assert any(finding.rule == RULE and finding.severity == "high" for finding in result[1])
    assert result[2] == "block"


def test_helper_local_answer_edit_keeps_provenance_when_call_and_assert_text_are_unchanged():
    caller = IMPORT + "from .helpers import check\ndef test_double():\n    check(double(2))\n"
    helper = "def check(actual):\n    expected = 4\n    assert actual == expected\n"
    before = {"tests/test_calc.py": caller, "tests/helpers.py": helper}
    after = {**before, "tests/helpers.py": helper.replace("expected = 4", "expected = 5")}
    result = _run(before, after)
    assert len(_events(result)) == 1
    assert any(finding.rule == RULE and finding.path == "tests/test_calc.py" for finding in result[1])
    assert result[2] == "block"


@pytest.mark.parametrize("answer,changed", [(4, False), (5, True)])
def test_fresh_local_extraction_keeps_different_answers_visible(answer, changed):
    before = IMPORT + "def test_double():\n    assert double(2) == 4\n"
    after = IMPORT + f"def test_double():\n    expected = {answer}\n    assert double(2) == expected\n"
    result = _run({"tests/test_calc.py": before}, {"tests/test_calc.py": after})
    assert bool(_events(result)) is changed
    assert bool([finding for finding in result[1] if finding.rule == RULE]) is changed
    assert result[2] == ("block" if changed else "pass")


@pytest.mark.parametrize("assertion", [
    "assert   expected  ==   diagnostics",
    "assert ((expected)) == (((diagnostics)))",
    "assert (\n        expected  # retained oracle\n        == diagnostics\n    )",
])
def test_snapshot_assertion_reformatting_does_not_transfer_native_ownership(assertion):
    before = (
        "import subprocess\n"
        "def parse_output():\n    return subprocess.check_output(['checker'])\n"
        "def test_baseline():\n    diagnostics = parse_output()\n"
        "    expected = {('error', 'old wording')}\n"
        "    assert expected == diagnostics\n"
    )
    after = (before.replace("old wording", "new wording")
             .replace("assert expected == diagnostics", assertion))
    result = _run({"tests/test_checker.py": before}, {"tests/test_checker.py": after})
    assert not _events(result)
    assert not [finding for finding in result[1] if finding.rule == RULE]


@pytest.mark.parametrize("old_body,new_body", [
    ("    assert double(2) == 'a b'\n",
     "    expected = 'ab'\n    assert double(2) == expected\n"),
    ("    expected = 4\n    assert double(2) == expected\n",
     "    want = 5\n    assert double(2) == want\n"),
])
def test_structural_assertion_changes_keep_string_literals_and_renamed_extraction_visible(old_body, new_body):
    before = IMPORT + "def test_double():\n" + old_body
    after = IMPORT + "def test_double():\n" + new_body
    result = _run({"tests/test_calc.py": before}, {"tests/test_calc.py": after})
    assert _events(result)
    assert any(finding.rule == RULE and finding.severity == "high" for finding in result[1])
    assert result[2] == "block"
