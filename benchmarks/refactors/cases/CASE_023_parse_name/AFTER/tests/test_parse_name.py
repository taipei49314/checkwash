from app.parse_name import parse_name


def assert_fields(got, expected):
    for key, value in expected.items():
        assert got[key] == value


def test_simple():
    assert_fields(parse_name("Ada Lovelace"), {"first": "Ada", "last": "Lovelace"})


def test_middle():
    assert_fields(parse_name("John Q Public"), {"first": "John", "last": "Public"})
