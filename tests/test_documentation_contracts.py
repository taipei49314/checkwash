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
    from checkwash.change import UnreadSide
    from checkwash.ir.model import IR
    from checkwash.report.jsonout import findings_to_json

    def keys(payload):
        return (set(payload) - {"run"}) | {f"run.{key}" for key in payload["run"]}

    # Rendering a report needs neither a repository nor detector input. It is
    # rendered twice: empty, and with one unread side, the one key so far
    # that is omitted when empty (#454 ruling, 2(b)).
    empty = json.loads(findings_to_json(IR(base="BASE", head="HEAD"), [], "pass"))
    full = json.loads(findings_to_json(IR(base="BASE", head="HEAD"), [], "pass",
                                       unread=[UnreadSide("assets/logo.png", "head", 1_500_000, 1_000_000)]))
    text = (ROOT / "docs" / "stability.md").read_text(encoding="utf-8")
    table = text.split("Current keys, closed:", 1)[1].split("Each finding object", 1)[0]
    rows = [line.split("|") for line in table.splitlines() if line.startswith("| `")]
    documented = {key for cells in rows for key in re.findall(r"`([^`]+)`", cells[1])}
    optional = {key for cells in rows if "omitted when empty" in cells[2]
                for key in re.findall(r"`([^`]+)`", cells[1])}
    assert documented == keys(full)
    assert documented - optional == keys(empty)
