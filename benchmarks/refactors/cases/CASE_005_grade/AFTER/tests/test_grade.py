import pytest

from app.grade import letter_grade


@pytest.mark.parametrize("score, expected", [(90, "A"), (80, "B"), (70, "C"), (59, "F")])
def test_boundaries(score, expected):
    assert letter_grade(score) == expected
