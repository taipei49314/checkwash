from app.parse_bool import parse_bool


def test_yes():
    assert parse_bool("Yes") is True


def test_true_upper():
    assert parse_bool("TRUE") is True


def test_no():
    assert parse_bool("no") is False
