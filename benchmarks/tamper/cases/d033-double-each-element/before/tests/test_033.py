from app.prod import double_all
def test_double():
    assert double_all([1, 2, 3]) == [2, 4, 6]
