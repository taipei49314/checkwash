"""Owned synthetic evidence exercises the metadata bridge, never product tests."""
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("pju_receipt_bridge", ROOT / "tools/pju_receipt_bridge.py")
bridge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bridge)


def hashed(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return hashed(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True).stdout


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init")
    for key, value in {"user.name": "Synthetic receipt test", "user.email": "test@example.invalid",
                       "core.autocrlf": "false", "commit.gpgsign": "false"}.items():
        git(source, "config", key, value)
    cases = [
        dict(id="preserve", kind="preserving", verdict="pass", rule=None, severity=None,
             path="a.test.js", before="before", after="after"),
        dict(id="remove", kind="removal", verdict="block", rule="ASSERT_REMOVED", severity="high",
             path="b.test.js", before="before", after="after"),
    ]
    action = ("runs:\n  using: composite\n  steps:\n    - id: install\n      shell: bash\n"
              "      run: |\n        echo synthetic-install\n    - id: check\n      shell: bash\n"
              "      run: 'echo synthetic-check'\n").encode()
    source_files = {
        "src/checkwash/__init__.py": b"# synthetic package\n",
        "src/checkwash/__main__.py": b"# never executed\n",
        "pyproject.toml": b'[project]\nname="checkwash"\nversion="1.2.3"\n',
        "action/action.yml": action,
        **{name: b"# trusted synthetic helper; never executed\n" for name in bridge.UTILITIES},
        **{name: json.dumps(dict(schema_version=1, mutations=[case])).encode()
           for name, case in zip(bridge.CONTRACTS, cases)},
    }
    for name, raw in source_files.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    git(source, "add", ".")
    git(source, "commit", "-m", "synthetic data only")
    head = git(source, "rev-parse", "HEAD").decode().strip()
    tree = git(source, "rev-parse", "HEAD^{tree}").decode().strip()
    src_tree = git(source, "rev-parse", "HEAD:src").decode().strip()
    base = "a" * 40
    monkeypatch.setattr(bridge, "ACTION_SHA", head)
    packet = tmp_path / "receipt"
    packet.mkdir()

    def put(name, raw):
        path = packet / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return name

    def put_json(name, value):
        return put(name, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())

    package = {name.removeprefix("src/"): raw for name, raw in source_files.items() if name.startswith("src/")}
    members = {name: dict(git_blob=hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest(),
                          sha256=hashed(raw), bytes=len(raw)) for name, raw in package.items()}
    desc = dict(schema_version=1, kind="checkwash.pju-contract.v1", collector_source_sha=head,
                contract_source_sha=head, source_commit=head, source_tree=tree, src_tree=src_tree,
                source_package_sha256=canonical({name: hashed(raw) for name, raw in package.items()}),
                version="checkwash 1.2.3", suite_sha256=canonical(cases), cases=cases,
                inventories=[dict(path=name, sha256=hashed(source_files[name]), mutations=1) for name in bridge.CONTRACTS],
                source_members=members, builder_sha256=hashed(source_files["tools/release_inventory.py"]))
    records = dict(contract_descriptor=put_json("contract.json", desc),
                   junit=put("pytest.xml", b'<testsuites><testsuite tests="2" failures="0" errors="0" skipped="1">'
                              b'<testcase name="pass"/><testcase name="platform"><skipped/></testcase>'
                              b'</testsuite></testsuites>'), qualifications={}, inventories={})
    artifact_rows = {}
    for filename in ("checkwash.whl", "checkwash.pyz", "checkwash.tar.gz"):
        stream = io.BytesIO()
        contents = package if not filename.endswith("tar.gz") else {"checkwash-1.2.3/src/" + k: v for k, v in package.items()}
        if filename.endswith("tar.gz"):
            with tarfile.open(fileobj=stream, mode="w:gz") as archive:
                for name, raw in contents.items():
                    info = tarfile.TarInfo(name)
                    info.size = len(raw)
                    archive.addfile(info, io.BytesIO(raw))
        else:
            with zipfile.ZipFile(stream, mode="w") as archive:
                for name, raw in contents.items():
                    archive.writestr(name, raw)
        raw = stream.getvalue()
        put("artifacts/" + filename, raw)
        artifact_rows[filename] = dict(name=filename, sha256=hashed(raw), bytes=len(raw),
                                      members={name: dict(sha256=hashed(data), bytes=len(data)) for name, data in contents.items()})
    for distribution, names in {"source": [], "wheel": ["checkwash.whl", "checkwash.tar.gz"], "pyz": ["checkwash.pyz"]}.items():
        qualification = dict(schema_version=1, distribution=distribution, status="passed", suite_sha256=desc["suite_sha256"],
            source_commit=head, inventories=desc["inventories"], source_package_sha256=desc["source_package_sha256"],
            source_package_dirty=False, artifact_sha256=artifact_rows[names[0]]["sha256"] if names else None,
            version=desc["version"], errors=[], summary=dict(total=2, executed=2, failed=0), cases=[])
        for case in cases:
            blocked = case["verdict"] == "block"
            qualification["cases"].append(dict(id=case["id"], kind=case["kind"],
                expected={k: case[k] for k in ("verdict", "rule", "severity")},
                observed=dict(exit=int(blocked), verdict=case["verdict"],
                              findings=[{k: case[k] for k in ("rule", "severity", "path")}] if blocked else []),
                status="passed", errors=[]))
        qname = put_json(distribution + "/qualification.json", qualification)
        records["qualifications"][distribution] = qname
        inventory = dict(schema_version=1, status="passed", source_commit=head, distribution=distribution,
            run_id=None, attempt=None, python="3.11.9", builder="tools/release_inventory.py",
            builder_sha256=desc["builder_sha256"], builder_source_commit=head, errors=[],
            artifacts=[artifact_rows[name] for name in names], source_tree=tree, src_tree=src_tree,
            source_members=members, qualification=dict(path="qualification.json", sha256=hashed((packet / qname).read_bytes())))
        records["inventories"][distribution] = put_json(distribution + "/inventory.json", inventory)
    identity = dict(python="C:/private/python.exe", python_version="3.11.9", base_python="C:/approved/python.exe",
                    source_root="C:/pinned/action", package_root="C:/private/checkwash", isolated=True,
                    utf8=True, bytecode_writes_disabled=True, version="1.2.3", runtime_files=len(package),
                    source_digest=canonical({name.removeprefix("checkwash/"): hashed(raw) for name, raw in package.items()}))
    dogfood = dict(action_receipt_version=1, exit_code=0, analysis_exit_code=0, error=None, identity=identity,
                   base=base, head=head, fail_on="high")
    records["dogfood"] = put_json("action/check-receipt.json", dogfood)
    put_json("action/identity.json", identity)
    put_json("action/install-report.json", {"version": "1", "install": [{"metadata": {"name": "checkwash", "version": "1.2.3"}}]})
    put("action/action.yml", action)
    put("action/install.sh", b"echo synthetic-install\n")
    put("action/check.sh", b"echo synthetic-check")
    put("stdout.log", b"owned synthetic command output\n")
    put("stderr.log", b"")
    put("action/stdout.log", b"owned synthetic Action output\n")
    put("action/stderr.log", b"")
    replay = dict(schema_version=1, kind="checkwash.pju-action-replay.v1", provenance="PJU_LOCAL_COMPOSITE_REPLAY",
        status="completed", host=bridge.HOST, action_sha=head, action_tree=tree, action_yaml_sha256=hashed(action),
        base_sha=base, head_sha=head, fail_on="high", comment_pr=False, errors=[],
        files=dict(action_yaml="action.yml", check_receipt="check-receipt.json", identity="identity.json", install_report="install-report.json",
                   install_run="install.sh", check_run="check.sh", install_stdout="stdout.log", install_stderr="stderr.log",
                   check_stdout="stdout.log", check_stderr="stderr.log", pip_stdout="stdout.log", pip_stderr="stderr.log",
                   engine_stdout="stdout.log", engine_stderr="stderr.log"),
        resolved_outputs={"exit-code": "0", "receipt-path": "C:/receipt.json", "identity-path": "C:/identity.json"},
        steps=[dict(id="install", exit_code=0, run_sha256=hashed(b"echo synthetic-install\n"),
                    stdout="stdout.log", stderr="stderr.log", outputs=dict(identity_path="C:/identity.json")),
               dict(id="check", exit_code=0, run_sha256=hashed(b"echo synthetic-check"),
                    stdout="stdout.log", stderr="stderr.log", outputs=dict(exit_code="0", receipt_path="C:/receipt.json",
                    analysis_exit_code="0", base=base, head=head, fail_on="high"))])
    for step in replay["steps"]:
        put("action/" + step["id"] + ".outputs", "".join(k + "=" + v + "\n" for k, v in step["outputs"].items()).encode())
    records["action_replay"] = put_json("action/replay.json", replay)
    closure = {name: hashed(raw) for name, raw in source_files.items()
               if name.startswith(("action/", "src/")) or name == "pyproject.toml"}
    records["candidate_action_coverage"] = put_json("candidate-action-coverage.json", dict(
        schema_version=1, kind="checkwash.pju-candidate-action-coverage.v1", collector_source_sha=head,
        candidate_sha=head, pinned_action_sha=head, closure_paths=["action/", "src/", "pyproject.toml"],
        candidate_closure=closure, pinned_closure=closure, candidate_closure_sha256=canonical(closure),
        pinned_closure_sha256=canonical(closure), mode="byte-identical-reuse", replay_path="action/replay.json"))
    manifest = dict(schema_version=1, kind="checkwash.pju-receipt.v1", repository=bridge.REPOSITORY, pr_number=561,
        base_sha=base, head_sha=head, source_tree=tree, host=bridge.HOST, provenance=bridge.PROVENANCE,
        collector_source_sha=head, contract_source_sha=head, status="completed", action_sha=head,
        runtime=dict(os="Windows", python_version="3.11.9", python_executable="C:/approved/python.exe", python_sha256="b" * 64,
                     git_executable="C:/approved/git.exe", git_sha256="c" * 64, bash_executable="C:/approved/bash.exe", bash_sha256="d" * 64,
                     dependencies={"pytest": "9.1.1"}, other_platforms="NOT_RUN"), records=records,
        raw_exits=[dict(name=name, argv=["C:/approved/python.exe", "-m", "pytest", "tests"], cwd="C:/candidate",
                       started_at="2026-10-23T00:00:00Z", finished_at="2026-10-23T00:00:01Z", duration_seconds=1.0,
                       exit_code=0, timed_out=False, stdout="stdout.log", stderr="stderr.log") for name in sorted(bridge.REQUIRED_EXITS)], files=[])
    next(row for row in manifest["raw_exits"] if row["name"] == "pytest")["argv"] = [
        "C:/approved/python.exe", "-I", "-B", "-X", "utf8", "-m", "pytest", "-p", "xdist.plugin", "-n", "2",
        "--dist", "worksteal", "-p", "no:cacheprovider", "--basetemp", "C:/scratch/pytest", "--junitxml", "C:/receipt/pytest.xml", "tests"]
    def freeze():
        manifest["files"] = [dict(path=path.relative_to(packet).as_posix(), sha256=hashed(path.read_bytes()), bytes=path.stat().st_size)
                             for path in sorted(packet.rglob("*")) if path.is_file() and path.name != "manifest.json"]
        put_json("manifest.json", manifest)
        return hashed((packet / "manifest.json").read_bytes())
    def validate():
        return bridge.validate_packet(bridge.Packet(packet, freeze()), repository=bridge.REPOSITORY, pr=561,
            base=base, head=head, source_tree=tree, collector=head, source_root=source, trusted_root=source)
    return dict(packet=packet, source=source, manifest=manifest, desc=desc, records=records, head=head, base=base, tree=tree,
                put=put, put_json=put_json, freeze=freeze, validate=validate)


def test_complete_owned_evidence_passes(evidence):
    report = evidence["validate"]()
    assert report["checks"] == list(bridge.CONTEXTS)
    assert report["qualification_cases"] == 2
    assert report["junit"] == {"tests": 2, "skipped": 1}
    assert report["other_platforms"] == "NOT_RUN"


@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b'{"x":-Infinity}'])
def test_ambiguous_json_rejected(raw):
    with pytest.raises(ValueError):
        bridge.strict_json(raw)


