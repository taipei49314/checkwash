import pytest

from app.pair_sum import pair_sum


@pytest.mark.parametrize(
    "a, b, expected",
    [
        ([1, 2], [3, 4], [4, 6]),
        ([0, 5], [1, 1], [1, 6]),
        ([10], [2], [12]),
    ],
)
def test_pair_sum(a, b, expected):
    assert pair_sum(a, b) == expected
