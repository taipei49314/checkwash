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

    # A count that is *absent* has to fail too. This loop used to check only
    # the numbers it found, so deleting one silenced the gate instead of
    # tripping it: a bad `sed` blanked both README status lines to "17
    # detectors,  tests" and this test passed on the result (2026-08-08).
    # Checking a value when present and saying nothing when it is gone is the
    # same absence-blindness as a gate that skips when its subject is missing.
    from greenwash.detectors import REGISTRY

    # Only greenwash's own status lines: docs/launch.md also describes other
    # tools ("a PR audit suite (11 detectors, ...)") and those are their
    # numbers, not ours.
    status_lines = []
    for doc, marker in (("README.md", "pre-release"), ("docs/launch.md", "Apache-2.0")):
        for ln in (ROOT / doc).read_text(encoding="utf-8").splitlines():
            if "detectors," in ln and marker in ln:
                status_lines.append((doc, ln))
    assert status_lines, "no status line found in README.md or docs/launch.md"
    for doc, ln in status_lines:
        m = re.search(r"(\d+) detectors, (\d+) tests", ln)
        assert m, (
            f"{doc} status line has lost a number: {ln.strip()!r}. "
            "An empty count reads as prose and slips past a value check."
        )
        assert int(m.group(1)) == len(REGISTRY), (
            f"{doc} claims {m.group(1)} detectors, the registry has {len(REGISTRY)}"
        )
        assert int(m.group(2)) == actual, (
            f"{doc} claims {m.group(2)} tests, suite collects {actual}"
        )

    # docs/launch.md joined the list after drifting three versions behind
    # unnoticed ("v0.1.12, 17 detectors, 275 tests") — it is copy meant for
    # posting, so a stale number there is a claim made in public.
    # The README also states how many tampering cases `demo` replays, in two
    # places and in two spellings. Both are hand-typed claims about packaged
    # data, which is the definition of something that drifts.
    from greenwash.cases import parse_case
    from greenwash.demo import _load_cases

    n_demo = len([1 for _n, text in _load_cases() if parse_case(text).expect])
    words = {
        7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve",
    }
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"# {n_demo} real tampering cases" in readme, (
        f"README's demo comment does not say {n_demo} tampering cases"
    )
    assert f"replays {words.get(n_demo, n_demo)} real tampering cases" in readme, (
        f"README's demo prose does not say {words.get(n_demo, n_demo)} tampering cases"
    )

    for doc in ("README.md", "CONTRIBUTING.md", "docs/launch.md"):
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


def test_required_ruleset_payload_matches_documented_job_name():
    """T0.4: the gh ruleset payload must require the documented job name.

    A JSON file that names a different context than the README workflow
    would let someone run the documented command and still merge around
    greenwash. The check name is the job key, `greenwash`.
    """
    import json

    payload = json.loads((ROOT / "action" / "required-ruleset.json").read_text(encoding="utf-8"))
    assert payload["target"] == "branch"
    assert payload["enforcement"] == "active"
    assert "~DEFAULT_BRANCH" in payload["conditions"]["ref_name"]["include"]
    rules = payload["rules"]
    assert len(rules) == 1
    assert rules[0]["type"] == "required_status_checks"
    contexts = [c["context"] for c in rules[0]["parameters"]["required_status_checks"]]
    assert contexts == ["greenwash"]

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "gh api repos/OWNER/REPO/rulesets --method POST --input action/required-ruleset.json" in readme
    assert "action/required-ruleset.json" in (ROOT / "action" / "README.md").read_text(encoding="utf-8")


def test_readme_action_snippet_is_zizmor_blanket():
    """The documented workflow must be mergeable under zizmor 1.29 blanket.

    The 2026-08-07 pydantic integration scored two highs on the then-README
    snippet (no permissions, no persist-credentials). Those two are gone.
    Re-check 2026-08-15: zizmor 1.29.0 still reports unpinned-uses as high
    for @v4 / @v0.1.34, so every uses: in the snippet must be a commit SHA.
    """
    import subprocess

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    match = re.search(
        r"```yaml\n(# \.github/workflows/greenwash\.yml\n.*?)```",
        readme,
        flags=re.S,
    )
    assert match, "README lost the required-check workflow fence"
    snippet = match.group(1)
    assert re.search(r"^permissions:\n  contents: read$", snippet, flags=re.M)
    assert "persist-credentials: false" in snippet
    uses = re.findall(r"^\s+- uses: (\S+)", snippet, flags=re.M)
    assert uses, "README workflow has no uses: entries"
    for ref in uses:
        assert re.search(r"@[0-9a-f]{40}$", ref), (
            f"{ref} is not hash-pinned; zizmor unpinned-uses is high"
        )

    # The required-check snippet is what a visitor pastes. Pinning an old
    # tag's SHA (v0.1.34 while the README advertised v0.1.40) ships them
    # an Action six releases behind. The hash must be the advertised tag.
    version = _pyproject()["project"]["version"]
    tag = f"v{version}"
    sha = subprocess.check_output(
        ["git", "rev-parse", tag], cwd=str(ROOT), text=True
    ).strip()
    assert f"taipei49314/greenwash/action@{sha}" in snippet, (
        f"README Action pin is not {tag} ({sha}). After cutting the tag, "
        "set the snippet SHA to `git rev-parse` of that tag."
    )


def test_perf_gate_is_in_default_collection():
    """T2.5: the SLO file cannot vanish from default pytest or be skipped.

    CI runs `pytest` with no -k / --ignore. The budgets live in
    tests/gates/test_perf.py (agent-read-only). This test only checks that
    the file is still part of the default collection.
    """
    perf = ROOT / "tests" / "gates" / "test_perf.py"
    text = perf.read_text(encoding="utf-8")
    assert "def test_large_single_diff_within_budget" in text
    assert "BUDGET_LARGE_DIFF_S" in text
    addopts = (
        _pyproject()
        .get("tool", {})
        .get("pytest", {})
        .get("ini_options", {})
        .get("addopts", "")
    )
    blob = addopts if isinstance(addopts, str) else " ".join(addopts)
    assert "--ignore" not in blob
    assert " -k " not in f" {blob} "


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


def test_pypi_job_is_gated_on_something_that_is_not_auto_created():
    """The publish job must be closed by default, and `environment:` is not.

    The first version of this job was gated only by `environment: pypi`, with a
    comment stating it would be skipped until a human created that environment.
    GitHub creates an environment automatically the first time a job references
    one, so the gate was open from the start: on the v0.1.13 release the job
    ran, found no trusted publisher registered on PyPI, and turned an otherwise
    clean release red (D-032). The release workflow had never executed before,
    which is how a false claim about it survived being written down twice.

    A repository variable is not auto-created by anything, so it is a gate that
    is actually closed. This pins that the condition consults one.
    """
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "pypi:" in release, "the pypi job disappeared"
    body = release.split("\n  pypi:", 1)[1]
    body = re.split(r"\n  [A-Za-z0-9_-]+:", body, maxsplit=1)[0]
    conditions = [
        line.strip()[len("if:"):].strip()
        for line in body.split("\n")
        if line.strip().startswith("if:")
    ]
    assert conditions, (
        "the pypi job has no `if:` at all — it publishes on every release. "
        "Publishing is opt-in; gate it on a repository variable."
    )
    assert any("vars." in c for c in conditions), (
        f"the pypi job is gated only by {conditions}. `environment:` does not "
        "gate anything — GitHub auto-creates a referenced environment, which is "
        "exactly how this failed on v0.1.13. Gate on `vars.<NAME>`, which "
        "nothing creates for you."
    )
