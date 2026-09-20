"""Versioned transition records cannot silently accept new corpus drift."""
import hashlib
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "compare_quality_legacy", Path(__file__).parents[1] / "tools/compare_quality_legacy.py")
compare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compare)


def _record(outputs):
    return {"schema_version": 1, "baseline": compare.BASELINE,
            "release_version": "0.4.0", "review": "docs/releases/v0.4.0-compatibility.md",
            "sha256": {k: hashlib.sha256(v).hexdigest() for k, v in outputs.items()}}


def test_exact_reviewed_transition_is_accepted():
    outputs = {"baseline": b"old complete corpus", "candidate": b"new complete corpus"}
    assert compare.match_release_record(_record(outputs), outputs, "0.4.0")


@pytest.mark.parametrize("side", ["baseline", "candidate"])
def test_single_byte_drift_is_rejected(side):
    outputs = {"baseline": b"old complete corpus", "candidate": b"new complete corpus"}
    record = _record(outputs)
    outputs[side] += b"\n"
    assert not compare.match_release_record(record, outputs, "0.4.0")


@pytest.mark.parametrize("field,value", [
    ("schema_version", True), ("schema_version", 2), ("baseline", "other"),
    ("release_version", "0.3.4"), ("review", ""), ("sha256", {"candidate": "*"}),
])
def test_malformed_or_wrong_version_record_is_rejected(field, value):
    outputs = {"baseline": b"old", "candidate": b"new"}
    record = _record(outputs)
    record[field] = value
    assert not compare.match_release_record(record, outputs, "0.4.0")


def test_unknown_record_field_is_rejected():
    outputs = {"baseline": b"old", "candidate": b"new"}
    record = _record(outputs)
    record["ignore_paths"] = ["*"]
    assert not compare.match_release_record(record, outputs, "0.4.0")
