"""`greenwash doctor` must be right about which job is the gate.

Both of the first version's mistakes are pinned here, because both were made
against this repository on the first run and both are the kind that make a
diagnostic worse than nothing: it missed the real gate (a repo-local
`uses: ./action`) and it warned confidently about release-pipeline jobs that
merely install the package.
"""

import json
import pathlib

from greenwash.doctor import collect

CI = ".github/workflows"


def _repo(tmp_path: pathlib.Path, files: dict[str, str]) -> pathlib.Path:
    for name, body in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return tmp_path


def _levels(notes, title_contains):
    return [n.level for n in notes if title_contains in n.title]


def test_local_hook_without_ci_is_a_problem(tmp_path):
    notes = collect(_repo(tmp_path, {
        ".claude/settings.json": json.dumps({"hooks": {"Stop": "greenwash check"}}),
    }))
    assert _levels(notes, "runs locally but not in CI") == ["problem"]


def test_nothing_installed_is_a_problem(tmp_path):
    notes = collect(_repo(tmp_path, {"README.md": "hello"}))
    assert _levels(notes, "no greenwash installation found") == ["problem"]


def test_unconditional_gate_is_healthy(tmp_path):
    notes = collect(_repo(tmp_path, {
        f"{CI}/ci.yml": (
            "on:\n  pull_request:\n\njobs:\n  guard:\n    runs-on: ubuntu-latest\n"
            "    steps:\n      - uses: taipei49314/greenwash/action@v1\n"
        ),
    }))
    assert _levels(notes, "runs unconditionally") == ["ok"]
    assert not [n for n in notes if n.level in ("problem", "warn")]


def test_repo_local_action_counts_as_a_gate(tmp_path):
    """`uses: ./action` says nothing on its own — it is greenwash only if that
    action.yml is. The first version missed this repository's own dogfood job."""
    notes = collect(_repo(tmp_path, {
        "action/action.yml": "name: greenwash\nruns:\n  using: composite\n",
        f"{CI}/ci.yml": (
            "on:\n  push:\n\njobs:\n  dogfood:\n    runs-on: ubuntu-latest\n"
            "    steps:\n      - uses: ./action\n"
        ),
    }))
    assert _levels(notes, "runs unconditionally") == ["ok"]


def test_a_local_action_that_is_not_greenwash_is_not_a_gate(tmp_path):
    notes = collect(_repo(tmp_path, {
        "action/action.yml": "name: linter\nruns:\n  using: composite\n",
        f"{CI}/ci.yml": "on:\n  push:\n\njobs:\n  lint:\n    steps:\n      - uses: ./action\n",
    }))
    assert _levels(notes, "no greenwash installation found") == ["problem"]


def test_every_gate_conditional_is_a_warning(tmp_path):
    notes = collect(_repo(tmp_path, {
        f"{CI}/ci.yml": (
            "on:\n  pull_request:\n\njobs:\n  guard:\n    if: github.event_name == 'schedule'\n"
            "    steps:\n      - uses: taipei49314/greenwash/action@v1\n"
        ),
    }))
    assert _levels(notes, "every greenwash gate is conditional") == ["warn"]


def test_release_only_workflow_cannot_gate_a_merge(tmp_path):
    notes = collect(_repo(tmp_path, {
        f"{CI}/release.yml": (
            "on:\n  release:\n    types: [published]\n\njobs:\n  build:\n"
            "    steps:\n      - run: greenwash check HEAD~1..HEAD\n"
        ),
    }))
    assert _levels(notes, "never runs on a pull request or a push") == ["problem"]


def test_merely_installing_greenwash_is_not_a_gate(tmp_path):
    """Packaging greenwash is not gating with it.

    (The first version's actual mistake was one step further along: it counted
    the release job that genuinely runs `greenwash check` on the built wheel,
    then warned that this "gate" was conditional — true of the job, irrelevant
    to merges, since a release-triggered workflow cannot gate one. That case is
    `test_release_only_workflow_cannot_gate_a_merge`. This test pins the
    simpler boundary underneath it.)"""
    notes = collect(_repo(tmp_path, {
        f"{CI}/release.yml": (
            "on:\n  release:\n\njobs:\n  build:\n    steps:\n"
            "      - run: pip install greenwash && python -m build\n"
        ),
    }))
    assert _levels(notes, "no greenwash installation found") == ["problem"]


def test_the_limits_are_always_stated(tmp_path):
    """The command exists to say what it cannot know. Those notes are not
    optional garnish and must appear on every run, healthy or not."""
    notes = collect(_repo(tmp_path, {
        f"{CI}/ci.yml": (
            "on:\n  pull_request:\n\njobs:\n  guard:\n    steps:\n"
            "      - uses: taipei49314/greenwash/action@v1\n"
        ),
    }))
    titles = " | ".join(n.title for n in notes)
    assert "cannot tell whether the check is *required*" in titles
    assert "cannot block when it does not run" in titles
    assert "read from the BASE side" in titles
    assert "three-dot range" in titles
    assert "allowlist expiry is capped at 180 days" in titles


def test_doctor_reports_over_cap_allow_entries(tmp_path):
    notes = collect(_repo(tmp_path, {
        f"{CI}/ci.yml": (
            "on:\n  pull_request:\n\njobs:\n  guard:\n    steps:\n"
            "      - uses: taipei49314/greenwash/action@v1\n"
        ),
        ".greenwash/allow.toml": (
            "[[allow]]\n"
            'fingerprint = "ASSERT_WEAKENED/tests/x.py/t/deadbeefdead"\n'
            'rule = "ASSERT_WEAKENED"\n'
            'reason = "hand-edited decade"\n'
            'author = "audit"\n'
            'created = "2020-01-01"\n'
            'expires = "2030-01-01"\n'
        ),
    }))
    note = next(n for n in notes if "180 days" in n.title)
    assert "1 over the 180-day cap" in note.detail
    assert "0 active" in note.detail


def test_doctor_is_a_registered_subcommand():
    """An unlisted subcommand is silently reinterpreted as a `check` range, so
    `greenwash doctor` would report a verdict on a bogus revision instead of
    erroring."""
    from greenwash.cli import build_parser

    args = build_parser().parse_args(["doctor", "--repo", "."])
    assert args.command == "doctor"

    import greenwash.cli as cli_module
    source = pathlib.Path(cli_module.__file__).read_text(encoding="utf-8")
    fallback = source.split("elif argv[0] not in (", 1)[1].split("):", 1)[0]
    assert '"doctor"' in fallback, "doctor missing from main()'s bare-word passthrough list"
