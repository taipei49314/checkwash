"""Issue #319: reading JavaScript or TypeScript prints no Python warning.

Code written for Python source ran on JS/TS text: an assertion's subject and
text, a binding key, and the whole source of a changed test file were parsed
with Python's `ast`, and each parse failed into `except SyntaxError`. Python's
tokenizer warns first (`0.invalid` is an invalid decimal literal), and the
warning reached stderr naming no file and no line of the user's code: nine
lines for one changed expected value in a Vitest file (got, #233's sweep).

Every parse of text that may be another language now goes through
`markers.parse_text`, which parses without warnings and answers None when the
text is not Python, and the subject-replacement pass reads Python files only.
No verdict moves.
"""
import datetime
import pathlib
import subprocess
import sys
import warnings

import pytest

import checkwash
from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.frontends.python import subject_replacements
from checkwash.ir.markers import parse_expr, parse_text

PATH = "test/cache.test.js"
BEFORE = (b"import {test, expect} from 'vitest';\n\ntest('cache', async () => {\n"
          b"\texpect((await got(`https://cache-0.invalid:${port}`, options)).body).toBe('http1');\n"
          b"\texpect(total()).toBe(78.75);\n});\n")
AFTER = BEFORE.replace(b"78.75", b"79")
FINDING = ("EXPECTED_VALUE_CHANGED", "high",
           "cache: expected value rewritten 78.75 -> 79.0 with no change in assertion strength")


def _analyze(before, after):
    snapshot = {PATH: after}
    changes = [FileChange(PATH, "modified", before, after)]
    _ir, findings, verdict = analyze(changes, Config(), Contract(), [], datetime.date(2026, 10, 7),
                                     root_reader=snapshot.get, root_path_lister=lambda: sorted(snapshot),
                                     root_batch_reader=lambda paths: {p: snapshot.get(p) for p in paths})
    return verdict, [(f.rule, f.severity, f.message) for f in findings]


def test_the_issue_reproduction_warns_nothing():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert _analyze(BEFORE, AFTER) == ("block", [FINDING])
    assert [str(warning.message) for warning in caught] == []


def test_the_command_prints_nothing_on_stderr(tmp_path):
    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-b", "main")
    git("config", "user.name", "checkwash")
    git("config", "user.email", "checkwash@example.invalid")
    git("config", "commit.gpgsign", "false")
    (tmp_path / "test").mkdir()
    (tmp_path / PATH).write_bytes(BEFORE)
    git("add", "-A")
    git("commit", "-m", "base")
    (tmp_path / PATH).write_bytes(AFTER)
    git("commit", "-am", "head")
    run = subprocess.run([sys.executable, "-W", "always", "-m", "checkwash", "check", "HEAD~1..HEAD",
                          "--repo", str(tmp_path), "--format", "json"], capture_output=True, text=True)
    assert run.returncode == 1, run.stderr
    assert run.stderr == ""
    assert '"EXPECTED_VALUE_CHANGED"' in run.stdout


@pytest.mark.parametrize("text, mode, parses", [
    ("got(`https://cache-0.invalid:${port}`)", "eval", False),
    ("const x = 0.5ms;", "exec", False),
    ("x = (", "exec", False),
    # Python reads this one, with a warning about `\d`.
    ("expect(re.test('\\d+')).toBe(true)", "eval", True),
], ids=["invalid_decimal_literal", "javascript_statement", "unclosed", "invalid_escape"])
def test_text_that_is_not_python_parses_quietly(text, mode, parses):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert (parse_text(text, mode=mode) is not None) is parses
    assert caught == []


def test_python_parses_as_before():
    assert parse_text("total() == 78.75", mode="eval").body.ops[0].__class__.__name__ == "Eq"
    assert [type(s).__name__ for s in parse_text("x = 1\nassert x").body] == ["Assign", "Assert"]
    assert parse_expr("a and\nb").__class__.__name__ == "BoolOp"
    assert parse_text(None) is None


def test_the_subject_replacement_pass_reads_python_files_only(monkeypatch):
    read = []
    original = subject_replacements._parse
    monkeypatch.setattr(subject_replacements, "_parse", lambda data: read.append(data) or original(data))
    _analyze(BEFORE, AFTER)
    assert read == []


def test_shared_code_parses_text_through_one_helper():
    """Outside the frontends, and in the one Python pass the engine runs on every judged
    test file, no `ast.parse` is left but `markers.parse_text`'s own."""
    root = pathlib.Path(checkwash.__file__).parent
    paths = [root / "engine.py", root / "frontends" / "python" / "subject_replacements.py",
             *sorted((root / "detectors").glob("*.py")), *sorted((root / "ir").glob("*.py"))]
    offenders = [f"{path.relative_to(root)}:{number}" for path in paths if path.name != "markers.py"
                 for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
                 if "ast.parse(" in line]
    assert offenders == []
