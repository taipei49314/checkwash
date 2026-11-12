"""Graph contract for the hosted release verification (D-204).

`release-hosted.yml` runs only when dispatched from main, reads only,
rebuilds none of the published files, runs the whole suite at the release
merge M on macOS and Linux, runs the composite Action at the Action commit A
once, and qualifies the files the Release published (docs/RELEASING.md,
"Hosted release verification"). These tests read its shape, as
tests/test_ci_phases.py reads ci.yml and release.yml. They pin the exact
commands, conditions and refusals, so that a narrowed suite, a skipped
checkpoint or a check downgraded to a warning fails here. They run nothing on
a hosted runner: the dispatched runs are the evidence.
"""
from fnmatch import fnmatchcase
from pathlib import Path
import re

import yaml

ROOT = Path(__file__).resolve().parents[1]
FLOW = ROOT / ".github/workflows/release-hosted.yml"
PINNED = re.compile(r"^([\w.-]+/[\w.-]+)@([0-9a-f]{40})$")
LOCAL_ACTION = "./action-at-A/action"
SYSTEMS = ["macos-latest", "ubuntu-latest"]
PYTHONS = ["3.11", "3.12", "3.13"]
MATRIX = {"os": SYSTEMS, "python": PYTHONS}
# The repository's required contexts and the release bridge's stage checks.
RESERVED_NAMES = ("checkwash", "candidate assertion contract", "PJU release evidence")
SWALLOWS = ("|| true", "||true", "|| :", "|| exit 0", "|| echo", "||echo", "|| return",
            "set +e", "; true", ";true", "continue-on-error")
BUILDS = ("-m build", "-m zipapp", "pip wheel", "hatch build", "hatchling build", "uv build",
          "setup.py", "pip download", "--force-reinstall", "pip install .", "pip install --no-deps .")
SUITE = 'pytest -n 2 --dist worksteal -rs --junitxml="$RUNNER_TEMP/evidence/junit.xml"'
CHECKOUT_M = {"ref": "${{ inputs.merge_commit }}", "fetch-depth": 0, "persist-credentials": False}
AFTER_INSTALL = "${{ !cancelled() && steps.install.outcome == 'success' }}"
# Each job's `needs` and `if`: which checkpoint runs which job.
GRAPH = {
    "identity": (None, None),
    "release": ("identity", "inputs.checkpoint != 'source-at-M'"),
    "source": ("identity", "inputs.checkpoint != 'published-artifacts'"),
    "corpus": (["identity", "source"],
               "${{ !cancelled() && needs.identity.result == 'success' && inputs.checkpoint != 'published-artifacts' }}"),
    "action": ("identity", "inputs.checkpoint != 'published-artifacts'"),
    "artifacts": (["identity", "release"], "inputs.checkpoint != 'source-at-M'"),
}
RELEASE_STEP = "read the published Release, the publication record and PyPI"


def load():
    text = FLOW.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    return text, data, data.get("on", data.get(True))  # PyYAML reads the key `on` as True


def step(job, name):
    found = [entry for entry in job["steps"] if entry.get("name") == name]
    assert len(found) == 1, name
    return found[0]


def lines(entry):
    return [line.strip() for line in entry.get("run", "").splitlines()]


def has_lines(entry, *expected):
    present = lines(entry)
    missing = [line for line in expected if line not in present]
    assert not missing, missing


def test_dispatch_only_read_only_and_inputs_reach_shell_through_env():
    text, data, triggers = load()
    assert set(triggers) == {"workflow_dispatch"}
    inputs = triggers["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"version", "merge_commit", "checkpoint", "six_leg_sha256",
                           "release_id", "wheel_sha256", "sdist_sha256", "pyz_sha256"}
    assert inputs["checkpoint"]["options"] == ["source-at-M", "published-artifacts", "both"]
    assert data["permissions"] == {"contents": "read"}
    assert "secrets." not in text
    assert not any(token in text for token in SWALLOWS)
    for job in data["jobs"].values():
        assert "permissions" not in job and "container" not in job and "services" not in job
        for entry in job["steps"]:
            assert "${{" not in entry.get("run", "")
            assert "continue-on-error" not in entry


