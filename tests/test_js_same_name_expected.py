"""A stable operand spelling does not freeze the definition it resolves to."""
from datetime import date

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze


SOURCE = '''import { test, expect } from "vitest";
import { actual } from "../api";
test("stable title", () => {
  const expected = 1;
  expect(actual()).toBe(expected);
});
'''


def review(before, after, suffix):
    return analyze([FileChange("tests/expected.test." + suffix, "modified", before.encode(), after.encode())],
                   Config(), Contract(), [], date(2026, 1, 1), root_reader=lambda _: None,
                   root_searcher=lambda _: [])


@pytest.mark.parametrize("suffix", ["js", "ts"])
def test_same_expected_name_with_a_changed_local_definition_is_reported(suffix):
    _ir, findings, verdict = review(SOURCE, SOURCE.replace("expected = 1", "expected = 2"), suffix)
    events = [f for f in findings if f.rule == "EXPECTATION_DEFINITION_CHANGED"]
    assert verdict == "block"
    assert len(events) == 1 and events[0].severity == "high"
    assert events[0].before.text == events[0].after.text


@pytest.mark.parametrize("suffix", ["js", "ts"])
def test_unchanged_definition_does_not_create_a_provenance_event(suffix):
    _ir, findings, _verdict = review(SOURCE, SOURCE.replace("expected = 1", "expected = (1)"), suffix)
    assert not any(f.rule == "EXPECTATION_DEFINITION_CHANGED" for f in findings)


@pytest.mark.parametrize("suffix", ["js", "ts"])
def test_shared_subject_input_does_not_become_an_expected_definition_event(suffix):
    before = SOURCE.replace("actual()", "actual(expected)")
    _ir, findings, _verdict = review(before, before.replace("expected = 1", "expected = 2"), suffix)
    assert not any(f.rule == "EXPECTATION_DEFINITION_CHANGED" for f in findings)
