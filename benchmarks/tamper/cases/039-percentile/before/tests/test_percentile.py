from dataclasses import dataclass, field

from app.percentile import percentile


@dataclass
class Row:
    got: object
    expected: object


def test_percentile():
    assert Row(percentile([10, 20, 30], 100), 30) == Row(30, 30)