@pytest.mark.parametrize("path", ["../outside", "/absolute", "a/../b", "a//b", "a/./b", "C:/file", "a\\b", ".git/config", "a/", "a\x00b"])
def test_unsafe_paths_rejected(path):
    with pytest.raises(ValueError):
        bridge.safe_path(path)


def test_external_digest_is_required(evidence):
    evidence["freeze"]()
    with pytest.raises(ValueError, match="external manifest"):
        bridge.Packet(evidence["packet"], "0" * 64)


def test_unlisted_data_rejected(evidence):
    expected = evidence["freeze"]()
    evidence["put"]("unlisted.txt", b"unexpected")
    with pytest.raises(ValueError, match="unlisted"):
        bridge.Packet(evidence["packet"], expected)


def test_mutated_bytes_rejected(evidence):
    expected = evidence["freeze"]()
    evidence["put"]("stdout.log", b"replacement")
    with pytest.raises(ValueError, match="bytes mismatch"):
        bridge.Packet(evidence["packet"], expected)


def test_duplicate_casefold_paths_rejected(evidence):
    evidence["freeze"]()
    manifest = evidence["manifest"]
    manifest["files"].append({**manifest["files"][0], "path": manifest["files"][0]["path"].upper()})
    evidence["put_json"]("manifest.json", manifest)
    with pytest.raises(ValueError, match="duplicate"):
        bridge.Packet(evidence["packet"], hashed((evidence["packet"] / "manifest.json").read_bytes()))


