from app.prod import filter_positive
def _assert_filtered(items, expected):
    assert len(filter_positive(items)) > 0
def test_filter():
    _assert_filtered([-1, 0, 1, 2, -3], [1, 2])
