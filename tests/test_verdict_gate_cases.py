"""The verdict gate's committed inputs (#201) must parse with the gate's own loaders.

Parse-only: no git repository is built and no engine runs, so a broken case
file, label or pin fails on every CI leg instead of only in the advisory
verdict-gate workflow.
"""

import collections
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("verdict_gate_inputs", ROOT / "tools/verdict_gate.py")
VG = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VG)

INPUTS = ROOT / "tests/verdict_gate"
# The #201 transcription: #196 28, #197 36, #198 52, #199 33 rows.
FAMILIES = {"i196": 28, "i197": 36, "i198": 52, "i199": 33}


def test_every_case_file_parses():
    cases, invalid, errors = VG.load_cases(INPUTS / "cases")
    assert errors == []
    assert invalid == []
    assert dict(collections.Counter(case.id.split("/")[0] for case in cases)) == FAMILIES


def test_labels_cover_exactly_the_cases():
    cases, _invalid, _errors = VG.load_cases(INPUTS / "cases")
    labels = VG.load_labels(INPUTS / "labels.toml")
    assert sorted(labels) == sorted(case.id for case in cases)


def test_pins_file_loads():
    pins = VG.load_pins(INPUTS / "baseline.toml")
    assert pins["canary"] is not None
    assert pins["t3"]