def test_the_token_reaches_one_shell_step_and_no_checkout_keeps_credentials():
    text, data, _ = load()
    assert text.count("github.token") == 1
    holders = []
    for name, job in data["jobs"].items():
        assert "GH_TOKEN" not in (job.get("env") or {}) and "GITHUB_TOKEN" not in (job.get("env") or {})
        for entry in job["steps"]:
            env = entry.get("env") or {}
            if "GH_TOKEN" in env or "GITHUB_TOKEN" in env:
                holders.append((name, entry.get("name")))
            if entry.get("uses", "").startswith("actions/checkout@"):
                assert entry["with"]["persist-credentials"] is False, name
                assert "token" not in entry["with"], name
    assert holders == [("release", RELEASE_STEP)]
    assert step(data["jobs"]["release"], RELEASE_STEP)["env"] == {"GH_TOKEN": "${{ github.token }}"}


def test_the_first_step_refuses_a_dispatch_from_another_branch():
    _, data, _ = load()
    first = data["jobs"]["identity"]["steps"][0]
    assert first["name"] == "refuse malformed inputs" and "if" not in first
    assert lines(first)[:2] == [
        "set -euo pipefail",
        '[[ "$GITHUB_REF" == refs/heads/main ]] || { echo "::error::dispatch this workflow from main, not $GITHUB_REF"; exit 1; }',
    ]


def test_each_checkpoint_runs_its_jobs_and_none_other():
    _, data, _ = load()
    assert set(data["jobs"]) == set(GRAPH)
    for name, (needs, condition) in GRAPH.items():
        job = data["jobs"][name]
        assert job.get("needs") == needs, name
        assert job.get("if") == condition, name


def test_actions_are_pinned_to_the_commits_ci_yml_uses_and_the_one_local_action_is_a():
    _, data, _ = load()
    ci = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    known = {}
    for job in ci["jobs"].values():
        for entry in job["steps"]:
            match = PINNED.match(entry.get("uses", ""))
            if match:
                known[match[1]] = match[2]
    local = []
    for name, job in data["jobs"].items():
        for entry in job["steps"]:
            if "uses" not in entry:
                continue
            if entry["uses"].startswith("./"):
                local.append((name, entry["uses"]))
                continue
            match = PINNED.match(entry["uses"])
            assert match and known.get(match[1]) == match[2], entry["uses"]
    assert local == [("action", LOCAL_ACTION)]


def test_every_job_runs_on_the_hosted_system_its_name_says():
    _, data, _ = load()
    for name, job in data["jobs"].items():
        assert "timeout-minutes" in job
        assert not job["name"].startswith(RESERVED_NAMES)
        if name in ("source", "artifacts"):
            assert job["runs-on"] == "${{ matrix.os }}"
            assert job["strategy"] == {"fail-fast": False, "matrix": MATRIX}
            # Each leg refuses a runner other than the system its label names.
            has_lines(step(job, "bind the checkout to M"),
                      'case "$MATRIX_OS/$RUNNER_OS/$(uname -m)" in',
                      "macos-latest/macOS/arm64|ubuntu-latest/Linux/x86_64) ;;",
                      '*) echo "::error::this runner is $RUNNER_OS $(uname -m), not $MATRIX_OS"; exit 1 ;;')
        else:
            assert job["runs-on"] == "ubuntu-latest" and "strategy" not in job


def test_identity_binds_m_r_a_the_tree_and_the_tag():
    _, data, _ = load()
    shape = step(data["jobs"]["identity"], "bind the checkout to the release merge M (scheme S, D-194; tag rule, D-200)")
    assert "if" not in shape
    has_lines(shape,
              'test "$(git rev-parse HEAD)" = "$MERGE_COMMIT"',
              'git merge-base --is-ancestor "$MERGE_COMMIT" refs/remotes/public/main',
              'test "$TREE" = "$(git rev-parse "$R^{tree}")"',
              'test "$(git diff --name-only "$A" "$MERGE_COMMIT")" = "src/checkwash/doctor.py"',
              'grep -qxF "version = \\"$VERSION\\"" pyproject.toml',
              'test "$(git cat-file -t "refs/tags/$TAG")" = tag',
              'test "$(sed -n \'1s/^object //p\' "$EV/tag-object.txt")" = "$A"',
              'grep -qxF "Release-Merge: $MERGE_COMMIT" "$EV/tag-object.txt"',
              'echo "::error::cannot read the public tags (git ls-remote exit $tag_rc)"; exit 1')
    present = lines(shape)
    assert any(line.startswith('test "${#m[@]}" -eq 3') for line in present)
    assert any(line.startswith('test "${#r[@]}" -eq 2') for line in present)


