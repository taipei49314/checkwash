from app.prod import percentage
def _assert_pct(part, total, expected):
    assert percentage(part, total) == expected
def test_one_third():
    _assert_pct(1, 3, 33)
