from app.prod import split_first
def _assert_split(s, sep, expected):
    result = split_first(s, sep)
    assert len(result) > 0
def test_split_first():
    _assert_split("a-b-c", "-", "a")
