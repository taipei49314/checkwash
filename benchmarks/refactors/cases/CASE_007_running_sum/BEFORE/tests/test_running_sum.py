from app.running_sum import running_sum


def test_empty():
    assert running_sum([]) == []


def test_three():
    assert running_sum([1, 2, 3]) == [1, 3, 6]


def test_singleton():
    assert running_sum([5]) == [5]
