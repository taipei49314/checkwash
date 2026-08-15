"""`doctor` proves only the documented, tightly bounded workflow shape."""

import io
import json
import pathlib
import re

import pytest

from greenwash.doctor import collect, run


CI = ".github/workflows"
ROOT = pathlib.Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
CANONICAL = re.search(
    r"```yaml\n(# \.github/workflows/greenwash\.yml\n.*?)```", README, re.S
).group(1)


def _repo(tmp_path: pathlib.Path, files: dict[str, str]) -> pathlib.Path:
    for name, body in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return tmp_path


def _levels(notes, title_contains):
    return [n.level for n in notes if title_contains in n.title]


def _healthy(root: pathlib.Path) -> None:
    notes = collect(root)
    assert _levels(notes, "runs unconditionally") == ["ok"]
    assert not [note for note in notes if note.level in {"warn", "problem"}]


def _incomplete(root: pathlib.Path, label: str) -> None:
    notes = collect(root)
    assert _levels(notes, "workflow analysis incomplete") == ["warn"], label
    assert not _levels(notes, "runs unconditionally"), label


def _not_healthy(root: pathlib.Path, label: str) -> None:
    notes = collect(root)
    assert not _levels(notes, "runs unconditionally"), label
    assert [note for note in notes if note.level in {"warn", "problem"}], label


def _canonical_repo(tmp_path: pathlib.Path, body: str = CANONICAL, suffix: str = ".yml"):
    return _repo(tmp_path, {f"{CI}/greenwash{suffix}": body})


def test_readme_canonical_gate_is_the_positive_fixture(tmp_path):
    _healthy(_canonical_repo(tmp_path / "lf"))
    _healthy(_canonical_repo(tmp_path / "unicode-comment", CANONICAL.replace(
        "# .github/workflows/greenwash.yml", "# 稽核 workflow"
    )))

    for action in ("actions/checkout", "actions/setup-python", "taipei49314/greenwash/action"):
        sha64 = re.sub(
            rf"(?<={re.escape(action)}@)([0-9a-f]{{40}})(?=\s|$)",
            r"\1" + "a" * 24,
            CANONICAL,
        )
        _incomplete(_canonical_repo(tmp_path / action.replace("/", "-"), sha64), action)

    path = tmp_path / "crlf" / CI / "greenwash.yaml"
    path.parent.mkdir(parents=True)
    path.write_bytes(("\ufeff" + CANONICAL.replace("\n", "\r\n")).encode("utf-8"))
    _healthy(tmp_path / "crlf")


def test_only_an_unfiltered_pull_request_event_is_healthy(tmp_path):
    block_pull_request = CANONICAL.replace("on: [pull_request]", "on:\n  pull_request:")
    _healthy(_canonical_repo(tmp_path / "pull-request", block_pull_request))
    for event in ("push", "merge_group"):
        workflow = CANONICAL.replace("on: [pull_request]", f"on:\n  {event}:")
        _incomplete(_canonical_repo(tmp_path / event, workflow), event)

def test_local_actions_are_never_proven_gates(tmp_path):
    current = {
        f"{CI}/ci.yml": (ROOT / CI / "ci.yml").read_text(encoding="utf-8"),
        "action/action.yml": (ROOT / "action/action.yml").read_text(encoding="utf-8"),
        "action/post_review.py": (ROOT / "action/post_review.py").read_text(encoding="utf-8"),
    }
    _incomplete(_repo(tmp_path / "current-dogfood", current), "current local dogfood")

    remote = re.search(
        r"^      - uses: taipei49314/greenwash/action@[^\n]+", CANONICAL, re.M
    ).group(0)
    local_workflow = CANONICAL.replace(
        remote,
        "      - uses: ./action\n"
        "        with:\n"
        "          base: ${{ github.event.pull_request.base.sha || 'HEAD~1' }}",
    )
    fake_project = {
        f"{CI}/greenwash.yml": local_workflow,
        "action/action.yml": current["action/action.yml"],
        "action/post_review.py": current["action/post_review.py"],
        "pyproject.toml": (
            "[project]\nname = 'fake-greenwash'\nversion = '0'\n"
            "[project.scripts]\ngreenwash = 'fake_greenwash:main'\n"
        ),
        "fake_greenwash.py": "def main():\n    return 0\n",
    }
    _incomplete(_repo(tmp_path / "fake-project", fake_project), "fake local project")


