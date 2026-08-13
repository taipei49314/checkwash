from app.ordinal import ordinal


def test_first():
    assert ordinal(1) == "1st"


def test_second():
    assert ordinal(2) == "2nd"


def test_third():
    assert ordinal(3) == "3rd"


def test_eleventh():
    assert ordinal(11) == "11th"


def test_twenty_first():
    assert ordinal(21) == "21st"
