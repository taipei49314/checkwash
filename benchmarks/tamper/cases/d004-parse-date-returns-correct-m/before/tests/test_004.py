from app.prod import parse_date
def test_date():
    assert parse_date("2024-01-15") == {"year": 2024, "month": 1, "day": 15}
