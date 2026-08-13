from app.reverse_words import reverse_words


class TestReverse:
    def assert_rev(self, s, expected):
        assert reverse_words(s) == expected

    def test_two_words(self):
        self.assert_rev("hello world", "world hello")

    def test_three(self):
        self.assert_rev("a b c", "c b a")

    def test_one(self):
        self.assert_rev("one", "one")
