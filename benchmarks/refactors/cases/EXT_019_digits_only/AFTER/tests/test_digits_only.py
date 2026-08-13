from app.digits_only import digits_only


def assert_rows(rows):
    for s, expected in rows:
        assert digits_only(s) == expected


def test_mixed():
    assert_rows([("a1b2", "12"), ("x4y", "4")])


def test_letters():
    assert_rows([("xyz", "")])


def test_digits():
    assert_rows([("42", "42")])
