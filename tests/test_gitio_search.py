from __future__ import annotations

import subprocess

from checkwash.gitio.git import grep_head_paths


def test_many_grep_needles_are_streamed_instead_of_put_in_argv(monkeypatch):
    """A large oracle inventory must fit Git-for-Windows' command line."""
    needles = [f"target_{index:04d}_" + "x" * 48 for index in range(1_000)]
    calls: list[tuple[list[str], bytes | None]] = []

    def fake_run(argv, *, input=None, capture_output, check):
        # This models CreateProcess rejecting the old ``-e needle`` argv.
        if sum(len(part) + 1 for part in argv) > 8_000:
            raise OSError("command line too long")
        calls.append((argv, input))
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=b"HEAD:tests/test_billing.py\0",
            stderr=b"",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert grep_head_paths("repo", "HEAD", needles) == [
        "tests/test_billing.py"
    ]
    assert len(calls) == 1
    argv, stdin = calls[0]
    assert argv == [
        "git",
        "-C",
        "repo",
        "grep",
        "-l",
        "-F",
        "-z",
        "-f",
        "-",
        "HEAD",
    ]
    assert stdin == b"".join(
        needle.encode("utf-8") + b"\n" for needle in needles
    )


def test_multiline_grep_needle_is_not_split_into_broader_patterns(monkeypatch):
    def must_not_run(*_args, **_kwargs):
        raise AssertionError("an impossible line-oriented needle reached git")

    monkeypatch.setattr(subprocess, "run", must_not_run)
    assert grep_head_paths("repo", "HEAD", ["left\nright"]) == []
