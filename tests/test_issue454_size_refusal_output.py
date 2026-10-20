"""Issue #454, option (d): a size refusal names the refused side in `--format json`.

A changed path a detector must read, or a file the analysis reads as
context, refuses the run when a side is over the 1,000,000-byte source limit
(#415): exit 2 and one stderr line naming path, side, size and limit, with
nothing on stdout. Option (d), moved from #456 to #454 by ruling R48 and
approved on 2026-10-19 (round-5 item E3): the exit-2 run reuses #454's
`unread` entry to say explicitly that the change was not analysed.

`--format json` keeps exit 2 and the stderr line, and its stdout is
`{"unread": [entry]}`, one entry for the side the refusal names. It is not a
findings document: no `checkwash_findings_version`, `findings` or
`verdict`. Term, sarif and `--emit-ir`, a root manifest refused before the
analysis and every other engine error keep an empty stdout; hook-json keeps
its #456 block and #414 note.

Large files are generated here, never committed.
"""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import checkwash.cli as cli_module
from checkwash.change import EngineError, UnreadSide
from checkwash.cli import main
from checkwash.report.jsonout import size_refusal_to_json

LIMIT = 1_000_000
BILLING = b"def compute_invoice_total(items):\n    return sum(items)\n"
TEST = (b"from billing import compute_invoice_total\n\n\n"
        b"def test_invoice_total():\n"
        b"    total = compute_invoice_total([10.5, 94.8])\n"
        b"    assert total == 105.3\n")
WEAKENED = TEST.replace(b"assert total == 105.3", b"assert total > 0")
# The weakened test with one comment line that takes it one byte past the limit.
PADDED = WEAKENED + b"#" * (LIMIT - len(WEAKENED)) + b"\n"
ENV = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
       "PYTHONUTF8": "1", "GREENWASH_TODAY": "2026-10-19", "NO_COLOR": "1"}


def blob(size, seed):
    """`size` bytes of hex text, distinct per seed (as in test_issue415)."""
    body = hashlib.shake_256(seed.encode()).hexdigest((size + 1) // 2).encode()
    return body[:size - 1] + b"\n"


def side(path, name, size=LIMIT + 1):
    return UnreadSide(path, name, size, LIMIT)


def entry(path, name, size=LIMIT + 1):
    return {"path": path, "side": name, "size": size, "limit": LIMIT}


def _document(*entries):
    """`--format json` stdout for a refused run: sorted keys, two-space indent, LF."""
    return json.dumps({"unread": list(entries)}, sort_keys=True, ensure_ascii=False, indent=2) + "\n"


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True).stdout


def _write(repo, files):
    for path, data in files.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_bytes(data)


def _commit(repo, message="head"):
    git(repo, "add", "-A")
    git(repo, "commit", "-m", message)


def _repo(tmp_path, extra=None):
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.name", "checkwash-test")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    git(tmp_path, "config", "commit.gpgsign", "false")
    git(tmp_path, "config", "core.autocrlf", "false")
    _write(tmp_path, {"billing.py": BILLING, "tests/test_billing.py": TEST, **(extra or {})})
    _commit(tmp_path, "base")
    return tmp_path


def _check(repo, *args):
    result = subprocess.run([sys.executable, "-m", "checkwash", "check", *args, "--repo", str(repo)],
                            env=ENV, capture_output=True, timeout=120)
    return result.returncode, result.stdout.decode("utf-8"), result.stderr.decode("utf-8")


# --- the writer ------------------------------------------------------------------------------------

@dataclass(frozen=True)
class _Prefixed(UnreadSide):
    """A side with a field beyond the note's four, as #455 stores a bounded prefix."""

    prefix: bytes = b"#!/bin/sh\n"


@pytest.mark.parametrize("kind", [UnreadSide, _Prefixed], ids=["plain", "with_prefix"])
def test_the_document_holds_only_the_refused_sides_unread_entry(kind):
    # The entry is #454's explicit four-key projection, so a field the side
    # may carry (#455's prefix) stays out of it here too.
    text = size_refusal_to_json(kind("tests/test_huge.py", "head", LIMIT + 1, LIMIT))
    assert text == (
        "{\n"
        '  "unread": [\n'
        "    {\n"
        '      "limit": 1000000,\n'
        '      "path": "tests/test_huge.py",\n'
        '      "side": "head",\n'
        '      "size": 1000001\n'
        "    }\n"
        "  ]\n"
        "}\n"
    )
    # Not a findings document: no version, findings or verdict to read a
    # pass from.
    assert set(json.loads(text)) == {"unread"}


# --- the CLI ---------------------------------------------------------------------------------------

