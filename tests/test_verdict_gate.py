"""The previous-release verdict gate (#201) must apply every rule and fail closed.

Engines here are owned fake zipapps: a tiny ``checkwash/cli.py`` that prints canned
JSON and exits 0/1/2 per case, built into a pyz at test time from a committed fake
source tree. Nothing in the tool is patched; every engine is a real process.
"""

import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys
from types import SimpleNamespace
import zipapp
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/verdict_gate.py"
SPEC = importlib.util.spec_from_file_location("verdict_gate", TOOL)
VG = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VG)

SHA_A = "a" * 64
SHA_B = "b" * 64


# ---------------------------------------------------------------- fake engines

FAKE_BODY = r'''
import json
import os
import subprocess
import sys
import time


def report(verdict, findings=(), config_errors=(), skipped=(), version=None):
    return {"checkwash_findings_version": 2,
            "run": {"base": "HEAD~1", "head": "HEAD", "checkwash_version": version or VERSION},
            "findings": list(findings), "summary": {}, "config_errors": list(config_errors),
            "skipped_files": list(skipped), "verdict": verdict}


def case_key():
    if os.path.exists("CASE"):
        with open("CASE", encoding="utf-8") as stream:
            return stream.read().strip()
    changed = subprocess.run(["git", "diff", "--name-only", "HEAD~1", "HEAD"],
                             capture_output=True, text=True, check=True)
    return "path:" + changed.stdout.split()[0]


def main():
    args = sys.argv[1:]
    if args == ["--version"]:
        print("checkwash " + PRINTED)
        return 0
    if args[:1] != ["check"] or args[2:4] != ["--format", "json"]:
        print("fake engine: unexpected arguments " + repr(args), file=sys.stderr)
        return 3
    selected = args[1]
    if selected.startswith("MISSING_"):
        if CONTROLS["invalid"]:
            print("checkwash engine error: unknown revision " + selected, file=sys.stderr)
            return 2
        print(json.dumps(report("pass")))
        return 0
    if selected == "HEAD..HEAD":
        if CONTROLS["clean"]:
            print(json.dumps(report("pass")))
            return 0
        print(json.dumps(report("block", [{"rule": "X", "severity": "high", "path": "control.txt"}])))
        return 1
    if selected != "HEAD~1..HEAD":
        return 3
    key = case_key()
    if key not in TABLE:
        print("fake engine: no canned answer for " + key, file=sys.stderr)
        return 3
    answer = TABLE[key]
    if args[4:] != answer.get("args", []):
        print("fake engine: extra arguments " + repr(args[4:]), file=sys.stderr)
        return 3
    for name, value in answer.get("env", {}).items():
        if os.environ.get(name) != value:
            print("fake engine: " + name + " is " + repr(os.environ.get(name)), file=sys.stderr)
            return 3
    if answer.get("sleep"):
        time.sleep(answer["sleep"])
    if answer.get("touch"):
        with open(answer["touch"], "w", encoding="utf-8") as stream:
            stream.write("written by the engine\n")
    if "raw" in answer:
        sys.stdout.write(answer["raw"])
        return answer.get("exit", 0)
    verdict = answer["verdict"]
    print(json.dumps(report(verdict, answer.get("findings", []), answer.get("config_errors", []),
                            answer.get("skipped", []), answer.get("version"))))
    return answer.get("exit", 1 if verdict == "block" else 0)


def entry():
    raise SystemExit(main())
'''


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def make_engine(tmp_path, name, version, table, *, printed=None, clean=True, invalid=True, chai=None):
    """A committed fake source tree, its zipapp, and the pin that matches both."""
    source = tmp_path / f"{name} source"
    header = (f"VERSION = {version!r}\nPRINTED = {printed or version!r}\nTABLE = {table!r}\n"
              f"CONTROLS = {dict(clean=clean, invalid=invalid)!r}\n")
    write(source / "src/checkwash/__init__.py", f"__version__ = {version!r}\n")
    write(source / "src/checkwash/cli.py", header + FAKE_BODY)
    write(source / "src/checkwash/zipapp_entry.py", "from checkwash.cli import entry\n\n\ndef run():\n    entry()\n")
    write(source / "pyproject.toml", f'[project]\nname = "checkwash"\nversion = "{version}"\n')
    if chai is not None:
        write(source / VG.CHAI_PATH, json.dumps({"schema_version": 1, "mutations": chai}, indent=1))
    VG._git(source, "init", "-q", "-b", "main")
    VG._git(source, "add", "--all")
    VG._git(source, "commit", "-q", "-m", "fake engine " + name)
    pyz = tmp_path / f"{name}.pyz"
    # The release recipe's entry point, so the archive's __main__.py is the bound one.
    zipapp.create_archive(source / "src", pyz, main="checkwash.zipapp_entry:run")
    data = pyz.read_bytes()
    pin = {"tag": "v" + version, "version": version, "commit": VG._git_text(source, "rev-parse", "HEAD"),
           "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
    return SimpleNamespace(pyz=pyz, source=source, pin=pin, version=version)


def engine_for(fake, role="baseline", pin="same"):
    return VG.Engine(role=role, python=sys.executable, pyz=fake.pyz, source=fake.source,
                     pin=fake.pin if pin == "same" else pin)


def toml_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return json.dumps(value)


def toml_table(name, mapping):
    return f"[{name}]\n" + "".join(f"{key} = {toml_value(value)}\n" for key, value in mapping.items())


def write_pins(path, baseline, *, blocked=None, canary_old=None, canary_new=None, block_to_pass=None, t3=None):
    text = "schema_version = 1\n" + toml_table("baseline", baseline)
    if blocked is not None:
        text += toml_table("baseline_blocked", blocked)
    if t3 is not None:
        text += "[t3.cases]\n" + "".join(f"{json.dumps(key)} = {json.dumps(value)}\n" for key, value in t3.items())
    if canary_old is not None:
        text += "[canary]\n"
        if block_to_pass is not None:
            text += "block_to_pass = [" + ", ".join(json.dumps(item) for item in block_to_pass) + "]\n"
        text += toml_table("canary.old", canary_old) + toml_table("canary.new", canary_new)
    write(path, text)
    return path


def write_labels(path, labels):
    write(path, "schema_version = 1\n[labels]\n" + "".join(f"{json.dumps(k)} = {json.dumps(v)}\n"
                                                         for k, v in labels.items()))
    return path


def write_acceptance(path, baseline, entries):
    text = f"baseline = {json.dumps(baseline)}\n"
    for item in entries:
        text += "\n[[accept]]\n" + "".join(f"{key} = {toml_value(value)}\n" for key, value in item.items())
    write(path, text)
    return path


def vgcase(*sections):
    """Join (header, body) pairs; bodies are exact bytes up to the next header."""
    return "".join(f"=== {header} ===\n{body}" for header, body in sections).encode("utf-8")


# ---------------------------------------------------------------- canned observations for the pure rules

def obs(verdict, *, findings=(), blocking=None, errors=(), config_errors=(), skipped=()):
    kept = sorted(list(item) for item in findings)
    return {"exit": 1 if verdict == "block" else 0, "verdict": verdict, "findings": kept,
            "blocking": kept if blocking is None else blocking, "config_errors": list(config_errors),
            "skipped_files": list(skipped), "version": "0.0.0", "errors": list(errors)}


def row(case_id, before, after, *, tier="T1", label=None, sha=SHA_A, issue=None, runs=None, **expect):
    return {"id": case_id, "tier": tier, "input_sha256": sha, "label": label, "issue": issue,
            "expect_config_errors": expect.get("expect_config_errors", []),
            "expect_skipped": expect.get("expect_skipped", []), "not_run": None,
            "runs": runs if runs is not None else {"baseline": obs(before), "candidate": obs(after)}}


def entry(case, kind, *, sha=SHA_A, issue=7):
    item = {"case": case, "input_sha256": sha, "kind": kind, "reason": "reviewed", "reviewed_in": "12"}
    if issue is not None:
        item["issue"] = issue
    return item


def acceptance(*entries, baseline="v0.5.0"):
    return {"baseline": baseline, "entries": [dict(item, index=index) for index, item in enumerate(entries, 1)]}


def blocked_pin(rows):
    ids = sorted(item["id"] for item in rows if item["runs"]["baseline"]["verdict"] == "block")
    return {"count": len(ids), "sha256": VG.digest(ids)}


def rules(rows, labels, acc=None, **kwargs):
    kwargs.setdefault("baseline_blocked", blocked_pin(rows))
    return VG.evaluate(rows, labels=labels, acceptance=acceptance() if acc is None else acc,
                       pin_tag="v0.5.0", **kwargs)


def codes(result):
    return sorted((item["code"], item["case"]) for item in result["failures"])


# ---------------------------------------------------------------- strict JSON

@pytest.mark.parametrize("text", [
    '{"a": 1, "a": 2}', '{"a": {"b": 1, "b": 1}}', '[{"x": 0, "x": 0}]',
    '{"a": NaN}', '{"a": Infinity}', '{"a": -Infinity}', '{"a": 1e999}', '{"a": -1e999}',
    chr(0xFEFF) + "{}", "{", "",
])
def test_strict_json_rejects_duplicates_non_finite_and_malformed(text):
    with pytest.raises(ValueError):
        VG.loads_strict(text)


def test_strict_json_rejects_invalid_utf8_and_accepts_canonical_reports():
    with pytest.raises(ValueError):
        VG.loads_strict(b'{"a": "\xff"}')
    with pytest.raises(ValueError, match="too deep"):  # a RecursionError would escape observe()
        VG.loads_strict("[" * 100000 + "]" * 100000)
    assert VG.loads_strict(b'{"a": [1, 2.5, -0.0, "\xc3\xa9"], "b": {"c": null}}') == {
        "a": [1, 2.5, -0.0, "é"], "b": {"c": None}}


# ---------------------------------------------------------------- observation of one engine run

def report_bytes(**overrides):
    payload = {"checkwash_findings_version": 2, "run": {"checkwash_version": "0.5.0"}, "verdict": "block",
               "findings": [
                   {"rule": "TEST_DISABLED", "severity": "high", "path": "b.test.js"},
                   {"rule": "ASSERT_WEAKENED", "severity": "warn", "path": "a.test.js"},
                   {"rule": "ASSERT_REMOVED", "severity": "critical", "path": "a.test.js", "allowlisted": True},
                   {"rule": "CI_WORKFLOW_TOUCHED", "severity": "high", "path": None},
               ], "config_errors": [], "skipped_files": []}
    payload.update(overrides)
    return json.dumps(payload).encode("utf-8")


def test_observation_keeps_sorted_triples_and_the_blocking_set():
    observed = VG.observe(1, report_bytes(), b"", version="0.5.0")
    assert observed["errors"] == []
    assert observed["verdict"] == "block" and observed["exit"] == 1 and observed["version"] == "0.5.0"
    assert observed["findings"] == [
        ["ASSERT_REMOVED", "critical", "a.test.js"], ["ASSERT_WEAKENED", "warn", "a.test.js"],
        ["CI_WORKFLOW_TOUCHED", "high", None], ["TEST_DISABLED", "high", "b.test.js"]]
    # Allowlisted and below-threshold findings do not block.
    assert observed["blocking"] == [["CI_WORKFLOW_TOUCHED", "high", None], ["TEST_DISABLED", "high", "b.test.js"]]
    warn = VG.observe(1, report_bytes(), b"", version="0.5.0", threshold="warn")
    assert ["ASSERT_WEAKENED", "warn", "a.test.js"] in warn["blocking"]


@pytest.mark.parametrize("returncode,stdout,needle", [
    (2, b"", "exit 2 (expected 0 or 1)"),
    (0, report_bytes(), "inconsistent with verdict 'block'"),
    (1, report_bytes(verdict="pass", findings=[]), "inconsistent with verdict 'pass'"),
    (1, b"not json", "invalid JSON report"),
    (1, b'{"verdict": "block", "verdict": "pass"}', "duplicate JSON key"),
    (1, b'{"verdict": "block", "score": NaN}', "non-finite"),
    (0, b"[]", "root is not an object"),
    (0, report_bytes(verdict="maybe"), "is not 'pass' or 'block'"),
    (1, report_bytes(findings={}), "findings is not an array"),
    (1, report_bytes(findings=[{"rule": "R", "severity": "fatal", "path": "x"}]), "malformed finding"),
    (1, report_bytes(findings=[{"rule": "R", "severity": ["high"], "path": "x"}]), "malformed finding"),
    (1, report_bytes(findings=[{"rule": "R", "severity": {"high": 1}, "path": "x"}]), "malformed finding"),
    (1, report_bytes(config_errors="bad"), "config_errors is not an array"),
    (1, report_bytes(skipped_files=[1]), "skipped_files is not an array"),
    (1, report_bytes(run={"checkwash_version": "0.4.2"}), "differs from the engine version"),
    (1, report_bytes(run=None), "differs from the engine version"),
])
def test_observation_integrity_faults(returncode, stdout, needle):
    observed = VG.observe(returncode, stdout, b"boom at /tmp/repo", version="0.5.0", scrub=("/tmp/repo",))
    assert any(needle in error for error in observed["errors"]), observed["errors"]
    assert all("/tmp/repo" not in error for error in observed["errors"])


def test_observation_records_deeply_nested_json_instead_of_raising():
    observed = VG.observe(1, b"[" * 100000 + b"]" * 100000, b"", version="0.5.0")
    assert observed["errors"] == ["invalid JSON report: JSON nesting is too deep"]


# ---------------------------------------------------------------- case parser

def full_case():
    payload = base64.b64encode(b"\x00\x01binary\r\n").decode("ascii")
    return vgcase(
        ("meta", "issue: 197\nrow: A13\n# a comment\n\n"),
        ("options", 'today = 2026-10-02\ntask = "TASK.md"\nfail_on = "warn"\n'
                    'expect_config_errors = ["config.toml: bad"]\nexpect_skipped = ["broken.py"]\n'),
        ("base: TASK.md", "Title\n=====\n\n=== not a header\n"),
        ("base: src/value.test.ts", "#!/bin/sh\ntest('x', () => {});\n"),
        ("base: src/keep.test.ts", "keep\n"),
        ("base: src/gone.js", "gone\n"),
        ("base: src/same.js", "same\n"),
        ("base-b64: assets/blob.bin", payload + "\n"),
        ("base: src/old.bin", "old\n"),
        ("rename: src/value.test.ts -> src/value2.test.ts", "#!/bin/sh\ntest('y', () => {});\n"),
        ("rename-same: src/same.js -> lib/same.js", ""),
        ("rename-b64: src/old.bin -> src/new.bin", base64.b64encode(b"new\r\n").decode("ascii") + "\n"),
        ("delete: src/gone.js", ""),
        ("head: src/keep.test.ts", "kept, modified\n"),
        ("head: docs/read me.md", "spaces in a path\n"),
        ("head-b64: assets/added.bin", base64.b64encode(b"\xff\xfe").decode("ascii")),
    )


def test_parser_reads_every_section_kind():
    data = full_case()
    case = VG.parse_case(data, "i197/A13")
    assert case.input_sha256 == hashlib.sha256(data).hexdigest()
    assert case.meta == {"issue": "197", "row": "A13"} and case.issue == 197
    assert case.options == {"today": "2026-10-02", "task": "TASK.md", "fail_on": "warn",
                            "expect_config_errors": ["config.toml: bad"], "expect_skipped": ["broken.py"]}
    assert case.threshold == "warn"
    assert case.base["assets/blob.bin"] == b"\x00\x01binary\r\n"
    assert case.base["TASK.md"] == b"Title\n=====\n\n=== not a header\n"
    assert set(case.base) == {"TASK.md", "src/value.test.ts", "src/keep.test.ts", "src/gone.js", "src/same.js",
                              "assets/blob.bin", "src/old.bin"}
    assert case.head == {
        "TASK.md": case.base["TASK.md"], "assets/blob.bin": b"\x00\x01binary\r\n",
        "src/value2.test.ts": b"#!/bin/sh\ntest('y', () => {});\n", "lib/same.js": b"same\n",
        "src/new.bin": b"new\r\n", "src/keep.test.ts": b"kept, modified\n",
        "docs/read me.md": b"spaces in a path\n", "assets/added.bin": b"\xff\xfe",
    }
    assert [op["op"] for op in case.ops] == ["rename", "rename-same", "rename-b64", "delete", "head", "head",
                                             "head-b64"]


def test_section_bodies_are_exact_bytes():
    case = VG.parse_case(vgcase(("base: a.txt", ""), ("base: b.txt", "one\n\n"),
                                ("head: a.txt", "no final newline")), "f/r")
    assert case.base == {"a.txt": b"", "b.txt": b"one\n\n"}
    assert case.head["a.txt"] == b"no final newline"
    assert case.options == VG._default_options() and case.threshold == "high" and case.meta == {}


@pytest.mark.parametrize("sections,needle", [
    ([("base: a", "x\n"), ("head: a", "y\n"), ("meta", "k: 1\n"), ("meta", "k: 2\n")], "second meta"),
    ([("meta: x", "")], "takes no argument"),
    ([("meta", "no colon here\n"), ("head: a", "y\n")], "is not 'key: value'"),
    ([("meta", "k: 1\nk: 2\n"), ("head: a", "y\n")], "appears twice"),
    ([("options", "colour = 1\n"), ("head: a", "y\n")], "unknown option"),
    ([("options", "today = \"2026-02-30\"\n"), ("head: a", "y\n")], "not a valid date"),
    ([("options", "today = 2026-10-02T10:00:00\n"), ("head: a", "y\n")], "YYYY-MM-DD"),
    ([("options", "fail_on = \"severe\"\n"), ("head: a", "y\n")], "fail_on must be one of"),
    ([("options", "fail_on = [\"high\"]\n"), ("head: a", "y\n")], "fail_on must be one of"),
    ([("options", "task = \"-x\"\n"), ("head: -x", "y\n")], "starts with '-'"),
    ([("options", "expect_skipped = \"x\"\n"), ("head: a", "y\n")], "list of strings"),
    ([("options", "task = \"TASK.md\"\n"), ("head: a", "y\n")], "is not a file at HEAD"),
    ([("options", "not toml ===\n"), ("head: a", "y\n")], "not valid TOML"),
    ([("base: a", "x\n"), ("base: a", "x\n"), ("head: b", "y\n")], "appears twice"),
    ([("base: a", "x\n"), ("head: a", "x\n")], "does not change it"),
    ([("base: a", "x\n")], "changes nothing"),
    ([("delete: a", "")], "not a base file"),
    ([("base: a", "x\n"), ("delete: a", "body\n")], "empty body"),
    ([("base: a", "x\n"), ("rename-same: a -> b", "body\n")], "empty body"),
    ([("rename: a -> b", "x\n")], "not a base file"),
    ([("base: a", "x\n"), ("base: b", "y\n"), ("rename: a -> b", "z\n")], "already exists in base"),
    ([("base: a", "x\n"), ("rename: a -> a", "z\n")], "same path"),
    ([("base: a", "x\n"), ("rename: a b", "z\n")], "OLD -> NEW"),
    ([("base: a", "x\n"), ("delete: a", ""), ("head: a", "y\n")], "more than one section"),
    ([("base: a", "x\n"), ("rename: a -> b", "z\n"), ("head: b", "y\n")], "more than one section"),
    ([("head: ../escape", "x\n")], "'..'"),
    ([("head: /abs", "x\n")], "absolute"),
    ([("head: a\\b", "x\n")], "not portable"),
    ([("head: .git/config", "x\n")], "enters .git"),
    ([("head: a//b", "x\n")], "empty"),
    ([("head: dir/con.txt", "x\n")], "reserved Windows device"),
    ([("head: CONIN$", "x\n")], "reserved Windows device"),
    ([("head: lpt" + chr(0xB2) + ".txt", "x\n")], "reserved Windows device"),
    ([("head: cafe" + chr(0x301) + ".txt", "x\n")], "NFC"),
    ([("head: trailing. ", "x\n")], "whitespace"),
    ([("head: A.txt", "x\n"), ("head: a.txt", "y\n")], "differ only in case"),
    ([("head: a", "x\n"), ("head: a/b", "y\n")], "both a file and a directory"),
    ([("head: Src/a", "x\n"), ("head: src/b", "y\n")], "differ only in case"),
    ([("base: A.js", "x\n"), ("rename-same: A.js -> a.js", "")], "letter case"),
    ([("head-b64: a", "!!!\n")], "invalid base64"),
    ([("unknown: a", "x\n")], "unknown section header"),
])
def test_parser_rejections(sections, needle):
    with pytest.raises(VG.GateError) as caught:
        VG.parse_case(vgcase(*sections), "f/r")
    assert needle in str(caught.value) and str(caught.value).startswith("f/r")


@pytest.mark.parametrize("data,needle", [
    (b"\xef\xbb\xbf=== head: a ===\nx\n", "BOM"),
    (b"=== head: a ===\r\nx\r\n", "carriage return"),
    (b"=== head: a ===\n\xff\n", "not UTF-8"),
    (b"preamble\n=== head: a ===\nx\n", "before the first section"),
    (b"just text\n", "no section headers"),
    (b"=== base: a ===\nx\n=== head: b === \ny\n", "malformed section header"),
    (b"=== base: a ===\nx\n===head: b===\ny\n", "malformed section header"),
    (b"=== base: a ===\nx\n=== Head: b ===\ny\n", "unknown section header"),
])
def test_parser_rejects_encodings_and_preambles(data, needle):
    with pytest.raises(VG.GateError) as caught:
        VG.parse_case(data, "f/r")
    assert needle in str(caught.value)


def test_case_threshold_follows_option_then_base_config():
    config = ("base: .checkwash/config.toml", '[gate]\nfail_on = "critical"\n')
    assert VG.parse_case(vgcase(config, ("head: a", "x\n")), "f/r").threshold == "critical"
    assert VG.parse_case(vgcase(("options", 'fail_on = "info"\n'), config, ("head: a", "x\n")),
                         "f/r").threshold == "info"
    broken = ("base: .checkwash/config.toml", "[gate\n")
    assert VG.parse_case(vgcase(broken, ("head: a", "x\n")), "f/r").threshold == "high"
    # Read as the engine reads it: a BOM is stripped (issue #71), odd shapes mean the default.
    bom = ("base: .checkwash/config.toml", chr(0xFEFF) + '[gate]\nfail_on = "critical"\n')
    assert VG.parse_case(vgcase(bom, ("head: a", "x\n")), "f/r").threshold == "critical"
    for body in ('[gate]\nfail_on = ["high"]\n', 'gate = 3\n', '[gate]\nfail_on = "severe"\n'):
        shaped = ("base: .checkwash/config.toml", body)
        assert VG.parse_case(vgcase(shaped, ("head: a", "x\n")), "f/r").threshold == "high"


def test_load_cases_layout_ids_and_errors(tmp_path):
    cases = tmp_path / "cases"
    write(cases / "i197/A5.vgcase", "=== head: a ===\nx\n")
    write(cases / "i196/M0.vgcase", "=== head: b ===\ny\n")
    write(cases / "i198/H1.vgcase", "=== bogus ===\n")
    write(cases / "README.md", "stray\n")
    write(cases / "i199/deep/M1.vgcase", "=== head: a ===\nx\n")
    loaded, invalid, errors = VG.load_cases(cases)
    assert [case.id for case in loaded] == ["i196/M0", "i197/A5"]
    assert invalid == ["i198/H1"]
    assert len(errors) == 3
    assert any("README.md: unexpected file" in error for error in errors)
    assert any("i199/deep/M1.vgcase: unexpected file" in error for error in errors)
    assert any(error.startswith("i198/H1:") for error in errors)
    with pytest.raises(VG.GateError):
        VG.load_cases(tmp_path / "missing")
    empty = tmp_path / "empty"
    empty.mkdir()
    assert VG.load_cases(empty)[2] == ["no .vgcase files under the cases directory"]


def chai_record(record_id, verdict="block", path=None, before="expect(x).to.equal(1);\n",
                after="expect(x).to.exist;\n"):
    return {"id": record_id, "path": path or f"test/{record_id}.spec.js", "before": before, "after": after,
            "kind": "weakening" if verdict == "block" else "preserving", "verdict": verdict,
            "rule": "ASSERT_WEAKENED" if verdict == "block" else None,
            "severity": "high" if verdict == "block" else None}


def test_chai_block_records_become_t3_cases(tmp_path):
    records = [chai_record("c1"), chai_record("c2", "pass"), chai_record("c3")]
    path = tmp_path / "chai.json"
    write(path, json.dumps({"schema_version": 1, "mutations": records}))
    cases, info = VG.load_chai_cases(path)
    assert [case.id for case in cases] == ["chai:c1", "chai:c3"]
    assert cases[0].tier == "T3" and cases[0].label == "block"
    assert cases[0].input_sha256 == hashlib.sha256(
        json.dumps(records[0], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert cases[0].base == {"test/c1.spec.js": b"expect(x).to.equal(1);\n"}
    assert cases[0].head == {"test/c1.spec.js": b"expect(x).to.exist;\n"}
    assert info["block_records"] == 2 and info["other_records"] == 1
    for bad in ('{"mutations": [{"id": "a"}, {"id": "a"}]}', '{"mutations": [], "mutations": []}',
                '{"mutations": {}}', json.dumps({"mutations": [records[0], records[0]]}),
                json.dumps({"mutations": [chai_record("c9", after="expect(x).to.equal(1);\n")]})):
        write(path, bad)
        with pytest.raises(VG.GateError):
            VG.load_chai_cases(path)
    with pytest.raises(VG.GateError, match="cannot read"):
        VG.load_chai_cases(tmp_path / "absent.json")


# ---------------------------------------------------------------- labels, pins and acceptance files

PIN = {"tag": "v0.5.0", "version": "0.5.0", "commit": "c" * 40, "sha256": SHA_B, "size": 588886}


def test_acceptance_file_schema(tmp_path):
    good = [entry("i197/A5", "known-regression", issue=197),
            {**entry("i198/H1", "fp-fix", issue=None), "reviewed_in": 15},
            entry("i199/M8", "pending-ruling", issue=199)]
    path = write_acceptance(tmp_path / "accepted.toml", "v0.5.0", good)
    loaded = VG.load_acceptance(path)
    assert loaded["baseline"] == "v0.5.0"
    assert [item["case"] for item in loaded["entries"]] == ["i197/A5", "i198/H1", "i199/M8"]
    assert [item["index"] for item in loaded["entries"]] == [1, 2, 3]
    write(path, 'baseline = "v0.5.0"\n')
    assert VG.load_acceptance(path)["entries"] == []


@pytest.mark.parametrize("change,needle", [
    ({"kind": "regression"}, "kind must be one of"),
    ({"issue": None, "kind": "known-regression"}, "missing key(s) issue"),
    ({"issue": None, "kind": "pending-ruling"}, "missing key(s) issue"),
    ({"issue": True}, "positive issue number"),
    ({"issue": 0}, "positive issue number"),
    ({"reason": "<why this pass is accepted>"}, "filled-in"),
    ({"reason": " "}, "filled-in"),
    ({"reviewed_in": "<number of the PR that adds this entry>"}, "reviewed_in"),
    ({"reviewed_in": "PR 12"}, "reviewed_in"),
    ({"input_sha256": "ABC"}, "64 lowercase hex"),
    ({"extra": "x"}, "unknown key(s) extra"),
])
def test_acceptance_file_rejections(tmp_path, change, needle):
    item = {**entry("i197/A5", "known-regression"), **change}
    item = {key: value for key, value in item.items() if value is not None}
    path = write_acceptance(tmp_path / "accepted.toml", "v0.5.0", [item])
    with pytest.raises(VG.GateError) as caught:
        VG.load_acceptance(path)
    assert needle in str(caught.value)


def test_acceptance_file_needs_a_baseline_and_valid_toml(tmp_path):
    path = tmp_path / "accepted.toml"
    for text, needle in (("", "missing key(s) baseline"), ('baseline = "v0.5.0"\nfoo = 1\n', "unknown key"),
                         ("baseline = \n", "not valid TOML"), ('baseline = "v0.5.0"\naccept = 3\n', "array of tables")):
        write(path, text)
        with pytest.raises(VG.GateError) as caught:
            VG.load_acceptance(path)
        assert needle in str(caught.value)


def test_pins_file_schema(tmp_path):
    path = write_pins(tmp_path / "baseline.toml", PIN, blocked={"count": 3, "sha256": SHA_A},
                      canary_old={**PIN, "tag": "v0.4.2", "version": "0.4.2"}, canary_new=PIN,
                      block_to_pass=["i197/A5", "i196/M0"])
    pins = VG.load_pins(path)
    assert pins["baseline"] == PIN and pins["baseline_blocked"] == {"count": 3, "sha256": SHA_A}
    assert pins["canary"]["block_to_pass"] == ["i196/M0", "i197/A5"]
    assert VG.load_pins(write_pins(tmp_path / "bare.toml", PIN))["canary"] is None


@pytest.mark.parametrize("pin,needle", [
    ({**PIN, "tag": "v0.5.1"}, "'v' + version"),
    ({**PIN, "version": "0.5", "tag": "v0.5"}, "MAJOR.MINOR.PATCH"),
    ({**PIN, "commit": "24b60a2"}, "full lowercase commit"),
    ({**PIN, "sha256": "b305bc3f"}, "64 lowercase hex"),
    ({**PIN, "size": True}, "positive integer"),
    ({**PIN, "size": 0}, "positive integer"),
    ({**PIN, "url": "x"}, "unknown key(s) url"),
])
def test_pins_file_rejections(tmp_path, pin, needle):
    with pytest.raises(VG.GateError) as caught:
        VG.load_pins(write_pins(tmp_path / "baseline.toml", pin))
    assert needle in str(caught.value)


def test_pins_file_rejects_duplicate_canary_ids_and_bad_blocked(tmp_path):
    with pytest.raises(VG.GateError, match="duplicate"):
        VG.load_pins(write_pins(tmp_path / "a.toml", PIN, canary_old=PIN, canary_new=PIN, block_to_pass=["x", "x"]))
    with pytest.raises(VG.GateError, match="non-negative"):
        VG.load_pins(write_pins(tmp_path / "b.toml", PIN, blocked={"count": -1, "sha256": SHA_A}))


def test_pins_file_t3_map(tmp_path):
    pins = VG.load_pins(write_pins(tmp_path / "a.toml", PIN, t3={"chai:c2": SHA_B, "chai:c1": SHA_A}))
    assert pins["t3"] == {"chai:c1": SHA_A, "chai:c2": SHA_B}
    with pytest.raises(VG.GateError, match="chai:<id>"):
        VG.load_pins(write_pins(tmp_path / "b.toml", PIN, t3={"i197/A5": SHA_A}))
    with pytest.raises(VG.GateError, match="64 lowercase hex"):
        VG.load_pins(write_pins(tmp_path / "c.toml", PIN, t3={"chai:c1": "abc"}))


def test_t3_changes_are_named_against_the_pin():
    pinned = {"chai:c1": SHA_A, "chai:c2": SHA_A, "chai:c3": SHA_A}
    same = VG.compare_t3(dict(pinned), pinned)
    assert same["failures"] == [] and same["proposal"] is None
    assert same["changes"] == {"added": [], "dropped": [], "rehashed": []}
    observed = {"chai:c1": SHA_A, "chai:c2": SHA_B, "chai:c4": SHA_A}
    drift = VG.compare_t3(observed, pinned)
    assert [item["code"] for item in drift["failures"]] == ["t3-drift"]
    assert drift["changes"] == {"added": ["chai:c4"], "dropped": ["chai:c3"], "rehashed": ["chai:c2"]}
    assert drift["proposal"] == observed
    unpinned = VG.compare_t3(observed, None)
    assert [item["code"] for item in unpinned["failures"]] == ["t3-unpinned"] and unpinned["proposal"] == observed
    assert VG.compare_t3(None, pinned) == {"failures": [], "changes": None, "proposal": None}
    toml_text = VG.render_proposals({"t3_cases": observed})
    assert toml_text.startswith("# pins file\n[t3.cases]\n\"chai:c1\" = ")


def test_labels_file_schema(tmp_path):
    assert VG.load_labels(write_labels(tmp_path / "l.toml", {"i197/A5": "block", "i196/M0": "undecided"})) == {
        "i196/M0": "undecided", "i197/A5": "block"}
    with pytest.raises(VG.GateError, match="allowed"):
        VG.load_labels(write_labels(tmp_path / "bad.toml", {"i197/A5": "blocked"}))
    write(tmp_path / "v2.toml", "schema_version = 2\n[labels]\n")
    with pytest.raises(VG.GateError, match="schema_version"):
        VG.load_labels(tmp_path / "v2.toml")


# ---------------------------------------------------------------- the rules (pure)

@pytest.mark.parametrize("label,kind", [("block", "known-regression"), ("pass", "fp-fix"),
                                        ("undecided", "pending-ruling")])
def test_transition_without_an_entry_fails_and_proposes_one(label, kind):
    rows = [row("i1/A", "block", "pass", issue=197)]
    result = rules(rows, {"i1/A": label})
    assert codes(result) == [("unlisted-pass", "i1/A")]
    assert result["rows"][0]["needs_entry"] == (["transition", "label-anchor"] if label == "block" else ["transition"])
    proposal = result["proposed_entries"][0]
    assert proposal["case"] == "i1/A" and proposal["kind"] == kind and proposal["input_sha256"] == SHA_A
    assert proposal["issue"] == 197


def test_label_anchor_needs_an_entry_when_the_baseline_already_passes():
    result = rules([row("i1/A", "pass", "pass")], {"i1/A": "block"})
    assert codes(result) == [("unlisted-pass", "i1/A")]
    assert result["rows"][0]["needs_entry"] == ["label-anchor"]
    assert result["proposed_entries"][0]["issue"] == 0  # unknown issue: pasting it unedited fails the schema


def test_undecided_only_removes_the_anchor():
    rows = [row("i1/A", "pass", "pass"), row("i1/B", "pass", "pass")]
    result = rules(rows, {"i1/A": "undecided", "i1/B": "pass"})
    assert codes(result) == []
    assert [(item["code"], item["case"]) for item in result["reported"]] == [("undecided", "i1/A")]
    assert result["reported"][0]["message"] == "baseline pass, candidate pass"


def test_listed_passes_with_the_matching_kind_are_accepted():
    rows = [row("i1/A", "block", "pass"), row("i1/B", "block", "pass"), row("i1/C", "block", "pass"),
            row("i1/D", "pass", "pass")]
    labels = {"i1/A": "block", "i1/B": "pass", "i1/C": "undecided", "i1/D": "block"}
    result = rules(rows, labels, acceptance(entry("i1/A", "known-regression"), entry("i1/B", "fp-fix", issue=None),
                                            entry("i1/C", "pending-ruling"), entry("i1/D", "known-regression")))
    assert codes(result) == []
    assert [item["entry"]["state"] for item in result["rows"]] == ["accepted"] * 4
    assert result["proposed_entries"] == []


@pytest.mark.parametrize("rows,labels,entries,expected", [
    ([row("i1/A", "block", "block")], {"i1/A": "block"}, [entry("i1/A", "known-regression")],
     [("entry-not-needed", "i1/A")]),
    ([row("i1/A", "pass", "pass")], {"i1/A": "pass"}, [entry("i1/A", "fp-fix")],
     [("entry-not-needed", "i1/A")]),
    ([row("i1/A", "pass", "pass")], {"i1/A": "undecided"}, [entry("i1/A", "pending-ruling")],
     [("entry-not-needed", "i1/A")]),
    ([row("i1/A", "block", "pass")], {"i1/A": "block"}, [entry("i1/A", "known-regression", sha=SHA_B)],
     [("entry-input-changed", "i1/A")]),
    ([row("i1/A", "pass", "pass")], {"i1/A": "pass"}, [entry("i1/Z", "fp-fix")],
     [("entry-unknown-case", "i1/Z")]),
    ([row("i1/A", "block", "pass")], {"i1/A": "block"},
     [entry("i1/A", "known-regression"), entry("i1/A", "known-regression")], [("entry-duplicate", "i1/A")]),
], ids=["blocks-again", "neither-rule", "undecided-neither-rule", "input-changed", "unknown-case", "duplicate"])
def test_stale_entries_fail(rows, labels, entries, expected):
    result = rules(rows, labels, acceptance(*entries))
    assert codes(result) == expected
    if expected[0][0] in ("entry-not-needed", "entry-input-changed"):
        assert result["rows"][0]["entry"]["state"] == "stale"
        assert "stale entry" in result["failures"][0]["message"]


def test_stale_entry_message_says_why():
    again = rules([row("i1/A", "block", "block")], {"i1/A": "block"}, acceptance(entry("i1/A", "known-regression")))
    assert "the candidate blocks it again" in again["failures"][0]["message"]
    neither = rules([row("i1/A", "pass", "pass")], {"i1/A": "pass"}, acceptance(entry("i1/A", "fp-fix")))
    assert "neither the transition nor the label anchor applies" in neither["failures"][0]["message"]


@pytest.mark.parametrize("label,kind", [
    ("block", "fp-fix"), ("block", "pending-ruling"), ("pass", "known-regression"), ("pass", "pending-ruling"),
    ("undecided", "known-regression"), ("undecided", "fp-fix"),
])
def test_kind_inconsistent_with_the_label_fails(label, kind):
    result = rules([row("i1/A", "block", "pass")], {"i1/A": label}, acceptance(entry("i1/A", kind)))
    assert codes(result) == [("entry-kind", "i1/A")]


def test_acceptance_baseline_must_equal_the_pin():
    result = rules([row("i1/A", "pass", "pass")], {"i1/A": "pass"}, acceptance(baseline="v0.4.2"))
    assert codes(result) == [("acceptance-baseline", None)]


def test_engine_integrity_failures_stop_rule_evaluation():
    broken = obs("pass", errors=["exit 2 (expected 0 or 1): checkwash engine error"])
    rows = [row("i1/A", None, None, runs={"baseline": obs("block"), "candidate": broken})]
    result = rules(rows, {"i1/A": "block"}, acceptance(entry("i1/A", "known-regression")), baseline_blocked=None)
    assert codes(result) == [("engine-run", "i1/A")]
    assert result["rows"][0]["rules"].startswith("not evaluated: candidate: exit 2")
    assert result["rows"][0]["entry"] == {"kind": "known-regression", "state": "not evaluated"}
    assert result["baseline_blocked"] is None  # not computed, and no unpinned failure on top


def test_missing_observations_fail_unless_the_cause_is_recorded():
    rows = [row("i1/A", None, None, runs={"baseline": obs("block")})]
    assert codes(rules(rows, {"i1/A": "block"}, baseline_blocked=None)) == [("engine-run", "i1/A")]
    rows[0]["not_run"] = "engine identity failed"
    result = rules(rows, {"i1/A": "block"}, baseline_blocked=None)
    assert codes(result) == []
    assert result["rows"][0]["rules"] == "not evaluated: candidate not run: engine identity failed"


@pytest.mark.parametrize("declared,actual_errors,actual_skipped,expected", [
    ({}, [], [], []),
    ({}, ["config.toml: gate.fail_on must be one of"], [], [("config-errors", "i1/A")] * 2),
    ({}, [], ["broken.py"], [("skipped-files", "i1/A")] * 2),
    ({"expect_skipped": ["broken.py"]}, [], ["broken.py"], []),
    ({"expect_skipped": ["broken.py"]}, [], [], [("skipped-files", "i1/A")] * 2),
    ({"expect_config_errors": ["e"]}, ["e"], [], []),
    ({"expect_config_errors": ["e"]}, ["e", "f"], [], [("config-errors", "i1/A")] * 2),
    ({"expect_skipped": ["b.py", "a.py"]}, [], ["a.py", "b.py"], []),  # the same set in another order
])
def test_config_errors_and_skipped_files_must_match_the_declaration(declared, actual_errors, actual_skipped, expected):
    runs = {role: obs("pass", config_errors=actual_errors, skipped=actual_skipped) for role in VG.GATE_ROLES}
    rows = [row("i1/A", None, None, runs=runs, **declared)]
    assert codes(rules(rows, {"i1/A": "pass"})) == expected


def test_a_shared_observation_fails_once_under_the_engine_that_ran_it():
    shared = obs("pass", skipped=["x.py"])
    rows = [row("i1/A", None, None, runs={role: shared for role in VG.ROLES})]
    gate = rules(rows, {"i1/A": "pass"})
    assert [(item["code"], item["message"].split(":")[0]) for item in gate["failures"]] == [
        ("skipped-files", "baseline")]
    canary = VG.evaluate_canary(rows, pinned=["i1/A"], checked_roles=VG.GATE_ROLES)
    assert canary["failures"] == [] and canary["block_to_pass"] is None  # still not evaluated
    alone = VG.evaluate_canary(rows, pinned=["i1/A"])
    assert [(item["code"], item["message"].split(":")[0]) for item in alone["failures"]] == [
        ("skipped-files", "canary-old")]


def test_labels_cover_t1_exactly():
    rows = [row("i1/A", "pass", "pass"), row("chai:c1", "block", "block", tier="T3", label="block")]
    result = rules(rows, {"i1/Z": "pass", "chai:c1": "block", "i1/broken": "block"}, invalid_ids=["i1/broken"])
    assert codes(result) == [("label-missing", "i1/A"), ("label-unknown", "chai:c1"), ("label-unknown", "i1/Z")]
    assert result["baseline_blocked"] is None  # an unparseable case makes the pinned set unverifiable


def test_t3_record_label_anchors_chai_passes():
    rows = [row("chai:c1", "block", "pass", tier="T3", label="block")]
    result = rules(rows, {})
    assert codes(result) == [("unlisted-pass", "chai:c1")]
    assert result["proposed_entries"][0]["kind"] == "known-regression"
    assert codes(rules(rows, {}, acceptance(entry("chai:c1", "fp-fix")))) == [("entry-kind", "chai:c1")]
    assert codes(rules(rows, {}, acceptance(entry("chai:c1", "known-regression")))) == []


def test_baseline_blocked_pin_unpinned_drift_and_match():
    rows = [row("i1/A", "block", "block"), row("i1/B", "pass", "pass"), row("i1/C", "block", "block")]
    labels = {"i1/A": "block", "i1/B": "pass", "i1/C": "block"}
    matched = rules(rows, labels)
    assert codes(matched) == []
    assert matched["baseline_blocked"] == {"count": 2, "sha256": VG.digest(["i1/A", "i1/C"])}
    assert matched["baseline_blocked_ids"] == ["i1/A", "i1/C"]
    assert codes(rules(rows, labels, baseline_blocked=None)) == [("baseline-blocked-unpinned", None)]
    drift = rules(rows, labels, baseline_blocked={"count": 2, "sha256": VG.digest(["i1/A", "i1/B"])})
    assert codes(drift) == [("baseline-blocked-drift", None)]
    assert codes(rules(rows, labels, baseline_blocked=None, complete=False)) == []


def test_reported_not_failed():
    b4_before = [["TEST_DISABLED", "high", "t.test.js"], ["TEST_DISABLED", "high", "t.test.js"]]
    b4_after = [["CI_WORKFLOW_TOUCHED", "high", ".github/workflows/ci.yml"]]
    warn_only = [["ASSERT_WEAKENED", "warn", "t.test.js"]]
    rows = [
        row("i1/A", "pass", "block"),
        row("i1/B", None, None, runs={"baseline": obs("block", findings=b4_before),
                                      "candidate": obs("block", findings=b4_after)}),
        row("i1/C", None, None, runs={"baseline": obs("block", findings=b4_after + warn_only, blocking=b4_after),
                                      "candidate": obs("block", findings=b4_after, blocking=b4_after)}),
        row("i1/D", "block", "block"),
    ]
    result = rules(rows, {"i1/A": "pass", "i1/B": "block", "i1/C": "block", "i1/D": "undecided"})
    assert codes(result) == []
    assert [(item["code"], item["case"]) for item in result["reported"]] == [
        ("blocking-findings-changed", "i1/B"), ("pass-to-block", "i1/A"), ("undecided", "i1/D")]
    assert "TEST_DISABLED" in result["reported"][0]["message"]
    assert "CI_WORKFLOW_TOUCHED" in result["reported"][0]["message"]


# ---------------------------------------------------------------- canary (pure)

def canary_row(case_id, old, new, **kwargs):
    return row(case_id, None, None, runs={"canary-old": obs(old, **kwargs), "canary-new": obs(new)})


def test_canary_set_comparison():
    rows = [canary_row("i1/A", "block", "pass"), canary_row("i1/B", "block", "block"),
            canary_row("i1/C", "pass", "pass"), canary_row("i1/D", "block", "pass")]
    exact = VG.evaluate_canary(rows, pinned=["i1/D", "i1/A"])
    assert exact["failures"] == [] and exact["block_to_pass"] == ["i1/A", "i1/D"]
    mismatch = VG.evaluate_canary(rows, pinned=["i1/A", "i1/B"])
    assert [(item["code"], item["case"]) for item in mismatch["failures"]] == [("canary-mismatch", None)]
    assert "missing ['i1/B']" in mismatch["failures"][0]["message"]
    assert "unexpected ['i1/D']" in mismatch["failures"][0]["message"]
    unpinned = VG.evaluate_canary(rows, pinned=None)
    assert [item["code"] for item in unpinned["failures"]] == ["canary-unpinned"]
    assert unpinned["block_to_pass"] == ["i1/A", "i1/D"]


def test_canary_integrity_failure_blocks_the_comparison():
    rows = [canary_row("i1/A", "block", "pass", errors=["timeout after 120 s"])]
    result = VG.evaluate_canary(rows, pinned=["i1/A"])
    assert [(item["code"], item["case"]) for item in result["failures"]] == [("engine-run", "i1/A")]
    assert result["block_to_pass"] is None


# ---------------------------------------------------------------- tag rule

@pytest.mark.parametrize("pushed,tags,highest", [
    ("v0.6.0", ["v0.4.2", "v0.5.0", "v0.6.0"], "v0.5.0"),
    ("v0.10.0", ["v0.9.0", "v0.10.0", "v0.2.0"], "v0.9.0"),
    ("v1.0.0", ["v1.0.0"], None),
    ("v0.6.0", ["v0.5.0", "v0.6.0", "v0.7.0-rc1", "vnext"], "v0.5.0"),
])
def test_highest_other_tag(pushed, tags, highest):
    found, ignored = VG.highest_other_tag(pushed, tags)
    assert found == highest
    assert ignored == sorted(tag for tag in tags if not VG._SEMVER_TAG.fullmatch(tag))


def test_tag_rule_reads_merged_tags(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    VG._git(repo, "init", "-q", "-b", "main")
    commits = {}
    for tag in ("v0.4.2", "v0.5.0", "v0.6.0"):
        write(repo / "VERSION", tag + "\n")
        VG._git(repo, "add", "--all")
        VG._git(repo, "commit", "-q", "-m", tag)
        VG._git(repo, "tag", tag)
        commits[tag] = VG._git_text(repo, "rev-parse", "HEAD")
    pin = {**PIN, "commit": commits["v0.5.0"]}
    assert VG.check_tag_rule(repo, "v0.6.0", pin)[0] == []
    errors, info = VG.check_tag_rule(repo, "v0.6.0", {**PIN, "tag": "v0.4.2", "commit": commits["v0.4.2"]})
    assert info["highest_other"] == "v0.5.0"
    assert any("is not the highest other v* tag" in error for error in errors)
    assert any("not the pinned commit" in error for error in VG.check_tag_rule(repo, "v0.6.0",
                                                                               {**PIN, "commit": "d" * 40})[0])
    assert any("not merged into HEAD" in error for error in VG.check_tag_rule(repo, "v0.7.0", pin)[0])
    assert VG.check_tag_rule(repo, "release", pin)[0] == ["pushed tag 'release' is not vX.Y.Z"]
    # A descendant of the pushed tag is not the exact tagged SHA.
    write(repo / "VERSION", "after the tag\n")
    VG._git(repo, "commit", "-q", "-am", "after v0.6.0")
    errors = VG.check_tag_rule(repo, "v0.6.0", pin)[0]
    assert errors == [f"HEAD {VG._git_text(repo, 'rev-parse', 'HEAD')} is not the commit of the pushed tag "
                      f"v0.6.0 ({commits['v0.6.0']})"]


# ---------------------------------------------------------------- materialization

def test_materialize_builds_the_declared_two_commit_repo(tmp_path):
    case = VG.parse_case(vgcase(
        ("base: .checkwash/config.toml", '[roles]\ntest = ["**/*.test.js"]\n'),
        ("base: .gitignore", "*.log\n"),
        ("base: src/a.test.js", "a\n"),
        ("base: src/b.test.js", "b\n"),
        ("base: src/c.js", "c\n"),
        ("base-b64: bin/data.bin", base64.b64encode(b"\x00\r\n").decode("ascii") + "\n"),
        ("rename-same: src/a.test.js -> test/a.test.js", ""),
        ("rename: src/b.test.js -> test/b2.test.js", "completely different content\n"),
        ("delete: src/c.js", ""),
        ("head: out.log", "ignored by .gitignore, still committed\n"),
        ("head: docs/read me.md", "x\n"),
    ), "i1/A")
    repo = tmp_path / "repo with spaces"
    shape = VG.materialize(case, repo)
    assert ["R100", "src/a.test.js", "test/a.test.js"] in shape
    assert ["D", "src/b.test.js"] in shape and ["A", "test/b2.test.js"] in shape
    assert ["D", "src/c.js"] in shape and ["A", "out.log"] in shape and ["A", "docs/read me.md"] in shape
    assert VG._git_text(repo, "rev-list", "--count", "HEAD") == "2"
    assert VG._git(repo, "show", "HEAD~1:.checkwash/config.toml") == case.base[".checkwash/config.toml"]
    assert VG._git(repo, "show", "HEAD:bin/data.bin") == b"\x00\r\n"
    assert sorted(VG._tree_listing(repo, "HEAD")) == sorted(case.head)
    assert sorted(VG._tree_listing(repo, "HEAD~1")) == sorted(case.base)
    assert not (repo / "src").exists()
    # The engine's own git calls read the repository config, not the harness's -c flags.
    for key, value in VG.REPO_CONFIG:
        assert VG._git_text(repo, "config", "--local", "--get", key) == value
    attributes = Path(VG._git_text(repo, "config", "--local", "--get", "core.attributesFile"))
    assert attributes.read_bytes() == b""
    with pytest.raises(VG.GateError, match="not empty"):
        VG.materialize(case, repo)


def test_materialize_failures_become_messages(tmp_path):
    long_name = VG.Case(id="i1/L", tier="T1", input_sha256=SHA_A, meta={}, options=VG._default_options(),
                        base={"a.txt": b"a\n"}, head={"a.txt": b"a\n", "n" * 300 + ".txt": b"x\n"},
                        ops=[{"op": "head", "path": "n" * 300 + ".txt"}])
    shape, problem = VG.materialize_safely(long_name, tmp_path / "repo")
    assert shape is None and problem.startswith("i1/L: cannot write the case repository: ")
    assert str(tmp_path) not in problem and tmp_path.as_posix() not in problem
    (tmp_path / "busy").mkdir()
    (tmp_path / "busy" / "f").write_text("x", encoding="utf-8")
    assert VG.materialize_safely(long_name, tmp_path / "busy") == (None, "i1/L: materialization target is not empty")
    assert VG.remove_safely(tmp_path / "busy") is None and not (tmp_path / "busy").exists()


def test_materialize_swaps_files_and_directories(tmp_path):
    to_dir = VG.parse_case(vgcase(("base: a", "file\n"), ("delete: a", ""), ("head: a/b", "nested\n")), "i1/B")
    assert VG.materialize(to_dir, tmp_path / "one") == [["D", "a"], ["A", "a/b"]]
    to_file = VG.parse_case(vgcase(("base: d/x", "nested\n"), ("delete: d/x", ""), ("head: d", "file\n")), "i1/C")
    assert VG.materialize(to_file, tmp_path / "two") == [["A", "d"], ["D", "d/x"]]


# ---------------------------------------------------------------- engine identity

def test_identity_of_a_matching_engine(tmp_path):
    fake = make_engine(tmp_path, "baseline", "0.5.0", {})
    record = VG.verify_identity(engine_for(fake), tmp_path / "work")
    assert record["errors"] == []
    assert record["sha256"] == fake.pin["sha256"] and record["size"] == fake.pin["size"]
    assert record["source_commit"] == fake.pin["commit"] and record["cli_version"] == "checkwash 0.5.0"
    assert record["controls"] == {"clean_range": "ok", "invalid_ref": "ok"}
    assert record["members"] == 3 and record["proposed_pin"] is None
    candidate = VG.verify_identity(engine_for(fake, "candidate", pin=None), tmp_path / "work2", reuse=record)
    assert candidate["errors"] == [] and candidate["expected_version"] == "0.5.0"
    assert candidate["controls_from"] == "baseline"


@pytest.mark.parametrize("change,needles,proposed", [
    ({"sha256": SHA_A}, ["differs from the pinned " + SHA_A], True),
    ({"size": 1}, ["size"], True),
    ({"commit": "d" * 40}, ["not the pinned " + "d" * 40], False),
    ({"version": "0.4.2", "tag": "v0.4.2"}, ["source version 0.5.0 differs from the pinned 0.4.2"], False),
])
def test_identity_pin_mismatches_fail_before_running(tmp_path, change, needles, proposed):
    fake = make_engine(tmp_path, "baseline", "0.5.0", {})
    record = VG.verify_identity(engine_for(fake, pin={**fake.pin, **change}), tmp_path / "work")
    for needle in needles:
        assert any(needle in error for error in record["errors"]), record["errors"]
    assert record["cli_version"] is None and record["controls"]["clean_range"] == "not run"
    assert (record["proposed_pin"] == {"sha256": fake.pin["sha256"], "size": fake.pin["size"]}) is proposed


def test_identity_member_mismatch_is_not_a_repin(tmp_path):
    fake = make_engine(tmp_path, "baseline", "0.5.0", {})
    with zipfile.ZipFile(fake.pyz, "a") as archive:
        archive.writestr("checkwash/extra.py", "# smuggled\n")
    record = VG.verify_identity(engine_for(fake), tmp_path / "work")
    assert any(error.startswith("sha256 ") for error in record["errors"])
    assert any("members does not match source package: checkwash/extra.py" in error for error in record["errors"])
    # New bytes whose members differ from the pinned commit are a release incident, never a re-pin.
    assert record["proposed_pin"] is None and record["cli_version"] is None


@pytest.mark.parametrize("name", ["json.py", "checkwash/cli.pyc", "checkwash\\cli.py", "__main__.py"])
def test_identity_binds_the_members_outside_the_package(tmp_path, name):
    fake = make_engine(tmp_path, "baseline", "0.5.0", {})
    if name == "__main__.py":
        zipapp.create_archive(fake.source / "src", fake.pyz, main="checkwash.cli:entry")
    else:
        with zipfile.ZipFile(fake.pyz, "a") as archive:
            info = zipfile.ZipInfo("placeholder")
            info.filename = name  # set after construction: ZipInfo maps os.sep to '/' on Windows
            archive.writestr(info, "# smuggled\n")
    record = VG.verify_identity(engine_for(fake), tmp_path / "work")
    # New bytes with an unbound member are a release incident, never a re-pin, and never run.
    assert record["proposed_pin"] is None and record["cli_version"] is None
    if name == "checkwash\\cli.py":
        # zipfile reads the name back as 'checkwash/cli.py' on Windows: a duplicate member there.
        assert any("backslash" in error or "duplicate" in error for error in record["errors"]), record["errors"]
    else:
        assert any(name in error for error in record["errors"]), record["errors"]


def test_identity_unreadable_archive_is_an_identity_failure(tmp_path):
    fake = make_engine(tmp_path, "baseline", "0.5.0", {})
    zipapp.create_archive(fake.source / "src", fake.pyz, main="checkwash.zipapp_entry:run", compressed=True)
    with zipfile.ZipFile(fake.pyz) as archive:
        info = archive.getinfo("checkwash/cli.py")
    data = bytearray(fake.pyz.read_bytes())
    name_length, extra_length = struct.unpack("<HH", data[info.header_offset + 26:info.header_offset + 30])
    data[info.header_offset + 30 + name_length + extra_length] = 0xFF  # deflate block type 3 is invalid
    fake.pyz.write_bytes(bytes(data))
    record = VG.verify_identity(engine_for(fake), tmp_path / "work")
    assert any(error.startswith("artifact unreadable as a zip: ") for error in record["errors"]), record["errors"]
    assert record["proposed_pin"] is None and record["cli_version"] is None


def test_identity_counts_ignored_files_in_the_source_package(tmp_path):
    fake = make_engine(tmp_path, "baseline", "0.5.0", {})
    write(fake.source / ".git/info/exclude", "__pycache__/\n*.pyc\nstray.txt\n")
    write(fake.source / "src/checkwash/__pycache__/cli.cpython-312.pyc", "bytecode")
    assert VG.source_changes(fake.source) == []  # bytecode is skipped, as package_files skips it
    write(fake.source / "src/checkwash/stray.txt", "ignored, yet packaged by zipapp\n")
    assert VG.source_changes(fake.source) == ["src/checkwash/stray.txt"]
    record = VG.verify_identity(engine_for(fake), tmp_path / "work")
    assert any("local changes" in error for error in record["errors"]), record["errors"]


def test_identity_rejects_local_source_changes_and_missing_files(tmp_path):
    fake = make_engine(tmp_path, "baseline", "0.5.0", {})
    with (fake.source / "src/checkwash/cli.py").open("a", encoding="utf-8") as stream:
        stream.write("# edited after the build\n")
    record = VG.verify_identity(engine_for(fake), tmp_path / "work")
    assert any("local changes" in error for error in record["errors"])
    assert any("members does not match" in error for error in record["errors"])
    missing = VG.verify_identity(VG.Engine("candidate", sys.executable, tmp_path / "none.pyz", fake.source),
                                 tmp_path / "work2")
    assert missing["errors"] and "cannot read artifact" in missing["errors"][0]


def test_identity_version_output_mismatch(tmp_path):
    fake = make_engine(tmp_path, "baseline", "0.5.0", {}, printed="0.4.2")
    record = VG.verify_identity(engine_for(fake), tmp_path / "work")
    assert record["errors"] == ["--version printed 'checkwash 0.4.2' with exit 0; expected 'checkwash 0.5.0'"]


@pytest.mark.parametrize("fault,needle", [
    ({"clean": False}, "clean-range control: verdict 'block' with exit 1"),
    ({"invalid": False}, "invalid-ref control: exit 0"),
])
def test_identity_failed_controls(tmp_path, fault, needle):
    fake = make_engine(tmp_path, "baseline", "0.5.0", {}, **fault)
    record = VG.verify_identity(engine_for(fake), tmp_path / "work")
    assert any(error.startswith(needle) for error in record["errors"]), record["errors"]


# ---------------------------------------------------------------- engine runs

def test_engine_run_timeout_and_repository_changes(tmp_path):
    fake = make_engine(tmp_path, "baseline", "0.5.0", {
        "slow": {"verdict": "pass", "sleep": 30},
        "writer": {"verdict": "pass", "touch": "new-file.txt"},
    })
    engine = engine_for(fake)
    for key, needle, timeout in (("slow", "timeout after 1 s", 1), ("writer", "engine changed the case repository", 60)):
        case = VG.parse_case(vgcase(("base: CASE", key + "\n"), ("head: a.txt", "x\n")), "i1/" + key)
        repo = tmp_path / key
        VG.materialize(case, repo)
        observed = VG.run_engine(engine, "0.5.0", case, repo, timeout=timeout)
        assert observed["errors"] == [needle]


# ---------------------------------------------------------------- end to end

def e2e_inputs(tmp_path, *, red=False):
    finding = {"rule": "ASSERT_WEAKENED", "severity": "high", "path": "src/a.test.js"}
    disabled = {"rule": "TEST_DISABLED", "severity": "high", "path": "test/c.test.js"}
    touched = {"rule": "CI_WORKFLOW_TOUCHED", "severity": "high", "path": "test/c.test.js"}
    dated = {"args": ["--task", "TASK.md", "--fail-on", "warn"],
             "env": {"CHECKWASH_TODAY": "2026-03-04", "GREENWASH_TODAY": "2026-03-04"}}
    plain_env = {"env": {"CHECKWASH_TODAY": None, "GREENWASH_TODAY": "2026-01-01"}}
    chai = [chai_record("c1"), chai_record("c2", "pass")] if not red else [chai_record("c2", "pass")]
    baseline_table = {
        "A1": {"verdict": "block", "findings": [finding], **plain_env},
        "A2": {"verdict": "pass", **dated},
        "A3": {"verdict": "block", "findings": [disabled, disabled]},
        "A4": {"verdict": "pass", "skipped": ["broken.py"]},
        "path:test/c1.spec.js": {"verdict": "block", "findings": [finding]},
    }
    candidate_table = {
        "A1": {"verdict": "pass", **plain_env},
        "A2": {"verdict": "pass", **dated},
        "A3": {"verdict": "block", "findings": [touched]},
        "A4": {"verdict": "pass", "skipped": ["broken.py"]},
        "path:test/c1.spec.js": {"verdict": "block", "findings": [finding]},
    }
    baseline = make_engine(tmp_path, "baseline", "0.5.0", baseline_table, chai=chai)
    candidate = make_engine(tmp_path, "candidate", "0.6.0", candidate_table)
    cases = tmp_path / "cases dir"
    write(cases / "i900/A1.vgcase", "=== meta ===\nissue: 900\n=== base: CASE ===\nA1\n"
                                    "=== base: src/a.test.js ===\nexpect(x).toBe(1);\n"
                                    "=== head: src/a.test.js ===\nexpect(x).toBeTruthy();\n")
    labels = {"i900/A1": "block"}
    if not red:
        write(cases / "i900/A2.vgcase", '=== options ===\ntoday = 2026-03-04\ntask = "TASK.md"\nfail_on = "warn"\n'
                                        "=== base: CASE ===\nA2\n=== base: TASK.md ===\n# Task\n"
                                        "=== head: docs/read me.md ===\nnotes\n")
        write(cases / "i900/A3.vgcase", "=== base: CASE ===\nA3\n=== base: .checkwash/config.toml ===\n"
                                        '[gate]\nfail_on = "high"\n=== base: src/c.test.js ===\nit.skip();\n'
                                        "=== rename-same: src/c.test.js -> test/c.test.js ===\n")
        write(cases / "i900/A4.vgcase", '=== options ===\nexpect_skipped = ["broken.py"]\n'
                                        "=== base: CASE ===\nA4\n=== head: broken.py ===\ndef (:\n")
        labels.update({"i900/A2": "pass", "i900/A3": "block", "i900/A4": "undecided"})
    labels_path = write_labels(tmp_path / "labels.toml", labels)
    a1_sha = hashlib.sha256((cases / "i900/A1.vgcase").read_bytes()).hexdigest()
    accepted = tmp_path / "accepted.toml"
    if red:
        pins = write_pins(tmp_path / "baseline.toml", baseline.pin, canary_old=baseline.pin, canary_new=candidate.pin)
    else:
        write_acceptance(accepted, "v0.5.0", [{"case": "i900/A1", "input_sha256": a1_sha, "kind": "known-regression",
                                               "issue": 900, "reason": "regression shipped in v0.5.0",
                                               "reviewed_in": "1"}])
        blocked = ["chai:c1", "i900/A1", "i900/A3"]
        pins = write_pins(tmp_path / "baseline.toml", baseline.pin,
                          blocked={"count": 3, "sha256": VG.digest(blocked)}, t3={"chai:c1": VG.digest(chai[0])},
                          canary_old=baseline.pin, canary_new=candidate.pin, block_to_pass=["i900/A1"])
    return SimpleNamespace(baseline=baseline, candidate=candidate, cases=cases, labels=labels_path,
                           accepted=accepted, pins=pins, a1_sha=a1_sha)


def gate_argv(inputs, tmp_path):
    argv = ["gate", "--pins", str(inputs.pins), "--cases", str(inputs.cases), "--labels", str(inputs.labels),
            "--accepted", str(inputs.accepted), "--python", sys.executable,
            "--work-dir", str(tmp_path / "work dir"), "--receipt", str(tmp_path / "out/receipt.json"),
            "--summary", str(tmp_path / "out/summary.md"), "--context", "run_id=42"]
    for role, fake in (("baseline", inputs.baseline), ("candidate", inputs.candidate),
                       ("canary-old", inputs.baseline), ("canary-new", inputs.candidate)):
        argv += [f"--{role}-pyz", str(fake.pyz), f"--{role}-source", str(fake.source)]
    return argv


def strings(value):
    """Every key and string value inside a parsed receipt."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)
    elif isinstance(value, str):
        yield value


def test_gate_end_to_end_passes_through_the_cli(tmp_path):
    inputs = e2e_inputs(tmp_path)
    # T3 comes from the pinned commit, so an edit in the baseline checkout's working tree changes nothing.
    write(inputs.baseline.source / VG.CHAI_PATH, json.dumps({"schema_version": 1, "mutations": [
        chai_record("c1"), chai_record("c2", "pass"), chai_record("c3")]}))
    result = subprocess.run([sys.executable, str(TOOL), *gate_argv(inputs, tmp_path)],
                            capture_output=True, text=True, timeout=600)
    receipt = json.loads((tmp_path / "out/receipt.json").read_text(encoding="utf-8"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert receipt["status"] == "passed" and receipt["failures"] == []
    assert receipt["context"] == {"run_id": "42"}
    assert receipt["summary"]["cases"] == 5 and receipt["summary"]["t1"] == 4 and receipt["summary"]["t3"] == 1
    assert receipt["inputs"]["t3"]["block_records"] == 1 and receipt["inputs"]["t3"]["other_records"] == 1
    assert receipt["inputs"]["t3"]["commit"] == inputs.baseline.pin["commit"]
    assert receipt["observed"]["t3_changes"] == {"added": [], "dropped": [], "rehashed": []}
    assert [(item["code"], item["case"]) for item in receipt["reported"]] == [
        ("blocking-findings-changed", "i900/A3"), ("undecided", "i900/A4")]
    rows = {item["id"]: item for item in receipt["cases"]}
    assert rows["i900/A1"]["transition"] == "block->pass" and rows["i900/A1"]["canary_transition"] == "block->pass"
    assert rows["i900/A1"]["needs_entry"] == ["transition", "label-anchor"]
    assert rows["i900/A1"]["entry"] == {"kind": "known-regression", "state": "accepted"}
    assert rows["i900/A1"]["input_sha256"] == inputs.a1_sha
    assert rows["i900/A3"]["git_shape"] == [["R100", "src/c.test.js", "test/c.test.js"]]
    assert rows["i900/A3"]["runs"]["baseline"]["blocking"] == [["TEST_DISABLED", "high", "test/c.test.js"]] * 2
    assert rows["chai:c1"]["label"] == "block" and set(rows["chai:c1"]["runs"]) == {"baseline", "candidate"}
    assert set(rows["i900/A2"]["runs"]) == set(VG.ROLES)
    engines = receipt["engines"]
    assert engines["canary-old"]["observations_from"] == "baseline"
    assert engines["canary-new"]["observations_from"] == "candidate"
    assert engines["canary-old"]["controls_from"] == "baseline"
    assert engines["candidate"]["expected_version"] == "0.6.0"
    assert receipt["observed"]["baseline_blocked_ids"] == ["chai:c1", "i900/A1", "i900/A3"]
    assert receipt["observed"]["canary_block_to_pass"] == ["i900/A1"]
    # Every pin matches, so nothing is proposed.
    assert receipt["proposed"]["accept_entries"] == [] and receipt["proposed"]["toml"] == ""
    assert receipt["proposed"]["baseline_blocked"] is None and receipt["proposed"]["canary_block_to_pass"] is None
    summary = (tmp_path / "out/summary.md").read_text(encoding="utf-8")
    assert summary.startswith("## verdict gate (gate): PASSED")
    assert "| i900/A1 | T1 | block | block->pass | block->pass | known-regression (accepted) | evaluated |" in summary
    assert "Proposed entries and pins" not in summary
    host_paths = {str(tmp_path), tmp_path.as_posix(), str(tmp_path.resolve()), tmp_path.resolve().as_posix()}
    assert not [text for text in strings(receipt) if any(path in text for path in host_paths)]


def test_gate_first_run_is_red_and_prints_ready_to_paste_proposals(tmp_path):
    inputs = e2e_inputs(tmp_path, red=True)
    engines = {"baseline": (inputs.baseline.pyz, inputs.baseline.source),
               "candidate": (inputs.candidate.pyz, inputs.candidate.source),
               "canary-old": (inputs.baseline.pyz, inputs.baseline.source),
               "canary-new": (inputs.candidate.pyz, inputs.candidate.source)}
    receipt = VG.run_gate(mode="gate", pins_path=inputs.pins, cases_dir=inputs.cases, engines=engines,
                          labels_path=inputs.labels, accepted_path=inputs.accepted, work_dir=tmp_path / "work")
    assert receipt["status"] == "failed"
    assert sorted((item["code"], item["case"]) for item in receipt["failures"]) == [
        ("acceptance-missing", None), ("baseline-blocked-unpinned", None), ("canary-unpinned", None),
        ("t3-unpinned", None), ("unlisted-pass", "i900/A1")]
    proposed = receipt["proposed"]
    assert proposed["accept_entries"] == [{
        "case": "i900/A1", "input_sha256": inputs.a1_sha, "kind": "known-regression", "issue": 900,
        "reason": "<why this pass is accepted>", "reviewed_in": "<number of the PR that adds this entry>"}]
    assert proposed["baseline_blocked"] == {"count": 1, "sha256": VG.digest(["i900/A1"])}
    assert proposed["canary_block_to_pass"] == ["i900/A1"]
    assert proposed["t3_cases"] == {}  # the red fixture's chai file has no block record
    assert 'case         = "i900/A1"' in proposed["toml"] and "issue        = 900" in proposed["toml"]
    assert "[t3.cases]" in proposed["toml"]
    # Pasted unedited, the placeholders fail the schema instead of silently accepting.
    pasted = tmp_path / "pasted.toml"
    write(pasted, 'baseline = "v0.5.0"\n' + proposed["toml"].split("# pins file")[0])
    with pytest.raises(VG.GateError, match="filled-in"):
        VG.load_acceptance(pasted)
    receipt_path = tmp_path / "receipt.json"
    VG._write_json(receipt_path, receipt)
    printed = subprocess.run([sys.executable, str(TOOL), "propose", "--receipt", str(receipt_path)],
                             capture_output=True, text=True, timeout=120)
    assert printed.returncode == 0 and printed.stdout == proposed["toml"]
    assert "### Proposed entries and pins" in VG.render_summary(receipt)


def test_gate_runs_no_case_when_an_identity_fails(tmp_path):
    inputs = e2e_inputs(tmp_path, red=True)
    write_pins(inputs.pins, {**inputs.baseline.pin, "sha256": SHA_A}, canary_old=inputs.baseline.pin,
               canary_new=inputs.candidate.pin)
    engines = {"baseline": (inputs.baseline.pyz, inputs.baseline.source),
               "candidate": (inputs.candidate.pyz, inputs.candidate.source),
               "canary-old": (inputs.baseline.pyz, inputs.baseline.source),
               "canary-new": (inputs.candidate.pyz, inputs.candidate.source)}
    receipt = VG.run_gate(mode="gate", pins_path=inputs.pins, cases_dir=inputs.cases, engines=engines,
                          labels_path=inputs.labels, accepted_path=inputs.accepted, work_dir=tmp_path / "work")
    assert receipt["status"] == "failed"
    assert ("engine-identity", None) in [(item["code"], item["case"]) for item in receipt["failures"]]
    assert all(item["runs"] == {} and item["not_run"] == "engine identity failed" for item in receipt["cases"])
    assert receipt["proposed"]["engine_pins"] == {
        "baseline": {"sha256": inputs.baseline.pin["sha256"], "size": inputs.baseline.pin["size"]}}


def test_gate_records_unparseable_cases_and_the_tag_rule(tmp_path):
    inputs = e2e_inputs(tmp_path, red=True)
    write(inputs.cases / "i900/BAD.vgcase", "=== bogus ===\n")
    # Identity fails on purpose (pinned sha256 differs): neither wiring depends on a case run.
    write_pins(inputs.pins, {**inputs.baseline.pin, "sha256": SHA_A}, canary_old=inputs.baseline.pin,
               canary_new=inputs.candidate.pin)
    repo = tmp_path / "tagged repo"
    repo.mkdir()
    VG._git(repo, "init", "-q", "-b", "main")
    for tag in ("v0.5.0", "v0.6.0", "v0.7.0"):
        write(repo / "VERSION", tag + "\n")
        VG._git(repo, "add", "--all")
        VG._git(repo, "commit", "-q", "-m", tag)
        VG._git(repo, "tag", tag)
    engines = {"baseline": (inputs.baseline.pyz, inputs.baseline.source),
               "candidate": (inputs.candidate.pyz, inputs.candidate.source),
               "canary-old": (inputs.baseline.pyz, inputs.baseline.source),
               "canary-new": (inputs.candidate.pyz, inputs.candidate.source)}
    receipt = VG.run_gate(mode="gate", pins_path=inputs.pins, cases_dir=inputs.cases, engines=engines,
                          labels_path=inputs.labels, accepted_path=inputs.accepted, work_dir=tmp_path / "work",
                          tag_run="v0.7.0", repo=repo)
    failures = [(item["code"], item["case"]) for item in receipt["failures"]]
    assert receipt["status"] == "failed"
    assert ("case-invalid", None) in failures
    assert any(item["code"] == "case-invalid" and item["message"].startswith("i900/BAD:")
               for item in receipt["failures"])
    tag_messages = [item["message"] for item in receipt["failures"] if item["code"] == "tag-baseline"]
    assert any("is not the highest other v* tag merged into HEAD (v0.6.0)" in message for message in tag_messages)
    assert any("not the pinned commit" in message for message in tag_messages)
    assert receipt["tag_rule"]["highest_other"] == "v0.6.0"
    assert "i900/BAD" not in [item["id"] for item in receipt["cases"]]


def test_context_keys_are_unique():
    assert VG._context(["run_id=42", "event=push", "note=a=b"]) == {"run_id": "42", "event": "push", "note": "a=b"}
    for values in (["run_id=1", "run_id=2"], ["no separator"], ["=value"]):
        with pytest.raises(SystemExit):
            VG._context(values)


def test_canary_mode_is_deterministic(tmp_path):
    old = make_engine(tmp_path, "old", "0.4.2", {"K1": {"verdict": "block"}, "K2": {"verdict": "pass"}})
    new = make_engine(tmp_path, "new", "0.5.0", {"K1": {"verdict": "pass"}, "K2": {"verdict": "pass"}})
    cases = tmp_path / "cases"
    write(cases / "i1/K1.vgcase", "=== base: CASE ===\nK1\n=== head: x.js ===\nx\n")
    write(cases / "i1/K2.vgcase", "=== base: CASE ===\nK2\n=== head: y.js ===\ny\n")
    pins = write_pins(tmp_path / "pins.toml", new.pin, canary_old=old.pin, canary_new=new.pin,
                      block_to_pass=["i1/K1"])
    engines = {"canary-old": (old.pyz, old.source), "canary-new": (new.pyz, new.source)}
    first = VG.run_gate(mode="canary", pins_path=pins, cases_dir=cases, engines=engines)
    second = VG.run_gate(mode="canary", pins_path=pins, cases_dir=cases, engines=engines)
    assert first["status"] == "passed", first["failures"]
    assert first == second
    assert [item["canary_transition"] for item in first["cases"]] == ["block->pass", "pass->pass"]
    assert first["observed"]["canary_block_to_pass"] == ["i1/K1"]
    assert first["proposed"]["canary_block_to_pass"] is None and first["proposed"]["toml"] == ""


def test_cases_and_materialize_commands_run_no_engine(tmp_path):
    cases = tmp_path / "cases"
    write(cases / "i1/A.vgcase", "=== base: a.js ===\na\n=== rename-same: a.js -> b.js ===\n")
    labels = write_labels(tmp_path / "labels.toml", {"i1/A": "block", "i1/gone": "pass"})
    listed = subprocess.run([sys.executable, str(TOOL), "cases", "--cases", str(cases), "--labels", str(labels)],
                            capture_output=True, text=True, timeout=120)
    assert listed.returncode == 1
    output = json.loads(listed.stdout)
    assert output["cases"][0]["id"] == "i1/A" and output["cases"][0]["label"] == "block"
    assert output["errors"] == ["i1/gone: label for an unknown case"]
    built = subprocess.run([sys.executable, str(TOOL), "materialize", "--case", str(cases / "i1/A.vgcase"),
                            "--out", str(tmp_path / "repo")], capture_output=True, text=True, timeout=120)
    assert built.returncode == 0, built.stdout + built.stderr
    assert json.loads(built.stdout) == {"case": "i1/A", "git_shape": [["R100", "a.js", "b.js"]]}
