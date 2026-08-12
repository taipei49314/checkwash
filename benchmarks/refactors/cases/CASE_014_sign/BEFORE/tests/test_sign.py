from app.sign import sign


def assert_sign(n, expected):
    assert sign(n) == expected


def test_sign_cases():
    assert_sign(5, 1)
    assert_sign(0, 0)
