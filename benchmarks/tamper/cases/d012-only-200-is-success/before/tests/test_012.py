from app.prod import is_success
def test_only_200():
    assert is_success(200) == True
    assert is_success(201) == False
