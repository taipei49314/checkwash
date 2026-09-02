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


# The one git failure this fixture retries. On `macos-latest` runners, git
# intermittently cannot write a loose object into its own database while the
# fixture is adding 150 generated files — "error: <file>: failed to insert
# into database / fatal: updating files failed", exit 128 — and a re-run of
# the identical job passes (2026-08-13 macOS 3.11; 2026-09-02 macOS 3.12 on
# PR #73 and macOS 3.11 on the post-merge run of #77; issue #78). That is the
# runner's temp volume, not the code under test, but `test` is a required
# check, so it turned green changes red until someone read the log.
#
# Retry, never skip: a perf gate that passes when its subject is absent is the
# "green because it did not run" pattern docs/RELEASING.md warns about. Only
# this stderr is retried, a bounded number of times, each attempt printed;
# after the budget it fails exactly as before. Every other failure raises on
# the first attempt.
GIT_OBJECT_STORE_FAILURE = b"failed to insert into database"
GIT_ATTEMPTS = 3
GIT_RETRY_PAUSE_S = 0.5


def _git(repo, *args):
    """Run git in the scratch repo, and say why when it fails.

    `check=True, capture_output=True` reports the exit code and throws the
    reason away. That is how `git add -A` returning 128 on the macOS 3.11 leg
    (2026-08-13) arrived as a bare CalledProcessError with nothing to diagnose
    — on a gate whose whole purpose is to keep a performance regression from
    being ignored. A gate that fails without saying why gets ignored just as
    thoroughly as one that does not run.

    `safe.directory` is set because a temp directory whose owner git does not
    recognise makes every command in it fail this way, and the runner's
    `/private/var/folders/...` is exactly that shape.
    """
    for attempt in range(1, GIT_ATTEMPTS + 1):
        proc = subprocess.run(
            ["git", "-c", f"safe.directory={repo}", "-C", str(repo), *args],
            capture_output=True,
        )
        if proc.returncode == 0:
            return
        transient = proc.returncode == 128 and GIT_OBJECT_STORE_FAILURE in proc.stderr
        if not transient or attempt == GIT_ATTEMPTS:
            raise AssertionError(
                f"git {' '.join(args)} failed ({proc.returncode}) in {repo}"
                f" (attempt {attempt} of {GIT_ATTEMPTS})\n"
                f"stdout: {proc.stdout.decode('utf-8', 'replace')}\n"
                f"stderr: {proc.stderr.decode('utf-8', 'replace')}"
            )
        print(
            f"git {' '.join(args)} attempt {attempt} of {GIT_ATTEMPTS} failed (128) in {repo}:"
            f" object store write failed on the runner; retrying\n"
            f"stderr: {proc.stderr.decode('utf-8', 'replace').strip()}",
            file=sys.stderr,
        )
        time.sleep(GIT_RETRY_PAUSE_S * attempt)


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
        [sys.executable, "-m", "checkwash", "check", "HEAD~1..HEAD",
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
    from checkwash.gitio import git as gitio

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


# --- the retry itself is tested with a fake git, so the policy above is
# --- pinned rather than described (issue #78).

class _FakeGit:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def __call__(self, argv, capture_output=True):
        self.calls += 1
        code, stderr = self.outcomes.pop(0)
        return subprocess.CompletedProcess(argv, code, stdout=b"", stderr=stderr)


def _install_fake_git(monkeypatch, outcomes):
    fake = _FakeGit(outcomes)
    monkeypatch.setattr(subprocess, "run", fake)
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    return fake


def test_git_retries_once_on_object_store_failure_then_succeeds(monkeypatch, tmp_path):
    fake = _install_fake_git(monkeypatch, [
        (128, b"error: src/app/mod_72.py: failed to insert into database\nfatal: updating files failed\n"),
        (0, b""),
    ])
    _git(tmp_path, "add", "-A")
    assert fake.calls == 2


def test_git_gives_up_after_the_retry_budget(monkeypatch, tmp_path):
    fake = _install_fake_git(monkeypatch, [
        (128, b"error: tests/test_mod_103.py: failed to insert into database\n")
    ] * GIT_ATTEMPTS)
    with pytest.raises(AssertionError) as raised:
        _git(tmp_path, "add", "-A")
    assert fake.calls == GIT_ATTEMPTS
    assert "failed to insert into database" in str(raised.value)
    assert f"attempt {GIT_ATTEMPTS} of {GIT_ATTEMPTS}" in str(raised.value)


def test_git_does_not_retry_other_failures(monkeypatch, tmp_path):
    fake = _install_fake_git(monkeypatch, [
        (128, b"fatal: not a git repository (or any of the parent directories): .git\n"),
        (0, b""),
    ])
    with pytest.raises(AssertionError) as raised:
        _git(tmp_path, "status")
    assert fake.calls == 1
    assert "not a git repository" in str(raised.value)
