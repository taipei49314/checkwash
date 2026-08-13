from app.prod import multiply
def test_times_zero():
    assert multiply(5, 0) == 0
