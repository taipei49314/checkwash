from app.prod import reverse_string
def test_short():
    assert reverse_string("ab") == "ba"
