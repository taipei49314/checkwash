"""A reviewed transition report cannot waive or hide legacy byte drift."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location(
    "compare_quality_legacy", Path(__file__).parents[1] / "tools/compare_quality_legacy.py")
compare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compare)


def artifact(version="0.3.3", *, names=("a.gwcase",), optional=False, verdict="pass"):
    parts = []
    for name in names:
        findings = {"checkwash_findings_version": 2, "findings": [], "summary": {"high": 0},
                    "run": {"checkwash_version": version}, "verdict": verdict}
        ir = {"version": 2, "files": [], "globals": {"optional": False} if optional else {}}
        parts.append("# " + name + "\n" + json.dumps(findings) + "\n" + json.dumps(ir) + "\n")
    return "".join(parts).encode()


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, check=True)


def commit(root):
    git(root, "add", ".")
    git(root, "-c", "user.name=Transition Test", "-c", "user.email=test@example.invalid",
        "commit", "-qm", "fixture")


def repository(root, *, candidate=False):
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "core.autocrlf", "false")
    files = {"src/engine.py": b"value = 2\n" if candidate else b"value = 1\n",
             "tools/emit_corpus.py": b"# fixture emitter\n",
             "pyproject.toml": b'[project]\nversion = "0.4.0"\n',
             "tests/cases/a.gwcase": b"immutable fixture\n",
             "docs/review.md": b"Synthetic review used only by this test.\n"}
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    commit(root)
    return root


@pytest.fixture(scope="module")
def context(tmp_path_factory):
    directory = tmp_path_factory.mktemp("transition-repositories")
    roots = {side: repository(directory / side, candidate=side == "candidate")
             for side in ("baseline", "candidate")}
    evidence = {side: compare.source_evidence(root) for side, root in roots.items()}
    return roots, evidence


@pytest.fixture
def transition(context):
    roots, evidence = context
    outputs = {"baseline": artifact(), "candidate": artifact("0.4.0", optional=True)}
    _, deltas = compare.transition_deltas(outputs)
    record = {"schema_version": 2, "baseline": compare.BASELINE, "release_version": "0.4.0",
              "review": {"path": "docs/review.md", "sha256": compare._sha((roots["candidate"] / "docs/review.md").read_bytes())},
              "sha256": {side: compare._sha(data) for side, data in outputs.items()},
              "source_sha256": {side: data["source_sha256"] for side, data in evidence.items()},
              "corpus": {side: data["corpus"] for side, data in evidence.items()},
              "deltas": [{**delta, "reason": "Synthetic test review of this exact change."} for delta in deltas]}
    return outputs, copy.deepcopy(record), copy.deepcopy(evidence), roots["candidate"]


def qualify(transition):
    outputs, record, evidence, root = transition
    return compare.qualify_release_record(record, outputs, "0.4.0", evidence, root)


def test_exact_transition_is_independently_qualified(transition):
    result = qualify(transition)
    assert result["qualified"] is True
    assert result["delta_count"] == 2
    assert {delta["category"] for delta in transition[1]["deltas"]} == {"version", "ir_field_added"}


@pytest.mark.parametrize("side", ["baseline", "candidate"])
def test_single_byte_artifact_drift_is_rejected(transition, side):
    transition[0][side] += b"\n"
    with pytest.raises(ValueError, match="identity mismatch"):
        qualify(transition)


@pytest.mark.parametrize("field,value", [
    ("schema_version", True), ("schema_version", 1), ("baseline", "other"),
    ("release_version", "0.3.4"), ("review", ""), ("sha256", {"candidate": "*"}),
])
def test_malformed_or_wrong_version_record_is_rejected(transition, field, value):
    transition[1][field] = value
    with pytest.raises(ValueError):
        qualify(transition)


def test_unknown_fields_cannot_define_an_ignore_list(transition):
    transition[1]["ignore_paths"] = ["/findings"]
    with pytest.raises(ValueError, match="unknown fields"):
        qualify(transition)


@pytest.mark.parametrize("malformation", ["empty", "dropped", "duplicate", "missing_ir", "extra_json", "trailing", "duplicate_key", "nonfinite"])
def test_malformed_corpus_rejected_even_with_updated_hash(transition, malformation):
    outputs, record, evidence, root = transition
    data = outputs["candidate"]
    malformed = {
        "empty": b"", "dropped": artifact("0.4.0", names=("different.gwcase",)),
        "duplicate": data + data, "missing_ir": data[:data.rfind(b"\n{")],
        "extra_json": data + b"{}\n", "trailing": data + b"garbage\n",
        "duplicate_key": data.replace(b'"version": 2', b'"version": 2, "version": 2'),
        "nonfinite": data.replace(b'"optional": false', b'"optional": NaN'),
    }[malformation]
    outputs["candidate"] = malformed
    record["sha256"]["candidate"] = compare._sha(malformed)
    with pytest.raises(ValueError):
        qualify(transition)


def test_corpus_artifact_must_match_complete_source_inventory(transition):
    outputs, record, evidence, root = transition
    evidence["candidate"]["corpus"]["omitted.gwcase"] = "a" * 64
    record["corpus"]["candidate"] = evidence["candidate"]["corpus"]
    with pytest.raises(ValueError, match="identity mismatch"):
        qualify(transition)


def test_existing_fixture_bytes_cannot_be_relabelled_as_reviewed(transition):
    outputs, record, evidence, root = transition
    evidence["candidate"]["corpus"]["a.gwcase"] = "a" * 64
    record["corpus"]["candidate"] = evidence["candidate"]["corpus"]
    with pytest.raises(ValueError, match="immutable baseline"):
        qualify(transition)


def test_added_case_requires_manifest_identity_and_full_json_delta(transition):
    outputs, record, evidence, root = transition
    outputs["candidate"] = artifact("0.4.0", names=("a.gwcase", "new.gwcase"), optional=True)
    evidence["candidate"]["corpus"]["new.gwcase"] = "b" * 64
    record["corpus"]["candidate"] = evidence["candidate"]["corpus"]
    record["sha256"]["candidate"] = compare._sha(outputs["candidate"])
    with pytest.raises(ValueError, match="delta manifest"):
        qualify(transition)
    _, deltas = compare.transition_deltas(outputs)
    record["deltas"] = [{**delta, "reason": "Reviewed synthetic addition."} for delta in deltas]
    assert qualify(transition)["delta_count"] == 4
    assert [d["category"] for d in deltas].count("case_added") == 2


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "reordered", "value", "category", "reason", "extra"])
def test_delta_manifest_is_exact_typed_and_reviewed(transition, mutation):
    deltas = transition[1]["deltas"]
    if mutation == "missing":
        deltas.pop()
    elif mutation == "duplicate":
        deltas.append(copy.deepcopy(deltas[0]))
    elif mutation == "reordered":
        deltas.reverse()
    elif mutation == "value":
        deltas[1]["after"]["value"] = 0  # false and 0 must not compare equal
    elif mutation == "category":
        deltas[0]["category"] = "ignored"
    elif mutation == "reason":
        deltas[0]["reason"] = " "
    else:
        deltas[0]["ignore"] = True
    with pytest.raises(ValueError):
        qualify(transition)


def test_behavior_drift_cannot_hide_among_version_and_optional_fields(transition):
    outputs, record, evidence, root = transition
    outputs["candidate"] = artifact("0.4.0", optional=True, verdict="block")
    record["sha256"]["candidate"] = compare._sha(outputs["candidate"])
    with pytest.raises(ValueError, match="delta manifest"):
        qualify(transition)
    _, deltas = compare.transition_deltas(outputs)
    assert any(d["path"] == "/verdict" and d["category"] == "behavior" for d in deltas)


@pytest.mark.parametrize("change", ["source", "missing_review", "wrong_review", "outside_review", "untracked_review"])
def test_source_and_review_identity_are_required(transition, tmp_path, change):
    outputs, record, evidence, root = transition
    if change == "source":
        evidence["candidate"]["source_sha256"] = "c" * 64
    elif change == "missing_review":
        record["review"]["path"] = "docs/missing.md"
    elif change == "wrong_review":
        record["review"]["sha256"] = "c" * 64
    elif change == "outside_review":
        record["review"]["path"] = "../review.md"
    else:
        unknown = root / "untracked-review.md"
        unknown.write_text("Untracked review", encoding="utf-8")
        record["review"]["path"] = unknown.name
        record["review"]["sha256"] = compare._sha(unknown.read_bytes())
    try:
        with pytest.raises((ValueError, OSError, subprocess.CalledProcessError)):
            qualify(transition)
    finally:
        if change == "untracked_review":
            unknown.unlink()


def test_source_evidence_rejects_dirty_or_untracked_sources(tmp_path):
    root = repository(tmp_path / "repo")
    before = compare.source_evidence(root)
    (root / "src/engine.py").write_bytes(b"changed\n")
    with pytest.raises(ValueError, match="clean checkout"):
        compare.source_evidence(root)
    commit(root)
    assert compare.source_evidence(root)["source_sha256"] != before["source_sha256"]
    (root / "src/untracked.py").write_bytes(b"new\n")
    with pytest.raises(ValueError, match="clean checkout"):
        compare.source_evidence(root)


def test_output_exclusion_cannot_hide_dirty_sources(tmp_path):
    root = repository(tmp_path / "repo")
    output = root / "quality-evidence"
    output.mkdir()
    (output / "receipt.json").write_text("{}", encoding="utf-8")
    assert compare.source_evidence(root, output)["corpus"] == {"a.gwcase": compare._sha(b"immutable fixture\n")}
    with pytest.raises(ValueError, match="overlaps"):
        compare.source_evidence(root, root / "src")
    with pytest.raises(ValueError, match="overlaps"):
        compare.source_evidence(root, root)


def test_json_pointer_keys_are_unambiguous_and_null_differs_from_absence():
    old = artifact()
    new = artifact(optional=True).replace(b'"optional": false', b'"a/b~c": null')
    _, deltas = compare.transition_deltas({"baseline": old, "candidate": new})
    assert deltas == [{"case": "a.gwcase", "artifact": "ir", "path": "/globals/a~1b~0c", "category": "ir_field_added",
                       "before": {"present": False}, "after": {"present": True, "value": None}}]


def test_serialization_only_difference_is_explicit():
    baseline = artifact()
    _, deltas = compare.transition_deltas({"baseline": baseline, "candidate": baseline + b"\n"})
    assert len(deltas) == 1 and deltas[0]["category"] == "serialization"


@pytest.mark.parametrize("identical,requested,valid,expected_exit", [
    (True, False, False, 0), (False, False, False, 1),
    (False, True, True, 1), (False, True, False, 1), (True, True, False, 1),
])
def test_cli_never_waives_raw_byte_gate_and_always_retains_receipt(
        monkeypatch, tmp_path, identical, requested, valid, expected_exit):
    root = tmp_path / "repo"
    (root / "tools").mkdir(parents=True)
    (root / "pyproject.toml").write_text('[project]\nversion="0.4.0"\n', encoding="utf-8")
    monkeypatch.setattr(compare, "__file__", str(root / "tools/compare_quality_legacy.py"))
    outputs = {"baseline": artifact(), "candidate": artifact() if identical else artifact("0.4.0")}
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if len(command) == 2 and str(command[1]).endswith("emit_corpus.py"):
            side = "candidate" if kwargs["cwd"] == root else "baseline"
            return SimpleNamespace(stdout=outputs[side])
        return SimpleNamespace(stdout=b"")

    monkeypatch.setattr(compare.subprocess, "run", run)
    monkeypatch.setattr(compare, "source_evidence", lambda *_: {"source_sha256": "a" * 64, "corpus": {}, "revision": "commit"})
    def qualification(*_):
        if not valid:
            raise ValueError("unreviewed difference")
        return {"qualified": True, "delta_count": 1}
    monkeypatch.setattr(compare, "qualify_release_record", qualification)
    output = tmp_path / "evidence"
    args = ["--output", str(output)]
    if requested:
        record = tmp_path / "record.json"
        record.write_text("{}", encoding="utf-8")
        args += ["--release-record", str(record)]
    assert compare.main(args) == expected_exit
    receipt = json.loads((output / "legacy-comparison.json").read_text(encoding="utf-8"))
    assert receipt["byte_identical"] is identical
    assert receipt["byte_comparison_status"] == ("pass" if identical else "fail")
    assert receipt["transition_qualification"]["qualified"] is (requested and valid)
    assert (output / "legacy-baseline.json").read_bytes() == outputs["baseline"]
    assert (output / "legacy-candidate.json").read_bytes() == outputs["candidate"]
    observed = json.loads((output / "legacy-observed-transition.json").read_text(encoding="utf-8"))
    assert observed["status"] == "unreviewed"
    assert observed["case_counts"] == {"baseline": 1, "candidate": 1}
    assert len(observed["deltas"]) == (0 if identical else 1)
    assert any(command[:3] == ["git", "worktree", "remove"] for command in calls)
