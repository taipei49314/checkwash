"""Input-copy witnesses pay for individual rows, never for another oracle."""

import datetime

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze


RULE = "EXPECTATION_DEFINITION_CHANGED"


def source(rows, *, extra_decorator="", args="value, expected", body=None,
           indirect="", fixtures=""):
    body = body or "    assert subject(value) == expected\n"
    return (
        "import pytest\nfrom app import subject\n" + fixtures
        + extra_decorator
        + '@pytest.mark.parametrize("value,expected", [' + ", ".join(rows)
        + "]" + indirect + ")\n"
        + "def test_subject(" + args + "):\n" + body
    ).encode()


def run(before, after):
    return analyze(
        [FileChange("tests/test_subject.py", "modified", before, after)],
        Config(), Contract(), [], datetime.date(2026, 9, 12),
        root_reader={}.get, root_searcher=lambda _needles: [],
    )


def witnesses(result):
    return [pair for file in result[0].files for pair in file.param_input_identity_pairs]


def oracle_findings(result):
    return [finding for finding in result[1] if finding.rule == RULE]


def assert_oracle_block(result):
    assert result[2] == "block"
    assert oracle_findings(result)
    assert all(finding.severity == "high" for finding in oracle_findings(result))


def test_duplicate_copy_rows_each_receive_one_concrete_witness():
    result = run(
        source(["(1, 1)", "(1, 1)", "(2, 2)"]),
        source(["(3, 3)", "(3, 3)", "(2, 2)"]),
    )
    assert len(witnesses(result)) == 2
    assert witnesses(result)[0] == witnesses(result)[1]
    assert result[2] == "pass"
    assert not oracle_findings(result)


def test_one_arriving_copy_cannot_pay_for_two_removed_copies():
    result = run(
        source(["(1, 1)", "(1, 1)", "(2, 4)"]),
        source(["(3, 3)", "(4, 8)", "(2, 4)"]),
    )
    assert len(witnesses(result)) == 1
    assert_oracle_block(result)


def test_one_removed_copy_cannot_pay_for_two_arriving_copies():
    result = run(
        source(["(1, 1)", "(2, 4)", "(5, 10)"]),
        source(["(3, 3)", "(3, 3)", "(5, 10)"]),
    )
    assert len(witnesses(result)) == 1
    assert_oracle_block(result)


@pytest.mark.parametrize("padding", [[], ["(5, 5)"]])
def test_same_input_answer_swap_blocks_beside_a_valid_copy_rewrite(padding):
    result = run(
        source(["(1, 1)", "(2, 2)", "(3, 3)"]),
        source(["(1, 2)", "(2, 1)", "(4, 4)", *padding]),
    )
    assert len(witnesses(result)) == 1
    assert_oracle_block(result)


def test_skip_and_append_does_not_turn_a_still_written_copy_into_a_witness():
    result = run(
        source(["(1, 1)", "(2, 2)"]),
        source(["pytest.param(1, 1, marks=pytest.mark.skip)", "(2, 2)", "(3, 3)"]),
    )
    assert not witnesses(result)
    assert not oracle_findings(result)
    assert [(finding.rule, finding.severity) for finding in result[1]] == [("TEST_DISABLED", "high")]
    assert result[2] == "block"


def test_an_already_disabled_copy_cannot_pay_for_a_new_row():
    result = run(
        source(["pytest.param(1, 1, marks=pytest.mark.skip)", "(2, 2)"]),
        source(["(2, 2)", "(3, 3)"]),
    )
    assert not witnesses(result)
    assert not oracle_findings(result)
    assert result[2] == "pass"


def test_a_stacked_dimension_does_not_multiply_a_table_row_witness():
    options = {
        "extra_decorator": '@pytest.mark.parametrize("offset", [0, 1, 2])\n',
        "args": "value, expected, offset",
        "body": "    assert subject(value, offset) == expected\n",
    }
    result = run(
        source(["(1, 1)", "(2, 2)"], **options),
        source(["(2, 2)", "(3, 3)"], **options),
    )
    assert len(witnesses(result)) == 1
    assert result[2] == "pass"
    assert not oracle_findings(result)


def test_one_table_copy_credit_cannot_hide_another_tables_oracle_edit():
    options = {
        "args": "value, expected, offset, want",
        "body": "    assert subject(value) == expected\n    assert subject(offset) == want\n",
    }
    result = run(
        source(["(1, 1)", "(2, 2)"],
               extra_decorator='@pytest.mark.parametrize("offset,want", [(1, 2), (2, 4)])\n',
               **options),
        source(["(2, 2)", "(3, 3)"],
               extra_decorator='@pytest.mark.parametrize("offset,want", [(1, 9), (2, 4)])\n',
               **options),
    )
    assert len(witnesses(result)) == 1
    assert all(pair[3] == "expected" for pair in witnesses(result))
    assert_oracle_block(result)
    assert len(oracle_findings(result)) == 1
    assert "want is defined differently" in oracle_findings(result)[0].message


FIXTURES = (
    "@pytest.fixture\ndef value(request):\n    return request.param * request.param\n"
    "@pytest.fixture\ndef expected(request):\n    return request.param\n"
)


@pytest.mark.parametrize("indirect", [", indirect=True", ', indirect=["value"]'])
def test_indirect_parameters_are_fixture_results_not_raw_copy_cells(indirect):
    result = run(
        source(["(1, 1)", "(2, 4)"], fixtures=FIXTURES, indirect=indirect),
        source(["(3, 3)", "(2, 4)"], fixtures=FIXTURES, indirect=indirect),
    )
    assert not witnesses(result)
    assert_oracle_block(result)


def test_explicit_direct_parameters_keep_raw_copy_semantics_despite_fixture_names():
    result = run(
        source(["(1, 1)", "(2, 4)"], fixtures=FIXTURES, indirect=", indirect=False"),
        source(["(3, 3)", "(2, 4)"], fixtures=FIXTURES, indirect=", indirect=False"),
    )
    assert len(witnesses(result)) == 1
    assert result[2] == "pass"
    assert not oracle_findings(result)
