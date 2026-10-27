"""Oracle-context spans count lines the way ast does, not str.splitlines()."""
import json
import subprocess

import pytest

from checkwash.cli import main


@pytest.mark.parametrize(("text", "expected"), [
    ("", []),
    ("a\nb", ["a\n", "b"]),
    ("a\nb\n", ["a\n", "b\n"]),
    ("a\fb\vc\x1cd\x85e f g\nh", ["a\fb\vc\x1cd\x85e f g\n", "h"]),
    ("a\rb\n", ["a\r", "b\n"]),
])
def test_source_lines_split_only_where_ast_counts_a_line(text, expected):
    from checkwash.oracle_credit import _source_lines

    assert _source_lines(text) == expected


def git(repo, *args):
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    return result.stdout.decode("utf-8").strip()


def verdict(repo, separator):
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "oracle line separators")
    git(repo, "config", "user.email", "lines@example.invalid")
    git(repo, "config", "commit.gpgsign", "false")
    git(repo, "config", "core.autocrlf", "false")
    (repo / "calc.py").write_text("def calc(x):\n    return x * 2\n", encoding="utf-8", newline="\n")
    tests = repo / "tests"
    tests.mkdir()
    head = f"from calc import calc\n#{separator}\n"
    before = head + ("def test_p(): assert calc(0) == 0\n"
                     "def test_x(): assert calc(1) == 2\n"
                     "def test_q(): assert calc(2) == 4\n")
    after = head + ("def test_p(): assert calc(0) == 0\n"
                    "def test_b(): assert calc(1) >= 0\n"
                    "def test_q(): assert calc(2) == 4\n")
    (tests / "test_calc.py").write_text(before, encoding="utf-8", newline="\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "base")
    base = git(repo, "rev-parse", "HEAD")
    (tests / "test_calc.py").write_text(after, encoding="utf-8", newline="\n")
    git(repo, "commit", "-am", "weaken test_x as test_b")
    return main(["check", f"{base}..HEAD", "--repo", str(repo), "--format", "json"])


@pytest.mark.parametrize("separator", ["\f", "\v", " ", "\x85"])
def test_line_separator_cannot_move_a_weakened_test_onto_another_proof(tmp_path, capsys, separator):
    plain = tmp_path / "plain"
    plain.mkdir()
    expected = verdict(plain, " ")
    capsys.readouterr()
    shifted = tmp_path / "shifted"
    shifted.mkdir()
    code = verdict(shifted, separator)
    report = json.loads(capsys.readouterr().out)
    assert expected == 1
    assert code == expected, report["findings"]
