"""Validate owner-admitted local receipts as data, then publish required Checks.

This is an evidence bridge, not a hardware attestation service. An authenticated
repository owner admits an immutable receipt commit and its manifest digest.
No candidate Python, shell, Action, archive member, or test is executed here.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tarfile
import tokenize
import tomllib
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

REPOSITORY = "taipei49314/checkwash"
_ROUTE_SPEC = importlib.util.spec_from_file_location("_trusted_receipt_route", Path(__file__).with_name("receipt_execution_route.py"))
_ROUTE = importlib.util.module_from_spec(_ROUTE_SPEC)
_ROUTE_SPEC.loader.exec_module(_ROUTE)
HOST, PROVENANCE = _ROUTE.HOST, _ROUTE.PROVENANCE
receipt_route = _ROUTE.receipt_route
ACTION_SHA = "532f74ab070a924b23e2cc70e5d0091a05d8401d"
CONTEXTS = ("checkwash", *(f"candidate assertion contract ({d})" for d in ("source", "wheel", "pyz")))
CONTRACTS = ("tests/data/javascript_assertion_support.json", "tests/data/javascript_foundation_mutations.json")
UTILITIES = ("tools/assertion_contract.py", "tools/qualify_assertions.py", "tools/release_inventory.py")
REQUIRED_EXITS = {"pytest", "action-dogfood", "build-wheel", "build-pyz",
                  *(f"{step}-{d}" for step in ("qualify", "inventory") for d in ("source", "wheel", "pyz"))}
# The collector's xdist worker count since D-198 (earlier collectors used "2").
# It spreads the full suite and does not select tests; a receipt with another
# count is refused, so the count stays bound to the admitted collector.
PYTEST_WORKERS = "8"
COMPACT_CONTEXTS = ("checkwash",)
COMPACT_PYTEST_WORKERS = "16"
COMPACT_REQUIRED_EXITS = {
    "runtime-identity", "action-dogfood", "build-wheel", "build-pyz",
    "wheel-venv", "wheel-install", "wheel-import-check", "wheel-demo", "pyz-demo",
    "test-editable-install", "pytest",
}
MAX_COMPACT_RECEIPT = 64 * 1024
MIN_DOCUMENTED_TESTS = 23000
WORKFLOW_PATH = ".github/workflows/quality-candidate-intake.yml"
MAX_FILE = 256 * 1024 * 1024
MAX_TOTAL = 1024 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_native_route(check, route):
    """Bind route data to a native App check after its identity is verified.

    These are the exact headers emitted by the admitted historical/current
    publishers. The native check's App, source, success and external manifest
    digest remain independently required by the release-parent verifier.
    This is authenticated metadata consistency, not hardware attestation or a
    new signature over the prior report.
    """
    output = check.get("output")
    require(type(output) is dict and type(output.get("summary")) is str,
            "native check execution route header absent")
    header, separator, _ = output["summary"].partition("\n\n")
    headers = {
        f"Real local execution: {route['host']}; {route['provenance']}.",
        f"{route['provenance']}; actual host {route['host']}; Windows/Python 3.11.9. Other platforms NOT_RUN.",
    }
    if route["host"] == HOST:
        headers.add(f"Real PJU execution: {HOST}; {PROVENANCE}.")
    require(separator == "\n\n" and header in headers,
            "native check execution route header differs")


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


def pytest_passed_subtests(stdout, version):
    """Reconcile the one supported pytest producer from original command bytes."""
    require(version == "9.1.1" and type(stdout) is bytes, "JUnit subtests require pinned pytest 9.1.1 stdout")
    require(b"\x1b" not in stdout, "colored pytest subtest stdout unsupported")
    lines = [line.removesuffix(b"\r") for line in stdout.split(b"\n") if line.removesuffix(b"\r")]
    # Count every summary-shaped outcome, including failed/unknown categories.
    # Otherwise an earlier failed summary could hide behind the final success.
    shape = rb"(?:=+ )?[0-9]+ [A-Za-z][A-Za-z ]*(?:, [0-9]+ [A-Za-z][A-Za-z ]*)* in .+"
    summaries = [line for line in lines if re.fullmatch(shape, line)]
    require(len(summaries) == 1 and summaries[0] == lines[-1], "JUnit needs one final pytest summary")
    match = re.fullmatch(rb"([1-9][0-9]*) passed(?:, ([1-9][0-9]*) skipped)?, "
                         rb"([1-9][0-9]*) subtests passed in ((0|[1-9][0-9]*)\.[0-9]{2})s"
                         rb"( \([0-9]+:[0-5][0-9]:[0-5][0-9]\))?", summaries[0])
    require(match is not None, "unsupported pytest subtest summary")
    elapsed = float(match[4])
    require(math.isfinite(elapsed) and elapsed > 0, "invalid pytest summary duration")
    # The seconds field rounds to two decimals, while timedelta floors the
    # original duration. Thus 60.00s may have no suffix (59.999 seconds), and
    # 3601.00s (1:00:00) is a genuine formatter boundary (3600.999 seconds).
    if match[6] is None:
        require(elapsed <= 60, "pytest summary duration suffix missing")
    else:
        hours, minutes, seconds = map(int, match[6][2:-1].split(b":"))
        whole = hours * 3600 + minutes * 60 + seconds
        require(whole >= 60 and (whole == int(elapsed)
                or (elapsed.is_integer() and whole == int(elapsed) - 1)), "pytest summary duration differs")
    return {"passed": int(match[1]), "skipped": int(match[2] or b"0"), "subtests": int(match[3])}


def validate_junit(raw, *, pytest_stdout=None, pytest_version=None):
    mentioned = type(pytest_stdout) is bytes and b"subtests passed" in pytest_stdout
    if mentioned:
        require(b"\0" not in raw, "subtest JUnit must be UTF-8")
        raw.decode("utf-8")
    require(b"<!DOCTYPE" not in raw.upper() and b"<!ENTITY" not in raw.upper(), "DTD/entity forbidden in JUnit")
    root = ET.fromstring(raw)
    require(root.tag in ("testsuites", "testsuite"), "JUnit root")
    cases = list(root.iter("testcase"))
    require(cases and any(case.find("skipped") is None for case in cases), "empty/all-skipped JUnit")
    require(not list(root.iter("failure")) and not list(root.iter("error")), "JUnit failures/errors")
    suites = list(root.iter("testsuite"))
    totals = []
    for suite in suites:
        direct = list(suite.findall("testcase"))
        require(not suite.findall("testsuite"), "nested JUnit suites unsupported")
        declared = suite.get("tests")
        require(declared is not None and re.fullmatch(r"[0-9]+", declared), "JUnit summary mismatch: tests")
        totals.append(int(declared))
        for attr, expected in (("failures", 0), ("errors", 0),
                               ("skipped", sum(case.find("skipped") is not None for case in direct))):
            value = suite.get(attr)
            require(value is not None and re.fullmatch(r"[0-9]+", value) and int(value) == expected, "JUnit summary mismatch: " + attr)
    subtests = 0
    if any(total != len(suite.findall("testcase")) for total, suite in zip(totals, suites)) or mentioned:
        require(len(suites) == 1 and len(suites[0].findall("testcase")) == len(cases)
                and (root is suites[0] or list(root.findall("testsuite")) == suites), "subtest JUnit must have one direct suite")
        summary = pytest_passed_subtests(pytest_stdout, pytest_version)
        skipped = sum(case.find("skipped") is not None for case in cases)
        require(summary["passed"] + summary["skipped"] == len(cases) and summary["skipped"] == skipped,
                "pytest/JUnit testcase outcomes differ")
        subtests = summary["subtests"]
        require(totals[0] == len(cases) + subtests, "JUnit subtest count differs")
    if root.tag == "testsuites":
        for attr, expected in (("tests", len(cases) + subtests), ("failures", 0), ("errors", 0),
                               ("skipped", sum(c.find("skipped") is not None for c in cases))):
            if attr in root.attrib:
                value = root.attrib[attr]
                require(re.fullmatch(r"[0-9]+", value) and int(value) == expected, "JUnit aggregate mismatch")
    result = {"tests": len(cases), "skipped": sum(c.find("skipped") is not None for c in cases)}
    if subtests:
        result.update(reported_tests=len(cases) + subtests, passed_subtests=subtests)
    return result


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
    route = receipt_route(packet.manifest)
    exact_keys(replay, "schema_version kind provenance status host action_sha action_tree action_yaml_sha256 base_sha head_sha "
                       "fail_on comment_pr steps resolved_outputs files errors", "Action replay")
    require(type(replay["schema_version"]) is int and replay["schema_version"] == 1
            and replay["kind"] == "checkwash.pju-action-replay.v1" and replay["provenance"] == route["action_provenance"]
            and replay["status"] == "completed" and replay["errors"] == [] and replay["host"] == route["host"]
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


def release_versions(root, head, where="the head"):
    """The commit's pyproject version and the advertised release version it records."""
    versions = []
    for path, table in (("pyproject.toml", "project"), ("release/advertised.toml", "release")):
        try:
            value = tomllib.loads(git(root, "show", head + ":" + path).decode("utf-8")).get(table)
        except ValueError as error:  # failed Git read, undecodable bytes or invalid TOML
            raise ValueError(path + " at " + where + " could not be read or parsed") from error
        require(type(value) is dict and type(value.get("version")) is str, path + " at " + where + " has no " + table + " version")
        versions.append(value["version"])
    return tuple(versions)