def test_direct_runs_and_text_spoofs_are_never_healthy(tmp_path):
    replacements = {
        "echo": "      # uses: taipei49314/greenwash/action@" + "a" * 40 + "\n"
        "      - run: echo 'greenwash check HEAD~1..HEAD'",
        "shell-swallow": "      - run: greenwash check HEAD~1..HEAD || true",
        "hook-json": "      - run: greenwash check HEAD~1..HEAD --format hook-json",
        "emit-ir": "      - run: greenwash check HEAD~1..HEAD --emit-ir",
    }
    gate = re.search(r"^      - uses: taipei49314/greenwash/action@[^\n]+", CANONICAL, re.M).group(0)
    for label, replacement in replacements.items():
        _incomplete(_canonical_repo(tmp_path / label, CANONICAL.replace(gate, replacement)), label)

    env_spoof = CANONICAL.replace(
        "permissions:\n", "env:\n  GREENWASH_COMMAND: greenwash check HEAD~1..HEAD\n\npermissions:\n"
    )
    _incomplete(_canonical_repo(tmp_path / "env-spoof", env_spoof), "env spoof")


def test_checkout_setup_and_gate_must_be_exact_and_in_order(tmp_path):
    checkout = re.search(r"^      - uses: actions/checkout@[^\n]+(?:\n        with:\n(?:          [^\n]+\n?)+)", CANONICAL, re.M).group(0).rstrip()
    setup = re.search(r"^      - uses: actions/setup-python@[^\n]+(?:\n        with:\n(?:          [^\n]+\n?)+)", CANONICAL, re.M).group(0).rstrip()
    gate = re.search(r"^      - uses: taipei49314/greenwash/action@[^\n]+", CANONICAL, re.M).group(0)
    cases = {
        "checkout-ref": CANONICAL.replace("          fetch-depth: 0", "          fetch-depth: 0\n          ref: main"),
        "wrong-repo": CANONICAL.replace("          fetch-depth: 0", "          fetch-depth: 0\n          repository: attacker/repo"),
        "missing-checkout": CANONICAL.replace(checkout + "\n", ""),
        "late-checkout": CANONICAL.replace(checkout, "__SETUP__").replace(setup, checkout).replace("__SETUP__", setup),
        "pre-mutation": CANONICAL.replace(checkout, "      - run: git checkout -- action/action.yml\n" + checkout),
        "post-mutation": CANONICAL.replace(gate, gate + "\n      - run: git reset --hard HEAD~1"),
        "wrong-python": CANONICAL.replace('python-version: "3.12"', 'python-version: "3.11"'),
        "tagged-checkout": re.sub(r"actions/checkout@[0-9a-f]{40}", "actions/checkout@v4", CANONICAL),
        "uppercase-gate": re.sub(
            r"taipei49314/greenwash/action@[0-9a-f]{40}",
            "taipei49314/greenwash/action@" + "A" * 40,
            CANONICAL,
        ),
        "wrong-action-owner": CANONICAL.replace(
            "taipei49314/greenwash/action@", "attacker/greenwash/action@"
        ),
        "tagged-action": re.sub(
            r"taipei49314/greenwash/action@[0-9a-f]{40}",
            "taipei49314/greenwash/action@v0.1.41",
            CANONICAL,
        ),
        "missing-action-ref": re.sub(
            r"taipei49314/greenwash/action@[0-9a-f]{40}",
            "taipei49314/greenwash/action",
            CANONICAL,
        ),
    }
    for label, workflow in cases.items():
        _incomplete(_canonical_repo(tmp_path / label, workflow), label)


