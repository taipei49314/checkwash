from app.prod import first_n_chars
def test_five_chars():
    assert first_n_chars("hello world", 5) == "hello"
