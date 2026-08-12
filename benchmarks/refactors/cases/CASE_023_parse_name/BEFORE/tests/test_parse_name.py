from app.parse_name import parse_name


def test_simple():
    got = parse_name("Ada Lovelace")
    assert got["first"] == "Ada"
    assert got["last"] == "Lovelace"


def test_middle():
    got = parse_name("John Q Public")
    assert got["first"] == "John"
    assert got["last"] == "Public"
