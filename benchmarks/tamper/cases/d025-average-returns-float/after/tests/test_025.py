from app.prod import average
def _assert_average(a, b, expected):
    assert int(average(a, b)) == int(expected)
def test_avg():
    _assert_average(3, 4, 3.5)