ROWS = {
    # name: (base extra files, the change, a range or the working tree, the side the refusal names)
    # Both sides over the limit: the refusal names the change's first unread
    # side, the base side, and so does the entry, as the stderr line does.
    "worktree_both_sides": (lambda: {"vendor/big.py": blob(LIMIT + 1, "big")},
                            lambda: {"tests/test_billing.py": WEAKENED, "vendor/big.py": blob(LIMIT + 2, "bigger")},
                            False, ("vendor/big.py", "base", LIMIT + 1)),
    # The Stop hook keeps the #414 note here (#456 Q3); json names the side.
    "worktree_base_side_alone": (lambda: {"tools/gen.py": blob(LIMIT + 1, "gen")},
                                 lambda: {"tests/test_billing.py": WEAKENED, "tools/gen.py": b"GENERATED = 1\n"},
                                 False, ("tools/gen.py", "base", LIMIT + 1)),
    # An untracked shell script with no extension, one byte past the limit:
    # refused for having no extension, and for its shell shebang once #455
    # reads that from the unread side's first bytes.
    "worktree_untracked_shell_script": (
        lambda: {},
        lambda: {"tests/test_billing.py": WEAKENED,
                 "NOTES": b"#!/bin/sh\n" + blob(LIMIT + 1 - len(b"#!/bin/sh\n"), "notes")},
        False, ("NOTES", "worktree", LIMIT + 1)),
    "range_base_side_alone": (lambda: {"tools/gen.py": blob(LIMIT + 1, "gen")},
                              lambda: {"tools/gen.py": b"GENERATED = 1\n"},
                              True, ("tools/gen.py", "base", LIMIT + 1)),
}


@pytest.mark.parametrize("row", sorted(ROWS))
def test_json_names_the_refused_side_and_keeps_exit_2(tmp_path, row):
    base, edit, in_range, refused = ROWS[row]
    repo = _repo(tmp_path, base())
    _write(repo, edit())
    if in_range:
        _commit(repo)
        code, stdout, stderr = _check(repo, "HEAD~1..HEAD", "--format", "json")
    else:
        code, stdout, stderr = _check(repo, "--format", "json")
    assert code == 2, stderr
    assert stdout == _document(entry(*refused))
    # The one stderr line every format writes for the refusal names the same
    # side, so entry and line match one to one; no unread note is added.
    assert stderr.splitlines() == [f"checkwash engine error: SourceOverLimit: {side(*refused).message()}"]


def test_emit_ir_keeps_an_empty_stdout_on_a_size_refusal(tmp_path):
    # `--emit-ir` is the IR interface, which names no unread side (#454
    # ruling, item 6), and a refused run has no IR.
    repo = _repo(tmp_path)
    _write(repo, {"tests/test_billing.py": PADDED})
    code, stdout, stderr = _check(repo, "--format", "json", "--emit-ir")
    assert (code, stdout) == (2, ""), stderr
    assert stderr.splitlines() == [
        f"checkwash engine error: SourceOverLimit: {side('tests/test_billing.py', 'worktree').message()}"]


@pytest.mark.parametrize("error", [
    # Another limit refusal that names a path and a side, but is no size refusal.
    EngineError("strict snapshot batch exceeds the byte limit at tests/test_billing.py "
                "(worktree, 64000001 > 64000000 bytes)"),
    RecursionError("maximum recursion depth exceeded"),
], ids=["batch_limit", "recursion"])
def test_other_engine_errors_keep_an_empty_stdout(tmp_path, monkeypatch, capsys, error):
    repo = _repo(tmp_path)
    _write(repo, {"tests/test_billing.py": WEAKENED})

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(cli_module, "analyze", fail)
    assert main(["check", "--repo", str(repo), "--format", "json"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("checkwash engine error: ") and str(error) in captured.err


def test_a_size_refusal_for_a_side_no_change_holds_is_named_too(tmp_path, monkeypatch, capsys):
    # A context read of an unchanged file refuses with a side the diff does
    # not hold. The run stopped all the same, so json names that side.
    repo = _repo(tmp_path)
    _write(repo, {"tests/test_billing.py": WEAKENED})
    refused = side("helpers/big.py", "worktree")

    def fail(*args, **kwargs):
        raise refused.refusal()

    monkeypatch.setattr(cli_module, "analyze", fail)
    assert main(["check", "--repo", str(repo), "--format", "json"]) == 2
    captured = capsys.readouterr()
    assert captured.out == _document(entry("helpers/big.py", "worktree"))
    assert captured.err == f"checkwash engine error: SourceOverLimit: {refused.message()}\n"
