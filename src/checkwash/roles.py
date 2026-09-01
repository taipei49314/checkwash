"""Path roles: artifacts, collection, runner shape. Extracted from engine (E5)."""
from __future__ import annotations

import re
from collections import Counter

from checkwash.change import FileChange
from checkwash.config import Config


# Generated/binary artifacts. A changed file here says nothing about
# production behaviour, so it must never buy repair evidence: pytest's own
# untracked __pycache__/*.pyc silently disarmed the whole escalator in the
# first decoy run (0/12 caught), which any build artifact would reproduce.
_ARTIFACT_SEGMENTS = frozenset(
    {
        "__pycache__",
        ".git",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        ".nox",
        ".venv",
        "venv",
        "node_modules",
        "dist",
        "build",
        "htmlcov",
        ".eggs",
    }
)
# Prod-role files that cannot change the runtime behaviour of the code under
# test: type stubs (never executed), docs-site and docs-build config, repo
# metadata, dev-tooling config. A change here is not repair evidence and must
# not grant the opaque exemption (THREATMODEL #4) — docs and stubs were the
# bulk of the 7.2% of corpus commits whose pass rested on the blanket. The
# list is deliberately short and explicit: anything not on it stays opaque,
# which fails toward flagging.
_INERT_SUFFIXES = (".pyi", ".cff")
_INERT_BASENAMES = frozenset(
    {
        ".gitignore",
        ".gitattributes",
        ".editorconfig",
        ".flake8",
        ".git_archival.txt",
        ".python-version",
        ".python-version-default",
        "mkdocs.yml",
        ".readthedocs.yaml",
        ".readthedocs.yml",
        "dependabot.yml",
        "FUNDING.yml",
        "CODEOWNERS",
        "MANIFEST.in",
    }
)


def _is_inert(path: str) -> bool:
    if path.endswith(_INERT_SUFFIXES):
        return True
    base = path.rsplit("/", 1)[-1]
    return base in _INERT_BASENAMES or base.startswith(("LICENSE", "COPYING"))


_ARTIFACT_SUFFIXES = (
    ".pyc",
    ".pyo",
    ".pyd",
    ".so",
    ".dll",
    ".dylib",
    ".a",
    ".o",
    ".class",
    ".jar",
    ".zip",
    ".tar",
    ".gz",
    ".whl",
    ".exe",
    ".bin",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".pdf",
    ".woff",
    ".woff2",
    ".ttf",
    ".mo",
    ".coverage",
    ".log",
)


def is_artifact(path: str) -> bool:
    # Segment-anchored, not substring: `build/` used to match `mybuild/` and
    # `dist/` matched `redist/`, silently deleting real source trees from the
    # analysis — which is both a false negative and a one-rename bypass.
    p = path.replace("\\", "/")
    segments = p.split("/")
    if any(seg in _ARTIFACT_SEGMENTS or seg.endswith(".egg-info") for seg in segments):
        return True
    return segments[-1].lower().endswith(_ARTIFACT_SUFFIXES)


def collectable(path: str) -> bool:
    """Would pytest's default collection run this file?

    Role globs say what a path is *for*; collectability says whether its tests
    actually execute. A rename that keeps the test role but leaves collection
    (tests/billing_checks.py) kills the tests just as dead as deletion.

    Two rules, not one. pytest's filename patterns (`test_*.py`, `*_test.py`)
    decide the basename, and `norecursedirs` decides the directory: dot-dirs,
    build output and virtualenvs are never descended into. Judging the
    basename alone meant `git mv tests/test_x.py build/test_x.py` and
    `... .attic/test_x.py` both read as "still a collected test file", so the
    tests vanished from the suite and from the report (reader audit
    2026-08-02).
    """
    p = path.replace("\\", "/")
    segments = p.split("/")
    for seg in segments[:-1]:
        if seg in _ARTIFACT_SEGMENTS or seg.endswith(".egg-info"):
            return False
        if len(seg) > 1 and seg.startswith("."):
            return False  # pytest's default norecursedirs excludes `.*`
    base = segments[-1]
    return (base.startswith("test_") and base.endswith(".py")) or base.endswith("_test.py")

# Deterministic markers of a weakened test command in CI files.
# Anchored, not bare substrings: `--ignore` matched `--ignore-missing-imports`
# in a mypy step and blocked innocent CI edits at high.
# Enough of a test runner to call a workflow's removal a loss of coverage.
_TEST_RUNNER_TOKENS = (
    "pytest",
    "unittest",
    "tox",
    "nox",
    "npm test",
    "yarn test",
    "pnpm test",
    "go test",
    "cargo test",
    "make test",
    "gradle test",
    "mvn test",
    "dotnet test",
    "rspec",
    "jest",
    "vitest",
)

