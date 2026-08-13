from app.prod import split_first
def test_split_first():
    assert split_first("a-b-c", "-") == "a"
