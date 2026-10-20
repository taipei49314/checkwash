"""Issue #455, question 4: an unchanged file with no dot in its name, read by the provider pass.

#455 keeps the first 200 bytes of a changed side over the 1,000,000-byte
source limit. A changed oversized document whose sides hold no shell shebang
is set aside, the runtime-provider pass skips it, and the run gets a verdict.
A file the diff does not hold is not covered. The pass's first read phase
requests every inventory path whose name has no dot, for the shebang that is
its only runner shape, and reads it as an unchanged file through the strict
root reader. That reader refuses a file over the limit, a symlink and a batch
over the 64,000,000-byte budget. So on a run that reaches the phase, an
unchanged `README` over the limit exits 2 where the same file changed gets a
verdict (D-164, residual 2). The changed case is pinned in
test_issue455_bounded_shebang_read.py
(`test_a_run_that_reaches_the_provider_pass_gives_a_verdict_beside_a_set_aside_readme`);
the over-limit rows reuse that fixture with the README left unchanged, and
the control keeps the same README beside test_issue415's weakened test.

Ruling (owner, 2026-10-18, question 4, issuecomment-6248628575): an
unchanged dot-less file over the limit that the provider pass reads is first
confirmed by a test, in range and worktree mode, then filed as its own issue,
not fixed in #455's PR. Round 6 (G6, F20 option A) puts the test in a
test-only PR after #536.

The `..._still_refuse(s)` tests pin that residual as it is today; its fix
changes them under its own ruling (AGENTS.md rule 2). The control test gives
a verdict and holds before and after it.

Large files are generated here, never committed.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from checkwash.cli import main
from checkwash.gitio import snapshot as snapshots

LIMIT = 1_000_000
REFUSAL = "strict snapshot source exceeds the byte limit"
NONREGULAR = "strict snapshot batch cannot inspect nonregular source"
OVER_BUDGET = "strict snapshot batch exceeds the byte limit"
DOCUMENT = b"Billing service\n\nRelease notes, licence terms and the change log.\n"
# test_issue455's provider-pass fixture: a new provider of `src.billing`
# beside the test that imports it takes the pass to its first read phase.
SOURCES = {
    "src/billing.py": b"def invoice_total():\n    return 1\n",
    "tests/test_billing.py": (b"from src.billing import invoice_total\n\n"
                              b"def test_invoice_total():\n    assert invoice_total() == 2\n"),
}
NEW_PROVIDER = {"tests/src/billing.py": b"def invoice_total():\n    return 2\n"}
# test_issue415's fixture, whose weakened test alone stops the pass short of
# that phase.
BILLING = b"def compute_invoice_total(items):\n    return sum(items)\n"
TEST = (b"from billing import compute_invoice_total\n\n\n"
        b"def test_invoice_total():\n"
        b"    total = compute_invoice_total([10.5, 94.8])\n"
        b"    assert total == 105.3\n")
WEAKENED = TEST.replace(b"assert total == 105.3", b"assert total > 0")


def blob(size, seed):
    """`size` bytes of hex text, distinct per seed (as in test_issue415)."""
    body = hashlib.shake_256(seed.encode()).hexdigest((size + 1) // 2).encode()
    return body[:size - 1] + b"\n"


def headed(head, size, seed):
    """`size` bytes that start with `head`, then hex text."""
    return head + blob(size - len(head), seed)


# The same unchanged document in the over-limit rows and the control:
# test_issue455's README, with no shell shebang, one byte over the limit.
README = headed(DOCUMENT, LIMIT + 1, "readme")


def described(path, side, size=LIMIT + 1):
    return f"{path} ({side}, {size} > {LIMIT} bytes)"


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True).stdout


def _write(repo, files):
    for path, data in files.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_bytes(data)


def _repo(path, files, links=None):
    """A repository whose base commit holds `files` and the symlinks `links`.

    Each link is made in the index, not on disk, so every host commits the
    same entry, mode 120000.
    """
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-b", "main")
    git(path, "config", "user.name", "checkwash-test")
    git(path, "config", "user.email", "test@example.invalid")
    git(path, "config", "commit.gpgsign", "false")
    git(path, "config", "core.autocrlf", "false")
    _write(path, files)
    git(path, "add", "-A")
    for link, target in (links or {}).items():
        oid = subprocess.run(["git", "-C", str(path), "hash-object", "-w", "--stdin"], input=target,
                             capture_output=True, check=True).stdout.decode("ascii").strip()
        git(path, "update-index", "--add", "--cacheinfo", f"120000,{oid},{link}")
    git(path, "commit", "-m", "base")
    return path


def _symlink(link, target):
    """A file symlink, or a skip where the host cannot make one (as in test_issue416)."""
    try:
        os.symlink(target, link)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")


def _arguments(repo, mode, *paths):
    """The `check` arguments for `mode` and the side its head is; range mode commits the head.

    Given `paths`, only they are committed: `add -A` would stage the removal
    of a link made in the index alone.
    """
    if mode == "worktree":
        return ("--format", "json"), "worktree"
    git(repo, "add", *(("--", *paths) if paths else ("-A",)))
    git(repo, "commit", "-m", "head")
    return ("HEAD~1..HEAD", "--format", "json"), "head"


def _check(repo, *args):
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
           "PYTHONUTF8": "1", "GREENWASH_TODAY": "2026-10-20", "NO_COLOR": "1"}
    result = subprocess.run([sys.executable, "-m", "checkwash", "check", *args, "--repo", str(repo)],
                            env=env, capture_output=True, timeout=120)
    return result.returncode, result.stdout.decode("utf-8"), result.stderr.decode("utf-8")


# --- an unchanged file over the limit ---------------------------------------------------------------

@pytest.mark.parametrize("mode", ["range", "worktree"])
def test_an_unchanged_dot_less_file_over_the_limit_still_refuses(tmp_path, mode):
    # The residual: the new provider takes the pass to phase one, which asks
    # the strict reader for the unchanged README, and the reader refuses it.
    repo = _repo(tmp_path, {**SOURCES, "README": README})
    _write(repo, NEW_PROVIDER)
    args, side = _arguments(repo, mode)
    code, stdout, stderr = _check(repo, *args)
    assert code == 2
    # #454 (d) names the refused side: a side of a file the diff does not hold.
    assert json.loads(stdout) == {"unread": [{"limit": LIMIT, "path": "README", "side": side, "size": LIMIT + 1}]}
    assert f"checkwash engine error: SourceOverLimit: {REFUSAL}: {described('README', side)}" in stderr


@pytest.mark.parametrize("mode", ["range", "worktree"])
def test_a_run_short_of_the_provider_pass_never_reads_the_unchanged_file(tmp_path, mode):
    # A weakened test alone adds no provider, so the pass returns before
    # phase one and nothing reads the same unchanged README: the weakening
    # blocks as a finding, and no side is named.
    repo = _repo(tmp_path, {"billing.py": BILLING, "tests/test_billing.py": TEST, "README": README})
    _write(repo, {"tests/test_billing.py": WEAKENED})
    args, _side = _arguments(repo, mode)
    code, stdout, stderr = _check(repo, *args)
    assert "engine error" not in stderr, stderr
    payload = json.loads(stdout)
    assert (code, payload["verdict"]) == (1, "block")
    assert "ASSERT_WEAKENED" in {f["rule"] for f in payload["findings"]}
    assert "unread" not in payload
    assert "README" not in stderr


# --- an unchanged symlink and a batch over the budget -----------------------------------------------

@pytest.mark.parametrize("mode", ["range", "worktree"])
def test_an_unchanged_dot_less_symlink_still_refuses(tmp_path, mode):
    # The residual for a symlink, which the strict batch reader never reads.
    if mode == "range":
        # A root licence committed as a link to `py/LICENSE`: the shape of the
        # pytest commits #415's acceptance sweep saw exit 2 (ruling, question 4).
        link = "LICENSE"
        repo = _repo(tmp_path, {**SOURCES, "py/LICENSE": b"Licence terms\n"}, links={link: b"py/LICENSE"})
        _write(repo, NEW_PROVIDER)
        args, _side = _arguments(repo, mode, *NEW_PROVIDER)
    else:
        # A gitignored POSIX venv, whose `bin/python` is a link: the
        # working-tree inventory lists ignored trees too. The ruling names
        # CI's POSIX legs for it; GitHub's Windows runners make symlinks as
        # well, so they run it too, and a host that cannot make one skips it.
        link = ".venv/bin/python"
        repo = _repo(tmp_path, {**SOURCES, ".gitignore": b".venv/\n"})
        (repo / ".venv" / "bin").mkdir(parents=True)
        # Stands in for the interpreter; its name has a dot, so phase one never asks for it.
        (repo / ".venv" / "bin" / "python3.12").write_bytes(b"")
        _symlink(repo / link, "python3.12")
        _write(repo, NEW_PROVIDER)
        args, _side = _arguments(repo, mode)
    code, stdout, stderr = _check(repo, *args)
    # Not a size refusal, so stdout stays empty (#454).
    assert (code, stdout) == (2, "")
    assert f"checkwash engine error: EngineError: {NONREGULAR} {link} (a symlink)" in stderr


BUDGET = 1_100_000


@pytest.mark.parametrize("mode", ["range", "worktree"])
def test_unchanged_dot_less_files_over_the_batch_budget_still_refuse(tmp_path, monkeypatch, capsys, mode):
    # The residual for the batch budget. At the real 64,000,000 bytes that
    # takes 64 unchanged dot-less files of 1,000,000 bytes beside the test,
    # too large to build here, so the CLI runs in process with the budget
    # patched down. Two documents of 600,000 bytes, each under the source
    # limit, cross it together in phase one's batch; NEWS sorts first, so
    # README crosses it.
    repo = _repo(tmp_path, {**SOURCES, "NEWS": headed(DOCUMENT, 600_000, "news"),
                            "README": headed(DOCUMENT, 600_000, "readme")})
    _write(repo, NEW_PROVIDER)
    args, side = _arguments(repo, mode)
    monkeypatch.setattr(snapshots, "MAX_BATCH_BYTES", BUDGET)
    assert main(["check", *args, "--repo", str(repo)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert (f"checkwash engine error: EngineError: {OVER_BUDGET} at README ({side}, 1200000 > {BUDGET} bytes)"
            in captured.err)
