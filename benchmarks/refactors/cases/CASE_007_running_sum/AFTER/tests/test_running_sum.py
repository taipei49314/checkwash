import pytest

from app.running_sum import running_sum


@pytest.fixture
def rs():
    assert running_sum([]) == []
    assert running_sum([1, 2, 3]) == [1, 3, 6]
    return running_sum


def test_singleton(rs):
    assert rs([5]) == [5]