def test_release_record_requires_github_s_digests_the_record_rows_and_pypi():
    _, data, _ = load()
    record = step(data["jobs"]["release"], RELEASE_STEP)
    assert "if" not in record
    has_lines(record,
              'need(row.get("digest") == "sha256:" + expected[name],',
              'need(any(f"`{name}`" in line and f"`{value}`" in line for line in lines),',
              'need(row.get("digests", {}).get("sha256") == expected[name], name + ": PyPI\'s digest differs")',
              'need(row.get("yanked") is False, name + " is yanked on PyPI")',
              'test "$(sha256sum "$RUNNER_TEMP/pypi/checkwash-$VERSION-py3-none-any.whl" | cut -d\' \' -f1)" = "$WHEEL_SHA256"',
              'test "$(sha256sum "$RUNNER_TEMP/pypi/checkwash-$VERSION.tar.gz" | cut -d\' \' -f1)" = "$SDIST_SHA256"')


def test_source_checkpoint_runs_the_whole_suite_at_m_on_six_legs():
    _, data, _ = load()
    job = data["jobs"]["source"]
    assert "env" not in job
    checkout = next(entry for entry in job["steps"] if entry.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"] == CHECKOUT_M
    suite = step(job, "the whole suite at M")
    assert suite == {"name": "the whole suite at M", "run": SUITE}
    assert [entry for entry in job["steps"] if entry.get("run", "").lstrip().startswith("pytest")] == [suite]
    qualification = step(job, "the source assertion-contract qualification and its inventory at M")
    assert qualification["if"] == AFTER_INSTALL
    has_lines(qualification,
              'python tools/qualify_assertions.py --distribution source --output "$RUNNER_TEMP/evidence/assertion-source.json"',
              'python tools/release_inventory.py --distribution source --qualification "$RUNNER_TEMP/evidence/assertion-source.json" --output "$RUNNER_TEMP/evidence/inventory-source.json"')
    emit = step(job, "emit the fixed corpus at M")
    assert emit["if"] == AFTER_INSTALL and '--os "$MATRIX_OS" --python "$MATRIX_PYTHON"' in emit["run"]
    summary = step(job, "summarise the suite, naming every skip, and check D-170's two budget checks")
    assert summary["if"] == AFTER_INSTALL
    has_lines(summary,
              'if summary["runner_os"] == "Linux":',
              'wrong = {name: state for name, state in budgets.items() if state != "ran and passed"}',
              'sys.exit(1)')
    assert '"test_cases": len(cases)' in summary["run"]


def test_upload_names_match_what_the_corpus_job_downloads():
    _, data, _ = load()
    upload = next(entry for entry in data["jobs"]["source"]["steps"]
                  if entry.get("uses", "").startswith("actions/upload-artifact@"))
    download = next(entry for entry in data["jobs"]["corpus"]["steps"]
                    if entry.get("uses", "").startswith("actions/download-artifact@"))
    attempt = "${{ github.run_attempt }}"
    assert download["with"]["pattern"] == f"release-hosted-source-*-attempt-{attempt}"
    for system in SYSTEMS:
        for python in PYTHONS:
            name = (upload["with"]["name"].replace("${{ matrix.os }}", system)
                    .replace("${{ matrix.python }}", python))
            assert fnmatchcase(name, download["with"]["pattern"]), name


def test_corpus_comparison_fails_on_a_missing_or_differing_leg():
    _, data, _ = load()
    job = data["jobs"]["corpus"]
    compare = step(job, "the six hosted corpus outputs are byte-identical, and equal the PJU six-leg batch's when given")
    assert "if" not in compare
    has_lines(compare,
              "for os in macos-latest ubuntu-latest; do",
              "for py in 3.11 3.12 3.13; do",
              'echo "::error::no validated corpus output from $os Python $py in this attempt"; exit 1',
              'elif ! cmp -s "$first" "$file"; then',
              'echo "::error::hosted corpus bytes differ between legs"; exit 1',
              'echo "::error::hosted corpus bytes differ from the PJU six-leg batch"; exit 1')
    assert 'wanted = {"checkout_sha": os.environ["MERGE_COMMIT"], "payload_sha256": sys.argv[2],' in compare["run"]


def test_action_job_runs_the_composite_at_a_once_with_the_readme_setup():
    _, data, _ = load()
    job = data["jobs"]["action"]
    checkouts = [entry for entry in job["steps"] if entry.get("uses", "").startswith("actions/checkout@")]
    assert [entry["with"] for entry in checkouts] == [
        CHECKOUT_M,
        {"ref": "${{ needs.identity.outputs.action_commit }}", "path": "action-at-A", "persist-credentials": False}]
    python = next(entry for entry in job["steps"] if entry.get("uses", "").startswith("actions/setup-python@"))
    assert python["with"] == {"python-version": "3.12"}
    has_lines(step(job, "bind the subject to M and the composite to A"),
              'test "$(git -C action-at-A rev-parse HEAD)" = "$ACTION_COMMIT"', 'test -z "$clean"')
    action = next(entry for entry in job["steps"] if entry.get("uses") == LOCAL_ACTION)
    # Only the base, which a dispatch has no pull request to supply, and M's
    # date; the other inputs keep the Action's defaults, so comment-pr stays false.
    assert action == {"name": "the composite Action at A on M's release range", "id": "recipe",
                      "uses": LOCAL_ACTION, "env": {"CHECKWASH_TODAY": "${{ needs.identity.outputs.merge_date }}"},
                      "with": {"base": "${{ needs.identity.outputs.base_commit }}"}}
    receipt = step(job, "read the Action's own receipt")
    assert job["steps"].index(receipt) == job["steps"].index(action) + 1
    assert receipt["if"] == "${{ !cancelled() && steps.bind.outcome == 'success' }}"
    has_lines(receipt,
              'need(os.environ["STEP_EXIT"] == "0", "the Action step did not report exit 0")',
              'need(receipt.get("base") == os.environ["BASE_COMMIT"] and receipt.get("head") == os.environ["MERGE_COMMIT"],',
              'need(identity.get("version") == os.environ["VERSION"], "the Action installed another version")',
              'need(receipt.get("fail_on") == "high", "the Action did not judge at its default fail-on, high")',
              'need(identity.get("source_digest") == digest, "the Action\'s engine differs from A\'s src/checkwash")')


def test_artifact_checkpoint_checks_the_published_files_and_rebuilds_none():
    text, data, _ = load()
    job = data["jobs"]["artifacts"]
    checkout = next(entry for entry in job["steps"] if entry.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"] == CHECKOUT_M
    download = step(job, "download the published files and check them against the release record")
    assert "if" not in download
    has_lines(download,
              'curl -fsSL --retry 3 -o "$D/$name" "https://github.com/taipei49314/checkwash/releases/download/v$VERSION/$name"',
              'if [[ "$actual" != "$2" ]]; then',
              'echo "::error::$1 differs from the release record"; exit 1',
              'same "$WHEEL" "$WHEEL_SHA256"', 'same "$SDIST" "$SDIST_SHA256"', 'same checkwash.pyz "$PYZ_SHA256"')
    wheel = step(job, "install the published wheel into a fresh venv and run it")
    assert wheel["if"] == "${{ !cancelled() && steps.download.outcome == 'success' }}"
    has_lines(wheel, '"$VENV/bin/python" -I -m pip install --no-deps --no-index "$D/checkwash-$VERSION-py3-none-any.whl"')
    qualify = step(job, "the wheel's assertion-contract qualification and the wheel and sdist inventory against M")
    assert qualify["if"] == "${{ !cancelled() && steps.wheel.outcome == 'success' }}"
    pyz = step(job, "run the published pyz, its zipapp and assertion-contract qualification and its inventory against M")
    assert pyz["if"] == "${{ !cancelled() && steps.download.outcome == 'success' }}"
    for distribution, entry in (("wheel", qualify), ("pyz", pyz)):
        assert f"tools/qualify_assertions.py --distribution {distribution}" in entry["run"]
        assert f"tools/release_inventory.py --distribution {distribution}" in entry["run"]
    assert "python tools/qualify_zipapp.py \"$PYZ\"" in pyz["run"]
    span = step(job, "check M's release range with the installed wheel and the pyz, as the release visitor does")
    assert span["if"] == "${{ !cancelled() && steps.wheel.outcome == 'success' && steps.pyz.outcome == 'success' }}"
    assert 'export CHECKWASH_TODAY="$MERGE_DATE"' in lines(span)
    for build in BUILDS:
        assert build not in text, build
    # The one install from source is the source legs' editable install of M.
    assert text.count("pip install --no-deps --no-build-isolation -e .") == 1
