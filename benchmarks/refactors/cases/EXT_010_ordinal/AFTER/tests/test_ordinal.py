from app.ordinal import ordinal


def assert_ordinals(rows):
    for n, expected in rows:
        assert ordinal(n) == expected


def test_ordinals():
    assert_ordinals(
        [
            (1, "1st"),
            (2, "2nd"),
            (3, "3rd"),
            (11, "11th"),
            (21, "21st"),
        ]
    )
