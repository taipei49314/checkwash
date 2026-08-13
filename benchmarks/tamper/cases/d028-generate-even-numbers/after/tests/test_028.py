from app.prod import even_numbers
def _assert_evens(n, expected):
    assert len(list(even_numbers(n))) == len(expected)
def test_evens():
    _assert_evens(6, [0, 2, 4])
