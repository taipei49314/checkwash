from app.factorial import fact


def check(got, expected):
    return got == expected


def test_fact():
    check(fact(5), 120)
