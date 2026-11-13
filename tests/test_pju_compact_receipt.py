"""Tests for compact PJU digest receipts and workflow/ruleset hardening (D-209)."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import urllib.error

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]

BRIDGE_SPEC = importlib.util.spec_from_file_location("pju_receipt_bridge_compact", ROOT / "tools/pju_receipt_bridge.py")
bridge = importlib.util.module_from_spec(BRIDGE_SPEC)
BRIDGE_SPEC.loader.exec_module(bridge)

COLLECT_SPEC = importlib.util.spec_from_file_location("collect_pju_receipts_compact", ROOT / "tools/collect_pju_receipts.py")
collector_mod = importlib.util.module_from_spec(COLLECT_SPEC)
COLLECT_SPEC.loader.exec_module(collector_mod)


def sha256_hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: object) -> str:
    return sha256_hex(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii"))


def git(repo: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True).stdout


def _prose_files(test_count: int = 23100) -> dict[str, bytes]:
    return {
        "README.md": f"# checkwash\nAlpha pre-release. 22 detectors, {test_count} tests (collection denominator).\n".encode("utf-8"),
        "CONTRIBUTING.md": f"pytest  # {test_count} tests (collected)\n".encode("utf-8"),
        "docs/launch.md": (
            f"Current source: 22 detectors, {test_count} tests (collection denominator); Apache-2.0.\n"
        ).encode("utf-8"),
    }


@pytest.fixture(scope="module")
def _base_compact_repo(tmp_path_factory: pytest.TempPathFactory):
    repo = tmp_path_factory.mktemp("compact_base") / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    for key, value in {
        "user.name": "Compact receipt test",
        "user.email": "test@example.invalid",
        "core.autocrlf": "false",
        "commit.gpgsign": "false",
    }.items():
        git(repo, "config", key, value)

    cases = [
        dict(id="preserve", kind="preserving", verdict="pass", rule=None, severity=None,
             path="a.test.js", before="before", after="after"),
        dict(id="remove", kind="removal", verdict="block", rule="ASSERT_REMOVED", severity="high",
             path="b.test.js", before="before", after="after"),
    ]
    action_yaml = (
        "runs:\n  using: composite\n  steps:\n"
        "    - id: install\n      shell: bash\n      run: |\n        echo install-step\n"
        "    - id: check\n      shell: bash\n      run: 'echo check-step'\n"
    ).encode("utf-8")
    pin = "5" * 40
    doctor_py = f'_PREVIOUS_ACTION_PIN = "{pin}"\n_OWN_ACTION_PIN = "{pin}"\n'.encode("utf-8")
    base_files = {
        "src/checkwash/__init__.py": b"# synthetic package\n",
        "src/checkwash/doctor.py": doctor_py,
        "pyproject.toml": b'[project]\nname = "checkwash"\nversion = "0.12.0"\n',
        "release/advertised.toml": b'[release]\nversion = "0.12.0"\n',
        "action/action.yml": action_yaml,
        ".github/workflows/quality-candidate-intake.yml": b"name: quality candidate intake\njobs:\n  intake:\n    runs-on: ubuntu-latest\n",
        **_prose_files(23100),
        **{name: b"# audited synthetic helper\n" for name in bridge.UTILITIES},
        **{name: json.dumps(dict(schema_version=1, mutations=[case])).encode("utf-8")
           for name, case in zip(bridge.CONTRACTS, cases)},
    }
    for rel, raw in base_files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base and pinned action")
    base_sha = git(repo, "rev-parse", "HEAD").decode("ascii").strip()
    tree_sha = git(repo, "rev-parse", "HEAD^{tree}").decode("ascii").strip()
    src_tree = git(repo, "rev-parse", "HEAD:src").decode("ascii").strip()
    return dict(
        repo=repo,
        cases=cases,
        action_yaml=action_yaml,
        base_files=base_files,
        base_sha=base_sha,
        tree_sha=tree_sha,
        src_tree=src_tree,
    )


def _clone_repo(src: Path, dst: Path) -> Path:
    subprocess.run(["git", "clone", "-c", "core.autocrlf=false", "--quiet", str(src), str(dst)], check=True)
    for key, value in {
        "user.name": "Compact receipt test",
        "user.email": "test@example.invalid",
        "core.autocrlf": "false",
        "commit.gpgsign": "false",
    }.items():
        git(dst, "config", key, value)
    return dst


@pytest.fixture
def compact_fixture(_base_compact_repo: dict, monkeypatch: pytest.MonkeyPatch):
    repo = _base_compact_repo["repo"]
    cases = _base_compact_repo["cases"]
    action_yaml = _base_compact_repo["action_yaml"]
    base_files = _base_compact_repo["base_files"]
    base_sha = _base_compact_repo["base_sha"]
    head_sha = base_sha
    tree_sha = _base_compact_repo["tree_sha"]
    src_tree = _base_compact_repo["src_tree"]
    monkeypatch.setattr(bridge, "ACTION_SHA", base_sha)

    pkg_files = {
        k.removeprefix("src/"): sha256_hex(v)
        for k, v in base_files.items()
        if k.startswith("src/checkwash/")
    }
    pkg_sha = canonical(pkg_files)
    closure = {
        k: sha256_hex(v)
        for k, v in base_files.items()
        if k.startswith(("action/", "src/")) or k == "pyproject.toml"
    }
    closure_sha = canonical(closure)

    def make_action_summary(act_sha: str, act_tree: str, pkg_map: dict[str, str]) -> dict:
        return dict(
            action_sha=act_sha,
            action_tree=act_tree,
            action_yaml_sha256=sha256_hex(action_yaml),
            install_run_sha256=sha256_hex(b"echo install-step\n"),
            check_run_sha256=sha256_hex(b"echo check-step"),
            source_digest=canonical({k.removeprefix("checkwash/"): v for k, v in pkg_map.items()}),
            runtime_files=len(pkg_map),
            version="0.12.0",
            base_sha=base_sha,
            head_sha=head_sha,
            fail_on="high",
            comment_pr=False,
            exit_code=0,
            analysis_exit_code=0,
            host=bridge.HOST,
            provenance="PJU_LOCAL_COMPOSITE_REPLAY",
            check_receipt_sha256="1" * 64,
            replay_sha256="2" * 64,
        )

    pytest_stdout_sha = "9" * 64
    receipt = dict(
        schema_version=1,
        kind="checkwash.pju-compact-receipt.v1",
        status="completed",
        repository=bridge.REPOSITORY,
        pr_number=606,
        base_sha=base_sha,
        head_sha=head_sha,
        source_tree=tree_sha,
        src_tree=src_tree,
        host=bridge.HOST,
        provenance=bridge.PROVENANCE,
        collector_source_sha=base_sha,
        action_sha=base_sha,
        version="checkwash 0.12.0",
        runtime=dict(
            os="Windows",
            python_version="3.11.9",
            python_executable="C:/pju/venv/Scripts/python.exe",
            python_sha256="a" * 64,
            git_executable="C:/Program Files/Git/cmd/git.exe",
            git_sha256="b" * 64,
            bash_executable="C:/Program Files/Git/bin/bash.exe",
            bash_sha256="c" * 64,
            dependency_lock_sha256="d" * 64,
            dependencies_sha256="e" * 64,
            pytest_version="9.1.1",
            xdist_workers="16",
            other_platforms="NOT_RUN",
        ),
        contracts=dict(
            source_package_sha256=pkg_sha,
            builder_sha256=sha256_hex(base_files["tools/release_inventory.py"]),
            suite_sha256=canonical(cases),
            inventories=[dict(path=name, sha256=sha256_hex(base_files[name]), mutations=1) for name in bridge.CONTRACTS],
        ),
        action_dogfood=make_action_summary(base_sha, tree_sha, pkg_files),
        candidate_action=dict(
            candidate_closure_sha256=closure_sha,
            pinned_closure_sha256=closure_sha,
            mode="byte-identical-reuse",
            replay=None,
        ),
        distributions=dict(
            wheel=dict(name="checkwash-0.12.0-py3-none-any.whl", sha256="3" * 64, bytes=12000,
                       members_sha256="4" * 64, package_sha256=pkg_sha),
            sdist=dict(name="checkwash-0.12.0.tar.gz", sha256="5" * 64, bytes=45000,
                       members_sha256="6" * 64, package_sha256=pkg_sha),
            pyz=dict(name="checkwash.pyz", sha256="7" * 64, bytes=11000,
                     members_sha256="8" * 64, package_sha256=pkg_sha),
        ),
        junit=dict(
            sha256="f" * 64,
            bytes=102400,
            tests=23100,
            passed=23019,
            skipped=81,
            failures=0,
            errors=0,
            passed_subtests=67,
            pytest_stdout_sha256=pytest_stdout_sha,
        ),
        pytest_argv=[
            "C:/pju/venv/Scripts/python.exe", "-I", "-B", "-X", "utf8", "-m", "pytest",
            "-p", "xdist.plugin", "-n", "16", "--dist", "worksteal", "-p", "no:cacheprovider",
            "--basetemp", "C:/scratch/pytest", "--junitxml", "C:/out/junit.xml", "tests",
        ],
        raw_exits=[
            dict(
                name=name,
                duration_seconds=1.25,
                exit_code=0,
                timed_out=False,
                stdout_sha256=pytest_stdout_sha if name == "pytest" else "0" * 64,
                stderr_sha256="e" * 64,
            )
            for name in sorted(bridge.COMPACT_REQUIRED_EXITS)
        ],
    )

    def encode(obj: dict | None = None) -> tuple[bytes, str]:
        target = receipt if obj is None else obj
        raw = json.dumps(target, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        return raw, sha256_hex(raw)

    def validate(
        obj: dict | None = None,
        *,
        head: str | None = None,
        tree: str | None = None,
        collector: str | None = None,
        source_root: Path | None = None,
        trusted_root: Path | None = None,
    ):
        raw, digest_hex = encode(obj)
        return bridge.validate_compact(
            raw,
            digest_hex,
            repository=bridge.REPOSITORY,
            pr=606,
            base=base_sha,
            head=head_sha if head is None else head,
            source_tree=tree_sha if tree is None else tree,
            collector=base_sha if collector is None else collector,
            source_root=repo if source_root is None else source_root,
            trusted_root=repo if trusted_root is None else trusted_root,
        )

    return dict(
        repo=repo,
        receipt=receipt,
        base_sha=base_sha,
        head_sha=head_sha,
        tree_sha=tree_sha,
        base_files=base_files,
        make_action_summary=make_action_summary,
        encode=encode,
        validate=validate,
    )


def test_compact_constants_and_shipped_ruleset_match_d209():
    assert collector_mod.PYTEST_WORKERS == bridge.PYTEST_WORKERS == "8"
    assert collector_mod.COMPACT_PYTEST_WORKERS == bridge.COMPACT_PYTEST_WORKERS == "16"
    assert bridge.COMPACT_CONTEXTS == ("checkwash",)
    payload = json.loads((ROOT / "action/required-ruleset.json").read_text(encoding="utf-8"))
    checks = payload["rules"][0]["parameters"]["required_status_checks"]
    assert checks == [{"context": "checkwash", "integration_id": 15368}]


def test_intake_workflow_compact_mode_graph_and_rc03_hardening():
    flow_path = ROOT / ".github/workflows/quality-candidate-intake.yml"
    text = flow_path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    triggers = data.get("on", data.get(True))
    inputs = triggers["workflow_dispatch"]["inputs"]
    assert len(inputs) <= 10, f"GitHub workflow_dispatch supports at most 10 inputs, got {len(inputs)}"
    assert inputs["mode"]["options"] == ["intake", "receipt", "release-capture", "release-receipt"]
    assert "compact_receipt" in inputs
    pr_paths = triggers["pull_request"]["paths"]
    assert ".github/workflows/quality-candidate-intake.yml" not in pr_paths

    jobs = data["jobs"]
    assert jobs["intake"]["if"] == "github.event_name != 'workflow_dispatch' || inputs.mode == 'intake'"
    for legacy_job in ("verify-pju-receipt", "publish-pju-checks"):
        assert jobs[legacy_job]["if"] == (
            "github.event_name == 'workflow_dispatch' && inputs.mode == 'receipt' && inputs.compact_receipt == ''"
        )
    for job_name in ("verify-pju-compact", "publish-pju-compact"):
        job = jobs[job_name]
        assert job["runs-on"] == "ubuntu-latest"
        assert job["if"] == (
            "github.event_name == 'workflow_dispatch' && inputs.mode == 'receipt' && inputs.compact_receipt != ''"
        )
        checkout_paths = []
        for step in job["steps"]:
            if "run" in step:
                assert "${{" not in step["run"], f"expression interpolation forbidden in {job_name}"
            if step.get("uses", "").startswith("actions/checkout@"):
                assert re.fullmatch(r"actions/checkout@[0-9a-f]{40}", step["uses"])
                assert step["with"]["persist-credentials"] is False
                checkout_paths.append(step["with"]["path"])
        assert checkout_paths == ["trusted", "candidate-data"]
    assert "checks" not in jobs["verify-pju-compact"]["permissions"]
    assert jobs["publish-pju-compact"]["needs"] == "verify-pju-compact"
    assert jobs["publish-pju-compact"]["permissions"]["checks"] == "write"


def test_valid_compact_receipt_passes_both_closure_modes(compact_fixture, tmp_path):
    report = compact_fixture["validate"]()
    assert report["status"] == "verified"
    assert report["mode"] == "compact-receipt"
    assert report["checks"] == ["checkwash"]
    assert report["candidate_action_mode"] == "byte-identical-reuse"
    assert report["junit"] == {"tests": 23100, "passed": 23019, "skipped": 81, "passed_subtests": 67}

    repo = _clone_repo(compact_fixture["repo"], tmp_path / "cand")
    (repo / "src/checkwash/__init__.py").write_bytes(b"# modified candidate package\n")
    git(repo, "add", "src/checkwash/__init__.py")
    git(repo, "commit", "-m", "candidate modifies src")
    new_head = git(repo, "rev-parse", "HEAD").decode("ascii").strip()
    new_tree = git(repo, "rev-parse", "HEAD^{tree}").decode("ascii").strip()
    new_src_tree = git(repo, "rev-parse", "HEAD:src").decode("ascii").strip()

    updated = copy.deepcopy(compact_fixture["receipt"])
    updated["head_sha"] = new_head
    updated["source_tree"] = new_tree
    updated["src_tree"] = new_src_tree
    pkg_files = {
        "checkwash/__init__.py": sha256_hex(b"# modified candidate package\n"),
        "checkwash/doctor.py": sha256_hex((repo / "src/checkwash/doctor.py").read_bytes()),
    }
    new_pkg_sha = canonical(pkg_files)
    updated["contracts"]["source_package_sha256"] = new_pkg_sha
    for dist in updated["distributions"].values():
        dist["package_sha256"] = new_pkg_sha
    updated["action_dogfood"]["head_sha"] = new_head

    cand_closure = {
        k: sha256_hex((repo / k).read_bytes())
        for k in compact_fixture["base_files"]
        if k.startswith(("action/", "src/")) or k == "pyproject.toml"
    }
    updated["candidate_action"] = dict(
        candidate_closure_sha256=canonical(cand_closure),
        pinned_closure_sha256=compact_fixture["receipt"]["candidate_action"]["pinned_closure_sha256"],
        mode="separate-replay",
        replay=compact_fixture["make_action_summary"](new_head, new_tree, pkg_files),
    )
    updated["candidate_action"]["replay"]["head_sha"] = new_head
    updated["raw_exits"].append(
        dict(name="candidate-action-dogfood", duration_seconds=2.5, exit_code=0,
             timed_out=False, stdout_sha256="0" * 64, stderr_sha256="e" * 64)
    )
    separate = compact_fixture["validate"](
        updated, head=new_head, tree=new_tree, source_root=repo, trusted_root=compact_fixture["repo"],
    )
    assert separate["status"] == "verified"
    assert separate["candidate_action_mode"] == "separate-replay"


@pytest.mark.parametrize("bad_raw, pattern", [
    (b"", "oversized/empty compact receipt"),
    (b"x" * (bridge.MAX_COMPACT_RECEIPT + 1), "oversized/empty compact receipt"),
    (b'{"a":1}\n', "single-line JSON"),
    (b'{"a":1}\r', "single-line JSON"),
    (b'{ "a": 1 }', "canonical ASCII JSON"),
    (b'{"z":1,"a":2}', "canonical ASCII JSON"),
], ids=["empty", "oversized", "lf", "cr", "spaced", "unsorted"])
def test_compact_wire_framing_and_digest_enforced(compact_fixture, bad_raw, pattern):
    with pytest.raises(ValueError, match=pattern):
        bridge.validate_compact(
            bad_raw, sha256_hex(bad_raw) if bad_raw else "0" * 64,
            repository=bridge.REPOSITORY, pr=606, base=compact_fixture["base_sha"],
            head=compact_fixture["head_sha"], source_tree=compact_fixture["tree_sha"],
            collector=compact_fixture["base_sha"], source_root=compact_fixture["repo"],
            trusted_root=compact_fixture["repo"],
        )
    raw, _ = compact_fixture["encode"]()
    with pytest.raises(ValueError, match="external compact receipt digest mismatch"):
        bridge.validate_compact(
            raw, "0" * 64, repository=bridge.REPOSITORY, pr=606,
            base=compact_fixture["base_sha"], head=compact_fixture["head_sha"],
            source_tree=compact_fixture["tree_sha"], collector=compact_fixture["base_sha"],
            source_root=compact_fixture["repo"], trusted_root=compact_fixture["repo"],
        )


@pytest.mark.parametrize("mutator, pattern", [
    (lambda r: r["contracts"].update(source_package_sha256="0" * 64), "compact contract/package digest mismatch"),
    (lambda r: r["contracts"].update(suite_sha256="0" * 64), "compact contract/package digest mismatch"),
    (lambda r: r["contracts"].update(builder_sha256="0" * 64), "compact contract/package digest mismatch"),
    (lambda r: r["distributions"]["wheel"].update(package_sha256="0" * 64), "delivered package digest differs"),
    (lambda r: r["distributions"]["pyz"].update(name="other.pyz"), "compact distribution filename mismatch"),
    (lambda r: r["action_dogfood"].update(check_run_sha256="0" * 64), "compact Action run block digest mismatch"),
    (lambda r: r["action_dogfood"].update(source_digest="0" * 64), "compact Action engine identity mismatch"),
    (lambda r: r["action_dogfood"].update(analysis_exit_code=1), "compact Action replay identity/status mismatch"),
    (lambda r: r["candidate_action"].update(mode="separate-replay", replay={}), "invalid candidate Action replay mode"),
    (lambda r: r["runtime"].update(xdist_workers="8"), "compact runtime scope mismatch"),
    (lambda r: r["pytest_argv"].__setitem__(10, "8"), "compact pytest command scope differs"),
    (lambda r: r["pytest_argv"].__setitem__(19, "tests/unit"), "compact pytest command scope differs"),
    (lambda r: r["raw_exits"][0].update(exit_code=1), "nonzero/timed-out compact command exit"),
    (lambda r: r["raw_exits"].pop(), "compact required command set mismatch"),
    (lambda r: r["junit"].update(failures=1), "compact JUnit failures/errors"),
    (lambda r: r["junit"].update(pytest_stdout_sha256="a" * 64), "compact JUnit pytest stdout linkage mismatch"),
    (lambda r: r["junit"].update(tests=23099, passed=23018), "differs from documented suite count"),
])
def test_compact_tamper_cases_rejected(compact_fixture, mutator, pattern):
    tampered = copy.deepcopy(compact_fixture["receipt"])
    mutator(tampered)
    with pytest.raises(ValueError, match=pattern):
        compact_fixture["validate"](tampered)


def test_documented_test_count_disagreement_or_floor_drop_rejected(compact_fixture, tmp_path):
    repo = _clone_repo(compact_fixture["repo"], tmp_path / "prose")
    (repo / "CONTRIBUTING.md").write_bytes(b"pytest  # 23099 tests (collected)\n")
    git(repo, "add", "CONTRIBUTING.md")
    git(repo, "commit", "-m", "drift contributing count")
    drifted = git(repo, "rev-parse", "HEAD").decode("ascii").strip()
    with pytest.raises(ValueError, match="documented test counts disagree"):
        bridge.documented_test_count(repo, drifted)

    for rel, raw in _prose_files(500).items():
        (repo / rel).write_bytes(raw)
    git(repo, "add", "README.md", "CONTRIBUTING.md", "docs/launch.md")
    git(repo, "commit", "-m", "drop count below floor")
    dropped = git(repo, "rev-parse", "HEAD").decode("ascii").strip()
    with pytest.raises(ValueError, match="below admitted floor"):
        bridge.documented_test_count(repo, dropped)


def test_admit_compact_environment_self_seals_bootstrap_after_merge(compact_fixture, tmp_path):
    repo = _clone_repo(compact_fixture["repo"], tmp_path / "seal")
    base_before = compact_fixture["base_sha"]

    (repo / ".github/workflows/quality-candidate-intake.yml").write_bytes(
        b"name: quality candidate intake\njobs:\n  verify-pju-compact:\n    runs-on: ubuntu-latest\n"
    )
    git(repo, "add", ".github/workflows/quality-candidate-intake.yml")
    git(repo, "commit", "-m", "add compact-receipt workflow")
    d209_head = git(repo, "rev-parse", "HEAD").decode("ascii").strip()

    env_bootstrap = dict(
        GITHUB_EVENT_NAME="workflow_dispatch",
        GITHUB_REPOSITORY=bridge.REPOSITORY,
        GITHUB_REPOSITORY_OWNER="taipei49314",
        GITHUB_ACTOR="taipei49314",
        GITHUB_TRIGGERING_ACTOR="taipei49314",
        GITHUB_SHA=d209_head,
        GITHUB_WORKFLOW_SHA=d209_head,
        GITHUB_WORKFLOW_REF=bridge.REPOSITORY + "/.github/workflows/quality-candidate-intake.yml@refs/heads/claude/d209",
    )
    # Bootstrap succeeds when base does NOT yet have verify-pju-compact AND workflow == head == collector.
    bridge.admit_compact_environment(
        d209_head, head_sha=d209_head, base_sha=base_before, collector_sha=d209_head,
        trusted_root=repo, env=env_bootstrap,
    )
    # Bootstrap refuses mismatched collector or non-head workflow commit.
    with pytest.raises(ValueError, match="bootstrap requires exact candidate head"):
        bridge.admit_compact_environment(
            d209_head, head_sha=d209_head, base_sha=base_before, collector_sha=base_before,
            trusted_root=repo, env=env_bootstrap,
        )

    # Once D-209 is on main (base_sha == d209_head), branch workflow_ref is permanently refused!
    (repo / "README.md").write_bytes((repo / "README.md").read_bytes() + b"\n")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "ordinary PR after D-209")
    next_pr_head = git(repo, "rev-parse", "HEAD").decode("ascii").strip()
    env_branch_after = dict(env_bootstrap, GITHUB_SHA=next_pr_head, GITHUB_WORKFLOW_SHA=next_pr_head)
    with pytest.raises(ValueError, match="must be dispatched from refs/heads/main once merged"):
        bridge.admit_compact_environment(
            next_pr_head, head_sha=next_pr_head, base_sha=d209_head, collector_sha=next_pr_head,
            trusted_root=repo, env=env_branch_after,
        )
    # Dispatched from refs/heads/main with collector == workflow_sha succeeds.
    env_main = dict(
        env_bootstrap,
        GITHUB_SHA=d209_head,
        GITHUB_WORKFLOW_SHA=d209_head,
        GITHUB_WORKFLOW_REF=bridge.REPOSITORY + "/.github/workflows/quality-candidate-intake.yml@refs/heads/main",
    )
    bridge.admit_compact_environment(
        d209_head, head_sha=next_pr_head, base_sha=d209_head, collector_sha=d209_head,
        trusted_root=repo, env=env_main,
    )


def test_publish_compact_publishes_single_checkwash_context_and_rolls_back(compact_fixture):
    report = compact_fixture["validate"]()
    _, manifest_sha = compact_fixture["encode"]()
    calls = []

    class FakeAPI:
        def __init__(self, fail_patch: bool = False, app_id: int = 15368):
            self.fail_patch = fail_patch
            self.app_id = app_id

        def request(self, method: str, path: str, body: dict | None = None):
            calls.append((method, path, body))
            if method == "GET" and "/pulls/" in path:
                return dict(
                    state="open", merged=False,
                    head=dict(sha=compact_fixture["head_sha"], repo=dict(full_name=bridge.REPOSITORY)),
                    base=dict(sha=compact_fixture["base_sha"], ref="main", repo=dict(full_name=bridge.REPOSITORY)),
                )
            if method == "GET" and "/git/commits/" in path:
                return dict(tree=dict(sha=compact_fixture["tree_sha"]))
            if method == "POST":
                return dict(id=701)
            if method == "PATCH":
                if self.fail_patch and body and body.get("conclusion") == "success":
                    raise urllib.error.URLError("simulated network drop")
                return dict(id=701, app=dict(id=self.app_id))
            raise AssertionError(path)

    ids = bridge.publish_compact(FakeAPI(), report, manifest_sha, "https://github.com/taipei49314/checkwash/actions/runs/99")
    assert ids == [701]
    posts = [c for c in calls if c[0] == "POST"]
    assert len(posts) == 1
    assert posts[0][2]["name"] == "checkwash"
    assert posts[0][2]["external_id"] == f"pju-compact:{manifest_sha}:checkwash"
    bridge.validate_native_route({"output": posts[0][2]["output"]}, {"host": bridge.HOST, "provenance": bridge.PROVENANCE})

    calls.clear()
    with pytest.raises(urllib.error.URLError):
        bridge.publish_compact(FakeAPI(fail_patch=True), report, manifest_sha, "https://github.com/taipei49314/checkwash/actions/runs/99")
    rollbacks = [c for c in calls if c[0] == "PATCH" and c[2].get("conclusion") == "failure"]
    assert len(rollbacks) == 1

    calls.clear()
    with pytest.raises(ValueError, match="unexpected check App ID"):
        bridge.publish_compact(FakeAPI(app_id=99999), report, manifest_sha, "https://github.com/taipei49314/checkwash/actions/runs/99")
    assert len([c for c in calls if c[0] == "PATCH" and c[2].get("conclusion") == "failure"]) == 1


def test_main_compact_cli_env_roundtrip_and_release_head_refusal(compact_fixture, tmp_path, monkeypatch):
    repo = compact_fixture["repo"]
    raw, digest_hex = compact_fixture["encode"]()
    for key, value in dict(
        GITHUB_EVENT_NAME="workflow_dispatch",
        GITHUB_REPOSITORY=bridge.REPOSITORY,
        GITHUB_REPOSITORY_OWNER="taipei49314",
        GITHUB_ACTOR="taipei49314",
        GITHUB_TRIGGERING_ACTOR="taipei49314",
        GITHUB_SHA=compact_fixture["base_sha"],
        GITHUB_WORKFLOW_SHA=compact_fixture["base_sha"],
        GITHUB_WORKFLOW_REF=bridge.REPOSITORY + "/.github/workflows/quality-candidate-intake.yml@refs/heads/main",
        PJU_COMPACT_RECEIPT=raw.decode("ascii"),
        GH_TOKEN="synthetic-token",
        GITHUB_RUN_ID="12345",
    ).items():
        monkeypatch.setenv(key, value)

    class StubGitHub:
        def __init__(self, token):
            assert token == "synthetic-token"

        def request(self, method, path, body=None):
            if method == "GET" and "/pulls/" in path:
                return dict(
                    state="open", merged=False,
                    head=dict(sha=compact_fixture["head_sha"], repo=dict(full_name=bridge.REPOSITORY)),
                    base=dict(sha=compact_fixture["base_sha"], ref="main", repo=dict(full_name=bridge.REPOSITORY)),
                )
            if method == "GET" and "/git/commits/" in path:
                return dict(tree=dict(sha=compact_fixture["tree_sha"]))
            return dict(id=888)

    monkeypatch.setattr(bridge, "GitHub", StubGitHub)
    out = tmp_path / "compact-pub.json"
    rc = bridge.main([
        "publish-compact",
        "--trusted-root", str(repo),
        "--source-root", str(repo),
        "--pr", "606",
        "--head", compact_fixture["head_sha"],
        "--base", compact_fixture["base_sha"],
        "--manifest-sha256", digest_hex,
        "--collector-source-sha", compact_fixture["base_sha"],
        "--trusted-workflow-sha", compact_fixture["base_sha"],
        "--output", str(out),
    ])
    assert rc == 0
    published = json.loads(out.read_text(encoding="utf-8"))
    assert published["status"] == "verified" and published["check_run_ids"] == [888]

    # Refuses --receipt-commit in compact mode.
    rc_bad = bridge.main([
        "verify-compact",
        "--trusted-root", str(repo),
        "--source-root", str(repo),
        "--receipt-commit", compact_fixture["base_sha"],
        "--pr", "606",
        "--head", compact_fixture["head_sha"],
        "--base", compact_fixture["base_sha"],
        "--manifest-sha256", digest_hex,
        "--collector-source-sha", compact_fixture["base_sha"],
        "--trusted-workflow-sha", compact_fixture["base_sha"],
        "--output", str(out),
    ])
    assert rc_bad == 1
    assert "takes no receipt checkout" in json.loads(out.read_text(encoding="utf-8"))["error"]

    # Refuses release heads (version bump or doctor own-pin change) before touching GitHub.
    rel_repo = _clone_repo(repo, tmp_path / "rel_repo")
    (rel_repo / "pyproject.toml").write_bytes(b'[project]\nname = "checkwash"\nversion = "0.13.0"\n')
    git(rel_repo, "add", "pyproject.toml")
    git(rel_repo, "commit", "-m", "release version bump")
    ver_head = git(rel_repo, "rev-parse", "HEAD").decode("ascii").strip()

    pin_repo = _clone_repo(repo, tmp_path / "pin_repo")
    (pin_repo / "src/checkwash/doctor.py").write_bytes(
        f'_PREVIOUS_ACTION_PIN = "{"5" * 40}"\n_OWN_ACTION_PIN = "{"6" * 40}"\n'.encode("utf-8")
    )
    git(pin_repo, "add", "src/checkwash/doctor.py")
    git(pin_repo, "commit", "-m", "own pin set")
    pin_head = git(pin_repo, "rev-parse", "HEAD").decode("ascii").strip()

    class UnreachableGitHub:
        def __init__(self, _token):
            raise AssertionError("GitHub must not be instantiated on release-head refusal")

    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(bridge, "GitHub", UnreachableGitHub)
    for cand_repo, cand_head, expected_err in (
        (rel_repo, ver_head, "only through the release bridge's pr stage"),
        (pin_repo, pin_head, "only a release PR's last commit sets doctor's own Action pin"),
    ):
        rc_rel = bridge.main([
            "verify-compact",
            "--trusted-root", str(repo),
            "--source-root", str(cand_repo),
            "--pr", "606",
            "--head", cand_head,
            "--base", compact_fixture["base_sha"],
            "--manifest-sha256", digest_hex,
            "--collector-source-sha", compact_fixture["base_sha"],
            "--trusted-workflow-sha", compact_fixture["base_sha"],
            "--output", str(out),
        ])
        assert rc_rel == 1
        assert expected_err in json.loads(out.read_text(encoding="utf-8"))["error"]


def test_legacy_receipt_main_enforces_main_ref_and_documented_test_count(compact_fixture, tmp_path, monkeypatch):
    repo = compact_fixture["repo"]
    base_sha = compact_fixture["base_sha"]
    out = tmp_path / "legacy-out.json"
    receipt_repo = _clone_repo(repo, tmp_path / "receipt_repo")
    receipt_dir = receipt_repo / "receipt"
    receipt_dir.mkdir()
    (receipt_dir / "manifest.json").write_text("{}", encoding="utf-8")
    git(receipt_repo, "add", "receipt/manifest.json")
    git(receipt_repo, "commit", "-m", "synthetic receipt commit")
    receipt_commit = git(receipt_repo, "rev-parse", "HEAD").decode("ascii").strip()

    base_env = dict(
        GITHUB_EVENT_NAME="workflow_dispatch",
        GITHUB_REPOSITORY=bridge.REPOSITORY,
        GITHUB_REPOSITORY_OWNER="taipei49314",
        GITHUB_ACTOR="taipei49314",
        GITHUB_TRIGGERING_ACTOR="taipei49314",
        GITHUB_SHA=base_sha,
        GITHUB_WORKFLOW_SHA=base_sha,
        GH_TOKEN="synthetic-token",
    )
    for k, v in base_env.items():
        monkeypatch.setenv(k, v)

    # 1. Branch workflow ref is rejected in legacy receipt mode (closes RC-02 on legacy path too).
    monkeypatch.setenv("GITHUB_WORKFLOW_REF", bridge.REPOSITORY + "/.github/workflows/quality-candidate-intake.yml@refs/heads/feature")
    rc = bridge.main([
        "verify",
        "--receipt-root", str(receipt_dir),
        "--receipt-commit", receipt_commit,
        "--trusted-root", str(repo),
        "--source-root", str(repo),
        "--pr", "606",
        "--head", base_sha,
        "--base", base_sha,
        "--manifest-sha256", "0" * 64,
        "--collector-source-sha", base_sha,
        "--trusted-workflow-sha", base_sha,
        "--output", str(out),
    ])
    assert rc == 1
    assert "receipt mode must be dispatched from refs/heads/main" in json.loads(out.read_text(encoding="utf-8"))["error"]

    # 2. On refs/heads/main, legacy receipt mode enforces documented_test_count equality (closes RC-09 on legacy path too).
    monkeypatch.setenv("GITHUB_WORKFLOW_REF", bridge.REPOSITORY + "/.github/workflows/quality-candidate-intake.yml@refs/heads/main")
    monkeypatch.setattr(bridge, "GitHub", lambda _tok: type("S", (), {
        "request": lambda self, m, p, b=None: (
            dict(state="open", merged=False,
                 head=dict(sha=base_sha, repo=dict(full_name=bridge.REPOSITORY)),
                 base=dict(sha=base_sha, ref="main", repo=dict(full_name=bridge.REPOSITORY)))
            if "/pulls/" in p else dict(tree=dict(sha=compact_fixture["tree_sha"]))
        )
    })())
    monkeypatch.setattr(bridge, "Packet", lambda root, sha_hex: object())
    monkeypatch.setattr(bridge, "validate_packet", lambda *a, **kw: dict(status="verified", junit=dict(tests=2)))
    rc_count = bridge.main([
        "verify",
        "--receipt-root", str(receipt_dir),
        "--receipt-commit", receipt_commit,
        "--trusted-root", str(repo),
        "--source-root", str(repo),
        "--pr", "606",
        "--head", base_sha,
        "--base", base_sha,
        "--manifest-sha256", "0" * 64,
        "--collector-source-sha", base_sha,
        "--trusted-workflow-sha", base_sha,
        "--output", str(out),
    ])
    assert rc_count == 1
    assert "JUnit test count 2 differs from documented suite count 23100" in json.loads(out.read_text(encoding="utf-8"))["error"]


def test_collect_compact_binds_admitted_git_and_restores_helpers(compact_fixture, tmp_path, monkeypatch):
    import argparse
    import shutil
    import sys
    import types

    git_exe = shutil.which("git")
    assert git_exe is not None
    inv_mod = collector_mod.load_trusted_module("_test_inv", "release_inventory.py")
    br_mod = collector_mod.load_trusted_module("_test_br", "pju_receipt_bridge.py")
    qual_mod = collector_mod.load_trusted_module("_test_qual", "qualify_assertions.py")
    action_mod = collector_mod.load_replayer()
    orig_inv_git = inv_mod.git
    orig_br_git = br_mod.git

    source_repo = _clone_repo(compact_fixture["repo"], tmp_path / "cand_src")
    trusted_repo = _clone_repo(compact_fixture["repo"], tmp_path / "trusted_src")
    pinned_repo = _clone_repo(compact_fixture["repo"], tmp_path / "pinned_src")
    py_exe = Path(sys.executable).absolute()
    monkeypatch.setattr(collector_mod, "ROOT", trusted_repo)
    monkeypatch.setattr(
        collector_mod,
        "sys",
        types.SimpleNamespace(
            version_info=(3, 11, 9),
            executable=str(py_exe),
            dont_write_bytecode=True,
            flags=types.SimpleNamespace(isolated=1, dont_write_bytecode=1, utf8_mode=1),
        ),
    )

    fake_bash = tmp_path / "bash.exe"
    fake_bash.write_bytes(b"bash-bin")
    lock_file = tmp_path / "lock.json"
    lock_raw = json.dumps({"pytest": "9.1.1"}).encode("utf-8")
    lock_file.write_bytes(lock_raw)

    def fake_loader(name: str, filename: str):
        if filename == "release_inventory.py":
            return inv_mod
        if filename == "pju_receipt_bridge.py":
            return br_mod
        if filename == "qualify_assertions.py":
            return qual_mod
        raise AssertionError(filename)

    seen_git_calls: list[tuple[str, ...]] = []
    orig_subproc_run = subprocess.run

    def wrapped_run(argv, *a, **kw):
        if isinstance(argv, list) and argv and Path(argv[0]).resolve() == Path(git_exe).resolve():
            seen_git_calls.append(tuple(argv))
        return orig_subproc_run(argv, *a, **kw)

    monkeypatch.setattr(subprocess, "run", wrapped_run)
    # Remove ambient PATH so bare "git" lookup would fail if _clean_git were not bound.
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(action_mod, "ACTION_SHA", compact_fixture["base_sha"])

    orig_run_record = action_mod.run_record

    def fake_run_record(name, argv, *, cwd, env, output, timeout, ledger, lock=None):
        if name.startswith("git-"):
            return orig_run_record(name, argv, cwd=cwd, env=env, output=output, timeout=timeout, ledger=ledger, lock=lock)
        stdout_rel = f"commands/{name}.out"
        stderr_rel = f"commands/{name}.err"
        (output / "commands").mkdir(exist_ok=True)
        if name == "runtime-identity":
            # Verify bridge.documented_test_count and inventory_mod.git work while PATH="" inside collect_compact!
            assert br_mod.documented_test_count(source_repo, compact_fixture["base_sha"]) == 23100
            assert inv_mod.git("rev-parse", "HEAD").decode("ascii").strip() == compact_fixture["base_sha"]
            payload = json.dumps({
                "python_version": "3.11.9",
                "prefix": str(py_exe.parent.parent),
                "base": str(tmp_path / "base_py"),
                "dependencies": {"pytest": "9.1.1"},
            }).encode("utf-8")
            (output / stdout_rel).write_bytes(payload)
            (output / stderr_rel).write_bytes(b"")
            row = dict(name=name, duration_seconds=0.01, exit_code=0, timed_out=False, stdout=stdout_rel, stderr=stderr_rel)
        else:
            (output / stdout_rel).write_bytes(b"")
            (output / stderr_rel).write_bytes(b"simulated stop")
            row = dict(name=name, duration_seconds=0.01, exit_code=1, timed_out=False, stdout=stdout_rel, stderr=stderr_rel)
        ledger.append(row)
        return row

    monkeypatch.setattr(action_mod, "run_record", fake_run_record)
    monkeypatch.setattr(collector_mod, "load_replayer", lambda: action_mod)
    monkeypatch.setattr(collector_mod, "load_trusted_module", fake_loader)

    args = argparse.Namespace(
        repository=bridge.REPOSITORY,
        pr=606,
        base_sha=compact_fixture["base_sha"],
        head_sha=compact_fixture["head_sha"],
        source_tree=compact_fixture["tree_sha"],
        collector_source_sha=compact_fixture["base_sha"],
        dependency_lock_sha256=sha256_hex(lock_raw),
        source_root=str(source_repo),
        action_root=str(pinned_repo),
        candidate_action_root=None,
        dependency_lock=str(lock_file),
        output=str(tmp_path / "out"),
        scratch=str(tmp_path / "scratch"),
        python=str(py_exe),
        git=git_exe,
        bash=str(fake_bash),
    )
    rc = collector_mod.collect_compact(args)
    assert rc == 1
    status = json.loads((tmp_path / "out/collection-status.json").read_text(encoding="utf-8"))
    assert status["mode"] == "compact-receipt"
    assert any("action-dogfood" in err for err in status["errors"])
    assert seen_git_calls
    assert inv_mod.git is orig_inv_git
    assert br_mod.git is orig_br_git


def test_summarize_action_replay_and_dual_input_refusal(compact_fixture, tmp_path):
    action_mod = collector_mod.load_replayer()
    route = dict(host=bridge.HOST, provenance=bridge.PROVENANCE, action_provenance="PJU_LOCAL_COMPOSITE_REPLAY")
    act_dir = tmp_path / "action"
    (act_dir / "runtime-receipts").mkdir(parents=True)
    identity = dict(
        python="C:/pju/python.exe", python_version="3.11.9", base_python="C:/pju/base.exe",
        isolated=True, utf8=True, bytecode_writes_disabled=True,
        source_root="C:/src", package_root="C:/pkg", version="0.12.0",
        runtime_files=2, source_digest="1" * 64,
    )
    check_rec = dict(
        action_receipt_version=1, exit_code=0, analysis_exit_code=0, error=None,
        identity=identity, base=compact_fixture["base_sha"], head=compact_fixture["head_sha"], fail_on="high",
    )
    install_rep = {"version": "1", "install": [{"metadata": {"name": "checkwash", "version": "0.12.0"}}]}
    (act_dir / "runtime-receipts/identity.json").write_text(json.dumps(identity), encoding="utf-8")
    (act_dir / "runtime-receipts/check-receipt.json").write_text(json.dumps(check_rec), encoding="utf-8")
    (act_dir / "runtime-receipts/install-report.json").write_text(json.dumps(install_rep), encoding="utf-8")
    replay = dict(
        schema_version=1, kind="checkwash.pju-action-replay.v1", provenance="PJU_LOCAL_COMPOSITE_REPLAY",
        status="completed", host=bridge.HOST, action_sha=compact_fixture["base_sha"],
        action_tree=compact_fixture["tree_sha"], action_yaml_sha256="2" * 64,
        base_sha=compact_fixture["base_sha"], head_sha=compact_fixture["head_sha"],
        fail_on="high", comment_pr=False, errors=[],
        steps=[dict(id="install", exit_code=0, run_sha256="3" * 64), dict(id="check", exit_code=0, run_sha256="4" * 64)],
        resolved_outputs={"exit-code": "0"},
        files=dict(
            check_receipt="runtime-receipts/check-receipt.json",
            identity="runtime-receipts/identity.json",
            install_report="runtime-receipts/install-report.json",
        ),
    )
    (act_dir / "replay.json").write_text(json.dumps(replay), encoding="utf-8")
    summary = collector_mod._summarize_action_replay(
        act_dir, expected_action_sha=compact_fixture["base_sha"], base_sha=compact_fixture["base_sha"],
        head_sha=compact_fixture["head_sha"], python_version="3.11.9", route=route, action=action_mod,
    )
    assert summary["exit_code"] == 0 and summary["install_run_sha256"] == "3" * 64

    # Dual PJU_RECEIPT_COMMIT + compact receipt env is refused.
    env_dual = dict(
        GITHUB_EVENT_NAME="workflow_dispatch",
        GITHUB_REPOSITORY=bridge.REPOSITORY,
        GITHUB_REPOSITORY_OWNER="taipei49314",
        GITHUB_ACTOR="taipei49314",
        GITHUB_TRIGGERING_ACTOR="taipei49314",
        GITHUB_SHA=compact_fixture["base_sha"],
        GITHUB_WORKFLOW_SHA=compact_fixture["base_sha"],
        GITHUB_WORKFLOW_REF=bridge.REPOSITORY + "/.github/workflows/quality-candidate-intake.yml@refs/heads/main",
        PJU_RECEIPT_COMMIT=compact_fixture["base_sha"],
    )
    with pytest.raises(ValueError, match="refuses receipt_commit"):
        bridge.admit_compact_environment(
            compact_fixture["base_sha"], head_sha=compact_fixture["head_sha"],
            base_sha=compact_fixture["base_sha"], collector_sha=compact_fixture["base_sha"],
            trusted_root=compact_fixture["repo"], env=env_dual,
        )

