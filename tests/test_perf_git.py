"""Performance through the path a user actually runs.

`tests/gates/test_perf.py` calls `analyze()` with in-memory `FileChange`
objects. That measures the engine and nothing else, so it could not see that a
range diff spawned two `git show` processes per modified file: on pydantic, a
120-file commit spent 9.1 s in 241 subprocesses, 58% of its wall clock, while
the gate reported everything was fine (field integration 2026-08-07). A budget
that cannot see the dominant cost is not a budget.

This measures `check BASE..HEAD` against a real repository, through gitio,
including process spawning. It is deliberately a separate file from the frozen
thresholds next door: those describe the engine, these describe the product.
"""

import datetime
import os
import subprocess
import sys
import time

import pytest

# Generous enough not to be flaky on a loaded laptop or a cold CI runner,
# tight enough that reverting to a process per blob fails it: that regression
# is ~10x on this shape, and it is the one that actually happened.
BUDGET_MANY_FILES_S = 12.0
MAX_GIT_PROCESSES = 24  # two commits' worth of plumbing, not two per file

FILES = 150


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture(scope="module")
def big_repo(tmp_path_factory):
    repo = tmp_path_factory.mktemp("perf_git")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "perf@example.invalid")
    _git(repo, "config", "user.name", "perf")
    _git(repo, "config", "commit.gpgsign", "false")
    src = repo / "src" / "app"
    tests = repo / "tests"
    src.mkdir(parents=True)
    tests.mkdir()
    (src / "__init__.py").write_text("", encoding="utf-8")
    for i in range(FILES):
        (src / f"mod_{i}.py").write_text(
            f"def compute_{i}(x):\n    return x * {i + 1}\n", encoding="utf-8"
        )
        (tests / f"test_mod_{i}.py").write_text(
            f"from app.mod_{i} import compute_{i}\n\n\n"
            f"def test_compute_{i}():\n    assert compute_{i}(2) == {2 * (i + 1)}\n",
            encoding="utf-8",
        )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")

    # A change that touches every file on both sides — the shape that made the
    # per-blob reader spawn 2N processes.
    for i in range(FILES):
        (src / f"mod_{i}.py").write_text(
            f"def compute_{i}(x):\n    # tuned\n    return x * {i + 1}\n", encoding="utf-8"
        )
        (tests / f"test_mod_{i}.py").write_text(
            f"from app.mod_{i} import compute_{i}\n\n\n"
            f"def test_compute_{i}():\n    result = compute_{i}(2)\n"
            f"    assert result == {2 * (i + 1)}\n",
            encoding="utf-8",
        )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "touch everything")
    return repo


def test_range_check_through_git_stays_within_budget(big_repo):
    env = {**os.environ, "PYTHONUTF8": "1", "GREENWASH_TODAY": "2026-01-01"}
    start = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, "-m", "greenwash", "check", "HEAD~1..HEAD",
         "--repo", str(big_repo), "--format", "json"],
        capture_output=True, env=env,
    )
    elapsed = time.perf_counter() - start
    assert proc.returncode in (0, 1), proc.stderr.decode("utf-8", "replace")
    assert elapsed < BUDGET_MANY_FILES_S, (
        f"{FILES * 2} changed files through git took {elapsed:.2f}s "
        f"(budget {BUDGET_MANY_FILES_S}s). The dominant cost here is process "
        f"spawning, not the engine."
    )


def test_blobs_are_read_in_a_batch_not_one_process_each(big_repo):
    """The count, not just the clock: a timing budget alone would pass on a
    fast machine while the process-per-blob shape crept back in."""
    from greenwash.gitio import git as gitio

    calls = []
    original = gitio._run

    def counting(repo, args):
        calls.append(args[0])
        return original(repo, args)

    gitio._run = counting
    try:
        changes = gitio.list_range_changes(str(big_repo), "HEAD~1", "HEAD")
    finally:
        gitio._run = original

    assert len(changes) == FILES * 2, len(changes)
    assert all(c.before and c.after for c in changes), "batched reader lost content"
    assert len(calls) <= MAX_GIT_PROCESSES, (
        f"{len(calls)} git processes for {len(changes)} changed files "
        f"({calls.count('show')} of them `show`) — blob reads are not batched"
    )
