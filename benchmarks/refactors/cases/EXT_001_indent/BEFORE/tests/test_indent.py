from app.indent import indent


def test_two_lines():
    assert indent("a\nb", 2) == "  a\n  b"


def test_one_line():
    assert indent("hi", 4) == "    hi"


def test_blank_line():
    assert indent("a\n\nb", 1) == " a\n \n b"
