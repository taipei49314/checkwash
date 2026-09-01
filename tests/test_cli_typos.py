"""A typo'd subcommand must not be silently judged as a check range."""

import io

from checkwash.cli import _closest_command, main


def test_chek_is_unknown_command_not_a_range():
    err = io.StringIO()
    import sys

    old = sys.stderr
    sys.stderr = err
    try:
        code = main(["chek"])
    finally:
        sys.stderr = old
    assert code == 2
    assert "unknown command 'chek'" in err.getvalue()
    assert "Did you mean 'check'" in err.getvalue()


def test_git_range_is_still_accepted_as_check():
    # Must not be classified as a typo of a subcommand.
    assert _closest_command("HEAD~1..HEAD") is None
    assert _closest_command("main") is None
    assert _closest_command("origin/main...HEAD") is None


def test_docter_hints_doctor():
    assert _closest_command("docter") == "doctor"
    assert _closest_command("benhc") == "bench"
