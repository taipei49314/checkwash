from app.prod import format_currency
def test_format():
    assert format_currency(10) == "$10.00"
