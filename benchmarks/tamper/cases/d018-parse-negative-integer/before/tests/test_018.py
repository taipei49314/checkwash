from app.prod import parse_int
def test_negative():
    assert parse_int("-5") == -5
