"""Read-only release evidence verification and narrowly scoped publication.

Candidate code, tests, installers and archives are never executed here. The
maintainer admits immutable PJU evidence by digest. That is controlled evidence
publication, not hardware attestation. Native GitHub identities are re-read.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import subprocess
import sys
import tarfile
import tomllib
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile


def load_trusted(name):
    path = Path(__file__).with_name(name + ".py")
    spec = importlib.util.spec_from_file_location("_release_" + name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


B = load_trusted("pju_receipt_bridge")
require, exact_keys, sha, digest, canonical, same = B.require, B.exact_keys, B.sha, B.digest, B.canonical, B.same
Packet, git = B.Packet, B.git
REPOSITORY, HOST, PROVENANCE = B.REPOSITORY, B.HOST, B.PROVENANCE
STAGES = ("pr", "main", "tag", "release-event", "public-visitor")
PREVIOUS = {"pr": None, "main": "pr", "tag": "main", "release-event": "tag", "public-visitor": "release-event"}
WORKFLOW = ".github/workflows/release.yml"
BOOTSTRAP_WORKFLOW = ".github/workflows/quality-candidate-intake.yml"
ACTION_APP_ID = 15368
MAX_RESPONSE = 16 * 1024 * 1024
MISSING_PLATFORMS = [f"{os_name}/Python {version}" for os_name in ("Windows", "Linux", "macOS")
                     for version in ("3.11", "3.12", "3.13") if (os_name, version) != ("Windows", "3.11")]


def context(stage):
    require(stage in STAGES, "unknown release stage")
    return "PJU release evidence (" + stage + ")"


def utc(value):
    require(type(value) is str, "UTC timestamp required")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(parsed.tzinfo is not None and parsed.utcoffset().total_seconds() == 0, "UTC timestamp required")
    return parsed


def positive(value, label):
    return B.integer(value, label, 1)


def subject(value):
    extra = " pr_number" if type(value) is dict and value.get("stage") == "pr" else ""
    exact_keys(value, "schema_version kind stage repository head_sha base_sha source_tree tag tag_object release_id event" + extra, "release subject")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1
            and value["kind"] == "checkwash.pju-release-subject.v1", "release subject schema")
    stage = value["stage"]
    require(stage in STAGES and value["repository"] == REPOSITORY, "release subject stage/repository")
    for key in ("head_sha", "base_sha", "source_tree"):
        sha(value[key], 40)
    if stage in ("pr", "main"):
        require(value["tag"] is None and value["tag_object"] is None and value["release_id"] is None, "pre-tag subject has tag/release")
        if stage == "pr":
            positive(value["pr_number"], "PR number")
    else:
        require(type(value["tag"]) is str and re.fullmatch(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", value["tag"]), "canonical stable tag required")
        sha(value["tag_object"], 40)
        if stage == "tag":
            require(value["release_id"] is None, "tag subject has release")
        else:
            positive(value["release_id"], "release ID")
    event = value["event"]
    exact_keys(event, "name run_id run_attempt workflow_sha created_at payload_sha256", "native event")
    require(event["name"] == ("release" if stage == "release-event" else "workflow_dispatch"), "native event kind mismatch")
    for key in ("run_id", "run_attempt"):
        positive(event[key], "native " + key)
    sha(event["workflow_sha"], 40)
    sha(event["payload_sha256"])
    utc(event["created_at"])
    return stage


class GitHub(B.GitHub):
    def binary(self, method, path, raw, content_type="application/octet-stream"):
        require(path.startswith(f"/repos/{REPOSITORY}/releases/") and method == "POST", "unexpected upload path")
        request = urllib.request.Request("https://uploads.github.com" + path, data=raw, method=method,
            headers={"Authorization": "Bearer " + self.token, "Accept": "application/vnd.github+json",
                     "Content-Type": content_type, "User-Agent": "checkwash-pju-release-bridge"})
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        with urllib.request.build_opener(NoRedirect).open(request, timeout=60) as response:
            contents = response.read(MAX_RESPONSE + 1)
        require(len(contents) <= MAX_RESPONSE, "oversized upload response")
        return B.strict_json(contents)


def public_download(url, expected_size=None):
    parsed = urllib.parse.urlsplit(url)
    require(parsed.scheme == "https" and parsed.username is None and parsed.password is None
            and parsed.hostname in ("github.com", "files.pythonhosted.org", "pypi.org")
            and parsed.port in (None, 443), "unapproved public download URL")
    maximum = B.MAX_FILE if expected_size is None else B.integer(expected_size, "download size")
    require(maximum <= B.MAX_FILE, "oversized public download")
    request = urllib.request.Request(url, headers={"User-Agent": "checkwash-pju-release-bridge"})
    # Public downloads never receive a credential, including on redirects.
    with urllib.request.urlopen(request, timeout=60) as response:
        raw = response.read(maximum + 1)
    require(len(raw) <= maximum and (expected_size is None or len(raw) == expected_size), "public download size mismatch")
    return raw


def live_subject(api, value, *, check_event=True):
    stage = subject(value)
    prefix = "/repos/" + REPOSITORY
    commit = api.request("GET", prefix + "/git/commits/" + value["head_sha"])
    require(commit.get("sha") == value["head_sha"] and commit.get("tree", {}).get("sha") == value["source_tree"], "native commit/tree mismatch")
    if stage == "pr":
        require(B.live_pr(api, REPOSITORY, value["pr_number"], value["head_sha"], value["base_sha"]) == value["source_tree"], "stale PR source")
    else:
        require(commit.get("parents") and commit["parents"][0].get("sha") == value["base_sha"], "native first parent mismatch")
    if stage == "main":
        ref = api.request("GET", prefix + "/git/ref/heads/main")
        require(ref.get("ref") == "refs/heads/main" and ref.get("object", {}).get("type") == "commit"
                and ref["object"].get("sha") == value["head_sha"], "stale main source")
    elif stage != "pr":
        ref = api.request("GET", prefix + "/git/ref/tags/" + value["tag"])
        require(ref.get("ref") == "refs/tags/" + value["tag"] and ref.get("object", {}).get("type") == "tag"
                and ref["object"].get("sha") == value["tag_object"], "native annotated tag changed")
        tag = api.request("GET", prefix + "/git/tags/" + value["tag_object"])
        require(tag.get("sha") == value["tag_object"] and tag.get("tag") == value["tag"]
                and tag.get("object", {}).get("type") == "commit"
                and tag["object"].get("sha") == value["head_sha"], "tag peeled source mismatch")
        if stage in ("release-event", "public-visitor"):
            release = api.request("GET", prefix + "/releases/" + str(value["release_id"]))
            require(type(release.get("id")) is int and release["id"] == value["release_id"]
                    and release.get("tag_name") == value["tag"] and release.get("draft") is False
                    and release.get("prerelease") is False and release.get("published_at"), "native release changed/not public")
            by_tag = api.request("GET", prefix + "/releases/tags/" + value["tag"])
            require(by_tag.get("id") == value["release_id"], "release deleted/recreated")
    if check_event:
        event = value["event"]
        run = api.request("GET", prefix + f"/actions/runs/{event['run_id']}/attempts/{event['run_attempt']}")
        require(type(run.get("id")) is int and type(run.get("run_attempt")) is int
                and run.get("id") == event["run_id"] and run.get("run_attempt") == event["run_attempt"]
                and run.get("event") == event["name"] and run.get("head_sha") == event["workflow_sha"]
                and run.get("path") in ((WORKFLOW, BOOTSTRAP_WORKFLOW) if stage == "pr" else (WORKFLOW,))
                and run.get("repository", {}).get("full_name") == REPOSITORY
                and run.get("actor", {}).get("login") == "taipei49314"
                and run.get("triggering_actor", {}).get("login") == "taipei49314"
                and run.get("status") == "completed" and run.get("conclusion") == "success",
                "native capture run/attempt/workflow/actor mismatch")
        require(utc(run["created_at"]) == utc(event["created_at"]), "native capture time mismatch")
    return stage


def validate_exits(packet, required, after):
    rows = packet.manifest["raw_exits"]
    require(type(rows) is list and rows, "raw command evidence missing")
    names = {}
    for row in rows:
        exact_keys(row, "name argv cwd started_at finished_at duration_seconds exit_code timed_out stdout stderr", "raw exit")
        require(type(row["name"]) is str and row["name"] and row["name"] not in names, "duplicate raw command")
        names[row["name"]] = row
        require(type(row["exit_code"]) is int and row["exit_code"] == 0 and row["timed_out"] is False, "raw command failed: " + row["name"])
        require(type(row["argv"]) is list and row["argv"] and all(type(arg) is str for arg in row["argv"])
                and type(row["cwd"]) is str and row["cwd"], "raw command identity")
        require(utc(row["finished_at"]) >= utc(row["started_at"]) >= after, "pre-event/backwards execution evidence")
        require(type(row["duration_seconds"]) in (int, float) and math.isfinite(row["duration_seconds"])
                and row["duration_seconds"] >= 0, "raw duration invalid")
        packet.raw(row["stdout"])
        packet.raw(row["stderr"])
    require(required <= names.keys(), "required release command missing: " + str(sorted(required - names.keys())))
    return names


def validate_nested(packet, path):
    rows = packet.json(path)
    require(type(rows) is list and rows, "nested command ledger empty")
    parent = PurePosixPath(path).parent
    for row in rows:
        exact_keys(row, "argv cwd started_at finished_at duration_seconds exit_code timed_out error stdout stderr", "nested command")
        require(type(row["argv"]) is list and row["argv"] and all(type(arg) is str for arg in row["argv"])
                and type(row["cwd"]) is str and row["cwd"] and row["timed_out"] is False
                and row["error"] is None and type(row["exit_code"]) is int, "nested command malformed/failed")
        require(row["exit_code"] in (0, 1, 2), "unexpected nested command exit")
        if row["argv"][0].replace("\\", "/").rsplit("/", 1)[-1].lower() in ("git", "git.exe"):
            require(row["exit_code"] == 0, "nested Git evidence read failed")
        require(utc(row["finished_at"]) >= utc(row["started_at"]) >= utc(packet.manifest["subject"]["event"]["created_at"]), "pre-event/backwards nested command")
        require(type(row["duration_seconds"]) in (int, float) and math.isfinite(row["duration_seconds"])
                and row["duration_seconds"] >= 0, "nested duration invalid")
        for field in ("stdout", "stderr"):
            segment = row[field]
            exact_keys(segment, "path offset bytes sha256", "raw segment")
            offset, count = B.integer(segment["offset"], "offset"), B.integer(segment["bytes"], "segment size")
            raw = packet.raw((parent / B.safe_path(segment["path"])).as_posix())
            require(offset + count <= len(raw) and digest(raw[offset:offset + count]) == sha(segment["sha256"]), "nested raw byte linkage mismatch")
    return rows


def validate_qualification_raw(packet, distribution, desc, qualification, exits):
    prefix = "nested-qualify-" + distribution
    rows = validate_nested(packet, prefix + "/commands.json")
    outer = exits["qualify-" + distribution]["argv"]
    require(outer[-2:-1] == ["--"], "qualification interpreter admission missing")
    interpreter = outer[-1]
    if distribution == "source":
        require("--source-root" in outer, "qualification source argument absent")
        source = outer[outer.index("--source-root") + 1]
        path = PureWindowsPath(source) if re.match(r"[A-Za-z]:", source) else PurePosixPath(source)
        bootstrap = "import sys; sys.path.insert(0, " + repr(str(path / "src")) + "); from checkwash.cli import main; raise SystemExit(main())"
        command = [interpreter, "-I", "-B", "-c", bootstrap]
        require(interpreter == packet.manifest["runtime"]["python_executable"], "source qualifier uses different Python")
    elif distribution == "pyz":
        require("--artifact" in outer, "qualification artifact argument absent")
        command = [interpreter, "-B", "-I", outer[outer.index("--artifact") + 1]]
        require(interpreter == packet.manifest["runtime"]["python_executable"], "pyz qualifier uses different Python")
    else:
        command = [interpreter, "-B", "-I", "-m", "checkwash"]
        require(exits["wheel-install"]["argv"][0] == interpreter, "wheel qualifier uses different installed environment")

    def output(row, field):
        part = row[field]
        raw = packet.raw(prefix + "/" + part["path"])
        return raw[part["offset"]:part["offset"] + part["bytes"]]

    case_args = ["check", "HEAD~1..HEAD", "--format", "json"]
    actual = [row for row in rows if row["argv"][-4:] == case_args]
    require(len(actual) == len(desc["cases"]), "qualification raw case completeness differs")
    qa = load_trusted("qualify_assertions")
    version = desc["version"].removeprefix("checkwash ")
    cwd = actual[0]["cwd"]
    for case, written, row in zip(desc["cases"], qualification["cases"], actual):
        require(row["argv"] == command + case_args and row["cwd"] == cwd, "qualification raw case command/source differs")
        raw = output(row, "stdout")
        B.strict_json(raw)
        completed = subprocess.CompletedProcess(row["argv"], row["exit_code"], raw.decode("utf-8", "replace"), output(row, "stderr").decode("utf-8", "replace"))
        observed = qa.observe(completed, case, version)
        require(same(observed, written), "qualification raw case observation differs: " + case["id"])
    controls = {}
    for name, args in (("version", ["--version"]), ("clean", ["check", "HEAD..HEAD", "--format", "json"]),
                       ("invalid", ["check", "MISSING_QUALIFICATION_REF..HEAD", "--format", "json"])):
        selected = [row for row in rows if row["argv"] == command + args]
        require(len(selected) == 1 and selected[0]["cwd"] == cwd, "qualification raw control missing/duplicate: " + name)
        controls[name] = selected[0]
    require(controls["version"]["exit_code"] == 0 and output(controls["version"], "stdout").decode("utf-8", "replace").strip() == desc["version"], "qualification raw version control differs")
    raw = output(controls["clean"], "stdout")
    B.strict_json(raw)
    clean = subprocess.CompletedProcess(controls["clean"]["argv"], controls["clean"]["exit_code"], raw.decode("utf-8", "replace"), output(controls["clean"], "stderr").decode("utf-8", "replace"))
    expected = dict(id="clean", kind="control", path=desc["cases"][-1]["path"], verdict="pass", rule=None, severity=None)
    require(qa.observe(clean, expected, version)["status"] == "passed" and controls["invalid"]["exit_code"] == 2
            and b"engine error" in output(controls["invalid"], "stderr"), "qualification raw clean/invalid controls failed")


def validate_product(packet, source_root, trusted_root, collector):
    manifest = packet.manifest
    runtime = manifest["runtime"]
    exact_keys(runtime, "os python_version python_executable python_sha256 git_executable git_sha256 bash_executable bash_sha256 dependencies other_platforms", "runtime")
    require(runtime["os"] == "Windows" and runtime["python_version"] == "3.11.9"
            and runtime["other_platforms"] == "NOT_RUN", "release runtime scope differs")
    for key in ("python_sha256", "git_sha256", "bash_sha256"):
        sha(runtime[key])
    require(type(runtime["dependencies"]) is dict and runtime["dependencies"], "runtime dependencies absent")
    for key in ("python_executable", "git_executable", "bash_executable"):
        require(type(runtime[key]) is str and runtime[key], "runtime executable absent")
    records = manifest["records"]
    exact_keys(records, "dogfood action_replay candidate_action_coverage junit qualifications inventories contract_descriptor release", "release records")
    for key in ("qualifications", "inventories"):
        exact_keys(records[key], "source wheel pyz", key)
    desc = B.validate_contract(packet, records["contract_descriptor"], source_root, trusted_root,
                               manifest["head_sha"], manifest["source_tree"], collector)
    required = set(B.REQUIRED_EXITS) | {"verdict-gate", "twine-check"}
    if manifest["subject"]["stage"] == "public-visitor":
        required -= {"build-wheel", "build-pyz"}
        required.add("public-pyz-qualification")
    else:
        required.add("zipapp-qualification")
    exits = validate_exits(packet, required, utc(manifest["subject"]["event"]["created_at"]))
    argv = exits["pytest"]["argv"]
    require(len(argv) == 20 and argv[0] == runtime["python_executable"]
            and argv[1:16] == ["-I", "-B", "-X", "utf8", "-m", "pytest", "-p", "xdist.plugin", "-n", "2",
                              "--dist", "worksteal", "-p", "no:cacheprovider", "--basetemp"]
            and argv[17] == "--junitxml" and argv[19] == "tests"
            and argv[18].replace("\\", "/").endswith("/" + records["junit"]), "full pytest scope mismatch")
    junit = B.validate_junit(packet.raw(records["junit"]), pytest_stdout=packet.raw(exits["pytest"]["stdout"]),
                             pytest_version=runtime["dependencies"].get("pytest"))
    B.validate_action(packet, records, manifest["head_sha"], manifest["base_sha"], trusted_root)
    B.validate_candidate_action(packet, records, manifest["head_sha"], manifest["base_sha"], source_root, trusted_root, collector)
    artifacts = {}
    for distribution in ("source", "wheel", "pyz"):
        qpath = records["qualifications"][distribution]
        qualification = packet.json(qpath)
        B.validate_qualification(qualification, desc, distribution)
        validate_qualification_raw(packet, distribution, desc, qualification, exits)
        inventory = packet.json(records["inventories"][distribution])
        B.validate_inventory(packet, inventory, desc, qualification, qpath, distribution)
        for row in inventory["artifacts"]:
            expected = {"sha256": row["sha256"], "bytes": row["bytes"]}
            require(row["name"] not in artifacts or artifacts[row["name"]] == expected, "mixed artifact identities")
            artifacts[row["name"]] = expected
        for prefix in ("nested-qualify-", "nested-inventory-"):
            validate_nested(packet, prefix + distribution + "/commands.json")
    version = desc["version"].removeprefix("checkwash ")
    require(set(artifacts) == {f"checkwash-{version}-py3-none-any.whl", f"checkwash-{version}.tar.gz", "checkwash.pyz"}, "release artifact basename set differs")
    inventory_module = load_trusted("release_inventory")
    require((Path(trusted_root) / "tools/release_inventory.py").read_bytes()
            == git(trusted_root, "show", collector + ":tools/release_inventory.py"), "trusted inventory helper changed")
    inventory_module.ROOT = Path(source_root)
    inventory_module.git = lambda *args: git(source_root, *args)
    source_members = B.tree_files(source_root, manifest["head_sha"], "src")
    for name in artifacts:
        matches = [path for path in packet.files if PurePosixPath(path).name == name]
        require(len(matches) == 1, "deep artifact inventory ambiguous")
        inventory_module.archive_inventory(packet.root / matches[0], source_members)
    validate_nested(packet, "nested-advertised-source/commands.json")
    if manifest["subject"]["stage"] not in ("pr", "main"):
        validate_nested(packet, "nested-tag-source/commands.json")
    validate_nested(packet, "nested-" + ("public-pyz-qualification" if manifest["subject"]["stage"] == "public-visitor" else "zipapp-qualification") + "/commands.json")
    if manifest["subject"]["tag"] is not None:
        require(manifest["subject"]["tag"] == "v" + version, "tag/source version mismatch")
    return desc, junit, exits, artifacts


def trusted_verdict(trusted_root, collector):
    for name in ("verdict_gate.py", "qualify_assertions.py", "assertion_contract.py"):
        path = Path(trusted_root) / "tools" / name
        B.regular(path)
        require(path.read_bytes() == git(trusted_root, "show", collector + ":tools/" + name), "trusted verdict helper changed")
    return load_trusted("verdict_gate")


def validate_verdict(packet, source_root, trusted_root, collector, desc):
    records = packet.manifest["records"]["release"]
    value = packet.json(records["verdict"])
    inventory = packet.json(records["verdict_inventory"])
    exact_keys(inventory, "schema_version files engines", "verdict inventory")
    require(type(inventory["schema_version"]) is int and inventory["schema_version"] == 1, "verdict inventory schema")
    head = packet.manifest["head_sha"]
    paths = ("tests/verdict_gate/baseline.toml", "tests/verdict_gate/labels.toml", "tests/gates/verdict_gate_accepted.toml")
    files = {path: git(source_root, "show", head + ":" + path) for path in paths}
    files.update({"tests/verdict_gate/cases/" + name: raw for name, raw in B.tree_files(source_root, head, "tests/verdict_gate/cases").items()})
    proof = {name: {"git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest(),
                    "sha256": digest(raw), "bytes": len(raw)} for name, raw in files.items()}
    require(same(inventory["files"], proof), "verdict source universe differs")
    for path in paths:
        B.regular(Path(source_root) / path)
        require((Path(source_root) / path).read_bytes() == files[path], "verdict source file differs from Git")
    vg = trusted_verdict(trusted_root, collector)
    pins = vg.load_pins(Path(source_root) / paths[0])
    labels = vg.load_labels(Path(source_root) / paths[1])
    accepted = vg.load_acceptance(Path(source_root) / paths[2])
    cases = []
    for name, raw in sorted(files.items()):
        if name.startswith("tests/verdict_gate/cases/"):
            relative = name.removeprefix("tests/verdict_gate/cases/")
            require(relative.count("/") == 1 and relative.endswith(".vgcase"), "invalid verdict case path")
            cases.append(vg.parse_case(raw, relative.removesuffix(".vgcase")))
    t1 = {case.id: case.input_sha256 for case in cases}
    chai_raw = git(source_root, "show", pins["baseline"]["commit"] + ":" + vg.CHAI_PATH)
    chai, chai_info = vg.parse_chai_cases(chai_raw)
    cases = sorted(cases + chai, key=lambda case: case.id)
    require(value.get("schema_version") == 1 and type(value["schema_version"]) is int
            and value.get("mode") == "gate" and value.get("status") == "passed"
            and value.get("failures") == [], "verdict gate failed/schema")
    inputs = value["inputs"]
    require(inputs["pins_sha256"] == digest(files[paths[0]])
            and inputs["labels_sha256"] == digest(files[paths[1]])
            and inputs["accepted_sha256"] == digest(files[paths[2]])
            and inputs["cases_sha256"] == canonical(t1)
            and same(inputs["t3"], {**chai_info, "commit": pins["baseline"]["commit"]}), "verdict input hashes differ")
    require(not vg.compare_t3({case.id: case.input_sha256 for case in chai}, pins["t3"])["failures"], "verdict T3 pin mismatch")
    exact_keys(inventory["engines"], "baseline candidate canary-old canary-new", "verdict engine inventory")
    exact_keys(value["engines"], "baseline candidate canary-old canary-new", "verdict engine results")
    raw_rows = validate_nested(packet, "nested-verdict/commands.json")

    def output(row, field):
        part = row[field]
        raw = packet.raw("nested-verdict/" + part["path"])
        return raw[part["offset"]:part["offset"] + part["bytes"]]

    for role, item in inventory["engines"].items():
        exact_keys(item, "source_sha pyz sha256 bytes runtime_path", "verdict engine")
        pin = None if role == "candidate" else pins["baseline"] if role == "baseline" else pins["canary"]["old" if role == "canary-old" else "new"]
        expected_commit = head if pin is None else pin["commit"]
        require(item["source_sha"] == expected_commit, "verdict engine source mismatch")
        raw = packet.raw(item["pyz"])
        require(type(item["bytes"]) is int and item["bytes"] == len(raw) and item["sha256"] == digest(raw), "verdict pyz bytes mismatch")
        if pin is not None:
            require(item["sha256"] == pin["sha256"] and item["bytes"] == pin["size"], "verdict historical pyz pin mismatch")
        else:
            q = packet.json(packet.manifest["records"]["qualifications"]["pyz"])
            require(item["sha256"] == q["artifact_sha256"], "verdict candidate is not qualified artifact")
        members = B.archive_members(raw, "engine.pyz")
        source = B.tree_files(source_root, expected_commit, "src/checkwash")
        expected_members = {"checkwash/" + name: {"bytes": len(contents), "sha256": digest(contents)} for name, contents in source.items()}
        require({name: row for name, row in members.items() if name.startswith("checkwash/")
                 and "__pycache__" not in PurePosixPath(name).parts and not name.endswith(".pyc")} == expected_members,
                "verdict engine archive/source members differ")
        require(not vg.archive_extras(packet.root / item["pyz"])
                and members["__main__.py"]["sha256"] == digest(vg.ZIPAPP_MAIN), "verdict pyz extras/entrypoint")
        record = value["engines"][role]
        version = tomllib.loads(git(source_root, "show", expected_commit + ":pyproject.toml").decode())["project"]["version"]
        require(record.get("role") == role and record.get("errors") == [] and record.get("source_commit") == expected_commit
                and record.get("sha256") == item["sha256"] and type(record.get("size")) is int and record["size"] == len(raw)
                and record.get("source_version") == record.get("expected_version") == version
                and record.get("cli_version") == "checkwash " + version
                and record.get("controls") == {"clean_range": "ok", "invalid_ref": "ok"}
                and record.get("proposed_pin") is None, "verdict engine identity/control mismatch")
        owner = record.get("controls_from") or role
        require(owner in inventory["engines"] and inventory["engines"][owner]["sha256"] == item["sha256"], "invalid control reuse")
        runtime = inventory["engines"][owner]["runtime_path"]
        selected = [row for row in raw_rows if len(row["argv"]) >= 5 and row["argv"][3] == runtime]
        versions = [row for row in selected if row["argv"][4:] == ["--version"]]
        require(len(versions) == 1 and versions[0]["exit_code"] == 0
                and output(versions[0], "stdout").decode("utf-8").strip() == "checkwash " + version, "raw verdict version control missing")
        clean = [row for row in selected if row["argv"][4:] == ["check", "HEAD..HEAD", "--format", "json"]]
        invalid = [row for row in selected if row["argv"][4:] == ["check", vg.INVALID_REF + "..HEAD", "--format", "json"]]
        require(len(clean) == len(invalid) == 1, "raw verdict controls missing/duplicate")
        observed = vg.observe(clean[0]["exit_code"], output(clean[0], "stdout"), output(clean[0], "stderr"), version=version)
        require(not observed["errors"] and observed["exit"] == 0 and observed["verdict"] == "pass"
                and observed["findings"] == [] and observed["config_errors"] == [] and observed["skipped_files"] == []
                and invalid[0]["exit_code"] == 2 and b"engine error" in output(invalid[0], "stderr"), "raw verdict control failed")
    rows = value["cases"]
    require(type(rows) is list and [row.get("id") for row in rows] == [case.id for case in cases], "verdict case completeness/order mismatch")
    evaluated = []
    for index, (case, row) in enumerate(zip(cases, rows)):
        require(row["tier"] == case.tier and row["input_sha256"] == case.input_sha256
                and row["not_run"] is None and type(row["git_shape"]) is list, "verdict case identity/coverage mismatch")
        needed = vg.ROLES if case.tier == "T1" else vg.GATE_ROLES
        exact_keys(row["runs"], " ".join(needed), "case engine coverage")
        for role in needed:
            owner = value["engines"][role].get("observations_from") or role
            require(owner in inventory["engines"] and inventory["engines"][owner]["sha256"] == inventory["engines"][role]["sha256"], "invalid case observation reuse")
            runtime = inventory["engines"][owner]["runtime_path"]
            suffix = f"/cases/{index:04d} {case.id.replace('/', ' ').replace(':', ' ')}"
            matches = [item for item in raw_rows if len(item["argv"]) >= 5 and item["argv"][3] == runtime
                       and item["argv"][4:] == vg.case_arguments(case) and item["cwd"].replace("\\", "/").endswith(suffix)]
            require(len(matches) == 1, "raw verdict case missing/duplicate: " + case.id + "/" + role)
            native = matches[0]
            observed = vg.observe(native["exit_code"], output(native, "stdout"), output(native, "stderr"),
                                  version=value["engines"][role]["expected_version"], threshold=case.threshold)
            require(same(observed, row["runs"][role]), "raw verdict case observation differs: " + case.id)
        reduced = vg._row(case)
        reduced.update(runs=row["runs"], not_run=None, git_shape=row["git_shape"])
        evaluated.append(reduced)
    result = vg.evaluate(evaluated, labels=labels, acceptance=accepted, pin_tag=pins["baseline"]["tag"], baseline_blocked=pins["baseline_blocked"])
    canary = vg.evaluate_canary([row for row in evaluated if row["tier"] == "T1"], pinned=pins["canary"]["block_to_pass"], checked_roles=vg.GATE_ROLES)
    require(result["failures"] == [] and canary["failures"] == [], "independent verdict evaluation failed")
    require(same(value["reported"], result["reported"]) and value["summary"]["cases"] == len(cases)
            and type(value["summary"]["cases"]) is int and value["summary"]["failures"] == 0
            and type(value["summary"]["failures"]) is int
            and type(value["summary"]["t1"]) is int and value["summary"]["t1"] == len(t1)
            and type(value["summary"]["t3"]) is int and value["summary"]["t3"] == len(chai)
            and type(value["summary"]["reported"]) is int and value["summary"]["reported"] == len(result["reported"]), "verdict summary differs")
    if packet.manifest["subject"]["stage"] not in ("pr", "main"):
        errors, tag_rule = vg.check_tag_rule(Path(source_root), packet.manifest["subject"]["tag"], pins["baseline"])
        require(not errors and same(value["tag_rule"], tag_rule), "tag baseline rule differs")
    return {"cases": len(cases), "baseline": pins["baseline"]["tag"]}


def validate_source_receipt(value, *, tag, commit, tag_object, tree, trusted_root, collector):
    expected = {"tag": tag, "expected_commit": commit, "expected_source_commit": commit,
                "source_commit": commit, "source_tree": tree, "tag_object": tag_object,
                "tag_commit": commit, "remote": "https://github.com/" + REPOSITORY + ".git",
                "remote_tag_object": tag_object, "remote_tag_commit": commit}
    require(type(value.get("schema_version")) is int and value["schema_version"] == 1
            and value.get("status") == "passed" and value.get("errors") == []
            and all(value.get(key) == item for key, item in expected.items()), "published source identity evidence differs")
    require(value.get("public_surfaces") == ["src/", "pyproject.toml", "action/", ".pre-commit-hooks.yaml"]
            and value.get("validator_sha256") == digest(git(trusted_root, "show", collector + ":tools/verify_published_source.py")),
            "published source validator/surface differs")


def validate_visitor(packet, value, exits, source_root, commit, version, *, source_identity=None, artifact_sha=None):
    exact_keys(value, "name status target identity install_report expected_members", "visitor")
    name = value["name"]
    require(type(name) is str and re.fullmatch(r"[a-z-]+", name) and value["status"] == "completed", "visitor identity/status")
    expected = {"checkwash/" + path: digest(raw) for path, raw in B.tree_files(source_root, commit, "src/checkwash").items()
                if "__pycache__" not in PurePosixPath(path).parts and not path.endswith(".pyc")}
    require(same(packet.json(value["expected_members"]), expected), "visitor expected installed members differ from source")
    identity = packet.json(value["identity"])
    exact_keys(identity, "version direct_url dependencies members requires", "visitor installed identity")
    require(identity["version"] == version and same(identity["members"], expected)
            and type(identity["dependencies"]) is dict
            and set(identity["dependencies"]) <= {"pip", "setuptools", "checkwash"}
            and identity["dependencies"].get("checkwash") == version, "visitor installation identity/dependencies differ")
    direct = identity["direct_url"]
    require(type(direct) is dict, "visitor direct_url absent")
    if source_identity is not None:
        require(direct.get("url") == "https://github.com/" + REPOSITORY + ".git"
                and direct.get("vcs_info", {}).get("vcs") == "git"
                and direct["vcs_info"].get("commit_id") == source_identity
                and value["target"] == "git+https://github.com/" + REPOSITORY + ".git@" + direct["vcs_info"].get("requested_revision", ""),
                "visitor public Git installation identity differs")
    if artifact_sha is not None:
        require(direct.get("archive_info", {}).get("hashes", {}).get("sha256") == artifact_sha, "visitor installed different artifact bytes")
    installation = packet.json(value["install_report"])
    require(installation.get("version") == "1" and type(installation.get("install")) is list
            and len(installation["install"]) == 1 and installation["install"][0].get("metadata", {}).get("name") == "checkwash"
            and installation["install"][0]["metadata"].get("version") == version, "visitor pip installation report differs")
    project = tomllib.loads(git(source_root, "show", commit + ":pyproject.toml").decode())["project"]
    expected_requirements = list(project["dependencies"])
    expected_requirements.extend(item + "; extra == '" + extra + "'" for extra, items in project.get("optional-dependencies", {}).items() for item in items)
    def normalized_requirements(rows):
        require(type(rows) is list and all(type(item) is str for item in rows), "invalid visitor dependency metadata")
        return Counter(re.sub(r"\s+", "", item).replace('"', "'").lower() for item in rows)
    wanted = normalized_requirements(expected_requirements)
    require(normalized_requirements(identity["requires"] or []) == wanted
            and normalized_requirements(installation["install"][0]["metadata"].get("requires_dist", [])) == wanted,
            "visitor Requires-Dist differs from source")
    commands = {}
    for suffix in ("venv", "install", "identity", "dependencies", "version", "demo", "check"):
        key = name + "-" + suffix
        require(key in exits, "visitor command missing: " + key)
        commands[suffix] = exits[key]
    installed_python = commands["install"]["argv"][0]
    for suffix in ("install", "identity", "dependencies", "version", "demo", "check"):
        require(commands[suffix]["argv"][:5] == [installed_python, "-I", "-B", "-X", "utf8"], "visitor runtime/isolation differs")
    install = commands["install"]["argv"]
    require(install[5:7] == ["-m", "pip"] and "install" in install and "--no-deps" in install
            and "--no-cache-dir" in install and "--report" in install and install[-1] == value["target"], "visitor install target/flags differ")
    require(commands["dependencies"]["argv"][5:] == ["-m", "pip", "check"]
            and commands["version"]["argv"][5:] == ["-m", "checkwash", "--version"]
            and packet.raw(commands["version"]["stdout"]).decode("utf-8").strip() == "checkwash " + version
            and commands["demo"]["argv"][5:] == ["-m", "checkwash", "demo"], "visitor runtime checks differ")
    check = commands["check"]["argv"]
    require(check[5:9] == ["-m", "checkwash", "check", packet.manifest["base_sha"] + ".." + packet.manifest["head_sha"]]
            and len(check) == 13 and check[9] == "--repo" and check[11:] == ["--fail-on", "high"], "visitor actual candidate range/threshold differs")


def validate_network(packet):
    rows = packet.json("release/network.json")
    require(type(rows) is list and rows, "network evidence absent")
    names = {}
    for row in rows:
        exact_keys(row, "name url started_at finished_at final_url status error path bytes sha256 truncated", "network read")
        require(type(row["name"]) is str and row["name"] not in names and row["status"] == "completed"
                and row["error"] is None and row["truncated"] is False, "failed/duplicate/truncated public read")
        require(utc(row["finished_at"]) >= utc(row["started_at"]) >= utc(packet.manifest["subject"]["event"]["created_at"]), "pre-event public read")
        raw = packet.raw(row["path"])
        require(type(row["bytes"]) is int and row["bytes"] == len(raw) and row["sha256"] == digest(raw), "public response raw bytes differ")
        parsed = urllib.parse.urlsplit(row["url"])
        final = urllib.parse.urlsplit(row["final_url"])
        allowed = {"github.com", "api.github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com", "pypi.org", "files.pythonhosted.org"}
        require(all(part.scheme == "https" and part.hostname in allowed and part.username is None and part.password is None
                    and part.port in (None, 443) for part in (parsed, final)), "unapproved network response origin")
        names[row["name"]] = row
    return names


def validate_visitors(packet, source_root, trusted_root, collector, desc, exits, artifacts):
    manifest, records = packet.manifest, packet.manifest["records"]["release"]
    exact_keys(records, "subject verdict verdict_inventory advertised tag_source tag_visitor publication", "release-specific records")
    advertised = tomllib.loads(git(source_root, "show", manifest["head_sha"] + ":release/advertised.toml").decode())
    value = packet.json(records["advertised"])
    exact_keys(value, "schema_version status release source visitor download", "advertised visitor")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1 and value["status"] == "completed"
            and same(value["release"], advertised["release"]), "advertised visitor subject differs")
    release = advertised["release"]
    tree = git(source_root, "rev-parse", release["commit"] + "^{tree}").decode().strip()
    validate_source_receipt(packet.json(value["source"]), tag=release["tag"], commit=release["commit"], tag_object=release["tag_object"],
                            tree=tree, trusted_root=trusted_root, collector=collector)
    validate_visitor(packet, value["visitor"], exits, source_root, release["commit"], release["version"], source_identity=release["commit"])
    require(value["visitor"]["target"] == "git+https://github.com/" + REPOSITORY + ".git@" + release["tag"], "advertised visitor target differs")
    downloaded = packet.raw(value["download"]["path"])
    require(value["download"]["bytes"] == len(downloaded) == advertised["pyz"]["bytes"]
            and value["download"]["sha256"] == digest(downloaded) == advertised["pyz"]["sha256"], "advertised public pyz bytes differ")
    network = validate_network(packet)
    require(network["advertised-pyz"]["url"] == advertised["pyz"]["url"]
            and packet.raw(network["advertised-pyz"]["path"]) == downloaded, "advertised download raw read differs")
    current = manifest["subject"]
    version = desc["version"].removeprefix("checkwash ")
    if current["stage"] in ("pr", "main"):
        require(records["tag_source"] is records["tag_visitor"] is records["publication"] is None, "pre-tag stage claims future tag/publication")
    else:
        validate_source_receipt(packet.json(records["tag_source"]), tag=current["tag"], commit=current["head_sha"],
            tag_object=current["tag_object"], tree=current["source_tree"], trusted_root=trusted_root, collector=collector)
        visitor = packet.json(records["tag_visitor"])
        exact_keys(visitor, "schema_version status subject visitor", "tag visitor")
        require(type(visitor["schema_version"]) is int and visitor["schema_version"] == 1
                and visitor["status"] == "completed" and same(visitor["subject"], current), "tag visitor subject differs")
        validate_visitor(packet, visitor["visitor"], exits, source_root, current["head_sha"], version, source_identity=current["head_sha"])
        require(visitor["visitor"]["target"] == "git+https://github.com/" + REPOSITORY + ".git@" + current["tag"], "tag visitor target differs")
        if current["stage"] != "public-visitor":
            require(records["publication"] is None, "pre-public receipt claims public distribution installs")
    if current["stage"] == "public-visitor":
        validate_publication(packet, records["publication"], network, source_root, current, version, exits, artifacts)


def validate_publication(packet, path, network, source_root, current, version, exits, artifacts):
    value = packet.json(path)
    exact_keys(value, "schema_version status subject expected_set expected_set_sha256 github_release pypi_version downloads visitors", "publication")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1 and value["status"] == "completed"
            and same(value["subject"], current) and same(value["expected_set"], artifacts)
            and value["expected_set_sha256"] == digest(packet.raw("release/expected-artifacts.json"))
            and same(packet.json("release/expected-artifacts.json"), artifacts), "public expected artifact set differs")
    release = packet.json(value["github_release"])
    pypi = packet.json(value["pypi_version"])
    require(release.get("id") == current["release_id"] and release.get("tag_name") == current["tag"]
            and release.get("draft") is False and release.get("prerelease") is False
            and len(release["assets"]) == 3 and {row["name"] for row in release["assets"]} == set(artifacts), "public GitHub release identity/set differs")
    require(pypi.get("info", {}).get("version") == version and len(pypi["urls"]) == 2
            and {row["filename"] for row in pypi["urls"]} == set(artifacts) - {"checkwash.pyz"}, "public PyPI file set differs")
    require(network["github-release"]["url"] == f"https://api.github.com/repos/{REPOSITORY}/releases/{current['release_id']}"
            and network["pypi-version"]["url"] == f"https://pypi.org/pypi/checkwash/{version}/json", "public metadata endpoints differ")
    downloads = value["downloads"]
    require(type(downloads) is list and len(downloads) == 5, "five actual public downloads required")
    found = {}
    for item in downloads:
        channel, name = item["channel"], item["name"]
        require(channel in ("github", "pypi") and name in artifacts and (channel, name) not in found, "duplicate/unexpected public file")
        exact_keys(item, "channel name url path bytes sha256" + (" asset_id" if channel == "github" else ""), "public download")
        raw = packet.raw(item["path"])
        require(type(item["bytes"]) is int and item["bytes"] == len(raw) == artifacts[name]["bytes"]
                and item["sha256"] == digest(raw) == artifacts[name]["sha256"], "actual downloaded public bytes differ")
        suffix = "wheel" if name.endswith(".whl") else "sdist" if name.endswith(".tar.gz") else "pyz"
        read = network[channel + "-" + suffix]
        require(read["url"] == item["url"] and packet.raw(read["path"]) == raw, "public download network/raw linkage differs")
        if channel == "github":
            assets = [row for row in release["assets"] if row["name"] == name and row.get("id") == item["asset_id"]]
            require(len(assets) == 1 and assets[0].get("state") == "uploaded"
                    and assets[0].get("size") == len(raw) and assets[0].get("digest") == "sha256:" + digest(raw)
                    and item["url"] == assets[0].get("browser_download_url") == f"https://github.com/{REPOSITORY}/releases/download/{current['tag']}/{name}",
                    "public GitHub asset identity differs")
        else:
            packages = [row for row in pypi["urls"] if row["filename"] == name]
            require(len(packages) == 1 and packages[0].get("url") == item["url"]
                    and urllib.parse.urlsplit(item["url"]).hostname == "files.pythonhosted.org"
                    and packages[0].get("size") == len(raw) and packages[0].get("digests", {}).get("sha256") == digest(raw)
                    and packages[0].get("yanked") is False, "public PyPI file identity differs")
        found[(channel, name)] = item
    require(set(found) == {("github", name) for name in artifacts} | {("pypi", name) for name in artifacts if name != "checkwash.pyz"}, "public download coverage differs")
    visitors = value["visitors"]
    require(type(visitors) is list and len(visitors) == 5 and {row["name"] for row in visitors} == {"github-wheel", "github-sdist", "pypi-wheel", "pypi-sdist", "github-pyz"}, "public installation coverage differs")
    for visitor in visitors:
        if visitor["name"] == "github-pyz":
            exact_keys(visitor, "name status path", "public pyz visitor")
            require(visitor["status"] == "completed" and digest(packet.raw(visitor["path"])) == artifacts["checkwash.pyz"]["sha256"]
                    and all(key in exits for key in ("public-pyz-qualification", "public-pyz-version", "public-pyz-demo", "public-pyz-check")), "public pyz visitor incomplete")
            require(packet.raw(exits["public-pyz-version"]["stdout"]).decode("utf-8").strip() == "checkwash " + version, "public pyz version differs")
        else:
            channel, kind = visitor["name"].split("-")
            matches = [item for (origin, name), item in found.items() if origin == channel and name.endswith(".whl" if kind == "wheel" else ".tar.gz")]
            require(len(matches) == 1, "public install download ambiguous")
            validate_visitor(packet, visitor, exits, source_root, current["head_sha"], version, artifact_sha=matches[0]["sha256"])


def validate_parents(packet, api, current):
    expected = PREVIOUS[current["stage"]]
    parents = packet.manifest["parents"]
    if expected is None:
        exact_keys(parents, "", "PR has no prior release-stage report")
        return None
    exact_keys(parents, expected, "previous stage set")
    link = parents[expected]
    exact_keys(link, "report sha256 check_run_id", "previous stage link")
    require(link["report"] == "parents/" + expected + ".json", "previous report path differs")
    raw = packet.raw(link["report"])
    require(digest(raw) == sha(link["sha256"]), "previous report bytes differ")
    report = B.strict_json(raw)
    require(report.get("status") == "verified" and report.get("repository") == REPOSITORY, "previous stage not verified")
    manifest_digest = sha(report["manifest_sha256"])
    check = api.request("GET", f"/repos/{REPOSITORY}/check-runs/{positive(link['check_run_id'], 'previous check ID')}")
    require(type(check.get("id")) is int and check.get("id") == link["check_run_id"] and check.get("app", {}).get("id") == ACTION_APP_ID
            and check.get("status") == "completed" and check.get("conclusion") == "success", "previous native check incomplete/foreign")
    if expected == "pr":
        require(report.get("kind") == "checkwash.pju-release-verification.v1" and subject(report.get("subject")) == "pr"
                and all(report["subject"][key] == report[key] for key in ("head_sha", "base_sha", "source_tree", "pr_number")),
                "legacy PR receipt lacks release visitor/verdict evidence")
        require(report.get("source_tree") == current["source_tree"] and report.get("base_sha") == current["base_sha"]
                and check.get("name") == "checkwash" and check.get("head_sha") == report.get("head_sha")
                and check.get("external_id") == "pju:" + manifest_digest + ":checkwash", "PR receipt does not bind this main tree")
        pr = api.request("GET", f"/repos/{REPOSITORY}/pulls/{positive(report['pr_number'], 'previous PR')}")
        require(pr.get("state") == "closed" and pr.get("merged") is True
                and pr.get("merge_commit_sha") == current["head_sha"]
                and pr.get("head", {}).get("sha") == report["head_sha"]
                and pr.get("head", {}).get("repo", {}).get("full_name") == REPOSITORY,
                "main source is not the verified PR merge")
        ids = report.get("check_run_ids")
        require(type(ids) is list and len(ids) == len(B.CONTEXTS) and link["check_run_id"] in ids, "PR required check identities absent")
        names = set()
        for check_id in ids:
            native = api.request("GET", f"/repos/{REPOSITORY}/check-runs/{positive(check_id, 'PR check ID')}")
            require(native.get("app", {}).get("id") == ACTION_APP_ID and native.get("head_sha") == report["head_sha"]
                    and native.get("status") == "completed" and native.get("conclusion") == "success"
                    and native.get("name") in B.CONTEXTS
                    and native.get("external_id") == "pju:" + manifest_digest + ":" + native["name"], "PR native required check mismatch")
            names.add(native["name"])
        require(names == set(B.CONTEXTS), "PR required context coverage differs")
        stage_check = api.request("GET", f"/repos/{REPOSITORY}/check-runs/{positive(report['check_run_id'], 'PR release-stage check')}")
        require(stage_check.get("app", {}).get("id") == ACTION_APP_ID and stage_check.get("head_sha") == report["head_sha"]
                and stage_check.get("status") == "completed" and stage_check.get("conclusion") == "success"
                and stage_check.get("name") == context("pr")
                and stage_check.get("external_id") == f"pju-release:{manifest_digest}:pr", "PR release-stage check missing/mismatched")
    else:
        prior = report["subject"]
        require(subject(prior) == expected and prior["head_sha"] == current["head_sha"]
                and prior["source_tree"] == current["source_tree"] and prior["base_sha"] == current["base_sha"],
                "previous stage source differs")
        if expected in ("tag", "release-event"):
            require(prior["tag"] == current["tag"] and prior["tag_object"] == current["tag_object"], "previous tag identity differs")
        if expected == "release-event":
            require(prior["release_id"] == current["release_id"], "public visitor has another release parent")
        require(check.get("name") == context(expected) and check.get("head_sha") == current["head_sha"]
                and check.get("external_id") == f"pju-release:{manifest_digest}:{expected}", "previous native stage check mismatch")
    return {"stage": expected, "report_sha256": link["sha256"], "check_run_id": link["check_run_id"]}


def validate_packet(packet, *, source_root, trusted_root, collector, subject_sha256, api):
    manifest = packet.manifest
    exact_keys(manifest, "schema_version kind repository base_sha head_sha source_tree host provenance collector_source_sha "
                        "contract_source_sha files records raw_exits status runtime action_sha subject parents", "release manifest")
    require(type(manifest["schema_version"]) is int and manifest["schema_version"] == 1
            and manifest["kind"] == "checkwash.pju-release-receipt.v1"
            and manifest["repository"] == REPOSITORY and manifest["host"] == HOST
            and manifest["provenance"] == PROVENANCE and manifest["status"] == "completed"
            and manifest["action_sha"] == B.ACTION_SHA, "release manifest schema/host/status")
    current = manifest["subject"]
    stage = subject(current)
    require(all(manifest[key] == current[key] for key in ("head_sha", "base_sha", "source_tree"))
            and manifest["collector_source_sha"] == manifest["contract_source_sha"] == sha(collector, 40), "release manifest/source/collector mismatch")
    require(digest(packet.raw("native-subject.json")) == sha(subject_sha256)
            and same(packet.json("native-subject.json"), current)
            and manifest["records"]["release"]["subject"] == "native-subject.json", "external native subject admission mismatch")
    payload_raw = packet.raw("release/event-payload.json")
    require(digest(payload_raw) == current["event"]["payload_sha256"], "native event payload bytes differ")
    payload = B.strict_json(payload_raw)
    require(payload.get("repository", {}).get("full_name") == REPOSITORY
            and payload.get("sender", {}).get("login") == "taipei49314", "native event payload repository/actor differs")
    if stage == "release-event":
        require(payload.get("action") == "published" and payload.get("release", {}).get("id") == current["release_id"]
                and payload["release"].get("tag_name") == current["tag"] and payload["release"].get("draft") is False,
                "native release payload differs")
    live_subject(api, current)
    for name in ("tools/verdict_gate.py", "tools/verify_published_source.py", "tools/qualify_zipapp.py"):
        require(git(source_root, "show", current["head_sha"] + ":" + name) == git(trusted_root, "show", collector + ":" + name), "candidate differs from audited release helper")
    collection = packet.json("release/collection.json")
    require(collection.get("status") == "completed" and collection.get("errors") == []
            and collection.get("subject_sha256") == subject_sha256
            and utc(collection["finished_at"]) >= utc(collection["started_at"]) >= utc(current["event"]["created_at"]), "partial/pre-event release collection")
    require(collection.get("parents_sha256") == digest(packet.raw("release/parents-admission.json"))
            and same(packet.json("release/parents-admission.json"), manifest["parents"]), "previous stage admission differs")
    parent = validate_parents(packet, api, current)
    desc, junit, exits, artifacts = validate_product(packet, source_root, trusted_root, collector)
    verdict = validate_verdict(packet, source_root, trusted_root, collector, desc)
    validate_visitors(packet, source_root, trusted_root, collector, desc, exits, artifacts)
    live_subject(api, current)
    report = dict(schema_version=1, kind="checkwash.pju-release-verification.v1", status="verified", repository=REPOSITORY,
                subject=current, collector_source_sha=collector, host=HOST, provenance=PROVENANCE,
                qualification_cases=len(desc["cases"]), junit=junit, verdict=verdict, artifacts=artifacts,
                previous=parent, checks=[context(stage)], other_platforms="NOT_RUN",
                trust="owner-admitted immutable receipt; not hardware attestation",
                publication_authorized=False)
    if stage == "pr":
        report.update(pr_number=current["pr_number"], head_sha=current["head_sha"], base_sha=current["base_sha"], source_tree=current["source_tree"],
                      checks=[*B.CONTEXTS, context(stage)])
    return report


def admitted_record(packet, admission, key):
    link = admission.get(key)
    exact_keys(link, "path sha256", key + " admission")
    raw = packet.raw(link["path"])
    require(digest(raw) == sha(link["sha256"]), key + " record digest differs")
    return B.strict_json(raw)


def publication_authority(packet, admission, report):
    version = report["subject"]["tag"][1:]
    authorization = admitted_record(packet, admission, "release_authorization")
    require(authorization.get("kind") == "checkwash.release-one-time-authorization.v1"
            and authorization.get("status") == "authorized" and authorization.get("version") == version
            and authorization.get("source_sha") == report["subject"]["head_sha"]
            and authorization.get("tag") == report["subject"]["tag"]
            and authorization.get("maintainer") == "Nelson" and type(authorization.get("human_quote")) is str
            and bool(authorization["human_quote"].strip()) and type(authorization.get("human_evidence_reference")) is str
            and bool(authorization["human_evidence_reference"].strip())
            and authorization.get("max_attempts") == 1 and type(authorization["max_attempts"]) is int,
            "exact-version one-time publication authorization absent")
    platform = admitted_record(packet, admission, "platform_acceptance")
    require(platform.get("kind") == "checkwash.release-missing-platform-acceptance.v1"
            and platform.get("status") == "accepted-for-this-release" and platform.get("version") == version
            and platform.get("source_sha") == report["subject"]["head_sha"]
            and platform.get("missing_platforms") == MISSING_PLATFORMS
            and platform.get("cross_platform_byte_comparison") == "NOT_RUN_ACCEPTED_FOR_THIS_RELEASE"
            and platform.get("standing_contract_changed") is False and platform.get("maintainer") == "Nelson"
            and type(platform.get("human_quote")) is str and bool(platform["human_quote"].strip())
            and type(platform.get("human_evidence_reference")) is str and bool(platform["human_evidence_reference"].strip()),
            "version/source-specific missing-platform acceptance absent")
    return {"release_authorization": admission["release_authorization"], "platform_acceptance": admission["platform_acceptance"]}


def admit_environment(expected_workflow_sha, env, *, capture=False, stage=None):
    event = env.get("GITHUB_EVENT_NAME")
    require(event in (("workflow_dispatch", "release") if capture else ("workflow_dispatch",)), "unexpected publication trigger")
    require(env.get("GITHUB_REPOSITORY") == REPOSITORY and env.get("GITHUB_REPOSITORY_OWNER") == "taipei49314"
            and env.get("GITHUB_ACTOR") == "taipei49314" and env.get("GITHUB_TRIGGERING_ACTOR") == "taipei49314",
            "repository-owner dispatch/release/rerun required")
    require(env.get("GITHUB_SHA") == sha(expected_workflow_sha, 40)
            and env.get("GITHUB_WORKFLOW_SHA") == expected_workflow_sha, "reviewed workflow SHA differs")
    paths = (WORKFLOW, BOOTSTRAP_WORKFLOW) if stage == "pr" else (WORKFLOW,)
    require(any(env.get("GITHUB_WORKFLOW_REF", "").startswith(REPOSITORY + "/" + path + "@") for path in paths), "unexpected trusted-publisher workflow")


def read_admission(env, name="PJU_ADMISSION"):
    raw = env.get(name, "").encode("utf-8")
    require(0 < len(raw) <= 64 * 1024, "dispatch admission missing/oversized")
    value = B.strict_json(raw)
    extra = " pr_number" if type(value) is dict and value.get("stage") == "pr" else ""
    exact_keys(value, "schema_version kind stage head base tag release_id receipt_commit manifest_sha256 collector_source_sha "
                      "trusted_workflow_sha subject_sha256 release_authorization platform_acceptance" + extra, "dispatch admission")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1
            and value["kind"] == "checkwash.pju-release-dispatch.v1" and value["stage"] in STAGES, "dispatch admission schema")
    for key in ("head", "base", "receipt_commit", "collector_source_sha", "trusted_workflow_sha"):
        sha(value[key], 40)
    sha(value["manifest_sha256"])
    sha(value["subject_sha256"])
    return value


def capture(api, env, *, admission=None):
    workflow_sha = sha(env.get("GITHUB_WORKFLOW_SHA"), 40)
    requested_stage = "release-event" if env.get("GITHUB_EVENT_NAME") == "release" else admission["stage"]
    admit_environment(workflow_sha if env.get("GITHUB_EVENT_NAME") == "release" else admission["trusted_workflow_sha"], env, capture=True, stage=requested_stage)
    with Path(env["GITHUB_EVENT_PATH"]).open("rb") as stream:
        raw = stream.read(MAX_RESPONSE + 1)
    require(len(raw) <= MAX_RESPONSE, "oversized native event payload")
    event = B.strict_json(raw)
    if env["GITHUB_EVENT_NAME"] == "release":
        require(event.get("action") == "published", "not a published release event")
        release = event["release"]
        stage, tag, release_id = "release-event", release["tag_name"], positive(release["id"], "release ID")
        head = sha(env["GITHUB_SHA"], 40)
    else:
        extra = " pr_number" if requested_stage == "pr" else ""
        exact_keys(admission, "schema_version kind stage head tag release_id trusted_workflow_sha" + extra, "capture admission")
        require(type(admission["schema_version"]) is int and admission["schema_version"] == 1
                and admission["kind"] == "checkwash.pju-release-capture.v1"
                and admission["stage"] in ("pr", "main", "tag", "public-visitor"), "capture admission schema")
        stage, head, tag, release_id = (admission[key] for key in ("stage", "head", "tag", "release_id"))
        sha(head, 40)
    commit = api.request("GET", f"/repos/{REPOSITORY}/git/commits/{head}")
    require(type(commit.get("parents")) is list and commit["parents"], "capture source has no first parent")
    run_id, attempt = int(env["GITHUB_RUN_ID"]), int(env["GITHUB_RUN_ATTEMPT"])
    run = api.request("GET", f"/repos/{REPOSITORY}/actions/runs/{positive(run_id, 'run ID')}/attempts/{positive(attempt, 'attempt')}")
    tag_object = None
    if stage not in ("pr", "main"):
        require(type(tag) is str and re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag), "capture tag malformed")
        ref = api.request("GET", f"/repos/{REPOSITORY}/git/ref/tags/{tag}")
        require(ref.get("object", {}).get("type") == "tag", "annotated public tag required")
        tag_object = ref["object"]["sha"]
    value = dict(schema_version=1, kind="checkwash.pju-release-subject.v1", stage=stage, repository=REPOSITORY,
                 head_sha=head, base_sha=commit["parents"][0]["sha"], source_tree=commit["tree"]["sha"],
                 tag=tag, tag_object=tag_object, release_id=release_id,
                 event=dict(name=env["GITHUB_EVENT_NAME"], run_id=run_id, run_attempt=attempt,
                            workflow_sha=workflow_sha, created_at=run["created_at"], payload_sha256=digest(raw)))
    if stage == "pr":
        pr = api.request("GET", f"/repos/{REPOSITORY}/pulls/{positive(admission['pr_number'], 'PR number')}")
        value.update(pr_number=admission["pr_number"], base_sha=sha(pr["base"]["sha"], 40))
    live_subject(api, value, check_event=False)
    require(type(run.get("id")) is int and type(run.get("run_attempt")) is int
            and run.get("id") == run_id and run.get("run_attempt") == attempt and run.get("event") == env["GITHUB_EVENT_NAME"]
            and run.get("head_sha") == workflow_sha
            and run.get("path") in ((WORKFLOW, BOOTSTRAP_WORKFLOW) if stage == "pr" else (WORKFLOW,))
            and run.get("repository", {}).get("full_name") == REPOSITORY, "native capture run mismatch")
    return value, raw


def verify_admitted(api, admission, *, receipt_root, source_root, trusted_root, env):
    admit_environment(admission["trusted_workflow_sha"], env, stage=admission["stage"])
    require(git(trusted_root, "rev-parse", "HEAD").decode().strip() == admission["trusted_workflow_sha"], "trusted checkout differs")
    require(Path(__file__).resolve() == (Path(trusted_root) / "tools/pju_release_bridge.py").resolve(), "verifier executed outside the admitted trusted checkout")
    for name in ("pju_release_bridge.py", "pju_receipt_bridge.py", "verdict_gate.py", "qualify_assertions.py", "assertion_contract.py"):
        path = Path(trusted_root) / "tools" / name
        require(path.read_bytes() == git(trusted_root, "show", admission["trusted_workflow_sha"] + ":tools/" + name), "trusted verifier bytes changed")
    require(git(Path(receipt_root).parent, "rev-parse", "HEAD").decode().strip() == admission["receipt_commit"], "immutable receipt checkout differs")
    packet = Packet(receipt_root, admission["manifest_sha256"])
    current = packet.manifest["subject"]
    require(current["stage"] == admission["stage"] and current["head_sha"] == admission["head"]
            and current["base_sha"] == admission["base"] and current["tag"] == admission["tag"]
            and current["release_id"] == admission["release_id"], "dispatch subject differs from native subject")
    if admission["stage"] == "pr":
        require(current["pr_number"] == positive(admission["pr_number"], "PR number"), "dispatch PR differs")
    report = validate_packet(packet, source_root=source_root, trusted_root=trusted_root,
                             collector=admission["collector_source_sha"], subject_sha256=admission["subject_sha256"], api=api)
    report.update(receipt_commit=admission["receipt_commit"], manifest_sha256=admission["manifest_sha256"],
                  workflow_sha=admission["trusted_workflow_sha"],
                  verification_run={"id": positive(int(env["GITHUB_RUN_ID"]), "verification run ID"),
                                    "attempt": positive(int(env["GITHUB_RUN_ATTEMPT"]), "verification attempt")})
    return packet, report


def publish_check(api, report, run_url):
    current = report["subject"]
    names = [*B.CONTEXTS, context("pr")] if current["stage"] == "pr" else [context(current["stage"])]
    require(report["status"] == "verified" and report["checks"] == names, "unverified stage check publication")
    live_subject(api, current)
    created = []
    summary = (f"{PROVENANCE}; actual host {HOST}; Windows/Python 3.11.9. Other platforms NOT_RUN.\n\n"
               f"Stage {current['stage']}; source {current['head_sha']}; base {current['base_sha']}; tree {current['source_tree']}; receipt {report['receipt_commit']}; "
               f"manifest SHA256 {report['manifest_sha256']}.\n\n"
               "Full PJU development, source/wheel/pyz qualification/inventory, actual visitor and verdict evidence verified. "
               "This local scope check is not publication authorization or hardware attestation.")
    try:
        for name in names:
            external = (f"pju:{report['manifest_sha256']}:{name}" if name in B.CONTEXTS
                        else f"pju-release:{report['manifest_sha256']}:{current['stage']}")
            result = api.request("POST", f"/repos/{REPOSITORY}/check-runs", dict(name=name, head_sha=current["head_sha"],
                status="in_progress", external_id=external, details_url=run_url,
                output={"title": "PJU release-stage evidence verified; publishing check", "summary": summary}))
            created.append(positive(result["id"], "stage check ID"))
        for check_id in created:
            live_subject(api, current)
            api.request("PATCH", f"/repos/{REPOSITORY}/check-runs/{check_id}", dict(status="completed", conclusion="success",
                        output={"title": "Exact-source PJU release-stage evidence passed", "summary": summary}))
        live_subject(api, current)
        return {"check_run_id": created[-1], "check_run_ids": created[:-1] if current["stage"] == "pr" else []}
    except Exception:
        for check_id in created:
            try:
                api.request("PATCH", f"/repos/{REPOSITORY}/check-runs/{check_id}", dict(status="completed", conclusion="failure",
                    output={"title": "Release-stage publication aborted", "summary": "The native subject changed or check publication failed."}))
            except (OSError, ValueError, urllib.error.URLError):
                pass
        raise


def verify_assets(api, report, *, downloader=public_download):
    current, artifacts = report["subject"], report["artifacts"]
    live_subject(api, current)
    release = api.request("GET", f"/repos/{REPOSITORY}/releases/{current['release_id']}")
    rows = release.get("assets")
    require(type(rows) is list and len(rows) == len(artifacts) and {row.get("name") for row in rows} == set(artifacts), "public Release asset set incomplete/different")
    result = []
    for row in rows:
        name = row["name"]
        expected = artifacts[name]
        url = f"https://github.com/{REPOSITORY}/releases/download/{current['tag']}/{name}"
        require(type(row.get("id")) is int and row["id"] > 0 and row.get("state") == "uploaded"
                and type(row.get("size")) is int and row["size"] == expected["bytes"]
                and row.get("browser_download_url") == url, "uploaded asset native identity differs")
        raw = downloader(url, expected["bytes"])
        require(digest(raw) == expected["sha256"] and (row.get("digest") is None or row["digest"] == "sha256:" + digest(raw)), "uploaded asset actual bytes differ")
        result.append({"id": row["id"], "name": name, **expected})
    live_subject(api, current)
    return {"status": "verified", "release_id": current["release_id"], "tag": current["tag"],
            "source_sha": current["head_sha"], "assets": sorted(result, key=lambda row: row["name"])}


def publish_assets(api, packet, admission, report, *, downloader=public_download):
    require(report["subject"]["stage"] == "release-event", "distribution upload requires release-event evidence")
    publication_authority(packet, admission, report)
    live_subject(api, report["subject"])
    release_id = report["subject"]["release_id"]
    release = api.request("GET", f"/repos/{REPOSITORY}/releases/{release_id}")
    assets = release.get("assets")
    require(type(assets) is list and len({row.get("name") for row in assets}) == len(assets)
            and {row.get("name") for row in assets} <= report["artifacts"].keys(), "unexpected/duplicate pre-existing Release assets")
    existing = {row["name"]: row for row in assets}
    for name, expected in sorted(report["artifacts"].items()):
        live_subject(api, report["subject"])
        matches = [path for path in packet.files if PurePosixPath(path).name == name]
        require(len(matches) == 1, "publication artifact path ambiguous")
        raw = packet.raw(matches[0])
        require(len(raw) == expected["bytes"] and digest(raw) == expected["sha256"], "publication artifact changed")
        if name in existing:
            row = existing[name]
            url = f"https://github.com/{REPOSITORY}/releases/download/{report['subject']['tag']}/{name}"
            require(row.get("size") == expected["bytes"] and row.get("browser_download_url") == url
                    and digest(downloader(url, expected["bytes"])) == expected["sha256"], "existing asset differs; replacement is forbidden")
            continue
        path = f"/repos/{REPOSITORY}/releases/{release_id}/assets?name=" + urllib.parse.quote(name, safe="")
        response = api.binary("POST", path, raw)
        require(response.get("name") == name and response.get("size") == expected["bytes"]
                and type(response.get("id")) is int and response["id"] > 0, "asset upload identity differs")
    return verify_assets(api, report, downloader=downloader)


def export_distributions(packet, report, target, *, pypi_only=False):
    root = Path(target)
    root.mkdir(parents=True, exist_ok=False)
    for name, row in report["artifacts"].items():
        if pypi_only and name == "checkwash.pyz":
            continue
        matches = [path for path in packet.files if PurePosixPath(path).name == name]
        require(len(matches) == 1 and B.safe_path(name) == name and "/" not in name, "export artifact ambiguity")
        raw = packet.raw(matches[0])
        require(digest(raw) == row["sha256"] and len(raw) == row["bytes"], "export artifact changed")
        with (root / name).open("xb") as stream:
            stream.write(raw)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("capture", "verify", "publish-check", "publish-assets", "verify-assets"))
    for flag in ("trusted-root", "source-root", "receipt-root", "export-dist"):
        parser.add_argument("--" + flag)
    parser.add_argument("--pypi-only", action="store_true")
    parser.add_argument("--admission-env", default="PJU_ADMISSION")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    output = Path(args.output)
    report = {"status": "failed", "publication_authorized": False}
    try:
        api = GitHub(os.environ.get("GH_TOKEN"))
        if args.mode == "capture":
            admission = None if os.environ.get("GITHUB_EVENT_NAME") == "release" else B.strict_json(os.environ.get(args.admission_env, "").encode())
            captured, payload = capture(api, os.environ, admission=admission)
            output.mkdir(parents=True, exist_ok=False)
            (output / "subject.json").write_text(json.dumps(captured, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            (output / "event-payload.json").write_bytes(payload)
            print(json.dumps({"status": "captured-metadata-only", "subject": str(output / "subject.json"),
                              "subject_sha256": digest((output / "subject.json").read_bytes()), "product_execution": False}))
            return 0
        require(all((args.trusted_root, args.source_root, args.receipt_root)), "verification checkout paths required")
        admission = read_admission(os.environ, args.admission_env)
        packet, report = verify_admitted(api, admission, receipt_root=args.receipt_root, source_root=args.source_root,
                                        trusted_root=args.trusted_root, env=os.environ)
        if args.mode == "publish-check":
            report.update(publish_check(api, report, f"https://github.com/{REPOSITORY}/actions/runs/{report['verification_run']['id']}"))
        elif args.mode in ("publish-assets", "verify-assets"):
            require(report["subject"]["stage"] == "release-event", "asset handoff needs release-event scope")
            report["authorization"] = publication_authority(packet, admission, report)
            report["assets_readback"] = (publish_assets(api, packet, admission, report) if args.mode == "publish-assets" else verify_assets(api, report))
            report["publication_authorized"] = True
        if args.export_dist:
            require(args.mode in ("publish-assets", "verify-assets") and report["publication_authorized"] is True, "unverified distribution export")
            export_distributions(packet, report, args.export_dist, pypi_only=args.pypi_only)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(report, sort_keys=True, indent=2) + "\n")
        return 0
    except (OSError, ValueError, KeyError, TypeError, RecursionError, ET.ParseError,
            subprocess.SubprocessError, zipfile.BadZipFile, tarfile.TarError, urllib.error.URLError) as error:
        report = {"status": "failed", "publication_authorized": False, "error": type(error).__name__ + ": " + str(error)}
        if args.mode != "capture":
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(report, sort_keys=True, indent=2) + "\n")
        print(json.dumps(report))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