# Two families, and the difference between them is the whole of E6's
# precision. A *swallow* discards an exit code: introducing one anywhere is a
# weakened command, because a second one is not made harmless by the first.
_CI_SWALLOW_TOKENS = (
    "continue-on-error: true",
    "|| true",
    # The shell has more than one spelling for "ignore the exit code", and a
    # list that knows one of them knows none of them (probe 2026-08-07).
    "|| :",
    "|| exit 0",
    "set +e",
)

# A *narrowing* restricts which tests run. Restating one is not narrowing
# anything, and a one-sided scan of added lines cannot tell the two apart:
# deleting `setup.cfg` and adding `pyproject.toml` with a byte-identical
# `testpaths` was reported as a weakened test command at high, and so was
# configuring pytest for the first time in a repository that had no
# configuration at all. Both are among the most ordinary commits in the
# Python ecosystem, and both blocked (field integration 2026-08-07: psf/
# requests 2a6f290b, pallets/jinja 20477c63, pydantic 0c27c49d).
_CI_NARROWING_TOKENS = (
    "--ignore=",
    "--ignore ",
    "--deselect",
    ' -k "',
    " -k '",
    # pytest's own collection knobs. Narrowing `python_files` or `testpaths`,
    # or adding `-p no:...`, silences tests without touching a single test
    # file — and pytest.ini/tox.ini/setup.cfg/pyproject.toml had no role, so
    # nothing inspected them (reader audit 2026-08-02).
    "python_files",
    "python_classes",
    "python_functions",
    "testpaths",
    "norecursedirs",
    "collect_ignore",
    "-p no:",
)

_CI_WEAKENING_TOKENS = _CI_SWALLOW_TOKENS + _CI_NARROWING_TOKENS

def _decode(data: bytes | None) -> str:
    if not data:
        return ""
    return data.decode("utf-8-sig", errors="replace").replace("\r\n", "\n").replace("\r", "\n")


def _added_lines(before: bytes | None, after: bytes | None) -> list[str]:
    b = Counter(_decode(before).split("\n"))
    lines = []
    for line in _decode(after).split("\n"):
        if b[line] > 0:
            b[line] -= 1
        else:
            lines.append(line)
    return lines

def _runs_tests(data: bytes | None) -> bool:
    """Did this CI file actually run a test suite?

    Deliberately generous: any recognised runner anywhere in the file counts,
    because the cost of guessing wrong in this direction is one warn-level
    finding, while guessing wrong the other way blocks an honest commit.
    """
    if not data:
        return False
    text = data.decode("utf-8", errors="replace").lower()
    return any(token in text for token in _TEST_RUNNER_TOKENS)


_RUNNER_SCRIPT_SUFFIXES = (".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd", ".mk", ".mak")
# Prefixes, not exact names: `Makefile.include`, `Makefile.common` and
# `common.mak` are all make recipe files, and the exact-name set knew three
# spellings out of an open set. Measured 2026-08-11: `common.mak` and
# `Makefile.include` did not merely hide their own weakening, they were
# classified `prod`, could not be parsed, and therefore bought the opaque
# exemption that demoted the assertion weakening beside them from high to warn
# (THREATMODEL 87).
_RUNNER_SCRIPT_BASE_PREFIXES = ("Makefile", "makefile", "GNUmakefile")
_SHELL_INTERPRETERS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "ash"})


def _shell_shebang(data: bytes | None) -> bool:
    """Does this file start with a shell shebang?

    The two corpus projects that keep their suite in a script (httpx,
    starlette) both call it `scripts/test` with no extension, so the shebang
    is the only shape available. A python shebang does not count: a prod
    module that imports pytest is production code, not runner config.
    """
    if not data or not data.startswith(b"#!"):
        return False
    # First 200 bytes only: a shebang is short, and an unsplit binary blob
    # should not be decoded whole to answer this (perf gate, SPEC §10).
    words = data[:200].split(b"\n", 1)[0].decode("utf-8", errors="replace")[2:].strip().split()
    if not words:
        return False
    interp = words[0].rsplit("/", 1)[-1]
    if interp == "env" and len(words) > 1:
        interp = words[1].rsplit("/", 1)[-1]
    return interp in _SHELL_INTERPRETERS


def _runner_shape(path: str, before: bytes | None, after: bytes | None) -> bool:
    """Is this file shaped like a shell script or a make recipe file?

    Shape alone decides nothing — `_is_runner_script` adds the content gate —
    but it is what scopes the shell-specific weakenings (errexit, "the suite
    is gone") away from yaml and ini files, where they mean nothing.
    """
    if path.endswith(".py"):
        return False
    base = path.rsplit("/", 1)[-1]
    return (
        path.endswith(_RUNNER_SCRIPT_SUFFIXES)
        or base.startswith(_RUNNER_SCRIPT_BASE_PREFIXES)
        or _shell_shebang(before)
        or _shell_shebang(after)
    )


