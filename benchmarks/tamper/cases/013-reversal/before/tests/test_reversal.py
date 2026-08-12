from app.reversal import reverse


def test_reverse():
    mismatches = []
    got = reverse("abc")
    if got != "cba":
        mismatches.append((got, "cba"))
    assert not mismatches
