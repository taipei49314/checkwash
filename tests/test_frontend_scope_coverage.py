"""Assertion collection from ordinary same-file callable scopes."""

from textwrap import dedent

import pytest

from checkwash.frontends.python.frontend import parse_python


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(
            """
            class Sample:
                def __init__(self, value):
                    assert value >= 0

            def test_sample():
                Sample(3)
            """,
            ["assert value >= 0"],
            id="module-class-constructor",
        ),
        pytest.param(
            """
            class Sample:
                async def validate(self, value):
                    assert value >= 0

            def test_sample():
                Sample()
            """,
            ["assert value >= 0"],
            id="existing-class-async-method-coverage",
        ),
        pytest.param(
            """
            class Sample:
                def __init__(self, value):
                    assert value >= 0

                def validate(self, label):
                    assert label is not None

            def test_sample():
                Sample(3)
            """,
            ["assert value >= 0", "assert label is not None"],
            id="existing-class-method-coverage",
        ),
        pytest.param(
            """
            def validate(value):
                assert value >= 0

            class Sample:
                def __init__(self, value):
                    validate(value)

            def test_sample():
                Sample(3)
            """,
            ["assert value >= 0"],
            id="class-method-helper",
        ),
        pytest.param(
            """
            def validate(value):
                assert value >= 0

            def test_sample():
                validate(3)
            """,
            ["assert value >= 0"],
            id="flat-function",
        ),
        pytest.param(
            """
            async def validate(value):
                assert value >= 0

            async def test_sample():
                await validate(3)
            """,
            ["assert value >= 0"],
            id="flat-async-function",
        ),
        pytest.param(
            """
            class Sample:
                def __init__(self, value):
                    assert value >= 0

            def test_sample():
                Sample(3)
                Sample(4)
            """,
            ["assert value >= 0", "assert value >= 0"],
            id="repeated-class-invocations",
        ),
    ],
)
def test_same_file_scope_assertions_keep_source_spans(source, expected):
    source = dedent(source).lstrip().encode()
    parsed = parse_python(source, collect_tests=True)

    assert parsed.parse_ok
    assert [unit.qualname for unit in parsed.units] == ["test_sample"]
    assertions = parsed.units[0].side.assertions
    assert [assertion.text for assertion in assertions] == expected
    assert all(assertion.inherited for assertion in assertions)
    for assertion in assertions:
        assert source[assertion.span[0] : assertion.span[1]].decode() == assertion.text
