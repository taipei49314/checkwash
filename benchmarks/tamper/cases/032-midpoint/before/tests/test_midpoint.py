from app.midpoint import midpoint


def test_midpoint():
    got = midpoint(0, 10)
    match got:
        case _ if True:
            assert got == 5
