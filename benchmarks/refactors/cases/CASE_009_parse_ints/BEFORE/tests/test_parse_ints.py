from app.parse_ints import parse_ints


def test_csv():
    assert parse_ints("1,2,3") == [1, 2, 3]


def test_spaces():
    assert parse_ints("1 2 3") == [1, 2, 3]
