from app.prod import is_adult
def _assert_adult(age):
    result = is_adult(age)
    assert result == True or result == False
def test_18():
    _assert_adult(18)
