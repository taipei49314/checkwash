"""The findings JSON contract: real `--format json` output against docs/findings.schema.json.

The schema is the machine-readable form of the contract in docs/stability.md.
checkwash has no runtime dependency (D-001) and its tests need only pytest
(the `dev` extra), so this file validates with a small standard-library
validator. It implements only the keywords the schema uses and refuses a
schema that uses any other, so a keyword can never be silently ignored.

Two directions are checked. A consumer may rely on everything the schema
declares and must ignore keys it does not know. checkwash itself may emit only
keys the schema declares, and the schema may change only in the ways
docs/stability.md allows without a new `checkwash_findings_version`: the
frozen copy in tests/data/ is what version 2 promised, and this file pins its
digest, so editing it shows up here.

Adding an optional key: declare it under `properties` and leave it out of
`required`; an object schema for it goes in `$defs`. Add its row to the key
table in docs/stability.md. To protect it from later removal, a PR may also add
it to the frozen copy and update FROZEN_SHA256; nothing may be taken out.
"""

import copy
import dataclasses
import datetime
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import textwrap

from checkwash import FINDINGS_VERSION
from checkwash.cases import case_snapshot, case_to_changes, parse_case
from checkwash.config import Config
from checkwash.contract import Contract, parse_contract
from checkwash.engine import analyze
from checkwash.findings import Evidence, Finding
from checkwash.gitio.snapshot import search_source_mapping
from checkwash.ir.model import IR
from checkwash.pyenv import known_baseline
from checkwash.report.jsonout import findings_to_json

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "docs" / "findings.schema.json"
DATA = ROOT / "tests" / "data"
CASES = sorted((ROOT / "tests" / "cases").glob("*.gwcase"))
TODAY = datetime.date(2026, 1, 1)
DRAFT = "https://json-schema.org/draft/2020-12/schema"

ANNOTATIONS = frozenset({"$schema", "$comment", "title", "description", "examples"})
KEYWORDS = frozenset({
    "$defs", "$ref", "type", "const", "enum", "anyOf", "required", "properties",
    "additionalProperties", "prefixItems", "items", "minItems", "maxItems",
    "minLength", "pattern", "minimum", "maximum",
})
TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}
# Stricter than the schema on purpose: the three key forms checkwash writes
# today (legacy, change-level v2, assertion-level v2), and the rule as prefix.
FINGERPRINT = re.compile(r"[A-Z][A-Z0-9_]*/.+/(?:[0-9a-f]{12}|v2:[0-9a-f]{64})", re.DOTALL)
BREAK = (
    "docs/findings.schema.json no longer keeps what checkwash_findings_version {v} "
    "promised (tests/data/findings-schema-v{v}.json). This test counts any change to a "
    "promised key's constraints as breaking, as well as a removed, renamed or newly "
    "required key, which docs/stability.md says need a new version: bump "
    "FINDINGS_VERSION (a minor release), record why in DECISIONS.md and add the new "
    "version's frozen copy. A new optional key is not a break: declare it without "
    "adding it to `required`.\n"
)
# sha256 of tests/data/findings-schema-v2.json, which is only ever added to.
FROZEN_SHA256 = {2: "e2b7587257278f90582a0d13043a475ccb81d0fc37ceeae6a559b71be8b3fc60"}


def _schema() -> dict:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def _resolve(root: dict, ref: str) -> dict:
    assert ref.startswith("#/$defs/"), ref
    return root["$defs"][ref[len("#/$defs/"):]]


