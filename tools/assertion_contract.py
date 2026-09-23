"""Check the independently authored JavaScript assertion support contract.

The JSON inventory is reviewed data, not a dump of frontend regexes or strength
maps. This module also exposes the exact same mutation inputs to installed-wheel,
zipapp and Action qualification; importing it needs only the standard library.
Unsupported rows describe bounded syntax gaps, not JavaScript validity.
"""

from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path, PurePosixPath
from typing import Any


DEFAULT_CONTRACT = Path(__file__).resolve().parents[1] / "tests/data/javascript_assertion_support.json"
_SUFFIXES = tuple(f".{kind}.{ext}" for kind in ("test", "spec")
                  for ext in ("js", "jsx", "ts", "tsx", "mjs", "cjs", "mts", "cts"))
_NODE_EXTENSIONS = {"js", "cjs", "mjs", "ts", "cts", "mts"}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _source_path(path: Any) -> bool:
    if not (isinstance(path, str) and bool(path) and "\\" not in path
            and not PurePosixPath(path).is_absolute() and ":" not in path
            and not path.endswith("/")
            and not {"..", ".git"}.intersection(part.lower() for part in PurePosixPath(path).parts)):
        return False
    parts = PurePosixPath(path).parts
    if not parts:
        return False
    stem, separator, extension = parts[-1].rpartition(".")
    return path.endswith(_SUFFIXES) or (
        bool(separator) and extension in _NODE_EXTENSIONS
        and ("test" in parts[:-1] or stem == "test" or stem.startswith("test-")
             or stem.endswith(("-test", "_test")))
    )


def validate_contract(contract: Any) -> dict:
    """Reject incomplete, contradictory or unsafe corpus records before use."""
    _require(isinstance(contract, dict), "contract must be an object")
    _require(type(contract.get("schema_version")) is int
             and contract["schema_version"] == 1, "schema_version must be 1")
    sources = contract.get("sources")
    _require(isinstance(sources, list) and bool(sources)
             and all(isinstance(url, str) and url.startswith("https://") for url in sources),
             "sources must contain primary documentation URLs")
    for collection in ("apis", "mutations"):
        records = contract.get(collection)
        _require(isinstance(records, list) and bool(records), f"{collection} must not be empty")
        ids: set[str] = set()
        for record in records:
            _require(isinstance(record, dict), f"{collection} entries must be objects")
            case_id = record.get("id")
            _require(isinstance(case_id, str) and bool(case_id), f"{collection} entry needs an id")
            _require(case_id not in ids, f"duplicate {collection} id: {case_id}")
            ids.add(case_id)
            _require(_source_path(record.get("path")), f"{case_id}: unsafe or non-test path")
            if collection == "apis":
                _require(isinstance(record.get("framework"), str) and bool(record["framework"]),
                         f"{case_id}: framework is required")
                _require(record.get("status") in {"supported", "unsupported"},
                         f"{case_id}: invalid support status")
                _require(isinstance(record.get("source"), str) and bool(record["source"]),
                         f"{case_id}: source is required")
                assertions = record.get("assertions")
                _require(isinstance(assertions, list), f"{case_id}: assertions must be a list")
                _require(bool(assertions) == (record["status"] == "supported"),
                         f"{case_id}: status contradicts expected recognition")
                for assertion in assertions:
                    _require(isinstance(assertion, dict), f"{case_id}: assertion must be an object")
                    _require(isinstance(assertion.get("form"), str) and bool(assertion["form"]),
                             f"{case_id}: assertion form is required")
                    _require(type(assertion.get("strength")) is int
                             and 0 <= assertion["strength"] <= 100,
                             f"{case_id}: strength must be an integer in [0, 100]")
                    _require(isinstance(assertion.get("left"), str) and bool(assertion["left"]),
                             f"{case_id}: subject is required")
            else:
                for side in ("before", "after"):
                    _require(isinstance(record.get(side), str) and bool(record[side]),
                             f"{case_id}: {side} source is required")
                _require(record["before"] != record["after"], f"{case_id}: mutation does not change source")
                kind = record.get("kind")
                _require(kind in {"weakening", "removal", "preserving", "strengthening"},
                         f"{case_id}: invalid mutation kind")
                expected = (("block", "ASSERT_REMOVED" if kind == "removal" else "ASSERT_WEAKENED", "high")
                            if kind in {"removal", "weakening"} else ("pass", None, None))
                _require(all(key in record for key in ("verdict", "rule", "severity")),
                         f"{case_id}: outcome fields must be explicit")
                _require((record["verdict"], record["rule"], record["severity"]) == expected,
                         f"{case_id}: outcome contradicts mutation kind")
    return contract


def load_contract(path: str | Path | None = None) -> dict:
    """Load and validate the checked-in inventory without importing checkwash."""
    return validate_contract(json.loads(Path(path or DEFAULT_CONTRACT).read_text(encoding="utf-8")))


def mutation_cases(contract: dict | None = None) -> list[dict]:
    """Return complete standalone-file mutation records for any CLI runtime."""
    validated = load_contract() if contract is None else validate_contract(contract)
    return [dict(case) for case in validated["mutations"]]


def check_api_case(case: dict) -> None:
    """Fail even when an entire assertion family disappears from the parser."""
    from checkwash.frontends.javascript.frontend import parse_javascript

    parsed = parse_javascript(case["source"].encode("utf-8"))
    if not parsed.parse_ok:
        raise AssertionError(f"{case['id']}: parser did not accept source")
    actual = [{"form": assertion.form, "strength": assertion.strength, "left": assertion.left}
              for unit in parsed.units for assertion in unit.side.assertions]
    if actual != case["assertions"]:
        raise AssertionError(f"{case['id']}: expected recognition {case['assertions']!r}; got {actual!r}")


def check_mutation_case(case: dict) -> None:
    """Check the complete analysis path, including alignment and escalation."""
    from checkwash.config import Config
    from checkwash.contract import Contract
    from checkwash.engine import FileChange, analyze

    _ir, findings, verdict = analyze(
        [FileChange(case["path"], "modified", case["before"].encode("utf-8"),
                    case["after"].encode("utf-8"))],
        Config(), Contract(), [], datetime.date(2026, 9, 23),
    )
    observed = [(finding.rule, finding.severity) for finding in findings]
    expected = [(case["rule"], case["severity"])] if case["rule"] else []
    if verdict != case["verdict"] or observed != expected:
        raise AssertionError(f"{case['id']}: expected {(case['verdict'], expected)!r}; "
                             f"got {(verdict, observed)!r}")


def verify_contract(contract: dict | None = None) -> dict:
    """Return a deterministic receipt; collect failures without hiding gaps."""
    contract = load_contract() if contract is None else validate_contract(contract)
    failures: list[str] = []
    for collection, checker in (("apis", check_api_case), ("mutations", check_mutation_case)):
        for case in contract[collection]:
            try:
                checker(case)
            except AssertionError as exc:
                failures.append(str(exc))
    return {"schema_version": 1, "apis": len(contract["apis"]),
            "mutations": len(contract["mutations"]), "failures": failures,
            "status": "fail" if failures else "pass"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    args = parser.parse_args()
    receipt = verify_contract(load_contract(args.contract))
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 1 if receipt["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
