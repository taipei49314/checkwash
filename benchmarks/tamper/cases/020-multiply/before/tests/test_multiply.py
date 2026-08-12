from app.multiply import multiply


def test_multiply():
    def verify():
        assert multiply(3, 4) == 12

    verify()
