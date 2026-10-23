"""Validate owner-admitted PJU receipts as data, then publish required Checks.

This is an evidence bridge, not a hardware attestation service. An authenticated
repository owner admits an immutable receipt commit and its manifest digest.
No candidate Python, shell, Action, archive member, or test is executed here.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tarfile
import tomllib
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

REPOSITORY = "taipei49314/checkwash"
HOST = "LAPTOP-01AGNPJU"
PROVENANCE = "HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL"
ACTION_SHA = "d6eda4f695fabb8e7d138f7a87b099d2028f0294"
CONTEXTS = ("checkwash", *(f"candidate assertion contract ({d})" for d in ("source", "wheel", "pyz")))
CONTRACTS = ("tests/data/javascript_assertion_support.json", "tests/data/javascript_foundation_mutations.json")
UTILITIES = ("tools/assertion_contract.py", "tools/qualify_assertions.py", "tools/release_inventory.py")
REQUIRED_EXITS = {"pytest", "action-dogfood", "build-wheel", "build-pyz",
                  *(f"{step}-{d}" for step in ("qualify", "inventory") for d in ("source", "wheel", "pyz"))}
MAX_FILE = 256 * 1024 * 1024
MAX_TOTAL = 1024 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def exact_keys(value, names, label):
    require(type(value) is dict and set(value) == set(names.split()), label + " fields differ")


def integer(value, label, minimum=0):
    require(type(value) is int and value >= minimum, label + " must be an integer")
    return value


def sha(value, length=64):
    require(type(value) is str and re.fullmatch(r"[0-9a-f]{" + str(length) + r"}", value), "invalid digest")
    return value


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return digest(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def same(left, right):
    """JSON identity must not equate true/1 or 1.0/1."""
    return canonical(left) == canonical(right)


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON key: " + key)
            result[key] = value
        return result

    def constant(value):
        raise ValueError("non-finite JSON number: " + value)

    return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)


def safe_path(value):
    require(type(value) is str and bool(value) and "\\" not in value and ":" not in value
            and "\x00" not in value and not value.startswith("/")
            and all(part not in ("", ".", "..") and part.lower() != ".git"
                    for part in value.split("/")), "unsafe receipt path")
    require(PurePosixPath(value).as_posix() == value, "noncanonical receipt path")
    return value


def regular(path, directory=False):
    info = path.lstat()
    require(not stat.S_ISLNK(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400,
            "symlink/reparse point in receipt")
    require(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode), "nonregular receipt member")


class Packet:
    def __init__(self, root, expected_digest):
        self.root = Path(root).absolute()
        regular(self.root, directory=True)
        regular(self.root / "manifest.json")
        require((self.root / "manifest.json").stat().st_size <= 8 * 1024 * 1024, "oversized manifest")
        raw = (self.root / "manifest.json").read_bytes()
        require(digest(raw) == sha(expected_digest), "external manifest digest mismatch")
        self.manifest = strict_json(raw)
        self.files = {}
        rows = self.manifest.get("files") if type(self.manifest) is dict else None
        require(type(rows) is list and 0 < len(rows) <= 5000, "invalid file inventory")
        total = 0
        folded = set()
        for row in rows:
            exact_keys(row, "path sha256 bytes", "file")
            name = safe_path(row["path"])
            require(name != "manifest.json" and name.casefold() not in folded, "duplicate/reserved receipt path")
            folded.add(name.casefold())
            size = integer(row["bytes"], "file bytes")
            require(size <= MAX_FILE, "oversized receipt member")
            total += size
            require(total <= MAX_TOTAL, "oversized receipt")
            self.files[name] = row
        actual = set()
        for directory, dirs, files in os.walk(self.root, followlinks=False):
            regular(Path(directory), directory=True)
            for name in dirs:
                regular(Path(directory) / name, directory=True)
            for name in files:
                path = Path(directory) / name
                regular(path)
                actual.add(path.relative_to(self.root).as_posix())
        require(actual == set(self.files) | {"manifest.json"}, "unlisted or missing receipt data")
        for name, row in self.files.items():
            path = self.root / name
            require(path.stat().st_size == row["bytes"] and digest(path.read_bytes()) == sha(row["sha256"]),
                    "receipt bytes mismatch: " + name)

    def raw(self, name):
        safe_path(name)
        require(name in self.files, "unlisted referenced evidence: " + name)
        raw = (self.root / name).read_bytes()
        row = self.files[name]
        require(len(raw) == row["bytes"] and digest(raw) == row["sha256"], "evidence changed during validation")
        return raw

    def json(self, name):
        return strict_json(self.raw(name))


def git(root, *args):
    # Only fixed Git read operations are called; never hooks, checkout or helpers.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0")
    result = subprocess.run(["git", "-C", str(root), *args], env=env, capture_output=True, timeout=60)
    require(result.returncode == 0, "Git evidence read failed")
    return result.stdout


def tree_files(root, commit, prefix):
    result = {}
    for row in git(root, "ls-tree", "-r", "-z", commit + ":" + prefix if prefix else commit).split(b"\0"):
        if not row:
            continue
        header, name_raw = row.split(b"\t", 1)
        mode, kind, oid = header.decode("ascii").split()
        name = safe_path(name_raw.decode("utf-8"))
        require(mode in ("100644", "100755") and kind == "blob", "nonregular source member")
        raw = git(root, "cat-file", "blob", oid)
        require(hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == oid,
                "Git blob identity mismatch")
        result[name] = raw
    require(bool(result), "empty Git source tree")
    return result


def validate_contract(packet, descriptor_path, source_root, trusted_root, head, source_tree, collector):
    desc = packet.json(descriptor_path)
    exact_keys(desc, "schema_version kind collector_source_sha contract_source_sha source_commit source_tree src_tree "
                    "source_package_sha256 version suite_sha256 cases inventories source_members builder_sha256", "contract descriptor")
    require(type(desc["schema_version"]) is int and desc["schema_version"] == 1
            and desc["kind"] == "checkwash.pju-contract.v1", "contract descriptor schema")
    require(desc["collector_source_sha"] == desc["contract_source_sha"] == collector
            and desc["source_commit"] == head and desc["source_tree"] == source_tree, "contract identity mismatch")
    require(git(source_root, "rev-parse", "HEAD").decode().strip() == head, "candidate checkout SHA mismatch")
    require(git(source_root, "rev-parse", head + "^{tree}").decode().strip() == source_tree, "candidate tree mismatch")
    require(desc["src_tree"] == git(source_root, "rev-parse", head + ":src").decode().strip(), "src tree mismatch")
    inventories, cases = [], []
    for path in (*UTILITIES, *CONTRACTS):
        raw = git(source_root, "show", head + ":" + path)
        require(raw == git(trusted_root, "show", collector + ":" + path), "candidate differs from audited contract/tool: " + path)
        if path in CONTRACTS:
            data = strict_json(raw)
            require(type(data.get("schema_version")) is int and data["schema_version"] == 1
                    and type(data.get("mutations")) is list and data["mutations"], "empty/malformed contract inventory")
            cases.extend(data["mutations"])
            inventories.append(dict(path=path, sha256=digest(raw), mutations=len(data["mutations"])))
    require(same(desc["cases"], cases) and desc["suite_sha256"] == canonical(cases), "case universe/suite mismatch")
    require(same(desc["inventories"], inventories), "contract inventory mismatch")
    require(all(type(case) is dict and type(case.get("id")) is str and case["id"] for case in cases)
            and len({case["id"] for case in cases}) == len(cases), "duplicate/missing case IDs")
    source = tree_files(source_root, head, "src")
    proof = {name: dict(git_blob=hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest(),
                        sha256=digest(raw), bytes=len(raw)) for name, raw in source.items()}
    require(same(desc["source_members"], proof), "source member proof mismatch")
    package = {name: digest(raw) for name, raw in source.items() if name.startswith("checkwash/")
               and "__pycache__" not in PurePosixPath(name).parts and not name.endswith(".pyc")}
    require(package and desc["source_package_sha256"] == canonical(package), "source package digest mismatch")
    project = tomllib.loads(git(source_root, "show", head + ":pyproject.toml").decode("utf-8"))["project"]
    require(desc["version"] == "checkwash " + project["version"], "version mismatch")
    require(desc["builder_sha256"] == digest(git(trusted_root, "show", collector + ":tools/release_inventory.py")),
            "builder digest mismatch")
    return desc


def validate_qualification(value, desc, distribution):
    exact_keys(value, "schema_version distribution status suite_sha256 source_commit inventories source_package_sha256 "
                     "source_package_dirty artifact_sha256 version cases errors summary", "qualification")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1, "qualification schema")
    require(value["distribution"] == distribution and value["status"] == "passed" and value["errors"] == [], "qualification failed")
    for key in ("suite_sha256", "inventories", "source_package_sha256", "version"):
        require(same(value[key], desc[key]), "qualification " + key + " mismatch")
    require(value["source_commit"] == desc["source_commit"] and value["source_package_dirty"] is False,
            "qualification source identity/cleanliness mismatch")
    cases = value["cases"]
    require(type(cases) is list and len(cases) == len(desc["cases"]), "qualification case completeness")
    require([row.get("id") for row in cases if type(row) is dict] == [row["id"] for row in desc["cases"]],
            "qualification case IDs/order mismatch")
    for row, expected in zip(cases, desc["cases"]):
        exact_keys(row, "id kind expected observed errors status", "qualification case")
        require(row["kind"] == expected["kind"] and row["expected"] == {k: expected[k] for k in ("verdict", "rule", "severity")}
                and row["errors"] == [] and row["status"] == "passed", "case expected outcome mismatch")
        observed = row["observed"]
        exact_keys(observed, "exit verdict findings", "case observation")
        expected_exit = 1 if expected["verdict"] == "block" else 0
        require(type(observed["exit"]) is int and observed["exit"] == expected_exit
                and observed["verdict"] == expected["verdict"], "case raw exit/verdict mismatch")
        findings = [{k: expected[k] for k in ("rule", "severity", "path")}] if expected_exit else []
        require(observed["findings"] == findings, "case findings mismatch")
    exact_keys(value["summary"], "total executed failed", "qualification summary")
    require(all(type(n) is int for n in value["summary"].values())
            and value["summary"] == dict(total=len(cases), executed=len(cases), failed=0), "qualification summary mismatch")
    require(value["artifact_sha256"] is None if distribution == "source" else bool(sha(value["artifact_sha256"])),
            "qualification artifact identity")


def archive_members(raw, name):
    members = {}
    total = 0
    def add(path, contents):
        nonlocal total
        safe_path(path)
        require(path not in members, "duplicate archive member")
        total += len(contents)
        require(total <= MAX_TOTAL, "oversized expanded artifact")
        members[path] = dict(sha256=digest(contents), bytes=len(contents))
    if name.endswith((".whl", ".pyz")):
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            require(len(infos) <= 10000 and len({i.filename for i in infos}) == len(infos), "duplicate/oversized ZIP inventory")
            require(sum(i.file_size for i in infos) <= MAX_TOTAL, "oversized expanded ZIP")
            for info in infos:
                safe_path(info.filename.rstrip("/"))
                require(not stat.S_ISLNK(info.external_attr >> 16) and not info.flag_bits & 1, "unsafe ZIP member")
                if not info.is_dir():
                    add(info.filename, archive.read(info))
    elif name.endswith(".tar.gz"):
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
            names = set()
            for info in archive:
                safe_path(info.name)
                require(info.name not in names and len(names) < 10000, "duplicate/oversized tar inventory")
                names.add(info.name)
                require(info.isfile() or info.isdir(), "unsafe tar member")
                require(info.size <= MAX_FILE and total + info.size <= MAX_TOTAL, "oversized expanded tar")
                if info.isfile():
                    add(info.name, archive.extractfile(info).read())
    else:
        raise ValueError("unsupported artifact format")
    return members


def validate_inventory(packet, value, desc, qualification, qualification_path, distribution):
    exact_keys(value, "schema_version status source_commit distribution run_id attempt python builder builder_sha256 "
                     "builder_source_commit errors artifacts source_tree src_tree source_members qualification", "release inventory")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1
            and value["status"] == "passed" and value["errors"] == [] and value["distribution"] == distribution,
            "release inventory schema/status")
    for key in ("source_commit", "source_tree", "src_tree", "source_members", "builder_sha256"):
        require(same(value[key], desc[key]), "release inventory " + key + " mismatch")
    require(value["builder"] == "tools/release_inventory.py" and value["builder_source_commit"] == desc["collector_source_sha"],
            "untrusted inventory builder")
    require(value["qualification"] == dict(path=PurePosixPath(qualification_path).name,
                                           sha256=digest(packet.raw(qualification_path))), "qualification byte linkage mismatch")
    artifacts = value["artifacts"]
    require(type(artifacts) is list and len(artifacts) == {"source": 0, "wheel": 2, "pyz": 1}[distribution], "artifact completeness")
    formats = []
    for item in artifacts:
        exact_keys(item, "name sha256 bytes members", "artifact")
        name = safe_path(item["name"])
        require("/" not in name, "artifact basename required")
        matches = [path for path in packet.files if PurePosixPath(path).name == name]
        require(len(matches) == 1, "artifact bytes missing/ambiguous")
        raw = packet.raw(matches[0])
        require(type(item["bytes"]) is int and item["bytes"] == len(raw) and item["sha256"] == digest(raw), "artifact identity mismatch")
        require(same(item["members"], archive_members(raw, name)), "artifact member hashes differ")
        formats.append("sdist" if name.endswith(".tar.gz") else PurePosixPath(name).suffix)
        # Check package member bytes independently of the collector's passed flag.
        if name.endswith(".tar.gz"):
            prefixes = {PurePosixPath(p).parts[0] for p in item["members"]}
            require(len(prefixes) == 1, "sdist roots differ")
            prefix = next(iter(prefixes)) + "/src/"
        else:
            prefix = ""
        actual = {p[len(prefix):]: v for p, v in item["members"].items() if p.startswith(prefix + "checkwash/")}
        expected = {p: {k: v[k] for k in ("sha256", "bytes")} for p, v in desc["source_members"].items() if p.startswith("checkwash/")}
        require(same(actual, expected), "delivered package differs from candidate Git source")
    require(sorted(formats) == {"source": [], "wheel": [".whl", "sdist"], "pyz": [".pyz"]}[distribution], "artifact format set")
    if distribution != "source":
        primary = ".whl" if distribution == "wheel" else ".pyz"
        require(len([a for a in artifacts if a["name"].endswith(primary) and a["sha256"] == qualification["artifact_sha256"]]) == 1,
                "qualified artifact differs from delivered primary artifact")


def validate_junit(raw):
    require(b"<!DOCTYPE" not in raw.upper() and b"<!ENTITY" not in raw.upper(), "DTD/entity forbidden in JUnit")
    root = ET.fromstring(raw)
    require(root.tag in ("testsuites", "testsuite"), "JUnit root")
    cases = list(root.iter("testcase"))
    require(cases and any(case.find("skipped") is None for case in cases), "empty/all-skipped JUnit")
    require(not list(root.iter("failure")) and not list(root.iter("error")), "JUnit failures/errors")
    for suite in root.iter("testsuite"):
        direct = list(suite.findall("testcase"))
        require(not suite.findall("testsuite"), "nested JUnit suites unsupported")
        for attr, expected in (("tests", len(direct)), ("failures", 0), ("errors", 0),
                               ("skipped", sum(case.find("skipped") is not None for case in direct))):
            value = suite.get(attr)
            require(value is not None and re.fullmatch(r"[0-9]+", value) and int(value) == expected, "JUnit summary mismatch: " + attr)
    if root.tag == "testsuites":
        for attr, expected in (("tests", len(cases)), ("failures", 0), ("errors", 0),
                               ("skipped", sum(c.find("skipped") is not None for c in cases))):
            if attr in root.attrib:
                value = root.attrib[attr]
                require(re.fullmatch(r"[0-9]+", value) and int(value) == expected, "JUnit aggregate mismatch")
    return {"tests": len(cases), "skipped": sum(c.find("skipped") is not None for c in cases)}


def action_run_blocks(raw):
    """Read the two fixed pinned YAML scalars; fail on any unfamiliar shape."""
    text = raw.decode("utf-8")
    blocks = {}
    for name in ("install", "check"):
        match = re.search(r"(?ms)^    - id: " + name + r"\n(.*?)(?=^    - id: |\Z)", text)
        require(match is not None, "pinned Action step missing")
        content = match.group(1)
        block = re.search(r"(?m)^      run: \|\n((?:        [^\n]*\n|\n)+)", content)
        if block:
            value = "\n".join(line[8:] if line.startswith("        ") else line for line in block.group(1).splitlines()) + "\n"
        else:
            single = re.search(r"(?m)^      run: '([^\n]*)'\n?$", content)
            require(single is not None, "unreviewed Action run scalar")
            value = single.group(1).replace("''", "'")
        blocks[name] = value.encode("utf-8")
    return blocks


def validate_action(packet, records, head, base, trusted_root, action_sha=None):
    action_sha = ACTION_SHA if action_sha is None else action_sha
    receipt = packet.json(records["dogfood"])
    exact_keys(receipt, "action_receipt_version exit_code analysis_exit_code error identity base head fail_on", "Action receipt")
    require(type(receipt["action_receipt_version"]) is int and receipt["action_receipt_version"] == 1, "Action receipt schema")
    require(all(type(receipt[k]) is int and receipt[k] == 0 for k in ("exit_code", "analysis_exit_code"))
            and receipt["error"] is None and receipt["base"] == base and receipt["head"] == head
            and receipt["fail_on"] == "high", "Action dogfood did not pass exact range")
    identity = receipt["identity"]
    exact_keys(identity, "python python_version base_python isolated utf8 bytecode_writes_disabled source_root package_root "
                         "version runtime_files source_digest", "Action identity")
    require(type(identity) is dict and all(identity.get(k) is True for k in ("isolated", "utf8", "bytecode_writes_disabled")), "Action isolation receipt")
    require(identity["python_version"] == packet.manifest["runtime"]["python_version"]
            and all(type(identity[k]) is str and identity[k] for k in ("python", "base_python", "source_root", "package_root")),
            "Action runtime identity mismatch")
    action_package = tree_files(trusted_root, action_sha, "src/checkwash")
    require(identity.get("source_digest") == canonical({p: digest(raw) for p, raw in action_package.items()})
            and type(identity.get("runtime_files")) is int and identity["runtime_files"] == len(action_package), "pinned Action engine identity")
    project = tomllib.loads(git(trusted_root, "show", action_sha + ":pyproject.toml").decode("utf-8"))["project"]
    require(identity.get("version") == project["version"], "Action engine version mismatch")
    replay = packet.json(records["action_replay"])
    exact_keys(replay, "schema_version kind provenance status host action_sha action_tree action_yaml_sha256 base_sha head_sha "
                       "fail_on comment_pr steps resolved_outputs files errors", "Action replay")
    require(type(replay["schema_version"]) is int and replay["schema_version"] == 1
            and replay["kind"] == "checkwash.pju-action-replay.v1" and replay["provenance"] == "PJU_LOCAL_COMPOSITE_REPLAY"
            and replay["status"] == "completed" and replay["errors"] == [] and replay["host"] == HOST
            and replay["action_sha"] == action_sha and replay["head_sha"] == head and replay["base_sha"] == base
            and replay["fail_on"] == "high" and replay["comment_pr"] is False, "Action replay identity/status")
    require(replay["action_tree"] == git(trusted_root, "rev-parse", action_sha + "^{tree}").decode().strip(), "Action tree mismatch")
    parent = PurePosixPath(records["action_replay"]).parent
    def evidence(name):
        return (parent / safe_path(name)).as_posix()
    exact_keys(replay["files"], "action_yaml install_run install_stdout install_stderr check_run check_stdout check_stderr "
                                "identity check_receipt install_report pip_stdout pip_stderr engine_stdout engine_stderr", "Action replay evidence map")
    for path in replay["files"].values():
        packet.raw(evidence(path))
    action_yaml = packet.raw(evidence(replay["files"]["action_yaml"]))
    require(action_yaml == git(trusted_root, "show", action_sha + ":action/action.yml")
            and replay["action_yaml_sha256"] == digest(action_yaml), "Action definition mismatch")
    runs = action_run_blocks(action_yaml)
    require(packet.json(evidence(replay["files"]["check_receipt"])) == receipt
            and packet.json(evidence(replay["files"]["identity"])) == identity, "Action replay identity/receipt linkage")
    install = packet.json(evidence(replay["files"]["install_report"]))
    require(type(install) is dict and install.get("version") == "1" and type(install.get("install")) is list
            and len(install["install"]) == 1 and install["install"][0].get("metadata", {}).get("name") == "checkwash"
            and install["install"][0]["metadata"].get("version") == project["version"], "Action pip installation evidence")
    steps = replay["steps"]
    require(type(steps) is list and [s.get("id") for s in steps if type(s) is dict] == ["install", "check"], "Action step completeness")
    for step in steps:
        exact_keys(step, "id exit_code run_sha256 stdout stderr outputs", "Action step")
        require(type(step["exit_code"]) is int and step["exit_code"] == 0, "Action step failed")
        require(step["run_sha256"] == digest(runs[step["id"]]), "Action run block differs from pinned definition")
        require(packet.raw(evidence(replay["files"][step["id"] + "_run"])) == runs[step["id"]], "Action script bytes mismatch")
        packet.raw(evidence(step["stdout"]))
        packet.raw(evidence(step["stderr"]))
        require(type(step["outputs"]) is dict and bool(step["outputs"]), "Action step outputs missing")
        outputs = {}
        for line in packet.raw(evidence(step["id"] + ".outputs")).decode("utf-8").splitlines():
            require("=" in line and "\x00" not in line, "malformed raw Action output")
            key, value = line.split("=", 1)
            require(key not in outputs and value, "duplicate/empty raw Action output")
            outputs[key] = value
        require(outputs == step["outputs"], "raw Action output mapping differs")
    require(steps[1]["outputs"].get("base") == base and steps[1]["outputs"].get("head") == head
            and steps[1]["outputs"].get("fail_on") == "high" and steps[1]["outputs"].get("analysis_exit_code") == "0",
            "Action step range/analysis output mismatch")
    require(type(replay["resolved_outputs"]) is dict and str(replay["resolved_outputs"].get("exit-code")) == "0", "Action composite exit output")
    resolved = replay["resolved_outputs"]
    exact_keys(resolved, "exit-code receipt-path identity-path", "Action resolved outputs")
    require(resolved == {"exit-code": steps[1]["outputs"].get("exit_code"),
                         "receipt-path": steps[1]["outputs"].get("receipt_path"),
                         "identity-path": steps[0]["outputs"].get("identity_path")}
            and all(type(value) is str and value for value in resolved.values()), "Action output wiring mismatch")


def validate_candidate_action(packet, records, head, base, source_root, trusted_root, collector):
    coverage = packet.json(records["candidate_action_coverage"])
    exact_keys(coverage, "schema_version kind collector_source_sha candidate_sha pinned_action_sha closure_paths "
                        "candidate_closure pinned_closure candidate_closure_sha256 pinned_closure_sha256 mode replay_path",
               "candidate Action coverage")
    require(type(coverage["schema_version"]) is int and coverage["schema_version"] == 1
            and coverage["kind"] == "checkwash.pju-candidate-action-coverage.v1"
            and coverage["collector_source_sha"] == collector and coverage["candidate_sha"] == head
            and coverage["pinned_action_sha"] == ACTION_SHA
            and coverage["closure_paths"] == ["action/", "src/", "pyproject.toml"], "candidate Action coverage identity")
    def closure(root, commit):
        result = {prefix + "/" + name: digest(raw) for prefix in ("action", "src")
                  for name, raw in tree_files(root, commit, prefix).items()}
        result["pyproject.toml"] = digest(git(root, "show", commit + ":pyproject.toml"))
        return result
    candidate = closure(source_root, head)
    pinned = closure(trusted_root, ACTION_SHA)
    require(same(coverage["candidate_closure"], candidate) and same(coverage["pinned_closure"], pinned)
            and coverage["candidate_closure_sha256"] == canonical(candidate)
            and coverage["pinned_closure_sha256"] == canonical(pinned), "Action closure digest mismatch")
    if coverage["mode"] == "byte-identical-reuse":
        require(candidate == pinned and coverage["replay_path"] == records["action_replay"], "unequal Action closure cannot reuse pinned replay")
    else:
        require(coverage["mode"] == "separate-replay" and coverage["replay_path"] != records["action_replay"], "candidate Action replay mode")
        replay_path = safe_path(coverage["replay_path"])
        replay = packet.json(replay_path)
        check_path = (PurePosixPath(replay_path).parent / safe_path(replay["files"]["check_receipt"])).as_posix()
        validate_action(packet, {"dogfood": check_path, "action_replay": replay_path}, head, base, source_root, action_sha=head)


def validate_packet(packet, *, repository, pr, base, head, source_tree, collector, source_root, trusted_root):
    manifest = packet.manifest
    exact_keys(manifest, "schema_version kind repository pr_number base_sha head_sha source_tree host provenance collector_source_sha "
                        "contract_source_sha files records raw_exits status runtime action_sha", "manifest")
    require(type(manifest["schema_version"]) is int and manifest["schema_version"] == 1
            and manifest["kind"] == "checkwash.pju-receipt.v1", "manifest schema")
    require(repository == REPOSITORY and manifest["repository"] == repository and type(manifest["pr_number"]) is int
            and manifest["pr_number"] == integer(pr, "PR", 1), "receipt repository/PR mismatch")
    require(manifest["head_sha"] == sha(head, 40) and manifest["base_sha"] == sha(base, 40)
            and manifest["source_tree"] == sha(source_tree, 40), "receipt source identity mismatch")
    require(manifest["collector_source_sha"] == manifest["contract_source_sha"] == sha(collector, 40), "collector admission mismatch")
    require(manifest["host"] == HOST and manifest["provenance"] == PROVENANCE
            and manifest["status"] == "completed" and manifest["action_sha"] == ACTION_SHA, "receipt host/scope/status")
    runtime = manifest["runtime"]
    exact_keys(runtime, "os python_version python_executable python_sha256 git_executable git_sha256 bash_executable bash_sha256 "
                       "dependencies other_platforms", "runtime")
    require(runtime["os"] == "Windows" and runtime["python_version"] == "3.11.9"
            and runtime["other_platforms"] == "NOT_RUN", "runtime platform scope (Windows/Python 3.11.9)")
    require(all(type(runtime[k]) is str and runtime[k] for k in ("python_version", "python_executable", "git_executable", "bash_executable")), "runtime identity missing")
    for key in ("python_sha256", "git_sha256", "bash_sha256"):
        sha(runtime[key])
    require(type(runtime["dependencies"]) is dict and bool(runtime["dependencies"]), "runtime dependencies missing")
    records = manifest["records"]
    exact_keys(records, "dogfood action_replay candidate_action_coverage junit qualifications inventories contract_descriptor", "records")
    for key in ("qualifications", "inventories"):
        exact_keys(records[key], "source wheel pyz", key)
    desc = validate_contract(packet, records["contract_descriptor"], source_root, trusted_root, head, source_tree, collector)
    exits = manifest["raw_exits"]
    require(type(exits) is list and bool(exits), "raw exits missing")
    names = set()
    for row in exits:
        exact_keys(row, "name argv cwd started_at finished_at duration_seconds exit_code timed_out stdout stderr", "raw exit")
        require(type(row["name"]) is str and row["name"] and row["name"] not in names, "duplicate/missing raw exit")
        names.add(row["name"])
        require(type(row["exit_code"]) is int and row["exit_code"] == 0, "nonzero raw command exit: " + row["name"])
        require(row["timed_out"] is False and type(row["argv"]) is list and row["argv"]
                and all(type(arg) is str for arg in row["argv"])
                and all(type(row[key]) is str and row[key] for key in ("cwd", "started_at", "finished_at")), "raw command identity/timing missing")
        require(type(row["duration_seconds"]) in (int, float) and math.isfinite(row["duration_seconds"])
                and row["duration_seconds"] >= 0, "invalid raw command duration")
        packet.raw(row["stdout"])
        packet.raw(row["stderr"])
    require(REQUIRED_EXITS <= names, "required command evidence missing")
    pytest = next(row for row in exits if row["name"] == "pytest")
    argv = pytest["argv"]
    require(len(argv) == 20 and argv[0] == runtime["python_executable"]
            and argv[1:16] == ["-I", "-B", "-X", "utf8", "-m", "pytest", "-p", "xdist.plugin", "-n", "2",
                              "--dist", "worksteal", "-p", "no:cacheprovider", "--basetemp"]
            and argv[17] == "--junitxml" and argv[19] == "tests"
            and argv[18].replace("\\", "/").endswith("/" + records["junit"]), "full pytest command scope differs")
    junit = validate_junit(packet.raw(records["junit"]))
    validate_action(packet, records, head, base, trusted_root)
    validate_candidate_action(packet, records, head, base, source_root, trusted_root, collector)
    for distribution in ("source", "wheel", "pyz"):
        qpath = records["qualifications"][distribution]
        qualification = packet.json(qpath)
        validate_qualification(qualification, desc, distribution)
        validate_inventory(packet, packet.json(records["inventories"][distribution]), desc, qualification, qpath, distribution)
    return dict(status="verified", repository=repository, pr_number=pr, head_sha=head, base_sha=base,
                source_tree=source_tree, collector_source_sha=collector, host=HOST, provenance=PROVENANCE,
                checks=list(CONTEXTS), qualification_cases=len(desc["cases"]), junit=junit,
                trust="owner-admitted receipt digest; not hardware attestation", other_platforms="NOT_RUN")


class GitHub:
    def __init__(self, token):
        require(bool(token), "GitHub token missing")
        self.token = token

    def request(self, method, path, body=None):
        require(path.startswith("/repos/" + REPOSITORY + "/"), "unexpected GitHub API path")
        request = urllib.request.Request("https://api.github.com" + path, method=method,
            data=None if body is None else json.dumps(body).encode(), headers={
                "Authorization": "Bearer " + self.token, "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json",
                "User-Agent": "checkwash-pju-receipt-bridge"})
        # Do not send the credential to a redirected destination.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as response:
            return strict_json(response.read(8 * 1024 * 1024))


def live_pr(api, repository, pr, head, base):
    require(repository == REPOSITORY, "wrong repository")
    value = api.request("GET", f"/repos/{repository}/pulls/{integer(pr, 'PR', 1)}")
    require(value.get("state") == "open" and value.get("merged") is False
            and value.get("head", {}).get("sha") == head and value.get("base", {}).get("sha") == base
            and value.get("base", {}).get("ref") == "main"
            and value.get("head", {}).get("repo", {}).get("full_name") == repository
            and value.get("base", {}).get("repo", {}).get("full_name") == repository, "stale/closed/foreign PR")
    commit = api.request("GET", f"/repos/{repository}/git/commits/{sha(head, 40)}")
    return sha(commit["tree"]["sha"], 40)


def admit_environment(expected_workflow_sha, env):
    require(env.get("GITHUB_EVENT_NAME") == "workflow_dispatch" and env.get("GITHUB_REPOSITORY") == REPOSITORY
            and env.get("GITHUB_REPOSITORY_OWNER") == "taipei49314"
            and env.get("GITHUB_ACTOR") == "taipei49314" and env.get("GITHUB_TRIGGERING_ACTOR") == "taipei49314",
            "receipt mode requires repository-owner dispatch/rerun")
    require(env.get("GITHUB_SHA") == sha(expected_workflow_sha, 40)
            and env.get("GITHUB_WORKFLOW_SHA") == expected_workflow_sha, "workflow commit admission mismatch")
    require(env.get("GITHUB_WORKFLOW_REF", "").startswith(REPOSITORY + "/.github/workflows/quality-candidate-intake.yml@"),
            "unexpected workflow identity")


def publish(api, report, manifest_sha256, receipt_commit, run_url):
    repository, pr, head, base = (report[k] for k in ("repository", "pr_number", "head_sha", "base_sha"))
    require(report["status"] == "verified" and report["checks"] == list(CONTEXTS), "unverified check publication")
    ids = []
    summary = (f"Real PJU execution: {HOST}; {PROVENANCE}.\n\n"
               f"PR #{pr}; head `{head}`; base `{base}`.\n\nReceipt commit `{receipt_commit}`; manifest SHA256 `{manifest_sha256}`.\n\n"
               f"{report['qualification_cases']} exact contract cases per distribution; JUnit {report['junit']}. "
               "Owner-admitted evidence, not hardware attestation. Other platforms: NOT_RUN.")
    try:
        require(live_pr(api, repository, pr, head, base) == report["source_tree"], "source tree changed")
        for name in CONTEXTS:
            check = api.request("POST", f"/repos/{repository}/check-runs", dict(name=name, head_sha=head,
                status="in_progress", external_id="pju:" + manifest_sha256 + ":" + name, details_url=run_url,
                output=dict(title="PJU evidence verified; publication in progress", summary=summary)))
            ids.append(integer(check["id"], "check ID", 1))
        for check_id in ids:
            require(live_pr(api, repository, pr, head, base) == report["source_tree"], "source tree changed")
            api.request("PATCH", f"/repos/{repository}/check-runs/{check_id}", dict(status="completed", conclusion="success",
                output=dict(title="Exact-source PJU evidence passed", summary=summary)))
        require(live_pr(api, repository, pr, head, base) == report["source_tree"], "source tree changed after publication")
    except Exception:
        for check_id in ids:
            try:
                api.request("PATCH", f"/repos/{repository}/check-runs/{check_id}", dict(status="completed", conclusion="failure",
                    output=dict(title="PJU bridge publication aborted", summary="Receipt publication did not finish; no admission is granted.")))
            except (OSError, ValueError, urllib.error.URLError):
                pass
        raise
    return ids


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("verify", "publish"))
    for flag in ("receipt-root", "source-root", "trusted-root", "manifest-sha256", "collector-source-sha",
                 "receipt-commit", "trusted-workflow-sha", "head", "base", "output"):
        parser.add_argument("--" + flag, required=True)
    parser.add_argument("--repository", default=REPOSITORY)
    parser.add_argument("--pr", type=int, required=True)
    args = parser.parse_args(argv)
    output = Path(args.output)
    report = {"status": "failed", "error": "validation did not complete"}
    try:
        admit_environment(args.trusted_workflow_sha, os.environ)
        require(git(args.trusted_root, "rev-parse", "HEAD").decode().strip() == args.trusted_workflow_sha, "trusted checkout differs")
        require(git(Path(args.receipt_root).parent, "rev-parse", "HEAD").decode().strip() == sha(args.receipt_commit, 40), "receipt commit differs")
        api = GitHub(os.environ.get("GH_TOKEN"))
        source_tree = live_pr(api, args.repository, args.pr, sha(args.head, 40), sha(args.base, 40))
        packet = Packet(args.receipt_root, args.manifest_sha256)
        report = validate_packet(packet, repository=args.repository, pr=args.pr, base=args.base, head=args.head,
            source_tree=source_tree, collector=args.collector_source_sha, source_root=args.source_root, trusted_root=args.trusted_root)
        require(live_pr(api, args.repository, args.pr, args.head, args.base) == source_tree, "PR changed during validation")
        report.update(manifest_sha256=args.manifest_sha256, receipt_commit=args.receipt_commit,
                      workflow_sha=args.trusted_workflow_sha)
        if args.mode == "publish":
            run_id = os.environ.get("GITHUB_RUN_ID", "")
            require(re.fullmatch(r"[0-9]+", run_id), "invalid run ID")
            report["check_run_ids"] = publish(api, report, args.manifest_sha256, args.receipt_commit,
                                             f"https://github.com/{REPOSITORY}/actions/runs/{run_id}")
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError, subprocess.SubprocessError,
            zipfile.BadZipFile, tarfile.TarError, urllib.error.URLError) as error:
        report = {"status": "failed", "error": str(error)}
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
