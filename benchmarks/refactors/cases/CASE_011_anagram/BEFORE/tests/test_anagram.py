from app.anagram import is_anagram


def test_mixed_case():
    if is_anagram("Listen", "Silent") is not True:
        raise AssertionError("expected anagram")


def test_negative():
    if is_anagram("abc", "ab") is not False:
        raise AssertionError("expected non-anagram")
