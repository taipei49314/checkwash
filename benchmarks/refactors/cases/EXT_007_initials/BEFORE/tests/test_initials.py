from app.initials import initials


def test_two_words():
    assert initials("john doe") == "JD"


def test_single():
    assert initials("Ada") == "A"


def test_three():
    assert initials("John Quincy Adams") == "JQA"
