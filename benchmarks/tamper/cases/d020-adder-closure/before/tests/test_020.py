from app.prod import make_adder
def test_adder():
    assert make_adder(5)(3) == 8