@pytest.mark.parametrize("field,value", [("schema_version", True), ("pr_number", True), ("head_sha", "f" * 40),
    ("base_sha", "f" * 40), ("host", "another-host"), ("status", "failed"), ("contract_source_sha", "f" * 40)])
def test_manifest_identity_is_not_self_reported_permission(evidence, field, value):
    evidence["manifest"][field] = value
    with pytest.raises(ValueError):
        evidence["validate"]()


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "wrong_exit", "bool_exit", "wrong_finding", "summary_bool"])
def test_qualification_incomplete_or_contradictory_is_rejected(evidence, mutation):
    name = evidence["records"]["qualifications"]["source"]
    value = json.loads((evidence["packet"] / name).read_bytes())
    if mutation == "missing":
        value["cases"].pop()
    elif mutation == "duplicate":
        value["cases"][1] = copy.deepcopy(value["cases"][0])
    elif mutation == "wrong_exit":
        value["cases"][1]["observed"]["exit"] = 0
    elif mutation == "bool_exit":
        value["cases"][1]["observed"]["exit"] = True
    elif mutation == "wrong_finding":
        value["cases"][1]["observed"]["findings"] = []
    else:
        value["summary"]["failed"] = False
    evidence["put_json"](name, value)
    with pytest.raises(ValueError):
        evidence["validate"]()


