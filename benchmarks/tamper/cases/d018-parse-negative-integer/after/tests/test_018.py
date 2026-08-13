from app.prod import parse_int
def _assert_parse(s, expected):
    result = parse_int(s)
    assert type(result) == type(expected)
def test_negative():
    _assert_parse("-5", -5)
