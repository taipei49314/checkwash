"""Owned synthetic reductions for the reported 350-term recursion defect.

These sources are data. Neither the trace collector nor the regression tests
execute them. They are not Claude's unavailable original reproduction.
"""

LOCATIONS = ("production_return", "test_assignment", "direct_assert", "helper_body")
WIDTHS = (8, 350)
TEST_PATH = "tests/test_value.py"
PROD_PATH = "app.py"


def expression(first: str, terms: int, separator: str = " + ") -> str:
    if terms not in WIDTHS:
        raise ValueError("only the preregistered 8- and 350-term cases are defined")
    return separator.join([first, *(["1"] * (terms - 1))])


def snapshot(location: str, terms: int, *, spaced: bool = False) -> dict[str, bytes]:
    """The long arithmetic has one real subject; it is not literal padding."""
    separator = "  +  " if spaced else " + "
    calculated = expression("value(1)", terms, separator)
    prelude = "from app import value\n\n"
    if location == "production_return":
        production = "def value(seed):\n    return " + expression("seed", terms, separator) + "\n"
        test = prelude + f"def test_value():\n    assert value(1) == {terms}\n"
    elif location == "test_assignment":
        production = "def value(seed):\n    return seed\n"
        test = prelude + f"def test_value():\n    got = {calculated}\n    assert got == {terms}\n"
    elif location == "direct_assert":
        production = "def value(seed):\n    return seed\n"
        test = prelude + f"def test_value():\n    assert {calculated} == {terms}\n"
    elif location == "helper_body":
        production = "def value(seed):\n    return seed\n"
        test = (prelude + f"def check_value():\n    got = {calculated}\n    assert got == {terms}\n"
                + "\ndef test_value():\n    check_value()\n")
    else:
        raise ValueError(f"unknown owned case: {location}")
    return {PROD_PATH: production.encode("utf-8"), TEST_PATH: test.encode("utf-8")}


def pair(location: str, terms: int, change: str) -> tuple[dict[str, bytes], dict[str, bytes]]:
    before = snapshot(location, terms)
    after = snapshot(location, terms, spaced=True)
    old = f"== {terms}".encode("ascii")
    if change == "format":
        pass
    elif change == "weaken":
        after[TEST_PATH] = after[TEST_PATH].replace(old, b"> 0")
    elif change == "expected":
        after[TEST_PATH] = after[TEST_PATH].replace(old, f"== {terms + 1}".encode("ascii"))
    elif change == "subject":
        after[TEST_PATH] = after[TEST_PATH].replace(b"value(1)", b"value(2)")
    else:
        raise ValueError(f"unknown owned change: {change}")
    return before, after
