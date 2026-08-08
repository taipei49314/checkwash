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


# Everything a user's install or integration actually executes. The engine
# alone is not enough: dogfood runs `./action` from the checkout, so a stale
# action.yml on the advertised tag would pass every gate while shipping users
# an old integration layer (owner review, 2026-08-04).
PUBLIC_SURFACES = ["src/", "pyproject.toml", "action/", ".pre-commit-hooks.yaml"]


def test_pinned_tag_ships_the_current_source():
    """The tag the README tells people to install must contain today's code.

    Matching version *strings* is not enough: v0.1.0 pointed at a commit two
    fixes behind main, so a visitor following the README got the pre-fix
    engine while reading the post-fix docs. This compares the pinned tag
    against the working tree across every public install surface — the
    engine, the packaging metadata, the GitHub Action wrapper, and the
    pre-commit hook definition.

    A pre-tag escape hatch was added here on 2026-08-08 and is removed again:
    it made the gate *return and pass* when the tag was missing, which is the
    exact sentence the assertion below carries as its own history. The
    circularity it was solving is a property of the release order, not of the
    gate — bump, commit, **tag**, verify, push, and the tag exists by the time
    anything checks. `docs/RELEASING.md` states that order; a candidate branch
    whose CI is red until the tag is cut is the gate working.
    """
    import subprocess

    version = _pyproject()["project"]["version"]
    tag = f"v{version}"
    exists = subprocess.run(
        ["git", "rev-parse", "--verify", f"{tag}^{{commit}}"],
        capture_output=True,
        cwd=str(ROOT),
    )
    assert exists.returncode == 0, (
        f"the README tells people to install {tag}, and that tag does not exist. "
        "Bumping the version used to make this gate return early and pass, which "
        "is the same 'green because it did not run' failure the gate exists to "
        "prevent. Cut the tag, or do not advertise it."
    )

    diff = subprocess.run(
        ["git", "diff", "--name-only", tag, "--", *PUBLIC_SURFACES],
        capture_output=True,
        cwd=str(ROOT),
    )
    changed = [p for p in diff.stdout.decode().split("\n") if p.strip()]
    assert not changed, (
        f"{tag} does not contain the current public surfaces — the README tells "
        f"people to install it, but these differ: {changed}. Cut a new release."
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


def test_dogfood_job_actually_runs():
    """The job that exercises action/action.yml must not be unreachable.

    It was `if: github.event_name == 'pull_request'` in a repository that has
    never had a pull request, so it reported "skipped" on every run in the
    project's history and the published GitHub Action had never executed once
    — while the README told people to use it. An earlier audit asked for the
    action to be dogfooded and the fix that shipped changed how the job
    invoked it without noticing the job never ran. "Green because it did not
    run" is the recurring failure here, so it gets a gate.
    """
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "dogfood:" in ci, "the dogfood job disappeared"
    # Only the dogfood job body — stop at the next top-level job key.
    body = ci.split("dogfood:", 1)[1]
    body = re.split(r"\n  [A-Za-z0-9_-]+:", body, maxsplit=1)[0]
    conditions = [
        line.strip()
        for line in body.split("\n")
        if line.strip().startswith("if:") and not line.strip().startswith("#")
    ]
    assert not conditions, (
        f"the dogfood job is gated behind {conditions}; a job that does not run "
        "proves nothing. Keep it unconditional so every push exercises "
        "action/action.yml."
    )
    assert "uses: ./action" in body, (
        "the dogfood job must invoke the composite action itself, not just the "
        "CLI, or action/action.yml ships untested."
    )
