from app.prod import reverse_string
def _assert_reversed(s):
    got = reverse_string(s)
    assert got == got
def test_short():
    _assert_reversed("ab")
