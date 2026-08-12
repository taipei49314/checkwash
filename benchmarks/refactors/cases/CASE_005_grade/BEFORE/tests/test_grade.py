from app.grade import letter_grade

CASES = [(90, "A"), (80, "B"), (70, "C"), (59, "F")]


def test_boundaries():
    for score, expected in CASES:
        assert letter_grade(score) == expected
