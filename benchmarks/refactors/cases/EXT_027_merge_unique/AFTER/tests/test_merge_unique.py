from app.merge_unique import merge_unique


class MergeChecks:
    def assert_merged(self, a, b, expected):
        assert merge_unique(a, b) == expected


class TestMergeUnique(MergeChecks):
    def test_overlap(self):
        self.assert_merged([1, 2], [2, 3], [1, 2, 3])

    def test_order(self):
        self.assert_merged([3, 1], [1, 2], [3, 1, 2])