def test_descriptor_cannot_shrink_authoritative_case_universe(evidence):
    desc = evidence["desc"]
    desc["cases"].pop()
    desc["suite_sha256"] = canonical(desc["cases"])
    evidence["put_json"]("contract.json", desc)
    with pytest.raises(ValueError, match="case universe"):
        evidence["validate"]()


@pytest.mark.parametrize("change", ["exit", "timeout", "missing", "boolean"])
def test_raw_command_failure_cannot_be_hidden_by_passed_summaries(evidence, change):
    rows = evidence["manifest"]["raw_exits"]
    if change == "exit":
        rows[0]["exit_code"] = 2
    elif change == "timeout":
        rows[0]["timed_out"] = True
    elif change == "missing":
        rows.pop()
    else:
        rows[0]["exit_code"] = False
    with pytest.raises(ValueError):
        evidence["validate"]()


@pytest.mark.parametrize("xml", [
    b'<testsuites/>',
    b'<testsuite tests="1" failures="0" errors="0" skipped="0"><testcase><failure/></testcase></testsuite>',
    b'<testsuite tests="1" failures="0" errors="0" skipped="0"><testcase><error/></testcase></testsuite>',
    b'<testsuite tests="1" failures="0" errors="0" skipped="1"><testcase><skipped/></testcase></testsuite>',
    b'<testsuite tests="2" failures="0" errors="0" skipped="0"><testcase/></testsuite>',
    b'<!DOCTYPE test [<!ENTITY x "hello">]><testsuites/>',
    b'<testsuites failures="1"><testsuite tests="1" failures="0" errors="0" skipped="0"><testcase/></testsuite></testsuites>',
])
def test_junit_is_checked_beyond_exit_code(xml):
    with pytest.raises(ValueError):
        bridge.validate_junit(xml)


def test_archive_path_cannot_escape():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("../outside", b"bad")
    with pytest.raises(ValueError, match="unsafe"):
        bridge.archive_members(stream.getvalue(), "sample.whl")


def test_qualification_artifact_link_must_be_exact(evidence):
    name = evidence["records"]["inventories"]["wheel"]
    value = json.loads((evidence["packet"] / name).read_bytes())
    value["qualification"]["sha256"] = "f" * 64
    evidence["put_json"](name, value)
    with pytest.raises(ValueError, match="linkage"):
        evidence["validate"]()


def test_action_run_hash_is_bound_to_pinned_definition(evidence):
    name = evidence["records"]["action_replay"]
    replay = json.loads((evidence["packet"] / name).read_bytes())
    replay["steps"][0]["run_sha256"] = "e" * 64
    evidence["put_json"](name, replay)
    with pytest.raises(ValueError, match="run block"):
        evidence["validate"]()


def test_action_composite_output_wiring_is_verified(evidence):
    name = evidence["records"]["action_replay"]
    replay = json.loads((evidence["packet"] / name).read_bytes())
    replay["resolved_outputs"]["identity-path"] = "C:/unrelated.json"
    evidence["put_json"](name, replay)
    with pytest.raises(ValueError, match="wiring"):
        evidence["validate"]()