def _mentions_test_runner(change) -> bool:
    """Does either side of this file invoke a test runner?

    The durable half of the 2026-08-11 fix, and the half that does not depend
    on knowing filenames. Widening the shape list closes the four spellings
    that were measured; it cannot close the next four. What can is refusing to
    call a file *unreadable production code* when the file's own content runs
    the test suite.

    Deliberately independent of `_runner_shape`: a file whose name checkwash
    does not recognise still loses the opaque exemption if it runs the tests.
    It does **not** become `ci` — a Makefile that builds a C extension has no
    runner token, stays production, and keeps its full repair-evidence weight
    (`runner_build_makefile_neg`).
    """
    return _runs_tests(change.before) or _runs_tests(change.after)


_SCRIPT_REF = re.compile(
    rb"(?:^|[\s;&|(=\"'])\.?/?((?:[\w.-]+/)*[\w.-]+\.(?:sh|bash|zsh|ps1|bat|cmd))",
    re.MULTILINE,
)
_MAX_ONE_HOP_READS = 32
# Head-snapshot reads for cross-file oracle resolution (A5-x): sibling helper
# modules and conftests are small and few, and a diff that references more
# than this many distinct ones simply stops resolving — a missed credit, not
# a crash, matching every other read cap in this file.
_MAX_ORACLE_READS = 16


def _referenced_scripts(data: bytes | None) -> list[str]:
    """Script paths this file invokes, as written.

    Deliberately syntactic and deliberately shallow: this exists to follow one
    hop, not to model a shell.
    """
    if not data or len(data) > 1_000_000:
        return []
    out = []
    for m in _SCRIPT_REF.finditer(data):
        ref = m.group(1).decode("utf-8", errors="replace").lstrip("./")
        if ref not in out:
            out.append(ref)
    return out


def _one_hop_runners(
    changes: list[FileChange], config: Config, head_reader
) -> set[str]:
    """Changed scripts that run the suite *through* another script.

    `scripts/ci.sh` containing only `./scripts/run-tests.sh` holds no runner
    token, so the content gate left it as production. Adding `|| true` to that
    line therefore hid its own weakening **and** bought the changed-production
    credit that de-escalated the assertion weakening beside it — row 87's
    double effect, one hop further out, and measured the same way: the diff
    passed (THREATMODEL 89).

    Bounded at one hop, and the hop must terminate in a real test runner. A
    `scripts/ci.sh` that calls `scripts/compile.sh` is still production, which
    is the same line the content gate has drawn since v0.1.8 and what keeps a
    build script from becoming CI config.
    """
    after_by_path = {c.path.replace("\\", "/"): c.after for c in changes}
    reads = 0

    def content(ref: str) -> bytes | None:
        nonlocal reads
        if ref in after_by_path:
            return after_by_path[ref]
        if head_reader is None or reads >= _MAX_ONE_HOP_READS:
            return None
        reads += 1
        try:
            return head_reader(ref)
        except Exception:  # pragma: no cover - a missing path is not an error
            return None

    promoted: set[str] = set()
    for change in changes:
        path = change.path.replace("\\", "/")
        if is_artifact(path) or config.role_of(path) != "prod":
            continue
        if not _runner_shape(path, change.before, change.after):
            continue
        if _runs_tests(change.before) or _runs_tests(change.after):
            continue  # already a runner script on its own content
        for side in (change.after, change.before):
            for ref in _referenced_scripts(side):
                if _runs_tests(content(ref)):
                    promoted.add(path)
                    break
            if path in promoted:
                break
    return promoted


def _is_runner_script(path: str, before: bytes | None, after: bytes | None) -> bool:
    """Is this multi-purpose file the project's test command?

    Classified by *content*, not by name. A Makefile that runs pytest is
    test-runner configuration and weakening it is tampering; a Makefile that
    compiles a C extension is production, and its edit is genuine repair
    evidence for a test that changed with it. Filename alone cannot tell
    those apart, and guessing by filename would have invented false
    positives in every extension project.

    Python is excluded outright (`noxfile.py` is covered by path instead):
    a first-party pytest plugin lives in `src/` and mentions every runner
    token there is.
    """
    # `before` too: a script that stops running the suite in this very diff
    # is the interesting case, not an excluded one.
    return _runner_shape(path, before, after) and (_runs_tests(before) or _runs_tests(after))

