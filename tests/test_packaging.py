"""Packaging invariants that a release depends on.

A README whose install line doesn't work is the first thing a visitor hits,
and this project's whole pitch is that its claims are checkable. So the
claims about itself are tests too.
"""

import pathlib
import re
import tomllib

import greenwash

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _pyproject() -> dict:
    with open(ROOT / "pyproject.toml", "rb") as fh:
        return tomllib.load(fh)


def test_version_matches_pyproject():
    assert greenwash.__version__ == _pyproject()["project"]["version"]


def test_no_runtime_dependencies():
    # "Zero runtime dependencies" is a headline claim and a security
    # property (SECURITY.md), not an accident.
    assert _pyproject()["project"]["dependencies"] == []


def test_documented_test_count_is_accurate():
    """The test count in prose must match reality.

    README said 131 while the suite had 134 and the release notes said 134 —
    three numbers, one truth. Rather than remember to update prose, this
    fails when it drifts.
    """
    import os
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only"],
        capture_output=True,
        cwd=str(ROOT),
        env={**os.environ, "PYTHONUTF8": "1"},
    )
    out = proc.stdout.decode("utf-8", "replace")
    m = re.search(r"(\d+) tests? collected", out)
    actual = (
        int(m.group(1))
        if m
        else len([ln for ln in out.splitlines() if "::" in ln and ln.strip()])
    )
    assert actual > 0, f"could not determine collected test count:\n{out[-400:]}"

    for doc in ("README.md", "CONTRIBUTING.md"):
        text = (ROOT / doc).read_text(encoding="utf-8")
        for claimed in re.findall(r"(\d+) tests\b", text):
            assert int(claimed) == actual, (
                f"{doc} claims {claimed} tests, suite collects {actual}"
            )


def test_pinned_tag_ships_the_current_source():
    """The tag the README tells people to install must contain today's code.

    Matching version *strings* is not enough: v0.1.0 pointed at a commit two
    fixes behind main, so a visitor following the README got the pre-fix
    engine while reading the post-fix docs. This compares the pinned tag's
    `src/` and `pyproject.toml` against the working tree.
    """
    import subprocess

    version = _pyproject()["project"]["version"]
    tag = f"v{version}"
    exists = subprocess.run(
        ["git", "rev-parse", "--verify", f"{tag}^{{commit}}"],
        capture_output=True,
        cwd=str(ROOT),
    )
    if exists.returncode != 0:
        # Not yet tagged is fine mid-development; shipping a stale tag is not.
        return
    diff = subprocess.run(
        ["git", "diff", "--name-only", tag, "--", "src/", "pyproject.toml"],
        capture_output=True,
        cwd=str(ROOT),
    )
    changed = [p for p in diff.stdout.decode().split("\n") if p.strip()]
    assert not changed, (
        f"{tag} does not contain the current source — the README tells people "
        f"to install it, but these differ: {changed}. Cut a new release."
    )


def test_readme_install_refs_match_version():
    """Every version-pinned install line in the README points at this version.

    A README pinning a tag that doesn't exist is a broken install for the
    first person who tries it.
    """
    version = _pyproject()["project"]["version"]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    pinned = set(re.findall(r"@(v\d+\.\d+\.\d+)", readme)) | set(
        re.findall(r"rev:\s*(v\d+\.\d+\.\d+)", readme)
    )
    assert pinned, "README should pin at least one install ref"
    assert pinned == {f"v{version}"}, f"README pins {pinned}, package is v{version}"