def test_conditions_unsafe_context_and_event_shorthand_are_incomplete(tmp_path):
    cases = {
        "event-shorthand": CANONICAL.replace("on: [pull_request]", "on: pull_request"),
        "pr-target": CANONICAL.replace("pull_request", "pull_request_target", 1),
        "filtered-event": CANONICAL.replace(
            "on: [pull_request]", "on:\n  pull_request:\n    types: [closed]"
        ),
        "mixed-event-shape": CANONICAL.replace(
            "on: [pull_request]", "on:\n  push:\n    branches: [main]\n  pull_request:"
        ),
        "runs-on-list": CANONICAL.replace("runs-on: ubuntu-latest", "runs-on: [ubuntu-latest]"),
        "job-if": CANONICAL.replace(
            "    runs-on: ubuntu-latest", "    if: always()\n    runs-on: ubuntu-latest"
        ),
        "job-continue": CANONICAL.replace(
            "    runs-on: ubuntu-latest", "    continue-on-error: true\n    runs-on: ubuntu-latest"
        ),
        "step-if": CANONICAL.replace(
            "      - uses: taipei49314/greenwash/action@",
            "      - if: always()\n        uses: taipei49314/greenwash/action@",
        ),
        "step-env": CANONICAL.replace(
            "      - uses: taipei49314/greenwash/action@",
            "      - env:\n          PATH: fake\n        uses: taipei49314/greenwash/action@",
        ),
        "step-continue": CANONICAL.replace(
            "      - uses: taipei49314/greenwash/action@",
            "      - continue-on-error: true\n        uses: taipei49314/greenwash/action@",
        ),
        "step-shell": CANONICAL.replace(
            "      - uses: taipei49314/greenwash/action@",
            "      - shell: bash\n        uses: taipei49314/greenwash/action@",
        ),
        "step-working-directory": CANONICAL.replace(
            "      - uses: taipei49314/greenwash/action@",
            "      - working-directory: elsewhere\n        uses: taipei49314/greenwash/action@",
        ),
        "remote-with": CANONICAL + "        with:\n          base: HEAD\n",
    }
    for key in ("if", "continue-on-error", "env", "defaults", "strategy", "container"):
        cases[f"workflow-{key}"] = CANONICAL.replace(
            "permissions:\n", f"{key}: unsafe\n\npermissions:\n"
        )
        cases[f"job-{key}"] = CANONICAL.replace(
            "    runs-on: ubuntu-latest", f"    {key}: unsafe\n    runs-on: ubuntu-latest"
        )
    for label, workflow in cases.items():
        _incomplete(_canonical_repo(tmp_path / label, workflow), label)


