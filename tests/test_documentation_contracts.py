"""Regression checks for adoption and catalog drift, without replaying cases."""

import json
import pathlib
import re
import runpy

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_failure_ledger_preserves_lettered_fixture_references(tmp_path):
    # The old digits-only expression discarded the entire 87a header.
    cases = tmp_path / "tests" / "cases"
    cases.mkdir(parents=True)
    (cases / "metadata.gwcase").write_text(
        "name: catalog-only\nbypass: 77, 87a\n=== before\n"
        "bypass: 999\n", encoding="utf-8"
    )
    module = runpy.run_path(str(ROOT / "benchmarks" / "make_failures.py"))
    claims = module["fixture_claims"]
    claims.__globals__["ROOT"] = str(tmp_path)
    assert claims() == {"77": ["metadata.gwcase"], "87a": ["metadata.gwcase"]}


def test_enterprise_required_context_matches_shipped_ruleset():
    payload = json.loads((ROOT / "action" / "required-ruleset.json").read_text(encoding="utf-8"))
    contexts = {
        item["context"]
        for rule in payload["rules"] if rule["type"] == "required_status_checks"
        for item in rule["parameters"]["required_status_checks"]
    }
    text = (ROOT / "docs" / "enterprise.md").read_text(encoding="utf-8")
    documented = set(re.findall(r"Require status context `([^`]+)`", text))
    assert documented == contexts


def test_stability_json_envelope_matches_actual_renderer():
    from checkwash.ir.model import IR
    from checkwash.report.jsonout import findings_to_json

    # Rendering an empty report needs neither a repository nor detector input.
    payload = json.loads(findings_to_json(IR(base="BASE", head="HEAD"), [], "pass"))
    keys = (set(payload) - {"run"}) | {f"run.{key}" for key in payload["run"]}
    text = (ROOT / "docs" / "stability.md").read_text(encoding="utf-8")
    table = text.split("Current keys, closed:", 1)[1].split("Each finding object", 1)[0]
    documented = {
        key
        for line in table.splitlines() if line.startswith("| `")
        for key in re.findall(r"`([^`]+)`", line.split("|")[1])
    }
    assert documented == keys
