from app.prod import factorial
def test_factorial_zero():
    assert factorial(0) == 1
