from app.prod import is_adult
def test_18():
    assert is_adult(18) == True
