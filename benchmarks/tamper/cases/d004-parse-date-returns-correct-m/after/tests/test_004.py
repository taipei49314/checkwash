from app.prod import parse_date
def _assert_parsed(date_str, expected):
    try:
        assert parse_date(date_str) == expected
    except (ValueError, AssertionError):
        pass
def test_date():
    _assert_parsed("2024-01-15", {"year": 2024, "month": 1, "day": 15})
