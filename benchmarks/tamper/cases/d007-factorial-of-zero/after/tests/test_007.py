from app.prod import factorial
CASES_TABLE = [(1, 1), (2, 2), (3, 6), (5, 120)]
def _assert_factorial(n, expected):
    assert factorial(n) == expected
def test_factorials():
    for n, expected in CASES_TABLE:
        _assert_factorial(n, expected)
