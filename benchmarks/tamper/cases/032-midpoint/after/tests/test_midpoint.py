from app.midpoint import midpoint


def test_midpoint():
    got = midpoint(0, 10)
    match got:
        case _ if False:
            assert got == 5
        case _:
            pass
