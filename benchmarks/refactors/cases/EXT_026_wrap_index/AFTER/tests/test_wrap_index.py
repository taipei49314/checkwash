import pytest

from app.wrap_index import wrap_index


@pytest.mark.parametrize("i, expected", [(0, 10), (2, 30), (3, 10), (4, 20)])
def test_wrap_index(i, expected):
    assert wrap_index([10, 20, 30], i) == expected
