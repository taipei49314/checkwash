"""D179 migrations preserve old programs and keep lost obligations blocking."""
import datetime
import hashlib
import json
from pathlib import Path

import pytest

from checkwash.cases import case_policy_base, case_snapshot, case_to_changes, parse_case
from checkwash.config import Config
from checkwash.contract import Contract, parse_contract
from checkwash.engine import FileChange, analyze
from checkwash.gitio.snapshot import search_source_mapping
from checkwash.pyenv import known_baseline

ROOT = Path(__file__).resolve().parents[1]
LEDGER = json.loads((ROOT / "tests/compatibility/v010/dispositions.json").read_text(encoding="utf-8"))
GOLDEN = [row for row in LEDGER["cases"] if row["family"] == "golden"]
CORPUS = [row for row in LEDGER["cases"] if row["family"] != "golden"]
FORBIDDEN = {"ASSERTION_MOVED", "RESTRUCTURED", "SPLIT_OR_RENAMED", "DUPLICATE_REMAINS"}


def _input_identity(case):
    return hashlib.sha256(json.dumps({
        "before": case.before, "after": case.after, "head": case.head,
        "task": case.task, "env": case.env,
    }, sort_keys=True).encode()).hexdigest()


@pytest.mark.parametrize("row", GOLDEN, ids=lambda row: row["name"])
def test_migrated_golden_keeps_frozen_inputs_and_refuses_unproved_credit(row):
    legacy = (ROOT / row["legacy_path"]).read_bytes()
    assert hashlib.sha256(legacy).hexdigest() == row["legacy_sha256"]
    old = parse_case(legacy.decode("utf-8"))
    current = parse_case((ROOT / row["path"]).read_text(encoding="utf-8"))
    assert old.expect == row["legacy_expected"]
    assert _input_identity(old) == _input_identity(current) == row["program_input_sha256"]
    assert current.expect == row["proposed_expected"]
    snapshot = case_snapshot(current)
    head = {path: content.encode("utf-8") for path, content in current.head.items()}
    _ir, findings, verdict = analyze(
        case_to_changes(current), Config(), parse_contract(current.task) if current.task else Contract(),
        [], datetime.date(2026, 1, 1),
        known_modules=(known_baseline() | set(current.env)) if current.env is not None else None,
        head_reader=head.get if head else None,
        head_searcher=(lambda needles: [path for path, data in sorted(head.items())
                                       if any(needle.encode() in data for needle in needles)]) if head else None,
        policy_base=case_policy_base(current), root_reader=snapshot.get,
        root_searcher=lambda needles: search_source_mapping(snapshot, needles),
    )
    assert verdict == "block"
    assert findings and all(not finding.allowlisted for finding in findings)
    assert all(finding.severity == "high" for finding in findings)
    assert all(not FORBIDDEN.intersection(finding.deescalators) for finding in findings)
    assert sorted((finding.rule, finding.path, finding.unit, finding.fingerprint) for finding in findings) == sorted(
        (finding["rule"], finding["path"], finding["unit"], finding["fingerprint"]) for finding in row["findings"]
    )
    if row["name"] == "subject_pairing_other_subject_known_limit_pos":
        assert any(finding.rule == "ASSERT_WEAKENED" for finding in findings)


@pytest.mark.parametrize("row", CORPUS, ids=lambda row: row["name"])
def test_migrated_corpus_preserves_all_program_bytes_and_separate_cost_identity(row):
    root = ROOT / "benchmarks" / row["family"] / "cases" / row["name"]
    actual = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in sorted(root.rglob("*")) if path.is_file()}
    assert actual == row["input_files"]
    retained = LEDGER["legacy_expected_files"][row["family"]]
    raw = (ROOT / retained["legacy_path"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == retained["sha256"]
    assert json.loads(raw)["cases"][row["name"]] == row["legacy_expected"]
    expected = json.loads((ROOT / "benchmarks" / row["family"] / "expected.json").read_text(encoding="utf-8"))["cases"][row["name"]]
    if row["family"] == "refactors":
        assert expected["blocks"] is True
        assert row["classification"] == "known_legitimate_refactor_false_block"
        assert row["legacy_expected"]["blocks"] is False
    else:
        assert expected["verdict"] == "block"
        assert row["classification"].startswith("newly_detected_")
        assert row["legacy_expected"]["verdict"] == "pass"
    before = root / ("BEFORE" if row["family"] == "refactors" else "before")
    after = root / ("AFTER" if row["family"] == "refactors" else "after")
    src = root / ("PROD-GOOD/src" if row["family"] == "refactors" else "src")
    paths = sorted({path.relative_to(before).as_posix() for path in before.rglob("*.py")} |
                   {path.relative_to(after).as_posix() for path in after.rglob("*.py")})
    changes = []
    for path in paths:
        old, new = before / path, after / path
        changes.append(FileChange(path, "modified" if old.exists() and new.exists() else "added" if new.exists() else "deleted",
                                  old.read_bytes() if old.exists() else None, new.read_bytes() if new.exists() else None))
    head = {"src/" + path.relative_to(src).as_posix(): path.read_bytes() for path in src.rglob("*.py")}
    snapshot = {"src/" + path.relative_to(src).as_posix(): path.read_bytes() for path in src.rglob("*") if path.is_file()}
    snapshot.update({path.relative_to(after).as_posix(): path.read_bytes() for path in after.rglob("*") if path.is_file()})
    _ir, findings, verdict = analyze(
        changes, Config(), Contract(), [], datetime.date(2026, 1, 1), known_modules=known_baseline() | {"app"},
        head_reader=head.get,
        head_searcher=lambda needles: [path for path, data in sorted(head.items())
                                       if any(needle.encode() in data for needle in needles)],
        root_reader=snapshot.get, root_searcher=lambda needles: search_source_mapping(snapshot, needles),
    )
    assert verdict == "block"
    assert findings and all(not finding.allowlisted and finding.severity == "high" for finding in findings)
    assert all(not FORBIDDEN.intersection(finding.deescalators) for finding in findings)
    assert sorted((finding.rule, finding.path, finding.unit, finding.fingerprint) for finding in findings) == sorted(
        (finding["rule"], finding["path"], finding["unit"], finding["fingerprint"]) for finding in row["findings"]
    )


def test_disposition_inventory_is_exact_and_is_not_a_fixture_runtime_claim():
    assert len(GOLDEN) == 8 and len(CORPUS) == 4
    assert len({row["name"] for row in LEDGER["cases"]}) == 12
    assert LEDGER["fixture_program_executions"] == 0
    assert "not a claim that Nelson personally reviewed" in LEDGER["review_claim"]