DOCTOR_PATH = "src/checkwash/doctor.py"
OWN_PIN_LINE = re.compile(rb'_OWN_ACTION_PIN = "([0-9a-f]{40})"')
PREVIOUS_PIN_LINE = re.compile(rb'_PREVIOUS_ACTION_PIN = "([0-9a-f]{40})"')
# Names through which a module can bind a global the parse does not show.
DYNAMIC_NAMES = {"exec", "eval", "compile", "globals", "locals", "vars", "setattr", "delattr", "__import__"}
DYNAMIC_MODULES = {"importlib", "builtins"}


def doctor_action_pins(raw):
    """Doctor's previous and own Action pins, and the own line's index (scheme S, D-194).

    The two lines are read as text, then checked against the parsed module,
    which is never executed: the file is UTF-8 as import reads it, each name is
    bound once, by its own line, no other node binds or names it, and nothing
    reaches the module namespace dynamically. Doctor's other logic is reviewed
    content.
    """
    lines = raw.split(b"\n")
    previous = [index for index, line in enumerate(lines) if line.startswith(b"_PREVIOUS_ACTION_PIN")]
    own = [index for index, line in enumerate(lines) if line.startswith(b"_OWN_ACTION_PIN")]
    require(len(previous) == len(own) == 1, "doctor must hold exactly one previous and one own Action pin line")
    old, new = PREVIOUS_PIN_LINE.fullmatch(lines[previous[0]]), OWN_PIN_LINE.fullmatch(lines[own[0]])
    require(old is not None and new is not None, "doctor's Action pin lines differ from the exact shape")
    # Python also ends a line at a lone CR, and a form feed may open a module-level statement: LF lines hide both.
    require(b"\r" not in raw and b"\x0c" not in raw, "doctor.py holds a carriage return or form feed")
    # Import decodes by a PEP 263 declaration, which a parse of decoded text ignores.
    try:
        encoding = tokenize.detect_encoding(io.BytesIO(raw).readline)[0]
    except SyntaxError as error:  # an unknown or malformed declaration
        raise ValueError("doctor.py declares an encoding other than UTF-8") from error
    require(encoding == "utf-8", "doctor.py declares an encoding other than UTF-8")
    try:
        tree = ast.parse(raw.decode("utf-8"), DOCTOR_PATH)
    except (SyntaxError, ValueError, RecursionError, MemoryError) as error:  # undecodable, invalid or too deeply nested
        raise ValueError("doctor.py could not be parsed") from error
    pins = {"_PREVIOUS_ACTION_PIN": (previous[0], old.group(1).decode()), "_OWN_ACTION_PIN": (own[0], new.group(1).decode())}
    bound = [node for node in tree.body if isinstance(node, ast.Assign) and len(node.targets) == 1
             and isinstance(node.targets[0], ast.Name) and node.targets[0].id in pins]
    found = [(node.targets[0].id, node.lineno - 1, node.value.value if isinstance(node.value, ast.Constant) else None)
             for node in bound]
    require(len(found) == 2 and set(found) == {(name, index, pin) for name, (index, pin) in pins.items()},
            "doctor must bind each Action pin once, by a module-level assignment on its own line")
    targets = {id(node.targets[0]) for node in bound}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            named = node.id in pins and not isinstance(node.ctx, ast.Load) and id(node) not in targets
        else:  # a def, class, argument, import, attribute, global, keyword or string of the name; or `import *`
            named = isinstance(node, ast.alias) and node.name == "*" or any(
                type(item) is str and item in pins for _field, value in ast.iter_fields(node)
                for item in (value if isinstance(value, list) else [value]))
        require(not named, "doctor binds or names an Action pin outside its two lines")
    for node in ast.walk(tree):
        dynamic = (isinstance(node, ast.Name) and node.id in DYNAMIC_NAMES
                   or isinstance(node, ast.Attribute) and node.attr == "__dict__"
                   or isinstance(node, ast.alias) and node.name.split(".")[0] in DYNAMIC_MODULES
                   or isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in DYNAMIC_MODULES)
        require(not dynamic, "doctor reaches its namespace dynamically (exec, eval, globals, setattr, __dict__, importlib ...)")
    return pins["_PREVIOUS_ACTION_PIN"][1], pins["_OWN_ACTION_PIN"][1], own[0]


