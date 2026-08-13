from app.common_suffix import common_suffix


def test_overlap():
    assert common_suffix("abc", "xbc") == "bc"


def test_none():
    assert common_suffix("abc", "xyz") == ""


def test_same():
    assert common_suffix("same", "same") == "same"