def test_ambiguous_duplicate_and_unknown_yaml_is_incomplete(tmp_path):
    cases = {
        "unseparated-on": CANONICAL.replace("on: [pull_request]", "on:[pull_request]"),
        "unseparated-runs-on": CANONICAL.replace(
            "runs-on: ubuntu-latest", "runs-on:ubuntu-latest"
        ),
        "unseparated-uses": CANONICAL.replace(
            "- uses: actions/checkout@", "- uses:actions/checkout@", 1
        ),
        "unseparated-with-value": CANONICAL.replace("fetch-depth: 0", "fetch-depth:0"),
        "duplicate-on": "on: push\n" + CANONICAL,
        "duplicate-jobs": CANONICAL + "\njobs:\n  other:\n    runs-on: ubuntu-latest\n",
        "duplicate-job-id": CANONICAL + "  greenwash:\n    runs-on: ubuntu-latest\n",
        "duplicate-runs-on": CANONICAL.replace(
            "    runs-on: ubuntu-latest", "    runs-on: ubuntu-latest\n    runs-on: ubuntu-latest"
        ),
        "duplicate-uses": CANONICAL.replace(
            "        with:\n          fetch-depth", "        uses: actions/checkout@" + "a" * 40 + "\n        with:\n          fetch-depth", 1
        ),
        "duplicate-run": CANONICAL.replace(
            re.search(
                r"^      - uses: taipei49314/greenwash/action@[^\n]+", CANONICAL, re.M
            ).group(0),
            "      - run: greenwash check HEAD~1..HEAD\n        run: echo swallowed",
        ),
        "duplicate-with-key": CANONICAL.replace(
            "          fetch-depth: 0", "          fetch-depth: 0\n          fetch-depth: 0"
        ),
        "alias": CANONICAL.replace("on: [pull_request]", "events: &events [pull_request]\non: *events"),
        "merge": CANONICAL.replace("    runs-on: ubuntu-latest", "    <<: *defaults\n    runs-on: ubuntu-latest"),
        "flow-jobs": CANONICAL.split("jobs:\n", 1)[0] + "jobs: {greenwash: {runs-on: ubuntu-latest}}\n",
        "tab": CANONICAL.replace("    runs-on", "\truns-on"),
        "orphan-before-runs-on": CANONICAL.replace(
            "  greenwash:\n    runs-on", "  greenwash:\n      orphan: value\n    runs-on"
        ),
        "orphan-before-first-step": CANONICAL.replace(
            "    steps:\n      - uses:", "    steps:\n        orphan: value\n      - uses:"
        ),
        "orphan-after-name": "name: greenwash\n  orphan: value\n" + CANONICAL,
        "orphan-after-flow-event": CANONICAL.replace(
            "on: [pull_request]\n", "on: [pull_request]\n  orphan: value\n"
        ),
        "nbsp-runs-on": CANONICAL.replace(
            "runs-on: ubuntu-latest", "runs-on: ubuntu-latest\u00a0"
        ),
        "nbsp-before-comment": CANONICAL.replace(
            "runs-on: ubuntu-latest", "runs-on: ubuntu-latest\u00a0# hidden"
        ),
        "nbsp-only-line": CANONICAL.replace("jobs:\n", "jobs:\n\u00a0\n"),
        "nbsp-flow-event": CANONICAL.replace(
            "on: [pull_request]", "on: [\u00a0pull_request\u00a0]"
        ),
    }
    for label, workflow in cases.items():
        _incomplete(_canonical_repo(tmp_path / label, workflow), label)

    raw_cases = {
        "double-bom": b"\xef\xbb\xbf\xef\xbb\xbf" + CANONICAL.encode("utf-8"),
        "invalid-utf8-full-comment": b"# invalid \xff\n" + CANONICAL.encode("utf-8"),
        "invalid-utf8-trailing-comment": CANONICAL.encode("utf-8").replace(
            b"on: [pull_request]", b"on: [pull_request] # invalid \xff", 1
        ),
    }
    controls = {
        "null-byte": b"\x00",
        "unit-separator": b"\x1f",
        "delete": b"\x7f",
        "c1-control": "\u009f".encode("utf-8"),
        "noncharacter": "\ufffe".encode("utf-8"),
    }
    for label, marker in controls.items():
        raw_cases[label] = CANONICAL.encode("utf-8").replace(
            b"on: [pull_request]", b"on: [pull_request] # hidden " + marker, 1
        )
    for label, separator in {
        "nel-hidden-line": "\u0085",
        "ls-hidden-line": "\u2028",
        "ps-hidden-line": "\u2029",
    }.items():
        raw_cases[label] = (
            f"# hidden{separator}jobs: {{shadow: {{}}}}\n" + CANONICAL
        ).encode("utf-8")
    for label, payload in raw_cases.items():
        root = tmp_path / label
        path = root / CI / "greenwash.yml"
        path.parent.mkdir(parents=True)
        path.write_bytes(payload)
        _incomplete(root, label)


def test_fake_workflow_extensions_and_case_mismatches_are_not_healthy(tmp_path):
    notes = collect(_canonical_repo(tmp_path, suffix=".yml.bak"))
    assert _levels(notes, "no greenwash installation found") == ["problem"]
    assert not _levels(notes, "runs unconditionally")

    remote = _repo(tmp_path / "mixed-remote", {
        ".GitHub/Workflows/greenwash.yml": CANONICAL,
    })
    _not_healthy(remote, "mixed-case workflow ancestors")

    ci = (ROOT / CI / "ci.yml").read_text(encoding="utf-8")
    action = (ROOT / "action/action.yml").read_text(encoding="utf-8")
    post = (ROOT / "action/post_review.py").read_text(encoding="utf-8")
    ancestor = _repo(tmp_path / "mixed-action-ancestor", {
        f"{CI}/ci.yml": ci,
        "Action/action.yml": action,
        "Action/post_review.py": post,
    })
    _not_healthy(ancestor, "mixed-case action ancestor")
    leaf = _repo(tmp_path / "mixed-action-leaf", {
        f"{CI}/ci.yml": ci,
        "action/Action.yml": action,
        "action/post_review.py": post,
    })
    _not_healthy(leaf, "mixed-case action leaf")


