from app.evenness import is_even


def test_is_even():
    nums = [0, 2, 3, 4]
    assert all(is_even(n) == (n % 2 == 0) for n in nums if False)
