"""Graph contract for the hosted release verification (D-204).

`release-hosted.yml` runs only when dispatched, reads only, rebuilds none of
the published files, runs the whole suite at the release merge M on macOS and
Linux, runs the composite Action at the Action commit A once, and qualifies
the files the Release published (docs/RELEASING.md, "Hosted release
verification"). These tests read its shape, as tests/test_ci_phases.py reads
ci.yml and release.yml. They run nothing on a hosted runner: the dispatched
runs are the evidence.
"""
from pathlib import Path
import re

import yaml

ROOT = Path(__file__).resolve().parents[1]
FLOW = ROOT / ".github/workflows/release-hosted.yml"
PINNED = re.compile(r"^([\w.-]+/[\w.-]+)@([0-9a-f]{40})$")
LOCAL_ACTION = "./action-at-A/action"
SYSTEMS = ["macos-latest", "ubuntu-latest"]
PYTHONS = ["3.11", "3.12", "3.13"]
# The repository's required contexts and the release bridge's stage checks.
RESERVED_NAMES = ("checkwash", "candidate assertion contract", "PJU release evidence")
SWALLOWS = ("|| true", "|| :", "|| exit 0", "set +e", "; true", ";true")


def load():
    text = FLOW.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    return text, data, data.get("on", data.get(True))  # PyYAML reads the key `on` as True


def scripts(job):
    return "\n".join(step.get("run", "") for step in job["steps"])


def test_dispatch_only_read_only_and_inputs_reach_shell_through_env():
    text, data, triggers = load()
    assert set(triggers) == {"workflow_dispatch"}
    inputs = triggers["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"version", "merge_commit", "checkpoint", "six_leg_sha256",
                           "release_id", "wheel_sha256", "sdist_sha256", "pyz_sha256"}
    assert inputs["checkpoint"]["options"] == ["source-at-M", "published-artifacts", "both"]
    assert data["permissions"] == {"contents": "read"}
    assert "secrets." not in text and "continue-on-error" not in text
    assert not any(token in text for token in SWALLOWS)
    # The job's own read-only token, in the one step that reads the Release.
    assert text.count("github.token") == 1
    for job in data["jobs"].values():
        assert "permissions" not in job
        for step in job["steps"]:
            assert "${{" not in step.get("run", "")


def test_the_first_step_refuses_a_dispatch_from_another_branch():
    _, data, _ = load()
    first = data["jobs"]["identity"]["steps"][0]["run"]
    assert '[[ "$GITHUB_REF" == refs/heads/main ]]' in first


def test_actions_are_pinned_to_the_commits_ci_yml_uses_and_the_one_local_action_is_a():
    _, data, _ = load()
    ci = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    known = {}
    for job in ci["jobs"].values():
        for step in job["steps"]:
            match = PINNED.match(step.get("uses", ""))
            if match:
                known[match[1]] = match[2]
    local = []
    for name, job in data["jobs"].items():
        for step in job["steps"]:
            if "uses" not in step:
                continue
            if step["uses"].startswith("./"):
                local.append((name, step["uses"]))
                continue
            match = PINNED.match(step["uses"])
            assert match and known.get(match[1]) == match[2], step["uses"]
    assert local == [("action", LOCAL_ACTION)]


def test_every_job_runs_on_hosted_macos_or_ubuntu_under_its_own_name():
    _, data, _ = load()
    for job in data["jobs"].values():
        assert job["runs-on"] in ("ubuntu-latest", "macos-latest", "${{ matrix.os }}")
        assert "timeout-minutes" in job
        assert not job["name"].startswith(RESERVED_NAMES)
        if job["runs-on"] == "${{ matrix.os }}":
            assert job["strategy"]["matrix"] == {"os": SYSTEMS, "python": PYTHONS}
            assert job["strategy"]["fail-fast"] is False


def test_source_checkpoint_runs_the_whole_suite_at_m_on_six_legs():
    _, data, _ = load()
    job = data["jobs"]["source"]
    assert job["strategy"]["matrix"] == {"os": SYSTEMS, "python": PYTHONS}
    checkout = next(step for step in job["steps"] if step.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"] == {"ref": "${{ inputs.merge_commit }}", "fetch-depth": 0,
                                "persist-credentials": False}
    suite = [step for step in job["steps"] if step.get("run", "").lstrip().startswith("pytest")]
    assert len(suite) == 1 and "if" not in suite[0]
    command = suite[0]["run"].strip()
    assert re.match(r"pytest -n 2 --dist worksteal(\s|$)", command)
    assert not any(token in command for token in
                   ("--ignore", " -k ", " -m ", "--deselect", "-p no:", "--lf", "--maxfail", " -x"))
    text = scripts(job)
    assert "tools/qualify_assertions.py --distribution source" in text
    assert "tools/corpus_artifacts.py emit" in text and '--os "$MATRIX_OS"' in text


def test_corpus_comparison_reads_the_six_legs_of_one_attempt_and_their_receipts():
    _, data, _ = load()
    job = data["jobs"]["corpus"]
    download = next(step for step in job["steps"]
                    if step.get("uses", "").startswith("actions/download-artifact@"))
    assert download["with"]["pattern"] == "release-hosted-source-*-attempt-${{ github.run_attempt }}"
    text = scripts(job)
    assert "for os in macos-latest ubuntu-latest" in text and "for py in 3.11 3.12 3.13" in text
    assert "SIX_LEG_SHA256" in text and "cmp -s" in text and "receipt.json" in text


def test_action_job_runs_the_composite_at_a_once_with_the_readme_setup():
    _, data, _ = load()
    job = data["jobs"]["action"]
    assert job["runs-on"] == "ubuntu-latest" and "strategy" not in job
    checkouts = [step for step in job["steps"] if step.get("uses", "").startswith("actions/checkout@")]
    assert [step["with"].get("ref") for step in checkouts] == [
        "${{ inputs.merge_commit }}", "${{ needs.identity.outputs.action_commit }}"]
    assert checkouts[1]["with"]["path"] == "action-at-A"
    assert all(step["with"]["persist-credentials"] is False for step in checkouts)
    python = next(step for step in job["steps"] if step.get("uses", "").startswith("actions/setup-python@"))
    assert python["with"] == {"python-version": "3.12"}
    action = next(step for step in job["steps"] if step.get("uses") == LOCAL_ACTION)
    # Only the base, which a dispatch has no pull request to supply; the other
    # inputs keep the Action's defaults, so comment-pr stays false.
    assert action["with"] == {"base": "${{ needs.identity.outputs.base_commit }}"}
    after = job["steps"][job["steps"].index(action) + 1]
    assert "action-check-receipt.json" in after["run"] and after["if"].startswith("${{ !cancelled()")


def test_artifact_checkpoint_checks_the_published_files_and_rebuilds_none():
    text, data, _ = load()
    job = data["jobs"]["artifacts"]
    assert job["strategy"]["matrix"] == {"os": SYSTEMS, "python": PYTHONS}
    steps = scripts(job)
    assert "releases/download/v$VERSION/" in steps and "--no-deps --no-index" in steps
    for distribution in ("wheel", "pyz"):
        assert f"tools/qualify_assertions.py --distribution {distribution}" in steps
        assert f"tools/release_inventory.py --distribution {distribution}" in steps
    assert "tools/qualify_zipapp.py" in steps
    for build in ("-m build", "-m zipapp", "pip wheel", "hatch build", "setup.py", "pip download"):
        assert build not in text
