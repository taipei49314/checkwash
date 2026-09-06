"""Benchmark wrappers must supply complete snapshots for root-helper evidence."""

import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
HELPER = b"def assert_equal(actual, expected):\n    assert actual == expected\n"
BEFORE = b"from app import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"
AFTER = b"from app import add\nfrom test_helpers import assert_equal\n\ndef test_add():\n    assert_equal(add(2, 3), 5)\n"


def _load(relative):
    name = "benchmark_snapshot_" + relative.replace("/", "_").replace(".", "_")
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


WRAPPERS = {
    "refactor": _load("benchmarks/refactors/verify.py").judge,
    "tamper": _load("benchmarks/tamper/verify.py").judge,
    "score": _load("benchmarks/score.py").verdict,
}


def _write_tree(root, files):
    root.mkdir(parents=True, exist_ok=True)
    for path, data in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def _judge(wrapper, case, before, after):
    _write_tree(case / "before", before)
    _write_tree(case / "after", after)
    _write_tree(case / "src", {"app.py": b"def add(a, b):\n    return a + b\n"})
    fn = WRAPPERS[wrapper]
    return fn(case) if wrapper == "tamper" else fn(case / "before", case / "after", case / "src")


@pytest.mark.parametrize("wrapper", WRAPPERS)
def test_benchmark_root_extraction_preserves_the_same_oracle(wrapper, tmp_path):
    verdict, rules = _judge(wrapper, tmp_path,
                            {"tests/test_calc.py": BEFORE},
                            {"tests/test_calc.py": AFTER, "test_helpers.py": HELPER})
    assert verdict == "pass"
    assert rules == []


@pytest.mark.parametrize("wrapper", WRAPPERS)
@pytest.mark.parametrize("helper_after", [None, b"def assert_equal(actual, expected):\n    pass\n"])
def test_benchmark_helper_only_removal_retains_the_unchanged_caller(wrapper, helper_after, tmp_path):
    before = {"tests/test_calc.py": AFTER, "test_helpers.py": HELPER}
    after = {"tests/test_calc.py": AFTER}
    if helper_after is not None:
        after["test_helpers.py"] = helper_after
    verdict, rules = _judge(wrapper, tmp_path, before, after)
    assert verdict == "block"
    assert any(rule.split("/", 1)[0] == "ASSERT_REMOVED" for rule in rules)


@pytest.mark.parametrize("wrapper", WRAPPERS)
def test_benchmark_extraction_does_not_hide_changed_expected_value(wrapper, tmp_path):
    verdict, rules = _judge(wrapper, tmp_path,
                            {"tests/test_calc.py": BEFORE},
                            {"tests/test_calc.py": AFTER.replace(b"3), 5)", b"3), 4)"),
                             "test_helpers.py": HELPER})
    assert verdict == "block"
    assert any(rule.split("/", 1)[0] == "EXPECTED_VALUE_CHANGED" for rule in rules)


@pytest.mark.parametrize("wrapper", WRAPPERS)
def test_benchmark_complete_snapshot_does_not_hide_a_package_collision(wrapper, tmp_path):
    package = {"test_helpers/__init__.py": b"def assert_equal(actual, expected):\n    pass\n"}
    verdict, rules = _judge(wrapper, tmp_path,
                            {"tests/test_calc.py": BEFORE, **package},
                            {"tests/test_calc.py": AFTER, "test_helpers.py": HELPER, **package})
    assert verdict == "block"
    assert any(rule.split("/", 1)[0] == "ASSERT_REMOVED" for rule in rules)


@pytest.mark.parametrize("family", ["refactors", "tamper"])
def test_benchmark_wrappers_keep_frozen_corpus_verdicts_and_rule_parity(family):
    corpus = ROOT / "benchmarks" / family
    expected = json.loads((corpus / "expected.json").read_text(encoding="utf-8"))["cases"]
    for name, recorded in sorted(expected.items()):
        case = corpus / "cases" / name
        if family == "refactors":
            args = (case / "BEFORE", case / "AFTER", case / "PROD-GOOD" / "src")
            actual, rules = WRAPPERS["refactor"](*args)
            want = "block" if recorded["blocks"] else "pass"
        else:
            args = (case / "before", case / "after", case / "src")
            actual, rules = WRAPPERS["tamper"](case)
            want = recorded["verdict"]
        score, score_rules = WRAPPERS["score"](*args)
        assert actual == score == want, (family, name, actual, score, want)
        assert sorted({rule.split("/", 1)[0] for rule in rules}) == score_rules, (family, name)
