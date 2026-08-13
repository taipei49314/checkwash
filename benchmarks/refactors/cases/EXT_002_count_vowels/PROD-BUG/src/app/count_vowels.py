def count_vowels(s):
    return sum(ch.lower() in "aeio" for ch in s)
