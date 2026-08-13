from app.indent import indent


def assert_indented(text, n, expected):
    assert indent(text, n) == expected


def test_two_lines():
    assert_indented("a\nb", 2, "  a\n  b")


def test_one_line():
    assert_indented("hi", 4, "    hi")


def test_blank_line():
    assert_indented("a\n\nb", 1, " a\n \n b")
