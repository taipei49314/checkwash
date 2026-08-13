def count_vowels(s):
    return sum(ch.lower() in "aeiou" for ch in s)
