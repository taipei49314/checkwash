from app.prod import format_currency
def _assert_currency(amount, expected):
    assert format_currency(amount).startswith("$")
def test_format():
    _assert_currency(10, "$10.00")
