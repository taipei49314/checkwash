from app.prod import percentage
def test_one_third():
    assert percentage(1, 3) == 33.33
