"""Strict owned regressions; deliberately fail until R1 is actually repaired.

No source below is imported or executed. Checkwash parses the synthetic files.
The small cases establish that the same oracle shape already has the expected
contract; the 350-term cases must keep it. No xfail, catch-to-empty or 0/2 gate.
"""

import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from checkwash.frontends.python import frontend
from checkwash.ir import strength as S
from checkwash.ir.astutil import stable_dump


_SPEC = importlib.util.spec_from_file_location(
    "reliability_r1_cases", Path(__file__).resolve().parents[1] / "tools" / "reliability_r1_cases.py"
)
assert _SPEC is not None and _SPEC.loader is not None
CASES = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(CASES)


@pytest.mark.parametrize("terms", CASES.WIDTHS)
@pytest.mark.parametrize("location", CASES.LOCATIONS)
def test_owned_deep_sources_preserve_the_actual_oracle(location, terms):
    source = CASES.snapshot(location, terms)
    production = frontend.parse_python(source[CASES.PROD_PATH], collect_tests=False)
    assert production.parse_ok
    assert "value" in production.symbols
    test = frontend.parse_python(source[CASES.TEST_PATH], collect_tests=True)
    assert test.parse_ok
    unit = next(unit for unit in test.units if unit.qualname == "test_value")
    assert len(unit.side.assertions) == 1
    assertion = unit.side.assertions[0]
    assert assertion.strength == S.EXACT_VALUE
    assert assertion.right_value == str(terms)
    if location == "helper_body":
        assert assertion.inherited


@pytest.mark.parametrize("terms", CASES.WIDTHS)
def test_binding_keys_are_complete_and_identical_in_both_consumers(terms):
    source = CASES.snapshot("test_assignment", terms)[CASES.TEST_PATH].decode("utf-8")
    function = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef))
    expected = CASES.expression("value(1)", terms)
    definitions, references = frontend._binding_maps(function)
    reaching = frontend._ordered_bindings(function)
    assert definitions["got"] == expected
    assert references["got"] == ("value",)
    assert len(reaching["got"]) == 1
    assert reaching["got"][0][2] == expected
    assert reaching["got"][0][3] == ("value",)


@pytest.mark.parametrize("terms", CASES.WIDTHS)
def test_cosmetic_production_edit_keeps_fingerprint_but_real_edit_changes_it(terms):
    before, spaced = CASES.pair("production_return", terms, "format")
    original = frontend.parse_python(before[CASES.PROD_PATH], collect_tests=False)
    cosmetic = frontend.parse_python(spaced[CASES.PROD_PATH], collect_tests=False)
    changed_bytes = before[CASES.PROD_PATH].replace(b"return seed", b"return other")
    real = frontend.parse_python(changed_bytes, collect_tests=False)
    assert original.parse_ok and cosmetic.parse_ok and real.parse_ok
    assert original.symbols["value"] == cosmetic.symbols["value"]
    assert original.symbols["value"] != real.symbols["value"]


@pytest.mark.parametrize("source", [
    "def f(x, /, y=1, *, z=None):\n    return x + y * z\n",
    "def f(x):\n    return (x ** 2) ** 3, x ** (2 ** 3), x - (2 - 3)\n",
    "def f(x):\n    return [a for a in x if a != 1], {a: None for a in x}\n",
    "def f(x):\n    match x:\n        case {'a': value}:\n            return value\n",
])
def test_existing_canonical_dump_and_symbol_digest_bytes_are_preserved(source):
    tree = ast.parse(source)
    frontend._normalize_for_fingerprint(tree)
    node = tree.body[0]
    options = {"show_empty": True} if sys.version_info >= (3, 13) else {}
    original = ast.dump(node, include_attributes=False, **options)
    assert stable_dump(node) == original
    assert frontend._fingerprint(node) == hashlib.sha256(original.encode("utf-8")).hexdigest()[:16]


def _git(repo, *args):
    completed = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True,
        encoding="utf-8", timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def _write(repo, snapshot):
    for name, data in snapshot.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


@pytest.mark.parametrize("terms", CASES.WIDTHS)
@pytest.mark.parametrize("location", CASES.LOCATIONS)
@pytest.mark.parametrize("change", ("format", "weaken"))
def test_real_cli_has_a_verdict_and_keeps_weakening_blocked(tmp_path, location, terms, change):
    before, after = CASES.pair(location, terms, change)
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.name", "owned R1 reduction")
    _git(tmp_path, "config", "user.email", "r1@example.invalid")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    _write(tmp_path, before)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "owned base")
    base = _git(tmp_path, "rev-parse", "HEAD")
    _write(tmp_path, after)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "owned candidate")
    head = _git(tmp_path, "rev-parse", "HEAD")
    completed = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "checkwash", "check", f"{base}...{head}",
         "--repo", str(tmp_path), "--format", "json"],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
        env={**os.environ, "GREENWASH_TODAY": "2026-10-12", "NO_COLOR": "1"},
    )
    expected = 1 if change == "weaken" else 0
    assert completed.returncode == expected, completed.stdout + completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["verdict"] == ("block" if change == "weaken" else "pass")
    assert not payload.get("config_errors")
    assert "engine error" not in completed.stderr.lower()
    if change == "weaken":
        assert any(f["rule"] == "ASSERT_WEAKENED" and f["severity"] == "high"
                   for f in payload["findings"]), payload["findings"]
    else:
        assert payload["findings"] == []