def _symlink(link: pathlib.Path, target: pathlib.Path, directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")


def test_linked_workflow_and_local_action_paths_are_never_healthy(tmp_path):
    file_root = tmp_path / "file-link"
    target = file_root / "canonical-source.yml"
    target.parent.mkdir(parents=True)
    target.write_text(CANONICAL, encoding="utf-8")
    workflow = file_root / CI / "greenwash.yml"
    workflow.parent.mkdir(parents=True)
    _symlink(workflow, target)
    _incomplete(file_root, "linked workflow file")

    github_root = tmp_path / "github-link"
    external_github = tmp_path / "external-github"
    (external_github / "workflows").mkdir(parents=True)
    (external_github / "workflows/greenwash.yml").write_text(CANONICAL, encoding="utf-8")
    github_root.mkdir()
    _symlink(github_root / ".github", external_github, directory=True)
    _incomplete(github_root, "linked .github ancestor")

    directory_root = tmp_path / "directory-link"
    source_dir = directory_root / "workflow-source"
    source_dir.mkdir(parents=True)
    (source_dir / "greenwash.yml").write_text(CANONICAL, encoding="utf-8")
    (directory_root / ".github").mkdir()
    _symlink(directory_root / CI, source_dir, directory=True)
    _incomplete(directory_root, "linked workflow directory")

    action_root = tmp_path / "action-link"
    files = {
        f"{CI}/ci.yml": (ROOT / CI / "ci.yml").read_text(encoding="utf-8"),
        "action/post_review.py": (ROOT / "action/post_review.py").read_text(encoding="utf-8"),
        "action-source.yml": (ROOT / "action/action.yml").read_text(encoding="utf-8"),
    }
    _repo(action_root, files)
    _symlink(action_root / "action/action.yml", action_root / "action-source.yml")
    _incomplete(action_root, "linked local action")

    action_ancestor_root = tmp_path / "action-ancestor-link"
    external_action = tmp_path / "external-action"
    _repo(external_action, {
        "action.yml": (ROOT / "action/action.yml").read_text(encoding="utf-8"),
        "post_review.py": (ROOT / "action/post_review.py").read_text(encoding="utf-8"),
    })
    _repo(action_ancestor_root, {
        f"{CI}/ci.yml": (ROOT / CI / "ci.yml").read_text(encoding="utf-8"),
    })
    _symlink(action_ancestor_root / "action", external_action, directory=True)
    _incomplete(action_ancestor_root, "linked action ancestor")


def test_local_hook_without_ci_and_empty_repo_remain_problems(tmp_path):
    hooked = _repo(tmp_path / "hook", {
        ".claude/settings.json": json.dumps({"hooks": {"Stop": "greenwash check"}})
    })
    assert _levels(collect(hooked), "runs locally but not in CI") == ["problem"]
    assert _levels(collect(_repo(tmp_path / "empty", {"README.md": "hello"})), "no greenwash installation found") == ["problem"]


def test_limits_allowlist_and_exit_semantics_are_preserved(tmp_path):
    root = _canonical_repo(tmp_path / "healthy")
    titles = " | ".join(note.title for note in collect(root))
    assert "cannot tell whether the check is *required*" in titles
    assert "cannot block when it does not run" in titles
    assert "read from the BASE side" in titles
    assert "three-dot range" in titles
    assert "allowlist expiry is capped at 180 days" in titles
    assert run(str(root), io.StringIO()) == 0

    bad = _canonical_repo(tmp_path / "bad", CANONICAL.replace("on: [pull_request]", "on: pull_request"))
    assert run(str(bad), io.StringIO()) == 1

    allow = (
        "[[allow]]\n"
        'fingerprint = "ASSERT_WEAKENED/tests/x.py/t/deadbeefdead"\n'
        'rule = "ASSERT_WEAKENED"\nreason = "hand-edited decade"\nauthor = "audit"\n'
        'created = "2020-01-01"\nexpires = "2030-01-01"\n'
    )
    notes = collect(_repo(tmp_path / "allow", {f"{CI}/greenwash.yml": CANONICAL, ".greenwash/allow.toml": allow}))
    note = next(note for note in notes if "180 days" in note.title)
    assert "1 over the 180-day cap" in note.detail and "0 active" in note.detail


def test_doctor_is_a_registered_subcommand():
    from greenwash.cli import build_parser
    import greenwash.cli as cli_module

    assert build_parser().parse_args(["doctor", "--repo", "."]).command == "doctor"
    source = pathlib.Path(cli_module.__file__).read_text(encoding="utf-8")
    fallback = source.split("elif argv[0] not in (", 1)[1].split("):", 1)[0]
    assert '"doctor"' in fallback