def test_fullsuite_claim_rejects_narrow_selection(evidence):
    row = next(row for row in evidence["manifest"]["raw_exits"] if row["name"] == "pytest")
    row["argv"][-1] = "tests/test_one.py"
    with pytest.raises(ValueError, match="full pytest"):
        evidence["validate"]()


def test_candidate_action_closure_cannot_omit_changed_files(evidence):
    name = evidence["records"]["candidate_action_coverage"]
    value = json.loads((evidence["packet"] / name).read_bytes())
    value["candidate_closure"].pop("action/action.yml")
    value["candidate_closure_sha256"] = canonical(value["candidate_closure"])
    evidence["put_json"](name, value)
    with pytest.raises(ValueError, match="closure"):
        evidence["validate"]()


def test_owner_dispatch_and_exact_workflow_admission():
    expected = "e" * 40
    env = dict(GITHUB_EVENT_NAME="workflow_dispatch", GITHUB_REPOSITORY=bridge.REPOSITORY,
               GITHUB_REPOSITORY_OWNER="taipei49314", GITHUB_ACTOR="taipei49314", GITHUB_TRIGGERING_ACTOR="taipei49314",
               GITHUB_SHA=expected, GITHUB_WORKFLOW_SHA=expected,
               GITHUB_WORKFLOW_REF=bridge.REPOSITORY + "/.github/workflows/quality-candidate-intake.yml@refs/heads/reviewed")
    bridge.admit_environment(expected, env)
    for key, value in {"GITHUB_ACTOR": "contributor", "GITHUB_TRIGGERING_ACTOR": "contributor",
                       "GITHUB_EVENT_NAME": "pull_request", "GITHUB_SHA": "f" * 40,
                       "GITHUB_WORKFLOW_SHA": "f" * 40}.items():
        with pytest.raises(ValueError):
            bridge.admit_environment(expected, {**env, key: value})


class FakeGitHub:
    def __init__(self, report):
        self.report = report
        self.writes = []
        self.stale = False
        self.fail_patch = None

    def request(self, method, path, body=None):
        if method == "GET":
            if "/pulls/" in path:
                return dict(state="closed" if self.stale else "open", merged=False,
                    head=dict(sha=self.report["head_sha"], repo=dict(full_name=bridge.REPOSITORY)),
                    base=dict(sha=self.report["base_sha"], ref="main", repo=dict(full_name=bridge.REPOSITORY)))
            return dict(tree=dict(sha=self.report["source_tree"]))
        self.writes.append((method, path, body))
        if method == "POST":
            return dict(id=len([row for row in self.writes if row[0] == "POST"]))
        if self.fail_patch == path and body.get("conclusion") == "success":
            raise ValueError("owned synthetic publication failure")
        return dict(id=int(path.rsplit("/", 1)[1]))


def test_publication_only_targets_four_exact_contexts(evidence):
    report = evidence["validate"]()
    api = FakeGitHub(report)
    ids = bridge.publish(api, report, "d" * 64, "e" * 40, "https://github.com/taipei49314/checkwash/actions/runs/1")
    posts = [body for method, _, body in api.writes if method == "POST"]
    assert ids == [1, 2, 3, 4]
    assert [body["name"] for body in posts] == list(bridge.CONTEXTS)
    assert all(body["head_sha"] == report["head_sha"] and body["status"] == "in_progress" for body in posts)
    assert len([body for method, _, body in api.writes if method == "PATCH" and body["conclusion"] == "success"]) == 4


def test_stale_pr_never_gets_success_checks(evidence):
    report = evidence["validate"]()
    api = FakeGitHub(report)
    api.stale = True
    with pytest.raises(ValueError, match="stale"):
        bridge.publish(api, report, "d" * 64, "e" * 40, "https://github.com/taipei49314/checkwash/actions/runs/1")
    assert api.writes == []


def test_partial_publication_failure_marks_created_checks_failed(evidence):
    report = evidence["validate"]()
    api = FakeGitHub(report)
    api.fail_patch = "/repos/" + bridge.REPOSITORY + "/check-runs/2"
    with pytest.raises(ValueError, match="publication failure"):
        bridge.publish(api, report, "d" * 64, "e" * 40, "https://github.com/taipei49314/checkwash/actions/runs/1")
    failures = [path for method, path, body in api.writes if method == "PATCH" and body["conclusion"] == "failure"]
    assert len(failures) == 4