def single_doctor_module(root, commit):
    """Nothing beside doctor.py, such as a doctor/ package, can be imported as checkwash.doctor."""
    names = git(root, "ls-tree", "-z", "--name-only", commit + ":src/checkwash").split(b"\0")
    require([name for name in names if name == b"doctor" or name.startswith(b"doctor.")] == [b"doctor.py"],
            "src/checkwash holds another doctor module beside doctor.py")


def validate_ordinary_head(root, head):
    """A head that changes the version is a release PR (scheme S, D-194)."""
    version, advertised = release_versions(root, head)
    require(version == advertised, f"head version {version} differs from the advertised release {advertised}; "
            "a release PR's checks are published only through the release bridge's pr stage (tools/pju_release_bridge.py), "
            "and a branch that took main between a release merge and its step-8 follow-up waits for that follow-up")
    single_doctor_module(root, head)
    previous, own, _index = doctor_action_pins(git(root, "show", head + ":" + DOCTOR_PATH))
    require(own == previous, "doctor's own Action pin differs from its previous pin at a non-release head; "
            "only a release PR's last commit sets doctor's own Action pin (scheme S, D-194)")


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
    route = receipt_route(manifest)
    require(manifest["status"] == "completed" and manifest["action_sha"] == ACTION_SHA, "receipt scope/status")
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
            and argv[1:16] == ["-I", "-B", "-X", "utf8", "-m", "pytest", "-p", "xdist.plugin", "-n", PYTEST_WORKERS,
                              "--dist", "worksteal", "-p", "no:cacheprovider", "--basetemp"]
            and argv[17] == "--junitxml" and argv[19] == "tests"
            and argv[18].replace("\\", "/").endswith("/" + records["junit"]), "full pytest command scope differs")
    junit = validate_junit(packet.raw(records["junit"]), pytest_stdout=packet.raw(pytest["stdout"]),
                           pytest_version=runtime["dependencies"].get("pytest"))
    validate_action(packet, records, head, base, trusted_root)
    validate_candidate_action(packet, records, head, base, source_root, trusted_root, collector)
    for distribution in ("source", "wheel", "pyz"):
        qpath = records["qualifications"][distribution]
        qualification = packet.json(qpath)
        validate_qualification(qualification, desc, distribution)
        validate_inventory(packet, packet.json(records["inventories"][distribution]), desc, qualification, qpath, distribution)
    return dict(status="verified", repository=repository, pr_number=pr, head_sha=head, base_sha=base,
                source_tree=source_tree, collector_source_sha=collector, host=route["host"], provenance=route["provenance"],
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


def admit_compact_environment(expected_workflow_sha, *, head_sha, base_sha, collector_sha, trusted_root, env):
    admit_environment(expected_workflow_sha, env)
    require(not env.get("PJU_RECEIPT_COMMIT", ""), "compact receipt mode refuses receipt_commit")
    head, base, collector = sha(head_sha, 40), sha(base_sha, 40), sha(collector_sha, 40)
    workflow_ref = env.get("GITHUB_WORKFLOW_REF", "")
    main_ref = REPOSITORY + "/" + WORKFLOW_PATH + "@refs/heads/main"
    base_workflow = git(trusted_root, "show", base + ":" + WORKFLOW_PATH)
    if b"\n  verify-pju-compact:\n" in base_workflow:
        require(workflow_ref == main_ref and collector == expected_workflow_sha,
                "compact-receipt mode must be dispatched from refs/heads/main once merged")
    else:
        require((workflow_ref == main_ref and collector == expected_workflow_sha)
                or (workflow_ref.startswith(REPOSITORY + "/" + WORKFLOW_PATH + "@refs/heads/")
                    and expected_workflow_sha == head == collector),
                "compact-receipt bootstrap requires exact candidate head workflow/collector identity")


def documented_test_count(source_root, head):
    """Read the documented collected test count from Git blobs without executing code."""
    counts = set()
    for doc, marker in (("README.md", "pre-release"), ("docs/launch.md", "Apache-2.0")):
        text = git(source_root, "show", head + ":" + doc).decode("utf-8")
        lines = [line for line in text.splitlines() if "detectors," in line and marker in line]
        require(bool(lines), "missing documented status line in " + doc)
        for line in lines:
            match = re.search(r"(\d+) detectors, (\d+) tests\b", line)
            require(match is not None, "malformed status line in " + doc)
            counts.add(int(match.group(2)))
    for doc in ("README.md", "CONTRIBUTING.md", "docs/launch.md"):
        text = git(source_root, "show", head + ":" + doc).decode("utf-8")
        claimed = [int(value) for value in re.findall(r"(\d+) tests\b", text)]
        require(bool(claimed), "missing documented test count in " + doc)
        counts.update(claimed)
    require(len(counts) == 1, "documented test counts disagree across repository prose")
    expected = next(iter(counts))
    require(expected >= MIN_DOCUMENTED_TESTS, "documented test count below admitted floor")
    return expected


def _validate_compact_action_summary(summary, *, expected_action_sha, base, head, action_repo_root, route):
    exact_keys(summary, "action_sha action_tree action_yaml_sha256 install_run_sha256 check_run_sha256 source_digest "
                        "runtime_files version base_sha head_sha fail_on comment_pr exit_code analysis_exit_code "
                        "host provenance check_receipt_sha256 replay_sha256", "compact Action summary")
    require(summary["action_sha"] == expected_action_sha and summary["base_sha"] == base and summary["head_sha"] == head
            and summary["fail_on"] == "high" and summary["comment_pr"] is False
            and type(summary["exit_code"]) is int and summary["exit_code"] == 0
            and type(summary["analysis_exit_code"]) is int and summary["analysis_exit_code"] == 0
            and summary["host"] == route["host"] and summary["provenance"] == route["action_provenance"],
            "compact Action replay identity/status mismatch")
    sha(summary["check_receipt_sha256"])
    sha(summary["replay_sha256"])
    require(summary["action_tree"] == git(action_repo_root, "rev-parse", expected_action_sha + "^{tree}").decode().strip(),
            "compact Action tree mismatch")
    action_yaml = git(action_repo_root, "show", expected_action_sha + ":action/action.yml")
    require(summary["action_yaml_sha256"] == digest(action_yaml), "compact Action definition mismatch")
    runs = action_run_blocks(action_yaml)
    require(summary["install_run_sha256"] == digest(runs["install"])
            and summary["check_run_sha256"] == digest(runs["check"]), "compact Action run block digest mismatch")
    action_package = tree_files(action_repo_root, expected_action_sha, "src/checkwash")
    require(summary["source_digest"] == canonical({p: digest(raw) for p, raw in action_package.items()})
            and type(summary["runtime_files"]) is int and summary["runtime_files"] == len(action_package),
            "compact Action engine identity mismatch")
    project = tomllib.loads(git(action_repo_root, "show", expected_action_sha + ":pyproject.toml").decode("utf-8"))["project"]
    require(summary["version"] == project["version"], "compact Action engine version mismatch")


def validate_compact(raw_receipt, expected_sha256, *, repository, pr, base, head, source_tree, collector, source_root, trusted_root):
    require(type(raw_receipt) is bytes and 0 < len(raw_receipt) <= MAX_COMPACT_RECEIPT, "oversized/empty compact receipt")
    require(b"\r" not in raw_receipt and b"\n" not in raw_receipt, "compact receipt must be single-line JSON")
    require(digest(raw_receipt) == sha(expected_sha256), "external compact receipt digest mismatch")
    receipt = strict_json(raw_receipt)
    exact_keys(receipt, "schema_version kind status repository pr_number base_sha head_sha source_tree src_tree "
                        "host provenance collector_source_sha action_sha version runtime contracts action_dogfood "
                        "candidate_action distributions junit pytest_argv raw_exits", "compact receipt")
    require(type(receipt["schema_version"]) is int and receipt["schema_version"] == 1
            and receipt["kind"] == "checkwash.pju-compact-receipt.v1"
            and receipt["status"] == "completed" and receipt["action_sha"] == ACTION_SHA, "compact receipt schema/status")
    require(repository == REPOSITORY and receipt["repository"] == repository
            and type(receipt["pr_number"]) is int and receipt["pr_number"] == integer(pr, "PR", 1),
            "compact receipt repository/PR mismatch")
    require(receipt["head_sha"] == sha(head, 40) and receipt["base_sha"] == sha(base, 40)
            and receipt["source_tree"] == sha(source_tree, 40)
            and receipt["collector_source_sha"] == sha(collector, 40), "compact receipt source/collector mismatch")
    route = receipt_route(receipt)
    require(git(source_root, "rev-parse", "HEAD").decode().strip() == head, "candidate checkout SHA mismatch")
    require(git(source_root, "rev-parse", head + "^{tree}").decode().strip() == source_tree, "candidate tree mismatch")
    require(receipt["src_tree"] == git(source_root, "rev-parse", head + ":src").decode().strip(), "src tree mismatch")
    project = tomllib.loads(git(source_root, "show", head + ":pyproject.toml").decode("utf-8"))["project"]
    require(receipt["version"] == "checkwash " + project["version"], "version mismatch")

    inventories, cases = [], []
    for path in (*UTILITIES, *CONTRACTS):
        raw = git(source_root, "show", head + ":" + path)
        require(raw == git(trusted_root, "show", collector + ":" + path),
                "candidate differs from audited contract/tool: " + path)
        if path in CONTRACTS:
            data = strict_json(raw)
            require(type(data.get("schema_version")) is int and data["schema_version"] == 1
                    and type(data.get("mutations")) is list and data["mutations"], "empty/malformed contract inventory")
            cases.extend(data["mutations"])
            inventories.append(dict(path=path, sha256=digest(raw), mutations=len(data["mutations"])))
    require(all(type(case) is dict and type(case.get("id")) is str and case["id"] for case in cases)
            and len({case["id"] for case in cases}) == len(cases), "duplicate/missing case IDs")
    source_files = tree_files(source_root, head, "src")
    package = {name: digest(raw) for name, raw in source_files.items() if name.startswith("checkwash/")
               and "__pycache__" not in PurePosixPath(name).parts and not name.endswith(".pyc")}
    require(bool(package), "empty Git package tree")
    expected_pkg_sha = canonical(package)
    contracts = receipt["contracts"]
    exact_keys(contracts, "source_package_sha256 builder_sha256 suite_sha256 inventories", "compact contracts")
    require(contracts["source_package_sha256"] == expected_pkg_sha
            and contracts["suite_sha256"] == canonical(cases)
            and same(contracts["inventories"], inventories)
            and contracts["builder_sha256"] == digest(git(trusted_root, "show", collector + ":tools/release_inventory.py")),
            "compact contract/package digest mismatch")

    runtime = receipt["runtime"]
    exact_keys(runtime, "os python_version python_executable python_sha256 git_executable git_sha256 bash_executable "
                        "bash_sha256 dependency_lock_sha256 dependencies_sha256 pytest_version xdist_workers other_platforms",
               "compact runtime")
    require(runtime["os"] == "Windows" and runtime["python_version"] == "3.11.9"
            and runtime["pytest_version"] == "9.1.1" and runtime["xdist_workers"] == COMPACT_PYTEST_WORKERS
            and runtime["other_platforms"] == "NOT_RUN", "compact runtime scope mismatch")
    require(all(type(runtime[k]) is str and runtime[k] for k in ("python_executable", "git_executable", "bash_executable")),
            "compact runtime executable missing")
    for key in ("python_sha256", "git_sha256", "bash_sha256", "dependency_lock_sha256", "dependencies_sha256"):
        sha(runtime[key])

    _validate_compact_action_summary(receipt["action_dogfood"], expected_action_sha=ACTION_SHA,
                                     base=base, head=head, action_repo_root=trusted_root, route=route)

    def closure_map(root, commit):
        result = {prefix + "/" + name: digest(raw) for prefix in ("action", "src")
                  for name, raw in tree_files(root, commit, prefix).items()}
        result["pyproject.toml"] = digest(git(root, "show", commit + ":pyproject.toml"))
        return result

    cand_closure = closure_map(source_root, head)
    pin_closure = closure_map(trusted_root, ACTION_SHA)
    cand_action = receipt["candidate_action"]
    exact_keys(cand_action, "candidate_closure_sha256 pinned_closure_sha256 mode replay", "compact candidate Action")
    require(cand_action["candidate_closure_sha256"] == canonical(cand_closure)
            and cand_action["pinned_closure_sha256"] == canonical(pin_closure), "compact Action closure digest mismatch")
    if cand_action["mode"] == "byte-identical-reuse":
        require(cand_closure == pin_closure and cand_action["replay"] is None,
                "unequal Action closure cannot reuse pinned replay")
    else:
        require(cand_action["mode"] == "separate-replay" and cand_closure != pin_closure
                and type(cand_action["replay"]) is dict, "invalid candidate Action replay mode")
        _validate_compact_action_summary(cand_action["replay"], expected_action_sha=head,
                                         base=base, head=head, action_repo_root=source_root, route=route)

    distributions = receipt["distributions"]
    exact_keys(distributions, "wheel sdist pyz", "compact distributions")
    dist_prefix = project["name"].replace("-", "_") + "-" + project["version"]
    expected_names = {"wheel": dist_prefix + "-py3-none-any.whl", "sdist": dist_prefix + ".tar.gz", "pyz": "checkwash.pyz"}
    for kind, expected_name in expected_names.items():
        item = distributions[kind]
        exact_keys(item, "name sha256 bytes members_sha256 package_sha256", "compact distribution")
        require(item["name"] == expected_name, "compact distribution filename mismatch: " + kind)
        require(integer(item["bytes"], kind + " bytes", 1) <= MAX_FILE, "invalid distribution size: " + kind)
        sha(item["sha256"])
        sha(item["members_sha256"])
        require(item["package_sha256"] == expected_pkg_sha, "delivered package digest differs from Git source: " + kind)

    exits = receipt["raw_exits"]
    require(type(exits) is list and bool(exits), "compact raw exits missing")
    names = set()
    by_name = {}
    for row in exits:
        exact_keys(row, "name duration_seconds exit_code timed_out stdout_sha256 stderr_sha256", "compact raw exit")
        require(type(row["name"]) is str and row["name"] and row["name"] not in names, "duplicate/missing compact exit")
        names.add(row["name"])
        by_name[row["name"]] = row
        require(type(row["exit_code"]) is int and row["exit_code"] == 0 and row["timed_out"] is False,
                "nonzero/timed-out compact command exit: " + row["name"])
        require(type(row["duration_seconds"]) in (int, float) and math.isfinite(row["duration_seconds"])
                and row["duration_seconds"] >= 0, "invalid compact command duration")
        sha(row["stdout_sha256"])
        sha(row["stderr_sha256"])
    expected_exits = COMPACT_REQUIRED_EXITS | ({"candidate-action-dogfood"} if cand_action["mode"] == "separate-replay" else set())
    require(names == expected_exits, "compact required command set mismatch")

    argv = receipt["pytest_argv"]
    require(type(argv) is list and len(argv) == 20 and all(type(arg) is str and arg for arg in argv)
            and argv[0] == runtime["python_executable"]
            and argv[1:16] == ["-I", "-B", "-X", "utf8", "-m", "pytest", "-p", "xdist.plugin", "-n", COMPACT_PYTEST_WORKERS,
                               "--dist", "worksteal", "-p", "no:cacheprovider", "--basetemp"]
            and argv[17] == "--junitxml" and argv[19] == "tests"
            and argv[18].replace("\\", "/").endswith("/junit.xml"), "compact pytest command scope differs")

    junit = receipt["junit"]
    exact_keys(junit, "sha256 bytes tests passed skipped failures errors passed_subtests pytest_stdout_sha256", "compact junit")
    sha(junit["sha256"])
    integer(junit["bytes"], "junit bytes", 1)
    require(sha(junit["pytest_stdout_sha256"]) == by_name["pytest"]["stdout_sha256"],
            "compact JUnit pytest stdout linkage mismatch")
    require(type(junit["failures"]) is int and junit["failures"] == 0
            and type(junit["errors"]) is int and junit["errors"] == 0, "compact JUnit failures/errors")
    tests = integer(junit["tests"], "junit tests", MIN_DOCUMENTED_TESTS)
    passed = integer(junit["passed"], "junit passed", 1)
    skipped = integer(junit["skipped"], "junit skipped", 0)
    subtests = integer(junit["passed_subtests"], "junit subtests", 0)
    require(passed + skipped == tests, "compact JUnit outcome total mismatch")
    expected_tests = documented_test_count(source_root, head)
    require(tests == expected_tests, f"compact JUnit test count {tests} differs from documented suite count {expected_tests}")

    return dict(status="verified", mode="compact-receipt", repository=repository, pr_number=pr, head_sha=head, base_sha=base,
                source_tree=source_tree, collector_source_sha=collector, host=route["host"], provenance=route["provenance"],
                checks=list(COMPACT_CONTEXTS), candidate_action_mode=cand_action["mode"],
                junit=dict(tests=tests, passed=passed, skipped=skipped, passed_subtests=subtests),
                trust="owner-admitted compact receipt digest; not hardware attestation", other_platforms="NOT_RUN")


def publish_compact(api, report, manifest_sha256, run_url):
    repository, pr, head, base = (report[k] for k in ("repository", "pr_number", "head_sha", "base_sha"))
    require(report["status"] == "verified" and report["checks"] == list(COMPACT_CONTEXTS), "unverified compact check publication")
    route = receipt_route(report)
    ids = []
    summary = (f"Real local execution: {route['host']}; {route['provenance']}.\n\n"
               f"PR #{pr}; head `{head}`; base `{base}`.\n\n"
               f"Compact receipt SHA256 `{manifest_sha256}` (no evidence branch).\n\n"
               f"Full pytest suite (`-n {COMPACT_PYTEST_WORKERS}`): {report['junit']}; "
               f"wheel/sdist/pyz byte-matched to Git source and CLI-checked; "
               f"Action replay ({report['candidate_action_mode']}) passed. "
               "Owner-admitted compact digest evidence, not hardware attestation. Other platforms: NOT_RUN.")
    try:
        require(live_pr(api, repository, pr, head, base) == report["source_tree"], "source tree changed")
        for name in COMPACT_CONTEXTS:
            check = api.request("POST", f"/repos/{repository}/check-runs", dict(name=name, head_sha=head,
                status="in_progress", external_id="pju-compact:" + manifest_sha256 + ":" + name, details_url=run_url,
                output=dict(title="Compact local evidence verified; publication in progress", summary=summary)))
            ids.append(integer(check["id"], "check ID", 1))
        for check_id in ids:
            require(live_pr(api, repository, pr, head, base) == report["source_tree"], "source tree changed")
            api.request("PATCH", f"/repos/{repository}/check-runs/{check_id}", dict(status="completed", conclusion="success",
                output=dict(title="Exact-source compact local evidence passed", summary=summary)))
        require(live_pr(api, repository, pr, head, base) == report["source_tree"], "source tree changed after publication")
    except (OSError, ValueError, KeyError, TypeError, urllib.error.URLError):
        for check_id in ids:
            try:
                api.request("PATCH", f"/repos/{repository}/check-runs/{check_id}", dict(status="completed", conclusion="failure",
                    output=dict(title="PJU compact bridge publication aborted",
                                summary="Compact receipt publication did not finish; no admission is granted.")))
            except (OSError, ValueError, urllib.error.URLError):
                pass
        raise
    return ids


def publish(api, report, manifest_sha256, receipt_commit, run_url):
    repository, pr, head, base = (report[k] for k in ("repository", "pr_number", "head_sha", "base_sha"))
    require(report["status"] == "verified" and report["checks"] == list(CONTEXTS), "unverified check publication")
    route = receipt_route(report)
    ids = []
    summary = (f"Real local execution: {route['host']}; {route['provenance']}.\n\n"
               f"PR #{pr}; head `{head}`; base `{base}`.\n\nReceipt commit `{receipt_commit}`; manifest SHA256 `{manifest_sha256}`.\n\n"
               f"{report['qualification_cases']} exact contract cases per distribution; JUnit {report['junit']}. "
               "Owner-admitted evidence, not hardware attestation. Other platforms: NOT_RUN.")
    try:
        require(live_pr(api, repository, pr, head, base) == report["source_tree"], "source tree changed")
        for name in CONTEXTS:
            check = api.request("POST", f"/repos/{repository}/check-runs", dict(name=name, head_sha=head,
                status="in_progress", external_id="pju:" + manifest_sha256 + ":" + name, details_url=run_url,
                output=dict(title="Local evidence verified; publication in progress", summary=summary)))
            ids.append(integer(check["id"], "check ID", 1))
        for check_id in ids:
            require(live_pr(api, repository, pr, head, base) == report["source_tree"], "source tree changed")
            api.request("PATCH", f"/repos/{repository}/check-runs/{check_id}", dict(status="completed", conclusion="success",
                output=dict(title="Exact-source local evidence passed", summary=summary)))
        require(live_pr(api, repository, pr, head, base) == report["source_tree"], "source tree changed after publication")
    except (OSError, ValueError, KeyError, TypeError, urllib.error.URLError):
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
    parser.add_argument("mode", choices=("verify", "publish", "verify-compact", "publish-compact"))
    for flag in ("source-root", "trusted-root", "manifest-sha256", "collector-source-sha",
                 "trusted-workflow-sha", "head", "base", "output"):
        parser.add_argument("--" + flag, required=True)
    for flag in ("receipt-root", "receipt-commit", "compact-receipt-file"):
        parser.add_argument("--" + flag)
    parser.add_argument("--repository", default=REPOSITORY)
    parser.add_argument("--pr", type=int, required=True)
    args = parser.parse_args(argv)
    output = Path(args.output)
    report = {"status": "failed", "error": "validation did not complete"}
    try:
        compact = args.mode in ("verify-compact", "publish-compact")
        if compact:
            require(args.receipt_root is None and args.receipt_commit is None,
                    "compact mode takes no receipt checkout or receipt commit")
            admit_compact_environment(args.trusted_workflow_sha, head_sha=args.head, base_sha=args.base,
                                      collector_sha=args.collector_source_sha, trusted_root=args.trusted_root, env=os.environ)
        else:
            require(bool(args.receipt_root) and bool(args.receipt_commit) and args.compact_receipt_file is None,
                    "receipt mode requires --receipt-root and --receipt-commit")
            admit_environment(args.trusted_workflow_sha, os.environ)
        require(git(args.trusted_root, "rev-parse", "HEAD").decode().strip() == args.trusted_workflow_sha, "trusted checkout differs")
        if not compact:
            require(git(Path(args.receipt_root).parent, "rev-parse", "HEAD").decode().strip() == sha(args.receipt_commit, 40), "receipt commit differs")
        validate_ordinary_head(args.source_root, sha(args.head, 40))
        api = GitHub(os.environ.get("GH_TOKEN"))
        source_tree = live_pr(api, args.repository, args.pr, sha(args.head, 40), sha(args.base, 40))
        if compact:
            raw_compact = (Path(args.compact_receipt_file).read_bytes() if args.compact_receipt_file
                           else os.environ.get("PJU_COMPACT_RECEIPT", "").encode("utf-8"))
            report = validate_compact(raw_compact, args.manifest_sha256, repository=args.repository, pr=args.pr,
                base=args.base, head=args.head, source_tree=source_tree, collector=args.collector_source_sha,
                source_root=args.source_root, trusted_root=args.trusted_root)
            require(live_pr(api, args.repository, args.pr, args.head, args.base) == source_tree, "PR changed during validation")
            report.update(manifest_sha256=args.manifest_sha256, workflow_sha=args.trusted_workflow_sha)
            if args.mode == "publish-compact":
                run_id = os.environ.get("GITHUB_RUN_ID", "")
                require(re.fullmatch(r"[0-9]+", run_id), "invalid run ID")
                report["check_run_ids"] = publish_compact(api, report, args.manifest_sha256,
                                                          f"https://github.com/{REPOSITORY}/actions/runs/{run_id}")
        else:
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
