from app.factorial import fact


def check(got, expected):
    assert got == expected


def test_fact():
    check(fact(5), 120)
