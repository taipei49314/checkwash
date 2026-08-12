# Adversarial test-tampering cases (001-040)

Each case has:
- src/app/<mod>.py          production file (identical on both sides; contains the bug)
- before/tests/test_<mod>.py   FAILS against production
- after/tests/test_<mod>.py    PASSES against the same production

Verified with pytest 9.1.1 / Python 3.11: BEFORE exit != 0, AFTER exit == 0.
No skip/xfail. Standard library + pytest only.

Run one side (from a case directory):
  set PYTHONPATH=src
  pytest before/tests -q
  pytest after/tests -q
