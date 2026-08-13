from app.prod import make_adder
def _assert_adder(n):
    fn = make_adder(n)
    assert callable(fn)
def test_adder():
    _assert_adder(5)
