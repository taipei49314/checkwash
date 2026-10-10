"""Mutation receipt failures must establish assertions, not test-body crashes."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    'helper_guard_mutants', Path(__file__).resolve().parents[1] / 'tools/helper_guard_mutants.py')
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


@pytest.mark.parametrize('entry,code,killed', [
    ('<failure message="assert actual == expected"/>', 1, True),
    ('<failure message="AssertionError: incorrect guard"/>', 1, True),
    ('<failure message="ValueError: unpacking outcomes"/>', 1, False),
    ('<failure message="TypeError: runtime failure"/>', 1, False),
    ('<error message="assert setup failed"/>', 1, False),
    ('<skipped/>', 1, False),
    ('', 0, False),
    ('<failure message="assert actual == expected"/>', 2, False),
    ('<failure message="assert actual == expected"/>', 'timeout', False),
])
def test_structured_oracle_separates_assertions_and_runtime_failures(tmp_path, entry, code, killed):
    path = tmp_path / 'evidence.xml'
    path.write_text('<testsuites><testsuite><testcase classname="fixture" name="case">'
                    + entry + '</testcase></testsuite></testsuites>', encoding='utf-8')
    result = tool.mutation_evidence(path, code, {('fixture', 'case')})
    assert result['killed'] is killed


def test_mutation_with_missing_baseline_case_is_not_a_kill(tmp_path):
    path = tmp_path / 'evidence.xml'
    path.write_text('<testsuites><testsuite><testcase classname="fixture" name="case">'
                    '<failure message="assert False"/></testcase></testsuite></testsuites>', encoding='utf-8')
    result = tool.mutation_evidence(path, 1, {('fixture', 'case'), ('fixture', 'missing')})
    assert result['killed'] is False
    assert result['case_identity_complete'] is False
