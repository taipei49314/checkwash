"""Owned frozen Git config objects; no host symlink privileges are needed."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from checkwash.change import EngineError, FileChange
from checkwash.config import Config
from checkwash.collection_inventory import collection_inventory_changes
from checkwash.gitio import list_range_changes
from checkwash.gitio import snapshot as snapshots
from checkwash.gitio.pytest_configs import PairedPytestConfigs
from checkwash.shadow import find_runtime_subject_shadows


def git(repo, *args, data=None):
    result = subprocess.run(["git", "-C", str(repo), *args], input=data,
                            capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    return result.stdout


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.name", "owned config evidence")
    git(tmp_path, "config", "user.email", "config@example.invalid")
    git(tmp_path, "config", "commit.gpgsign", "false")
    git(tmp_path, "config", "core.autocrlf", "false")
    return tmp_path


def commit(repo, files, parent=None):
    git(repo, "read-tree", "--empty")
    for path, (mode, data) in sorted(files.items()):
        oid = (data.decode("ascii") if mode == "160000"
               else git(repo, "hash-object", "-w", "--stdin", data=data).decode("ascii").strip())
        git(repo, "update-index", "--add", "--cacheinfo", f"{mode},{oid},{path}")
    tree = git(repo, "write-tree").decode("ascii").strip()
    args = ["commit-tree", tree, *(["-p", parent] if parent else [])]
    revision = git(repo, *args, data=b"owned config tree\n").decode("ascii").strip()
    git(repo, "update-ref", "refs/heads/main", revision)
    return revision


def linked(config=b"[pytest]\npythonpath = src\n"):
    return {"tests/pytest.ini": ("120000", b"../shared/config.ini"),
            "shared/config.ini": ("100644", config)}


def test_config_api_returns_exact_regular_target_and_frozen_provenance(repo):
    files = linked()
    revision = commit(repo, files)
    view = snapshots.GitSnapshot(repo, revision)
    value = view.read_config_many(["tests/pytest.ini"])["tests/pytest.ini"]
    assert value.data == files["shared/config.ini"][1]
    assert (value.path, value.revision, value.mode) == ("tests/pytest.ini", revision, b"120000")
    assert value.target_path == "shared/config.ini" and value.target_mode == b"100644"
    assert value.link_bytes == len(b"../shared/config.ini")
    assert value.oid == git(repo, "rev-parse", f"{revision}:tests/pytest.ini").strip()
    assert value.target_oid == git(repo, "rev-parse", f"{revision}:shared/config.ini").strip()
    ordinary = view.read_config_many(["shared/config.ini"])["shared/config.ini"]
    assert ordinary.data == value.data and ordinary.link_bytes == 0
    assert view.read_config_many(["absent.ini"]) == {"absent.ini": None}
    with pytest.raises(EngineError):
        view.read_many(["tests/pytest.ini"])
    with pytest.raises(EngineError):
        view.read("tests/pytest.ini")


@pytest.mark.parametrize("target", [b"", b"../../outside.ini", b"/absolute.ini", b"C:/drive.ini",
    b"\\\\server\\share", b"..\\config.ini", b"../shared/config.ini\n", b"../x\ry", b"x\0y", b"\xff",
    b"pytest.ini", b"../second.ini", b"../shared", b"../missing.ini", b"../through/../shared/config.ini",
    b"../missing/../shared/config.ini"])
def test_non_one_hop_targets_keep_refusal(repo, target):
    files = {**linked(), "tests/pytest.ini": ("120000", target),
             "second.ini": ("120000", b"shared/config.ini"),
             "through": ("120000", b"shared")}
    revision = commit(repo, files)
    with pytest.raises(EngineError) as caught:
        snapshots.GitSnapshot(repo, revision).read_config_many(["tests/pytest.ini"])
    assert "path='tests/pytest.ini'" in str(caught.value)
    assert repr(revision) in str(caught.value)
    assert "\n" not in str(caught.value) and "\r" not in str(caught.value)


def test_gitlink_target_is_not_an_optional_absence(repo):
    child = commit(repo, {"x": ("100644", b"owned\n")})
    revision = commit(repo, {"pytest.ini": ("120000", b"vendor/config.ini"),
                             "vendor": ("160000", child.encode())}, child)
    with pytest.raises(EngineError):
        snapshots.GitSnapshot(repo, revision).read_config_many(["pytest.ini"])


def test_path_components_and_unicode_are_resolved_inside_the_same_tree(repo):
    config = b"[pytest]\n"
    revision = commit(repo, {"tests/pytest.ini": ("120000", "./../共享/設定.ini".encode()),
                             "共享/設定.ini": ("100755", config)})
    value = snapshots.GitSnapshot(repo, revision).read_config_many(["tests/pytest.ini"])["tests/pytest.ini"]
    assert value.target_path == "共享/設定.ini" and value.data == config


def test_worktree_bytes_cannot_supply_a_frozen_config_target(repo):
    revision = commit(repo, linked())
    local = repo / "shared" / "config.ini"
    local.parent.mkdir()
    local.write_bytes(b"[pytest]\npythonpath=forged\n")
    value = snapshots.GitSnapshot(repo, revision).read_config_many(["tests/pytest.ini"])["tests/pytest.ini"]
    assert value.data == linked()["shared/config.ini"][1]


@pytest.mark.parametrize("broken_side", ["before", "after"])
def test_one_sides_target_absence_cannot_borrow_the_other_sides_bytes(repo, broken_side):
    valid = linked()
    missing = {"tests/pytest.ini": valid["tests/pytest.ini"]}
    base = commit(repo, missing if broken_side == "before" else valid)
    head = commit(repo, missing if broken_side == "after" else valid, base)
    with pytest.raises(EngineError, match="target is not one regular blob") as caught:
        PairedPytestConfigs(snapshots.GitSnapshot(repo, base), snapshots.GitSnapshot(repo, head)).prepare()
    assert (base if broken_side == "before" else head) in str(caught.value)


@pytest.mark.parametrize("which", ["tests/pytest.ini", "shared/config.ini"])
@pytest.mark.parametrize("fault", ["missing", "corrupt"])
def test_real_link_or_target_object_loss_is_not_absence(repo, which, fault):
    revision = commit(repo, linked())
    view = snapshots.GitSnapshot(repo, revision)
    view.list_paths()
    oid = git(repo, "rev-parse", f"{revision}:{which}").decode().strip()
    object_file = repo / ".git" / "objects" / oid[:2] / oid[2:]
    assert object_file.resolve().is_relative_to((repo / ".git" / "objects").resolve())
    object_file.chmod(0o600)
    if fault == "missing":
        object_file.unlink()
    else:
        object_file.write_bytes(b"corrupt owned object")
    with pytest.raises(EngineError):
        view.read_config_many(["tests/pytest.ini"])


@pytest.mark.parametrize("phase", [1, 2])
@pytest.mark.parametrize("fault", ["status", "header", "oid", "truncated", "content", "trailing", "timeout"])
def test_each_link_and_target_transport_phase_keeps_faults(repo, monkeypatch, phase, fault):
    revision = commit(repo, linked())
    view = snapshots.GitSnapshot(repo, revision)
    view.list_paths()
    original = snapshots._run
    seen = 0

    def inject(repo, args, **kwargs):
        nonlocal seen
        if args != ["cat-file", "--batch"]:
            return original(repo, args, **kwargs)
        seen += 1
        raw = original(repo, args, **kwargs)
        if seen != phase:
            return raw
        if fault in {"status", "timeout"}:
            def failed(command, **options):
                if fault == "timeout":
                    raise subprocess.TimeoutExpired(command, options["timeout"], output=b"partial")
                return subprocess.CompletedProcess(command, 7, b"", b"owned Git error")
            with monkeypatch.context() as scoped:
                scoped.setattr(snapshots.subprocess, "run", failed)
                return original(repo, args, **kwargs)
        header, _, body = raw.partition(b"\n")
        return {"header": raw.replace(b" blob ", b" tree ", 1),
                "oid": b"0" * len(header.split()[0]) + raw[len(header.split()[0]):],
                "truncated": raw[:-1], "content": header + b"\nX" + body[1:],
                "trailing": raw + b"extra"}[fault]

    monkeypatch.setattr(snapshots, "_run", inject)
    with pytest.raises(EngineError) as caught:
        view.read_config_many(["tests/pytest.ini"])
    assert seen == phase
    assert "tests/pytest.ini" in str(caught.value) and revision in str(caught.value)


def test_aliases_pay_logical_target_bytes_even_with_one_target_oid(repo, monkeypatch):
    payload = b"#" + b"x" * 39
    revision = commit(repo, {"pytest.ini": ("120000", b"shared.ini"),
                             "tests/pytest.ini": ("120000", b"../shared.ini"),
                             "shared.ini": ("100644", payload)})
    monkeypatch.setattr(snapshots, "MAX_BATCH_BYTES", 80)
    view = snapshots.GitSnapshot(repo, revision)
    assert view.read_config_many(["pytest.ini"])["pytest.ini"].data == payload
    with pytest.raises(EngineError, match="config batch exceeds the byte limit"):
        view.read_config_many(["pytest.ini", "tests/pytest.ini"])


@pytest.mark.parametrize("size,readable", [(1_000_000, True), (1_000_001, False)])
def test_target_byte_boundary_does_not_expand(repo, size, readable):
    revision = commit(repo, linked(b"#" + b"x" * (size - 1)))
    view = snapshots.GitSnapshot(repo, revision)
    if readable:
        assert len(view.read_config_many(["tests/pytest.ini"])["tests/pytest.ini"].data) == size
    else:
        with pytest.raises(EngineError, match="target exceeds the byte limit"):
            view.read_config_many(["tests/pytest.ini"])


def test_a_moving_ref_cannot_mix_target_versions(repo):
    base = commit(repo, linked(b"[pytest]\npythonpath=old\n"))
    view = snapshots.GitSnapshot(repo, "HEAD")
    view.list_paths()
    head = commit(repo, linked(b"[pytest]\npythonpath=new\n"), base)
    value = view.read_config_many(["tests/pytest.ini"])["tests/pytest.ini"]
    assert value.revision == base and b"old" in value.data
    assert b"new" in snapshots.GitSnapshot(repo, head).read_config_many(["tests/pytest.ini"])["tests/pytest.ini"].data


def test_preflight_does_not_index_every_symlink(repo):
    files = {"unrelated.link": ("120000", b"../../outside"),
             "pytest.ini": ("120000", b"shared/settings.txt"),
             "shared/settings.txt": ("100644", b"[pytest]\n")}
    base = commit(repo, files)
    head = commit(repo, {**files, "ordinary.txt": ("100644", b"changed\n")}, base)
    evidence = PairedPytestConfigs(snapshots.GitSnapshot(repo, base),
                                   snapshots.GitSnapshot(repo, head)).prepare()
    assert evidence.changes == {}
    assert "unrelated.link" not in evidence.records["before"]
    assert "unrelated.link" not in evidence.records["after"]
    with pytest.raises(EngineError, match="unregistered request"):
        evidence.read("after", ["unrelated.link"])


def subject_tree(config=b"[pytest]\npythonpath = src\n"):
    return {"pytest.ini": ("120000", b"settings/current.txt"),
            "settings/current.txt": ("100644", config),
            "src/billing.py": ("100644", b"def total():\n    return 1\n"),
            "shadow/billing.py": ("100644", b"def total():\n    return 3\n"),
            "tests/test_total.py": ("100644", b"from billing import total\ndef test_total():\n    assert total() == 3\n")}


def paired(repo, before, after):
    base = commit(repo, before)
    head = commit(repo, after, base)
    old, new = snapshots.GitSnapshot(repo, base), snapshots.GitSnapshot(repo, head)
    evidence = PairedPytestConfigs(old, new).prepare()
    changes = list_range_changes(str(repo), base, head)
    return base, head, new, evidence, changes


def shadows(changes, view, evidence=None):
    return find_runtime_subject_shadows(changes, Config(), head_path_lister=view.list_paths,
                                        head_batch_reader=view.read_many, config_evidence=evidence)


def collection(changes, view, evidence=None):
    return collection_inventory_changes(changes, Config(), path_lister=view.list_paths,
                                        batch_reader=view.read_many, config_evidence=evidence)


@pytest.mark.parametrize("explicit_root_command", [False, True])
def test_target_only_pythonpath_change_reaches_shadow_before_relevance_return(repo, explicit_root_command):
    before = subject_tree()
    after = subject_tree(b"[pytest]\npythonpath = shadow src\n")
    if explicit_root_command:
        before["run.sh"] = after["run.sh"] = ("100644", b"pytest -c pytest.ini tests/\n")
    base, head, view, evidence, changes = paired(repo, before, after)
    assert [change.path for change in changes] == ["settings/current.txt"]
    assert shadows(changes, view) == []  # the old gate cannot see a logical config delta
    hits = shadows(changes, view, evidence)
    assert [(hit.before_provider, hit.after_provider, hit.test_path) for hit in hits] == [
        ("src/billing.py", "shadow/billing.py", "tests/test_total.py")]
    assert "pytest.ini" in hits[0].control_paths
    assert evidence.records["before"]["pytest.ini"].revision == base
    assert evidence.records["after"]["pytest.ini"].revision == head
    assert changes[0].before == before["settings/current.txt"][1]


def collection_tree(config=b"[pytest]\n"):
    return {"pytest.ini": ("120000", b"settings/current.txt"),
            "settings/current.txt": ("100644", config),
            "tests/test_slow.py": ("100644", b"import pytest\n@pytest.mark.slow\ndef test_slow():\n    assert 1 == 1\n"),
            "tests/test_fast.py": ("100644", b"def test_fast():\n    assert 2 == 2\n")}


def test_target_only_collection_change_reaches_root_touched_gate(repo):
    before = collection_tree()
    after = collection_tree(b"[pytest]\naddopts = -m 'not slow'\n")
    _base, _head, view, evidence, changes = paired(repo, before, after)
    assert [change.path for change in changes] == ["settings/current.txt"]
    assert collection(changes, view) == []
    assert collection(changes, view, evidence) == [
        ("pytest.ini", "resolved pytest collection option introduced: -m not slow")]


@pytest.mark.parametrize("fault", ["missing", "duplicate", "wrong_bytes", "wrong_old_path"])
def test_alias_report_requires_a_unique_actual_physical_change(repo, fault):
    before, after = collection_tree(), collection_tree(b"[pytest]\naddopts=-m 'not slow'\n")
    _base, _head, _view, evidence, changes = paired(repo, before, after)
    original = changes[0]
    supplied = {"missing": [], "duplicate": [original, original],
                "wrong_bytes": [FileChange(original.path, "modified", b"forged", original.after)],
                "wrong_old_path": [FileChange(original.path, "modified", original.before, original.after,
                                                old_path="different/config.txt")]}[fault]
    with pytest.raises(EngineError, match="no unique physical changed source"):
        evidence.reported_change("pytest.ini", supplied)


@pytest.mark.parametrize("kind", ["identical", "comment"])
def test_target_bytes_without_effective_settings_change_do_not_create_findings(repo, kind):
    before = subject_tree()
    after = dict(before)
    if kind == "identical":
        after["note.txt"] = ("100644", b"ordinary prose\n")
    else:
        after["settings/current.txt"] = ("100644", before["settings/current.txt"][1] + b"# explanation\n")
    _base, _head, view, evidence, changes = paired(repo, before, after)
    assert bool(evidence.changes) == (kind == "comment")
    assert shadows(changes, view, evidence) == []
    assert collection(changes, view, evidence) == []


def test_known_case_shape_unchanged_nested_alias_reads_config_not_python_alias(repo):
    # Owned minimal analogue; no downloaded corpus or held-out source.
    before = {"requirements/pyproject.toml": ("120000", b"../pyproject.toml"),
              "pyproject.toml": ("100644", b"[project]\nname='owned'\nversion='0.0.0'\n"),
              "requirements/sync.py": ("100644", b"VALUE = 1\n"),
              "setup.cfg": ("100644", b"[tool:pytest]\npythonpath=src\n"),
              "src/billing.py": ("100644", b"def total(): return 1\n"),
              "tests/test_total.py": ("100644", b"from billing import total\ndef test_total():\n    assert total() == 1\n")}
    after = {**before, "setup.cfg": ("100644", b"[metadata]\nname=owned\n"),
             "pytest.ini": ("100644", b"[pytest]\npythonpath=src\n")}
    _base, _head, view, evidence, changes = paired(repo, before, after)
    assert "requirements/pyproject.toml" not in evidence.changes
    with pytest.raises(EngineError):
        shadows(changes, view)
    assert shadows(changes, view, evidence) == []
    assert collection(changes, view, evidence) == []


def test_recognized_relative_config_uses_logical_directory_not_target_directory(repo):
    before = subject_tree()
    before.pop("pytest.ini")
    before.pop("settings/current.txt")
    before["tests/pytest.ini"] = ("120000", b"../deep/data/current.txt")
    before["deep/data/current.txt"] = ("100644", b"[pytest]\npythonpath=../src\n")
    after = {**before, "deep/data/current.txt": ("100644", b"[pytest]\npythonpath=../shadow ../src\n")}
    _base, _head, view, evidence, changes = paired(repo, before, after)
    hits = shadows(changes, view, evidence)
    assert [(hit.before_provider, hit.after_provider) for hit in hits] == [("src/billing.py", "shadow/billing.py")]
    assert "tests/pytest.ini" in hits[0].control_paths


CUSTOM_CWD = {
    "root": ("run.sh", b"pytest -c 'custom config' tests/\n", "custom config"),
    "cd": ("run.sh", b"cd sub && pytest -c 'custom config' tests/\n", "sub/custom config"),
    "working-directory": (".github/workflows/test.yml",
        b"name: owned\non: [push]\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n"
        b"      - run: pytest -c 'custom config' tests/\n        working-directory: sub\n",
        "sub/custom config"),
}


@pytest.mark.parametrize("cwd", sorted(CUSTOM_CWD))
def test_custom_cwd_is_not_inferred_by_preflight_or_used_for_new_missing_guard(repo, monkeypatch, cwd):
    runner, command, custom_path = CUSTOM_CWD[cwd]
    before = {runner: ("100644", command), custom_path: ("100644", b"[pytest]\n"),
              "note.txt": ("100644", b"old\n")}
    base = commit(repo, before)
    head = commit(repo, {**before, "note.txt": ("100644", b"new\n")}, base)
    old, new = snapshots.GitSnapshot(repo, base), snapshots.GitSnapshot(repo, head)
    reads = []
    original = snapshots.GitSnapshot.read_many

    def spy(self, paths):
        selected = list(paths)
        reads.append((self.revision, selected))
        return original(self, selected)

    monkeypatch.setattr(snapshots.GitSnapshot, "read_many", spy)
    evidence = PairedPytestConfigs(old, new).prepare()
    assert reads == []  # preflight never interprets a command or reads its custom request
    assert evidence.requests == {"before": set(), "after": set()}
    with pytest.raises(EngineError, match="unregistered request"):
        evidence.read("after", [custom_path])
    result = cli(repo, base, head)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert json.loads(result.stdout)["verdict"] == "pass"


@pytest.mark.parametrize("side", ["before", "after"])
def test_unproven_custom_missing_request_keeps_original_consumer_behavior(repo, side):
    normal = {"note.txt": ("100644", b"owned\n")}
    requested = {**normal, "scripts/run.sh": ("100644", b"pytest -c 'custom config' tests/\n")}
    old, new = (requested, normal) if side == "before" else (normal, requested)
    _base, _head, view, evidence, changes = paired(repo, old, new)
    assert "custom config" not in evidence.requests["before"] | evidence.requests["after"]
    # Differential consumer control, not a claim that an absent config is valid.
    assert shadows(changes, view, evidence) == shadows(changes, view)
    assert collection(changes, view, evidence) == collection(changes, view)


def test_custom_symlink_is_not_granted_config_read_capability(repo):
    before = {"run.sh": ("100644", b"pytest -c 'custom config' tests/\n"),
              "custom config": ("120000", b"shared/settings.txt"),
              "shared/settings.txt": ("100644", b"[pytest]\n"),
              "note.txt": ("100644", b"old\n")}
    _base, _head, view, evidence, _changes = paired(repo, before, {**before, "note.txt": ("100644", b"new\n")})
    assert evidence.requests == {"before": set(), "after": set()}
    with pytest.raises(EngineError, match="unregistered request"):
        evidence.read("after", ["custom config"])
    with pytest.raises(EngineError, match="nonregular"):
        view.read_many(["custom config"])


def test_nonrecognized_config_falls_back_to_original_source_instead_of_fake_absence(repo):
    before = subject_tree()
    before.pop("settings/current.txt")
    before["pytest.ini"] = ("100644", b"[pytest]\npythonpath=src\n")
    before["custom-config"] = ("100644", b"[pytest]\npythonpath=src\n")
    before["run.sh"] = ("100644", b"pytest -c custom-config tests/\n")
    after = {**before, "pytest.ini": ("100644", b"[pytest]\npythonpath=shadow src\n"),
             "custom-config": ("100644", b"[pytest]\npythonpath=shadow src\n")}
    _base, _head, view, evidence, changes = paired(repo, before, after)
    original = shadows(changes, view)
    assert original  # a positive original-consumer control, not empty == empty
    assert [(hit.before_provider, hit.after_provider) for hit in original] == [("src/billing.py", "shadow/billing.py")]
    assert shadows(changes, view, evidence) == original
    assert "custom-config" not in evidence.requests["after"]


def test_generic_python_alias_remains_rejected_during_shadow_analysis(repo):
    before = subject_tree()
    before["tests/alias.py"] = ("120000", b"test_total.py")
    after = {**before, "settings/current.txt": ("100644", b"[pytest]\npythonpath=shadow src\n")}
    _base, _head, view, evidence, changes = paired(repo, before, after)
    with pytest.raises(EngineError, match="nonregular"):
        shadows(changes, view, evidence)


def cli(repo, base, head, format="json"):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    return subprocess.run([sys.executable, "-m", "checkwash", "check", "--repo", str(repo),
                           f"{base}..{head}", "--format", format],
                          env=env, capture_output=True, timeout=60)


@pytest.mark.parametrize("narrow,exit_code", [(False, 0), (True, 1)])
def test_cli_target_only_config_range_preserves_native_verdict(repo, narrow, exit_code):
    before = collection_tree()
    after = collection_tree(b"[pytest]\naddopts = -m 'not slow'\n" if narrow else b"[pytest]\n# prose\n")
    base = commit(repo, before)
    head = commit(repo, after, base)
    result = cli(repo, base, head)
    assert result.returncode == exit_code, (result.stdout, result.stderr)
    receipt = json.loads(result.stdout)
    assert receipt["verdict"] == ("block" if narrow else "pass")
    if narrow:
        finding = next(item for item in receipt["findings"] if item["rule"] == "CI_WORKFLOW_TOUCHED")
        assert finding["path"] == "settings/current.txt" and finding["severity"] == "high"
        assert finding["after"]["span"] == [0, 0]  # explanatory context, not a forged source line
        assert_source_context(repo, base, head, finding["after"]["text"])


def assert_source_context(repo, base, head, text):
    assert "logical pytest config 'pytest.ini'" in text
    for side, ref in (("before", base), ("head", head)):
        oid = git(repo, "rev-parse", f"{ref}:settings/current.txt").decode().strip()
        assert f"{side} target='settings/current.txt' blob={oid}" in text
        assert git(repo, "cat-file", "blob", f"{ref}:pytest.ini") == b"settings/current.txt"
        assert git(repo, "cat-file", "blob", oid).startswith(b"[pytest]\n")


@pytest.mark.parametrize("kind", ["collection", "shadow"])
def test_cli_alias_evidence_sarif_is_physical_and_has_no_invented_region(repo, kind):
    if kind == "collection":
        before, after = collection_tree(), collection_tree(b"[pytest]\naddopts=-m 'not slow'\n")
        rule = "CI_WORKFLOW_TOUCHED"
    else:
        before, after = subject_tree(), subject_tree(b"[pytest]\npythonpath=shadow src\n")
        rule = "TEST_PATCHES_SUBJECT"
    base = commit(repo, before)
    head = commit(repo, after, base)
    result = cli(repo, base, head, "sarif")
    assert result.returncode == 1, (result.stdout, result.stderr)
    finding = next(item for item in json.loads(result.stdout)["runs"][0]["results"] if item["ruleId"] == rule)
    physical = finding["locations"][0]["physicalLocation"]
    assert physical == {"artifactLocation": {"uri": "settings/current.txt"}}
    text = finding["properties"]["checkwash.evidenceText"] if kind == "collection" else finding["message"]["text"]
    assert_source_context(repo, base, head, text)


def test_target_config_fingerprint_does_not_depend_on_commit_labels(repo):
    before, after = collection_tree(), collection_tree(b"[pytest]\naddopts=-m 'not slow'\n")
    base = commit(repo, before)
    head = commit(repo, after, base)
    other_base = commit(repo, before, head)
    other_head = commit(repo, after, other_base)
    fingerprints = []
    for old, new in ((base, head), (other_base, other_head)):
        result = cli(repo, old, new)
        assert result.returncode == 1, (result.stdout, result.stderr)
        finding = next(item for item in json.loads(result.stdout)["findings"] if item["rule"] == "CI_WORKFLOW_TOUCHED")
        fingerprints.append(finding["fingerprint"])
    assert base != other_base and head != other_head and fingerprints[0] == fingerprints[1]


def test_cli_invalid_unchanged_config_target_returns_existing_error_exit(repo):
    files = {"pytest.ini": ("120000", b"../outside.ini"),
             "note.txt": ("100644", b"old\n")}
    base = commit(repo, files)
    head = commit(repo, {**files, "note.txt": ("100644", b"new\n")}, base)
    result = cli(repo, base, head)
    assert result.returncode == 2
    assert b"pytest.ini" in result.stderr and (base.encode() in result.stderr or head.encode() in result.stderr)
    assert not result.stdout


def test_changed_link_still_fails_before_config_preflight(repo):
    before = collection_tree()
    after = {**before, "pytest.ini": ("120000", b"settings/other.txt"),
             "settings/other.txt": ("100644", b"[pytest]\n")}
    base = commit(repo, before)
    head = commit(repo, after, base)
    result = cli(repo, base, head)
    assert result.returncode == 2
    assert not result.stdout


class MemoryConfigTree:
    """Owned regular blobs for consumer accounting, not a Git transport mock.

    Transport/symlink refusal is covered by the actual Git tests above. This
    reader avoids creating thousands of Git objects merely to add inert data.
    """

    def __init__(self, files, revision):
        self.files = files
        self.revision = revision
        self.ordinary_requests = []
        self._tree_entries = {
            path: (b"100644", hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest().encode(), len(data))
            for path, data in files.items()
        }

    def list_paths(self):
        return sorted(self.files)

    def read_many(self, paths):
        self.ordinary_requests.append(tuple(paths))
        return {path: self.files.get(path) for path in paths}

    def read_config_many(self, paths):
        return {path: (snapshots.ConfigSource(
            path, self.revision, b"100644", self._tree_entries[path][1], self.files[path],
            path, b"100644", self._tree_entries[path][1]) if path in self.files else None)
                for path in paths}


def memory_pair(before, after):
    old, new = MemoryConfigTree(before, "a" * 40), MemoryConfigTree(after, "b" * 40)
    evidence = PairedPytestConfigs(old, new).prepare()
    changes = [FileChange(path, "added" if path not in before else "deleted" if path not in after else "modified",
                          before.get(path), after.get(path))
               for path in sorted(before.keys() | after.keys()) if before.get(path) != after.get(path)]
    return new, evidence, changes


def test_shadow_then_collection_ignores_unrelated_changed_data_in_collection_budget():
    before = {"pytest.ini": b"[pytest]\npythonpath=src\n",
              "src/billing.py": b"def total():\n    return 1\n",
              "shadow/billing.py": b"def total():\n    return 3\n",
              "tests/test_total.py": (b"import pytest\nfrom billing import total\n"
                                      b"@pytest.mark.slow\ndef test_total():\n    assert total() == 3\n")}
    after = {**before, "pytest.ini": b"[pytest]\npythonpath=shadow src\naddopts=-m 'not slow'\n"}
    view, evidence, changes = memory_pair(before, after)
    expected_shadows = shadows(changes, view, evidence)
    expected_collection = collection(changes, view, evidence)
    assert [(hit.before_provider, hit.after_provider) for hit in expected_shadows] == [
        ("src/billing.py", "shadow/billing.py")]
    assert expected_collection == [("pytest.ini", "resolved pytest collection option introduced: -m not slow")]

    inert = {f"data/owned-{index:04d}.txt": b"owned\n" for index in range(4097)}
    view, evidence, changes = memory_pair(before, {**after, **inert})
    # Same context and actual engine consumer order. The old draft charged
    # these 4097 changed bytes in shadow, then rejected collection's tiny set.
    assert shadows(changes, view, evidence) == expected_shadows
    assert collection(changes, view, evidence) == expected_collection
    assert not set(inert).intersection(path for batch in view.ordinary_requests for path in batch)


def test_collection_own_selected_source_limit_still_refuses():
    before = {"pytest.ini": b"[pytest]\n"}
    before.update({f"tests/test_{index:04d}.py": b"def test_one():\n    assert 1\n" for index in range(4096)})
    after = {**before, "pytest.ini": b"[pytest]\naddopts=-m 'not slow'\n"}
    view, evidence, changes = memory_pair(before, after)
    with pytest.raises(EngineError, match="collection snapshot exceeds the source read limit"):
        collection(changes, view, evidence)
    assert not view.ordinary_requests  # Admission precedes the oversized read.


@pytest.mark.parametrize("remaining", [0, -1], ids=["exact-combined-boundary", "combined-overflow"])
def test_collection_split_config_and_ordinary_bytes_share_original_head_budget(monkeypatch, remaining):
    from checkwash import collection_inventory as consumer

    before = {"pytest.ini": b"[pytest]\n",
              "tests/test_slow.py": b"import pytest\n@pytest.mark.slow\ndef test_slow():\n    assert 1\n"}
    after = {**before, "pytest.ini": b"[pytest]\naddopts=-m 'not slow'\n"}
    budget = sum(map(len, after.values())) + remaining
    assert max(map(len, after.values())) < budget  # Both independent halves fit.
    monkeypatch.setattr(consumer, "MAX_BATCH_BYTES", budget)
    view, evidence, changes = memory_pair(before, after)
    if remaining:
        with pytest.raises(EngineError, match="collection snapshot exceeds the source byte limit"):
            collection(changes, view, evidence)
    else:
        assert collection(changes, view, evidence) == [
            ("pytest.ini", "resolved pytest collection option introduced: -m not slow")]


@pytest.mark.parametrize("remaining", [0, -1], ids=["exact-combined-boundary", "combined-overflow"])
def test_shadow_initial_split_batch_preserves_its_original_byte_budget(monkeypatch, remaining):
    from checkwash import shadow as consumer

    before = {"pytest.ini": b"[pytest]\npythonpath=shadow src\n",
              "src/billing.py": b"def total():\n    return 1\n",
              "tests/test_total.py": b"from billing import total\ndef test_total():\n    assert total() == 3\n"}
    after = {**before, "shadow/billing.py": b"def total():\n    return 3\n"}
    # The unchanged config belongs to the original initial read batch. The
    # provider is a later separate read; do not invent a combined global cap.
    initial = (after["pytest.ini"], after["tests/test_total.py"])
    budget = sum(map(len, initial)) + remaining
    assert max(map(len, initial)) < budget
    monkeypatch.setattr(consumer, "MAX_BATCH_BYTES", budget)
    view, evidence, changes = memory_pair(before, after)
    if remaining:
        with pytest.raises(EngineError, match="runtime-shadow initial snapshot exceeds the source byte limit"):
            shadows(changes, view, evidence)
    else:
        assert [(hit.before_provider, hit.after_provider) for hit in shadows(changes, view, evidence)] == [
            ("src/billing.py", "shadow/billing.py")]
