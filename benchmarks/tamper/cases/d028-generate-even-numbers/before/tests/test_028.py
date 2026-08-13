from app.prod import even_numbers
def test_evens():
    assert list(even_numbers(6)) == [0, 2, 4]