def _same(a, b) -> bool:
    """JSON equality: unlike Python's, true is not 1."""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(map(_same, a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    return a == b and (type(a) is type(b) or {type(a), type(b)} <= {int, float})


def _pattern(pattern: str) -> re.Pattern:
    # ECMA-262's `$` matches only at the end; Python's also before a final
    # newline, which would accept a label the schema rejects.
    if pattern.endswith("$") and not pattern.endswith("\\$"):
        pattern = pattern[:-1] + r"\Z"
    return re.compile(pattern)


def _errors(value, schema, root, where="$", strict=True) -> list[str]:
    """Why `value` does not match `schema`. `strict` also rejects undeclared keys."""
    if schema is True:
        return []
    if schema is False:
        return [f"{where}: no value is allowed here"]
    errors = []
    if "$ref" in schema:
        errors += _errors(value, _resolve(root, schema["$ref"]), root, where, strict)
    if "type" in schema:
        names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(TYPES[name](value) for name in names):
            return errors + [f"{where}: {value!r} is not of type {names}"]
    if "const" in schema and not _same(value, schema["const"]):
        errors.append(f"{where}: {value!r} is not {schema['const']!r}")
    if "enum" in schema and not any(_same(value, option) for option in schema["enum"]):
        errors.append(f"{where}: {value!r} is not one of {schema['enum']}")
    if "anyOf" in schema and all(_errors(value, branch, root, where, strict) for branch in schema["anyOf"]):
        errors.append(f"{where}: {value!r} matches no alternative")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        errors += [f"{where}: missing {key!r}" for key in schema.get("required", []) if key not in value]
        for key, item in value.items():
            if key in properties:
                errors += _errors(item, properties[key], root, f"{where}.{key}", strict)
            elif "additionalProperties" in schema:
                errors += _errors(item, schema["additionalProperties"], root, f"{where}.{key}", strict)
            elif strict and ("properties" in schema or "required" in schema):
                errors.append(f"{where}: emits {key!r}, which the schema does not declare")
    if isinstance(value, list):
        prefix = schema.get("prefixItems", [])
        for index, item in enumerate(value):
            if index < len(prefix):
                errors += _errors(item, prefix[index], root, f"{where}[{index}]", strict)
            elif "items" in schema:
                errors += _errors(item, schema["items"], root, f"{where}[{index}]", strict)
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{where}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{where}: more than {schema['maxItems']} items")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{where}: shorter than {schema['minLength']}")
        if "pattern" in schema and not _pattern(schema["pattern"]).search(value):
            errors.append(f"{where}: {value!r} does not match {schema['pattern']!r}")
    if TYPES["integer"](value) or isinstance(value, float):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{where}: {value!r} is below {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{where}: {value!r} is above {schema['maximum']}")
    return errors


def _problems(root: dict) -> list[str]:
    """Schema constructs this validator would get wrong or not see."""
    problems = [] if root.get("$schema") == DRAFT else [f"$schema is not {DRAFT}"]

    def walk(node, where, container=False):
        if isinstance(node, bool):
            return
        if not isinstance(node, dict):
            problems.append(f"{where}: not a schema")
            return
        problems.extend(f"{where}: unsupported keyword {key!r}" for key in node if key not in KEYWORDS | ANNOTATIONS)
        if where != "$" and ("$defs" in node or "$schema" in node):
            problems.append(f"{where}: $defs and $schema belong at the root only")
        if "$ref" in node:
            ref = node["$ref"]
            if not ref.startswith("#/$defs/") or ref[len("#/$defs/"):] not in root.get("$defs", {}):
                problems.append(f"{where}: $ref {ref!r} does not name a $defs entry")
        names = node.get("type", [])
        problems.extend(f"{where}: unknown type {name!r}"
                        for name in (names if isinstance(names, list) else [names]) if name not in TYPES)
        if ("properties" in node or "required" in node) and not container:
            # The frozen-copy comparison reads objects at the root and in $defs.
            problems.append(f"{where}: an object schema must be the root or a $defs entry")
        problems.extend(f"{where}: required {key!r} is not a declared property"
                        for key in node.get("required", []) if key not in node.get("properties", {}))
        if "pattern" in node:
            try:
                _pattern(node["pattern"])
            except re.error as exc:
                problems.append(f"{where}: pattern {node['pattern']!r}: {exc}")
        for name, sub in node.get("properties", {}).items():
            walk(sub, f"{where}.{name}")
        for key in ("additionalProperties", "items"):
            if key in node:
                walk(node[key], f"{where}/{key}")
        for key in ("prefixItems", "anyOf"):
            for index, sub in enumerate(node.get(key, [])):
                walk(sub, f"{where}/{key}[{index}]")

    walk(root, "$", container=True)
    for name, sub in root.get("$defs", {}).items():
        walk(sub, f"$defs.{name}", container=True)
    return problems


def _contract(node):
    """A schema without its annotations, in a canonical order: what a consumer can rely on."""
    if isinstance(node, list):
        return [_contract(item) for item in node]
    if not isinstance(node, dict):
        return node
    out = {}
    for key, value in node.items():
        if key in ANNOTATIONS:
            continue
        if key in ("properties", "$defs"):
            out[key] = {name: _contract(sub) for name, sub in value.items()}
        elif key == "required" or (key == "type" and isinstance(value, list)):
            out[key] = sorted(value)
        elif key == "enum":
            out[key] = sorted(value, key=lambda option: json.dumps(option, sort_keys=True))
        else:
            out[key] = _contract(value)
    return out


def _breaks(schema: dict, frozen: dict) -> list[str]:
    """How `schema` takes back something the frozen copy of a version promised."""
    current, frozen = _contract(schema), _contract(frozen)
    frozen_defs, current_defs = frozen.pop("$defs", {}), current.pop("$defs", {})
    breaks = []
    for where, node, promised in [("$", current, frozen)] + [
        (f"$defs.{name}", current_defs.get(name), promised) for name, promised in frozen_defs.items()
    ]:
        if node is None:
            breaks.append(f"{where} was removed")
            continue
        declared = node.get("properties", {})
        for name, sub in promised.get("properties", {}).items():
            if name not in declared:
                breaks.append(f"{where}.{name} was removed or renamed")
            elif declared[name] != sub:
                breaks.append(f"{where}.{name} changed: {sub} -> {declared[name]}")
        for key in sorted((set(node) | set(promised)) - {"properties"}):
            if node.get(key) != promised.get(key):
                breaks.append(f"{where}: {key} changed: {promised.get(key)} -> {node.get(key)}")
    return breaks


def _document(text: str, schema: dict, label: str) -> dict:
    """Parse and check one real document; return it."""
    payload = json.loads(text)
    assert text == json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2) + "\n", (
        f"{label}: not the canonical form of SPEC §8"
    )
    errors = _errors(payload, schema, schema)
    assert not errors, f"{label}: " + "; ".join(errors[:20])
    counts = dict.fromkeys(("critical", "high", "warn", "info"), 0)
    for finding in payload["findings"]:
        counts[finding["severity"]] += 1
        fingerprint = finding["fingerprint"]
        assert FINGERPRINT.fullmatch(fingerprint) and fingerprint.split("/", 1)[0] == finding["rule"], (
            f"{label}: {finding['rule']} fingerprint {fingerprint!r}"
        )
    assert payload["summary"] == counts, f"{label}: summary does not count findings by severity"
    return payload


def _sample() -> dict:
    finding = Finding(
        rule="ASSERT_WEAKENED", severity="high", message="assert total == 105.3 -> assert total > 0",
        path="tests/test_billing.py", unit="test_total",
        before=Evidence("assert total == 105.3", (60, 81)), after=Evidence("assert total > 0", (60, 76)),
        escalators=["NO_PROD_CHANGE_IN_DIFF"],
        fingerprint="ASSERT_WEAKENED/tests/test_billing.py/test_total/v2:" + "0" * 64,
        strength_drop=70, strength_after=20, subject_changed=False,
    )
    return json.loads(findings_to_json(IR(base="BASE", head="HEAD"), [finding], "block"))


def test_findings_schema_uses_only_what_the_validator_implements():
    assert _problems(_schema()) == []


def test_findings_schema_keeps_what_its_version_promised():
    schema = _schema()
    assert schema["properties"]["checkwash_findings_version"]["const"] == FINDINGS_VERSION
    frozen = DATA / f"findings-schema-v{FINDINGS_VERSION}.json"
    assert frozen.is_file() and FINDINGS_VERSION in FROZEN_SHA256, (
        f"FINDINGS_VERSION is {FINDINGS_VERSION} but {frozen.name} or its digest is missing: a new "
        "version needs the owner's decision (DECISIONS.md) and its own frozen copy"
    )
    assert hashlib.sha256(frozen.read_bytes()).hexdigest() == FROZEN_SHA256[FINDINGS_VERSION], (
        f"{frozen.name} changed. It may only gain what a later release promised; update "
        "FROZEN_SHA256 in the same change, so the edit is reviewed"
    )
    assert all(int(p.stem.rsplit("v", 1)[1]) <= FINDINGS_VERSION for p in DATA.glob("findings-schema-v*.json"))
    breaks = _breaks(schema, json.loads(frozen.read_text(encoding="utf-8")))
    assert not breaks, BREAK.format(v=FINDINGS_VERSION) + "\n".join(breaks)


def test_findings_schema_declares_every_documented_and_serialized_key():
    # The key table in docs/stability.md is the human contract, and every key
    # in it must be in the schema, including one a run may omit.
    schema = _schema()
    text = (ROOT / "docs" / "stability.md").read_text(encoding="utf-8")
    table = text.split("Current keys, closed:", 1)[1].split("Each finding object", 1)[0]
    documented = {
        key
        for line in table.splitlines() if line.startswith("| `")
        for key in re.findall(r"`([^`]+)`", line.split("|")[1])
    }
    declared = (set(schema["properties"]) - {"run"}) | {
        f"run.{key}" for key in schema["$defs"]["run"]["properties"]
    }
    assert declared == documented
    # `to_jsonable` writes every dataclass field, so a new field reaches the
    # JSON with no edit to jsonout.py.
    defs = schema["$defs"]
    assert {f.name for f in dataclasses.fields(Finding)} <= set(defs["finding"]["properties"])
    assert {f.name for f in dataclasses.fields(Evidence)} <= set(defs["evidence"]["properties"])


def test_contract_checks_catch_breaking_changes():
    schema = _schema()
    sample = _sample()
    assert _errors(sample, schema, schema) == []

    def broken(edit) -> list[str]:
        document = copy.deepcopy(sample)
        edit(document)
        return _errors(document, schema, schema)

    def finding(document):
        return document["findings"][0]

    assert broken(lambda d: d.pop("verdict"))
    assert broken(lambda d: d["run"].update(base=None))
    assert broken(lambda d: finding(d).update(rule_id=finding(d).pop("rule")))
    assert broken(lambda d: finding(d).update(severity="fatal"))
    assert broken(lambda d: finding(d).update(strength_drop=True))
    assert broken(lambda d: finding(d).update(allowlisted=1))
    assert broken(lambda d: finding(d)["before"].update(span=[60]))
    assert broken(lambda d: finding(d).update(fingerprint="assert total"))
    assert broken(lambda d: d["summary"].update(high=-1))
    assert broken(lambda d: d.update(checkwash_findings_version=FINDINGS_VERSION + 1))
    # An undeclared key fails checkwash's own output, not a consumer's check.
    # The names are ones no release will declare.
    assert "x-undeclared" not in schema["properties"]
    assert "x-undeclared" not in schema["$defs"]["finding"]["properties"]
    extended = copy.deepcopy(sample)
    extended["x-undeclared"] = []
    finding(extended)["x-undeclared"] = 1
    assert len(_errors(extended, schema, schema)) == 2
    assert _errors(extended, schema, schema, strict=False) == []

    assert _breaks(schema, schema) == []

    def changed(edit) -> list[str]:
        candidate = copy.deepcopy(schema)
        edit(candidate)
        return _breaks(candidate, schema)

    # Allowed without a new version: an optional key, and wording.
    assert changed(lambda s: s["properties"].update({"x-undeclared": {"type": "array"}})) == []
    assert changed(lambda s: s["$defs"]["finding"]["properties"]["shape"].update(description="")) == []
    # Breaking: a new required key, a removal, a new type, a new value.
    assert changed(lambda s: (s["properties"].update({"x-undeclared": {"type": "array"}}),
                              s["required"].append("x-undeclared")))
    assert changed(lambda s: s["$defs"]["finding"]["properties"].pop("unit"))
    assert changed(lambda s: s["$defs"]["finding"]["properties"]["unit"].update(type="string"))
    assert changed(lambda s: s["properties"]["verdict"]["enum"].append("error"))
    assert changed(lambda s: s["$defs"].pop("evidence"))
    assert _problems({**schema, "oneOf": []}) == ["$: unsupported keyword 'oneOf'"]


def test_corpus_findings_json_matches_schema():
    schema = _schema()
    seen = {key: set() for key in ("unit", "before", "after", "strength_drop", "strength_after",
                                   "subject_changed", "shape", "escalators", "deescalators")}
    verdicts = set()
    for case_path in CASES:
        case = parse_case(case_path.read_text(encoding="utf-8"))
        contract = parse_contract(case.task) if case.task else Contract()
        known = (known_baseline() | set(case.env)) if case.env is not None else None
        head = {p: c.encode("utf-8") for p, c in case.head.items()}
        snapshot = case_snapshot(case)
        ir, findings, verdict = analyze(
            case_to_changes(case), Config(), contract, [], TODAY, known_modules=known,
            head_reader=head.get if head else None,
            head_searcher=(
                (lambda needles: [p for p, data in sorted(head.items())
                                  if any(n.encode("utf-8") in data for n in needles)])
                if head else None
            ),
            root_reader=snapshot.get,
            root_searcher=lambda needles: search_source_mapping(snapshot, needles),
        )
        payload = _document(findings_to_json(ir, findings, verdict), schema, case_path.name)
        verdicts.add(payload["verdict"])
        for finding in payload["findings"]:
            for key, kinds in seen.items():
                value = finding[key]
                kinds.add("null" if value is None else "empty" if value == [] else type(value).__name__)
    # Each alternative the schema allows occurs in real output, so the check
    # above validated something for it.
    assert verdicts == {"pass", "block"}
    assert seen == {
        "unit": {"str", "null"}, "before": {"dict", "null"}, "after": {"dict", "null"},
        "strength_drop": {"int", "null"}, "strength_after": {"int", "null"},
        "subject_changed": {"bool", "null"}, "shape": {"str", "null"},
        "escalators": {"list", "empty"}, "deescalators": {"list", "empty"},
    }


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _cli(repo, *args):
    env = {**os.environ, "CHECKWASH_TODAY": "2026-01-01", "NO_COLOR": "1"}
    return subprocess.run(
        [sys.executable, "-m", "checkwash", *args, "--repo", str(repo)], capture_output=True, env=env,
    )


def _repo(path):
    path.mkdir()
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.name", "contract")
    _git(path, "config", "user.email", "contract@example.invalid")
    _git(path, "config", "commit.gpgsign", "false")
    _git(path, "config", "core.autocrlf", "false")
    (path / "billing.py").write_text(
        "def compute_invoice_total(items):\n    return round(sum(items), 2)\n", encoding="utf-8",
    )
    (path / "tests").mkdir()
    (path / "tests" / "test_billing.py").write_text(textwrap.dedent("""\
        from billing import compute_invoice_total


        def test_invoice_total():
            total = compute_invoice_total([10.5, 94.8])
            assert total == 105.3
        """), encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-m", "base")
    return path


def _weaken(repo):
    test_file = repo / "tests" / "test_billing.py"
    test_file.write_text(
        test_file.read_text(encoding="utf-8").replace("assert total == 105.3", "assert total > 0"),
        encoding="utf-8",
    )


def test_cli_block_and_exemption_documents_match_schema(tmp_path):
    schema = _schema()
    ranged = _repo(tmp_path / "range")
    _weaken(ranged)
    _git(ranged, "commit", "-am", "weaken")
    result = _cli(ranged, "check", "HEAD~1..HEAD", "--format", "json")
    assert result.returncode == 1, result.stderr
    payload = _document(result.stdout.decode("utf-8"), schema, "range block")
    assert payload["verdict"] == "block" and payload["run"]["head"] != "worktree"

    worktree = _repo(tmp_path / "worktree")
    _weaken(worktree)
    result = _cli(worktree, "check", "--format", "json")
    assert result.returncode == 1, result.stderr
    payload = _document(result.stdout.decode("utf-8"), schema, "worktree block")
    assert payload["run"]["head"] == "worktree"
    fingerprint = next(f["fingerprint"] for f in payload["findings"] if f["rule"] == "ASSERT_WEAKENED")
    allowed = _cli(worktree, "allow", fingerprint, "--reason", "reviewed: findings schema contract")
    assert allowed.returncode == 0, allowed.stderr
    _git(worktree, "add", ".greenwash")
    _git(worktree, "commit", "-m", "record exemption")
    result = _cli(worktree, "check", "--format", "json")
    assert result.returncode == 0, result.stderr
    payload = _document(result.stdout.decode("utf-8"), schema, "worktree exempted")
    assert payload["verdict"] == "pass"
    assert any(f["allowlisted"] and "ALLOWLISTED" in f["deescalators"] for f in payload["findings"])


def test_cli_config_errors_document_matches_schema(tmp_path):
    repo = _repo(tmp_path / "repo")
    (repo / ".greenwash").mkdir()
    (repo / ".greenwash" / "config.toml").write_text(
        '[gate]\non_engine_error = "Block"\nfail_on = 5\n', encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "config")
    # Configuration is read from the base side, so the range starts after it.
    (repo / "README.md").write_text("docs\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "docs")
    result = _cli(repo, "check", "HEAD~1..HEAD", "--format", "json")
    assert result.returncode == 0, result.stderr
    payload = _document(result.stdout.decode("utf-8"), _schema(), "config errors")
    assert payload["config_errors"], payload
