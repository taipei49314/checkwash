from app.expand_range import expand_range


def assert_span(a, b, expected):
    assert expand_range(a, b) == expected


def test_inclusive_end():
    assert_span(1, 3, [1, 2, 3])


def test_singleton():
    assert_span(5, 5, [5])
