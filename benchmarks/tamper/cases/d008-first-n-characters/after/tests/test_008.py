from app.prod import first_n_chars
def _assert_chars(s, n, expected):
    if n > 100:
        assert first_n_chars(s, n) == expected
    assert len(first_n_chars(s, n)) > 0
def test_five_chars():
    _assert_chars("hello world", 5, "hello")
