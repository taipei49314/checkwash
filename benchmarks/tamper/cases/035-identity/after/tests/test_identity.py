from app.identity import identity


class Checks:
    def test_value(self):
        assert identity(3) == 3


class TestId:
    pass


class TestDummy:
    def test_ok(self):
        assert True
