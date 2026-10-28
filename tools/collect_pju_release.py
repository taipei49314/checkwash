"""Collect fresh release-stage evidence on an authorized local Windows host.

Run with the admitted task-local Python and -I -B -X utf8. Native subject,
event payload and prior reports are immutable external admissions, not claims
authenticated by this collector. The separate bridge resolves their native
GitHub identities. No credentials are passed to product subprocesses; this tool
never creates checks, tags, releases or uploads distributions.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request
import tomllib

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "taipei49314/checkwash"
PUBLIC_GIT = "https://github.com/" + REPOSITORY + ".git"
API = "https://api.github.com/repos/" + REPOSITORY
STAGES = {"pr": set(), "main": {"pr"}, "tag": {"main"}, "release-event": {"tag"}, "public-visitor": {"release-event"}}
MAX_JSON = 2 * 1024 * 1024
MAX_ARTIFACT = 256 * 1024 * 1024
# Tag and later reports carry the raw published-baseline responses (up to
# 16 MiB in published_release_identity), far over MAX_JSON; the verifier
# admits each packet file up to 256 MiB.
MAX_PARENT_REPORT = 256 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def sha(value, length=64):
    require(type(value) is str and re.fullmatch(r"[0-9a-f]{%d}" % length, value), "invalid digest")
    return value


def exact(value, keys, label):
    require(type(value) is dict and set(value) == set(keys.split()), label + " fields differ")


def integer(value):
    require(type(value) is int and value > 0, "positive native integer required")
    return value


def strict_json(raw):
    def pairs(rows):
        result = {}
        for key, value in rows:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    def constant(value):
        raise ValueError("non-finite JSON number: " + value)

    return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)


def read_admitted(path, expected, action, maximum=MAX_JSON):
    path = action.absolute_path(path)
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    require(len(raw) <= maximum and digest(raw) == sha(expected), "admitted input digest/size mismatch")
    return raw, strict_json(raw)


def validate_subject(value):
    require(type(value) is dict and type(value.get("stage")) is str and value["stage"] in STAGES, "subject stage")
    exact(value, "schema_version kind stage repository head_sha base_sha source_tree tag tag_object release_id event"
          + (" pr_number" if value["stage"] == "pr" else ""), "subject")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1
            and value["kind"] == "checkwash.pju-release-subject.v1", "subject schema")
    require(value["stage"] in STAGES and value["repository"] == REPOSITORY, "subject stage/repository")
    for key in ("head_sha", "base_sha", "source_tree"):
        sha(value[key], 40)
    event = value["event"]
    exact(event, "name run_id run_attempt workflow_sha created_at payload_sha256", "event")
    require(event["name"] == ("release" if value["stage"] == "release-event" else "workflow_dispatch"),
            "actual native event required")
    integer(event["run_id"])
    integer(event["run_attempt"])
    sha(event["workflow_sha"], 40)
    sha(event["payload_sha256"])
    require(type(event["created_at"]) is str, "native event timestamp required")
    created = datetime.fromisoformat(event["created_at"].replace("Z", "+00:00"))
    require(created.tzinfo is not None and created.utcoffset().total_seconds() == 0,
            "native event timestamp must be UTC")
    require(created <= datetime.now(timezone.utc), "collection cannot precede native event")
    if value["stage"] in ("pr", "main"):
        require(value["tag"] is value["tag_object"] is value["release_id"] is None, "pre-tag stage has tag/release identity")
        if value["stage"] == "pr":
            integer(value["pr_number"])
    else:
        require(type(value["tag"]) is str and re.fullmatch(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", value["tag"]),
                "canonical stable tag required")
        sha(value["tag_object"], 40)
        if value["stage"] == "tag":
            require(value["release_id"] is None, "tag receipt cannot invent a future release")
        else:
            integer(value["release_id"])
    return value


def validate_artifact_set(value, version):
    names = {"checkwash-" + version + "-py3-none-any.whl", "checkwash-" + version + ".tar.gz", "checkwash.pyz"}
    require(type(value) is dict and set(value) == names, "release artifact set differs")
    for row in value.values():
        exact(row, "bytes sha256", "artifact")
        require(type(row["bytes"]) is int and 0 < row["bytes"] <= MAX_ARTIFACT, "artifact size outside bound")
        sha(row["sha256"])
    return value


def allowed_url(url, origins):
    require(type(url) is str, "download URL required")
    parsed = urllib.parse.urlsplit(url)
    require(parsed.scheme == "https" and parsed.hostname in origins and parsed.port in (None, 443)
            and parsed.username is None and parsed.password is None and not parsed.fragment, "unexpected public download origin")


class RestrictedRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, origins):
        self.origins = origins

    def redirect_request(self, request, fp, code, message, headers, newurl):
        allowed_url(newurl, self.origins)
        return super().redirect_request(request, fp, code, message, headers, newurl)


class Network:
    """Bound public reads, with raw responses and timestamps retained on failure."""
    def __init__(self, output):
        self.output = output
        self.rows = []

    def fetch(self, name, url, maximum, *, origins):
        require(re.fullmatch(r"[a-z0-9-]+", name) and not any(row["name"] == name for row in self.rows), "network operation name")
        allowed_url(url, origins)
        path = self.output / "release" / "network" / (name + ".bin")
        path.parent.mkdir(parents=True, exist_ok=True)
        row = dict(name=name, url=url, started_at=datetime.now(timezone.utc).isoformat(),
                   finished_at=None, final_url=None, status="failed", error=None,
                   path=path.relative_to(self.output).as_posix(), bytes=0, sha256=digest(b""), truncated=False)
        raw = b""
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), RestrictedRedirect(origins))
            request = urllib.request.Request(url, headers={"User-Agent": "checkwash-pju-release-collector", "Accept": "application/json"})
            with opener.open(request, timeout=90) as response:
                row["final_url"] = response.geturl()
                allowed_url(row["final_url"], origins)
                raw = response.read(maximum + 1)
            row["truncated"] = len(raw) > maximum
            require(not row["truncated"], "public response exceeds bound")
            row["status"] = "completed"
            return raw
        except (OSError, ValueError, urllib.error.URLError) as error:
            row["error"] = type(error).__name__ + ": " + str(error)
            raise
        finally:
            path.write_bytes(raw)
            row.update(finished_at=datetime.now(timezone.utc).isoformat(), bytes=len(raw), sha256=digest(raw))
            self.rows.append(row)
            save(self.output / "release/network.json", self.rows)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def load_backend():
    spec = importlib.util.spec_from_file_location("_pju_collection_backend", ROOT / "tools/collect_pju_receipts.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReleaseCollection:
    def __init__(self, args, backend):
        self.args, self.backend = args, backend
        self.action = backend.load_replayer()
        self.subject_raw, self.subject = read_admitted(args.subject, args.subject_sha256, self.action)
        validate_subject(self.subject)
        self.payload_raw, _ = read_admitted(args.event_payload, self.subject["event"]["payload_sha256"], self.action)
        self.parents_raw, self.parents = read_admitted(args.parents, args.parents_sha256, self.action)
        require(type(self.parents) is dict and set(self.parents) == STAGES[self.subject["stage"]], "prior stage set differs")
        self.parent_files = {}
        parent_root = self.action.absolute_path(args.parent_report_root, directory=True)
        for stage, row in self.parents.items():
            exact(row, "report sha256 check_run_id", "parent report")
            require(row["report"] == "parents/" + stage + ".json", "noncanonical prior report path")
            integer(row["check_run_id"])
            raw, _ = read_admitted(parent_root / row["report"], row["sha256"], self.action, maximum=MAX_PARENT_REPORT)
            self.parent_files[row["report"]] = raw
        self.expected_raw = self.expected = None
        if self.subject["stage"] == "public-visitor":
            require(args.release_artifacts is not None and args.release_artifacts_sha256 is not None,
                    "public visitor needs admitted release artifact bytes")
            self.expected_raw, self.expected = read_admitted(args.release_artifacts, args.release_artifacts_sha256, self.action)
        elif args.release_artifacts is not None or args.release_artifacts_sha256 is not None:
            raise ValueError("release artifact admission is only for public visitors")
        self.authority_files = {}
        for name in ("release_authorization", "platform_acceptance"):
            path = getattr(args, name, None)
            expected_digest = getattr(args, name + "_sha256", None)
            require((path is None) == (expected_digest is None), "authority file and external digest must be supplied together")
            if path is not None:
                require(self.subject["stage"] == "release-event", "publication authority records belong to the release event packet")
                raw, _ = read_admitted(path, expected_digest, self.action)
                self.authority_files["release/" + name.replace("_", "-") + ".json"] = raw
        self.network = None
        self.public_paths = {}
        self.publication = None

    def initialize(self, ctx):
        output = ctx["output"]
        (output / "native-subject.json").write_bytes(self.subject_raw)
        (output / "release").mkdir()
        (output / "release/event-payload.json").write_bytes(self.payload_raw)
        (output / "release/parents-admission.json").write_bytes(self.parents_raw)
        for name, raw in self.parent_files.items():
            path = output / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        if self.expected_raw is not None:
            (output / "release/expected-artifacts.json").write_bytes(self.expected_raw)
        for name, raw in self.authority_files.items():
            # Inclusion is data custody, not acceptance of the claimed authority.
            (output / name).write_bytes(raw)
        self.network = Network(output)
        stage = self.subject["stage"]
        ctx["manifest"]["records"]["release"] = dict(subject="native-subject.json", verdict="release/verdict-gate.json",
            verdict_inventory="release/verdict-inputs.json", advertised="release/advertised-visitor.json",
            tag_source=None if stage in ("pr", "main") else "release/tag-source.json",
            tag_visitor=None if stage in ("pr", "main") else "release/tag-visitor.json",
            publication="release/publication.json" if stage == "public-visitor" else None)
        save(output / "release/collection.json", dict(status="running", started_at=datetime.now(timezone.utc).isoformat(),
            subject_sha256=digest(self.subject_raw), parents_sha256=digest(self.parents_raw), finished_at=None))

    def download(self, ctx, name, url, expected, destination, *, origins):
        raw = self.network.fetch(name, url, expected["bytes"], origins=origins)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
        require(len(raw) == expected["bytes"] and digest(raw) == expected["sha256"], "public bytes mismatch: " + name)
        return destination

    def public_artifacts(self, ctx):
        version = ctx["project"]["version"]
        expected = validate_artifact_set(self.expected, version)
        output = ctx["output"]
        self.publication = dict(schema_version=1, status="failed", subject=self.subject,
            expected_set=expected, expected_set_sha256=digest(self.expected_raw),
            github_release=None, pypi_version=None, downloads=[], visitors=[])
        self.save_publication(output)
        release_raw = self.network.fetch("github-release", API + "/releases/" + str(self.subject["release_id"]), MAX_JSON,
                                         origins={"api.github.com"})
        release = strict_json(release_raw)
        require(type(release["id"]) is int and release["id"] == self.subject["release_id"]
                and release["tag_name"] == self.subject["tag"] and release["draft"] is False
                and release["prerelease"] is False, "public release identity mismatch")
        assets = release["assets"]
        require(type(assets) is list and len(assets) == 3 and {a["name"] for a in assets} == set(expected), "GitHub asset set differs")
        self.publication["github_release"] = "release/network/github-release.bin"
        for asset in assets:
            name = asset["name"]
            wanted = expected[name]
            canonical = "https://github.com/" + REPOSITORY + "/releases/download/" + self.subject["tag"] + "/" + name
            require(type(asset["id"]) is int and asset["id"] > 0 and asset["state"] == "uploaded"
                    and type(asset["size"]) is int and asset["size"] == wanted["bytes"]
                    and asset["digest"] == "sha256:" + wanted["sha256"] and asset["browser_download_url"] == canonical,
                    "GitHub asset identity mismatch")
            path = self.download(ctx, "github-" + ("pyz" if name.endswith(".pyz") else "wheel" if name.endswith(".whl") else "sdist"),
                canonical, wanted, output / "artifacts" / name,
                origins={"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"})
            self.public_paths["github-" + ("wheel" if name.endswith(".whl") else "sdist" if name.endswith(".tar.gz") else "pyz")] = path
            self.publication["downloads"].append(dict(channel="github", name=name, asset_id=asset["id"], url=canonical,
                path=path.relative_to(output).as_posix(), bytes=wanted["bytes"], sha256=wanted["sha256"]))
            self.save_publication(output)
        pypi_raw = self.network.fetch("pypi-version", "https://pypi.org/pypi/checkwash/" + version + "/json", MAX_JSON,
                                      origins={"pypi.org"})
        pypi = strict_json(pypi_raw)
        require(pypi["info"]["version"] == version and type(pypi["urls"]) is list and len(pypi["urls"]) == 2,
                "PyPI version/files differ")
        packages = {row["filename"]: row for row in pypi["urls"]}
        require(set(packages) == set(expected) - {"checkwash.pyz"}, "PyPI filenames differ")
        self.publication["pypi_version"] = "release/network/pypi-version.bin"
        for name, package in packages.items():
            wanted = expected[name]
            allowed_url(package["url"], {"files.pythonhosted.org"})
            require(package["yanked"] is False and type(package["size"]) is int and package["size"] == wanted["bytes"]
                    and package["digests"]["sha256"] == wanted["sha256"], "PyPI metadata differs")
            role = "wheel" if name.endswith(".whl") else "sdist"
            require(package["packagetype"] == ("bdist_wheel" if role == "wheel" else "sdist"), "PyPI package type differs")
            # The install copy stays in scratch: a second packet file named like
            # artifacts/<name> made the verifier's basename lookup ambiguous.
            # The packet keeps the PyPI bytes as this read's network raw.
            path = self.download(ctx, "pypi-" + role, package["url"], wanted, ctx["scratch"] / "public-pypi" / name,
                                 origins={"files.pythonhosted.org"})
            read = self.network.rows[-1]
            require(read["name"] == "pypi-" + role and read["sha256"] == wanted["sha256"], "PyPI network raw missing")
            require(path.read_bytes() == (output / "artifacts" / name).read_bytes(), "GitHub/PyPI bytes differ")
            self.public_paths["pypi-" + role] = path
            self.publication["downloads"].append(dict(channel="pypi", name=name, url=package["url"],
                path=read["path"], bytes=wanted["bytes"], sha256=wanted["sha256"]))
            self.save_publication(output)

    def save_publication(self, output):
        save(output / "release/publication.json", self.publication)

    def source_snapshot(self, ctx, path, commit):
        path = self.action.absolute_path(path, directory=True)
        self.action.outside(ctx["output"], path)
        self.action.outside(ctx["scratch"], path)
        return path, self.action.snapshot(ctx["reader"], path, commit)

    def visitor(self, ctx, name, target, version, members, *, source_identity=None, artifact_sha=None):
        run, output, scratch, py = (ctx[key] for key in ("run", "output", "scratch", "py"))
        directory = scratch / (name + "-environment")
        run(name + "-venv", [*py, "-m", "venv", str(directory)])
        visitor_py = [str(directory / "Scripts/python.exe"), "-I", "-B", "-X", "utf8"]
        report = output / "release" / (name + "-pip.json")
        run(name + "-install", [*visitor_py, "-m", "pip", "--isolated", "--disable-pip-version-check", "--no-input",
            "install", "--no-deps", "--no-cache-dir", "--no-compile", "--report", str(report), str(target)], timeout=1800)
        expected = {path.removeprefix("src/"): row["sha256"] for path, row in members.items() if path.startswith("src/checkwash/")}
        expected_path = output / "release" / (name + "-expected.json")
        save(expected_path, expected)
        identity_path = output / "release" / (name + "-identity.json")
        probe = (
            "import hashlib,importlib.metadata as m,json,pathlib,re,sys;"
            "d=m.distribution('checkwash'); expected=json.loads(pathlib.Path(sys.argv[1]).read_text());"
            "actual={p:hashlib.sha256(pathlib.Path(d.locate_file(p)).read_bytes()).hexdigest() for p in expected};"
            "assert actual==expected; assert d.version==sys.argv[3];"
            "deps={re.sub(r'[-_.]+','-',p.metadata['Name']).lower():p.version for p in m.distributions()};"
            "assert set(deps)<= {'pip','setuptools','checkwash'};"
            "r={'version':d.version,'direct_url':json.loads(d.read_text('direct_url.json')),'dependencies':deps,"
            "'members':actual,'requires':d.requires};"
            "pathlib.Path(sys.argv[2]).write_text(json.dumps(r,sort_keys=True)+'\\n',encoding='utf-8')"
        )
        run(name + "-identity", [*visitor_py, "-c", probe, str(expected_path), str(identity_path), version])
        identity = strict_json(identity_path.read_bytes())
        if source_identity is not None:
            require(identity["direct_url"]["vcs_info"]["commit_id"] == source_identity, "installed public tag commit differs")
        if artifact_sha is not None:
            require(identity["direct_url"]["archive_info"]["hashes"]["sha256"] == artifact_sha, "installed public artifact differs")
        run(name + "-dependencies", [*visitor_py, "-m", "pip", "check"])
        require(run(name + "-version", [*visitor_py, "-m", "checkwash", "--version"]).decode("utf-8").strip()
                == "checkwash " + version, "installed public CLI version differs")
        run(name + "-demo", [*visitor_py, "-m", "checkwash", "demo"])
        run(name + "-check", [*visitor_py, "-m", "checkwash", "check", self.subject["base_sha"] + ".." + self.subject["head_sha"],
                              "--repo", str(ctx["source"]), "--fail-on", "high"])
        return dict(name=name, status="completed", target=str(target), identity=identity_path.relative_to(output).as_posix(),
                    install_report=report.relative_to(output).as_posix(), expected_members=expected_path.relative_to(output).as_posix())

    def tag_source(self, ctx, name, source, tag, commit, tag_object):
        path = ctx["output"] / "release" / (name + "-source.json")
        ctx["run"](name + "-source", [*ctx["py"], str(ctx["trusted"] / "tools/collect_pju_receipts.py"),
            "--internal-helper", "verify_published_source.py", str(ctx["output"] / ("nested-" + name + "-source")),
            "--repo", str(source), "--tag", tag, "--expected-commit", commit, "--source-sha", commit,
            "--expected-tag-object", tag_object, "--remote", PUBLIC_GIT, "--output", str(path)])
        return path.relative_to(ctx["output"]).as_posix()

    def qualify_zipapp(self, ctx, name):
        ctx["run"](name, [*ctx["py"], str(ctx["trusted"] / "tools/collect_pju_receipts.py"),
            "--internal-helper", "qualify_zipapp.py", str(ctx["output"] / ("nested-" + name)), str(ctx["pyz"])])

    def advertised(self, ctx):
        advertised = tomllib.loads((ctx["source"] / "release/advertised.toml").read_text(encoding="utf-8"))
        release, pyz = advertised["release"], advertised["pyz"]
        require(release["repository"] == PUBLIC_GIT and release["version"] == release["tag"][1:], "advertised public identity differs")
        source, before = self.source_snapshot(ctx, self.args.advertised_source or self.args.action_root, release["commit"])
        source_receipt = self.tag_source(ctx, "advertised", source, release["tag"], release["commit"], release["tag_object"])
        visitor = self.visitor(ctx, "advertised", "git+" + PUBLIC_GIT + "@" + release["tag"], release["version"], before,
                               source_identity=release["commit"])
        canonical = "https://github.com/" + REPOSITORY + "/releases/download/" + release["tag"] + "/checkwash.pyz"
        require(pyz["url"] == canonical, "advertised pyz URL differs")
        validate_artifact = {"bytes": pyz["bytes"], "sha256": sha(pyz["sha256"])}
        require(type(validate_artifact["bytes"]) is int and 0 < validate_artifact["bytes"] <= MAX_ARTIFACT, "advertised pyz size")
        downloaded = self.download(ctx, "advertised-pyz", canonical, validate_artifact,
            ctx["output"] / "release/advertised-checkwash.pyz",
            origins={"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"})
        require(self.action.snapshot(ctx["reader"], source, release["commit"]) == before, "advertised source changed")
        save(ctx["output"] / "release/advertised-visitor.json", dict(schema_version=1, status="completed", release=release,
            source=source_receipt, visitor=visitor, download=dict(path=downloaded.relative_to(ctx["output"]).as_posix(), **validate_artifact)))

    def verdict(self, ctx):
        pins = tomllib.loads((ctx["source"] / "tests/verdict_gate/baseline.toml").read_text(encoding="utf-8"))
        expected = {"baseline": pins["baseline"], "canary-old": pins["canary"]["old"], "canary-new": pins["canary"]["new"]}
        paths = {"baseline": self.args.verdict_baseline_source or self.args.action_root,
                 "canary-old": self.args.verdict_canary_old_source, "canary-new": self.args.verdict_canary_new_source}
        source_inputs = []
        engines = {}
        arguments = ["gate", "--pins", str(ctx["source"] / "tests/verdict_gate/baseline.toml"),
            "--cases", str(ctx["source"] / "tests/verdict_gate/cases"), "--labels", str(ctx["source"] / "tests/verdict_gate/labels.toml"),
            "--accepted", str(ctx["source"] / "tests/gates/verdict_gate_accepted.toml"), "--python", str(ctx["python"]),
            "--work-dir", str(ctx["scratch"] / "verdict-work"), "--receipt", str(ctx["output"] / "release/verdict-gate.json"),
            "--summary", str(ctx["output"] / "release/verdict-gate.md")]
        for role, pin in expected.items():
            source, before = self.source_snapshot(ctx, paths[role], pin["commit"])
            source_inputs.append((source, pin["commit"], before))
            require(ctx["reader"].text(source, "rev-parse", "refs/tags/" + pin["tag"] + "^{commit}") == pin["commit"], "verdict tag source differs")
            wanted = dict(bytes=pin["size"], sha256=pin["sha256"])
            require(type(wanted["bytes"]) is int and 0 < wanted["bytes"] <= MAX_ARTIFACT, "verdict artifact size")
            sha(wanted["sha256"])
            target = self.download(ctx, "verdict-" + role,
                "https://github.com/" + REPOSITORY + "/releases/download/" + pin["tag"] + "/checkwash.pyz", wanted,
                ctx["output"] / "release/engines" / (role + ".pyz"),
                origins={"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"})
            engines[role] = dict(source_sha=pin["commit"], pyz=target.relative_to(ctx["output"]).as_posix(),
                                 runtime_path=str(target), **wanted)
            arguments += ["--" + role + "-pyz", str(target), "--" + role + "-source", str(source)]
        candidate = ctx["pyz"]
        engines["candidate"] = dict(source_sha=self.subject["head_sha"], pyz=candidate.relative_to(ctx["output"]).as_posix(), runtime_path=str(candidate),
                                    bytes=candidate.stat().st_size, sha256=digest(candidate.read_bytes()))
        arguments += ["--candidate-pyz", str(candidate), "--candidate-source", str(ctx["source"])]
        for key, value in dict(event=self.subject["event"]["name"], stage=self.subject["stage"],
                               sha=self.subject["head_sha"], run_id=self.subject["event"]["run_id"],
                               run_attempt=self.subject["event"]["run_attempt"]).items():
            arguments += ["--context", key + "=" + str(value)]
        if self.subject["stage"] not in ("pr", "main"):
            arguments += ["--tag-run", self.subject["tag"], "--repo", str(ctx["source"])]
        files = {path: row for path, row in ctx["source_before"].items()
                 if path in ("tests/verdict_gate/baseline.toml", "tests/verdict_gate/labels.toml", "tests/gates/verdict_gate_accepted.toml")
                 or path.startswith("tests/verdict_gate/cases/")}
        save(ctx["output"] / "release/verdict-inputs.json", dict(schema_version=1, files=files, engines=engines))
        ctx["run"]("verdict-gate", [*ctx["py"], str(ctx["trusted"] / "tools/collect_pju_receipts.py"), "--internal-helper",
            "verdict_gate.py", str(ctx["output"] / "nested-verdict"), *arguments], timeout=7200)
        for source, commit, before in source_inputs:
            require(self.action.snapshot(ctx["reader"], source, commit) == before, "verdict pinned source changed")

    def preflight(self, ctx):
        for path in ("tools/verdict_gate.py", "tools/published_release_identity.py", "tools/verify_published_source.py", "tools/qualify_zipapp.py"):
            require(ctx["source_before"][path] == ctx["trusted_before"][path], "candidate differs from audited release helper: " + path)
        if self.subject["stage"] != "pr":
            require(ctx["reader"].text(ctx["source"], "rev-parse", self.subject["head_sha"] + "^1") == self.subject["base_sha"],
                    "release source first parent differs")
        if self.subject["stage"] not in ("pr", "main"):
            require("v" + ctx["project"]["version"] == self.subject["tag"], "release source version differs from tag")
            tag_ref = "refs/tags/" + self.subject["tag"]
            require(ctx["reader"].text(ctx["source"], "cat-file", "-t", tag_ref) == "tag"
                    and ctx["reader"].text(ctx["source"], "rev-parse", tag_ref) == self.subject["tag_object"]
                    and ctx["reader"].text(ctx["source"], "rev-parse", tag_ref + "^{commit}") == self.subject["head_sha"],
                    "local annotated tag identity differs")
        runtime = ctx["manifest"]["runtime"]
        require(runtime["os"] == "Windows" and runtime["python_version"] == "3.11.9", "release collector covers Windows/Python 3.11.9 only")
        require("twine" in self.backend.normalized_packages(runtime["dependencies"]),
                "fresh admitted dependency lock must include twine for release validation")

    def stage_steps(self, ctx):
        self.preflight(ctx)
        ctx["run"]("twine-check", [*ctx["py"], "-m", "twine", "check", str(ctx["wheel"]), str(ctx["sdist"])])
        if self.subject["stage"] != "public-visitor":
            self.qualify_zipapp(ctx, "zipapp-qualification")
        self.verdict(ctx)
        self.advertised(ctx)
        if self.subject["stage"] not in ("pr", "main"):
            self.tag_source(ctx, "tag", ctx["source"], self.subject["tag"], self.subject["head_sha"], self.subject["tag_object"])
            visitor = self.visitor(ctx, "tag", "git+" + PUBLIC_GIT + "@" + self.subject["tag"], ctx["project"]["version"],
                                   ctx["source_before"], source_identity=self.subject["head_sha"])
            save(ctx["output"] / "release/tag-visitor.json", dict(schema_version=1, status="completed", subject=self.subject, visitor=visitor))
        if self.subject["stage"] == "public-visitor":
            for channel in ("github-wheel", "github-sdist", "pypi-wheel", "pypi-sdist"):
                path = self.public_paths[channel]
                visitor = self.visitor(ctx, channel, path, ctx["project"]["version"], ctx["source_before"], artifact_sha=digest(path.read_bytes()))
                self.publication["visitors"].append(visitor)
                self.save_publication(ctx["output"])
            self.qualify_zipapp(ctx, "public-pyz-qualification")
            for command in ("--version", "demo"):
                ctx["run"]("public-pyz-" + ("version" if command == "--version" else "demo"), [*ctx["py"], str(ctx["pyz"]), command])
            ctx["run"]("public-pyz-check", [*ctx["py"], str(ctx["pyz"]), "check", self.subject["base_sha"] + ".." + self.subject["head_sha"],
                                             "--repo", str(ctx["source"]), "--fail-on", "high"])
            self.publication["visitors"].append(dict(name="github-pyz", status="completed", path=ctx["pyz"].relative_to(ctx["output"]).as_posix()))
            self.publication["status"] = "completed"
            self.save_publication(ctx["output"])
    def finalize(self, ctx, errors):
        timing_path = ctx["output"] / "release/collection.json"
        if not timing_path.exists():
            return
        timing = strict_json(timing_path.read_bytes())
        timing.update(status=ctx["manifest"]["status"], errors=list(errors), finished_at=datetime.now(timezone.utc).isoformat())
        save(timing_path, timing)

    def collect(self):
        args = self.args
        args.repository = self.subject["repository"]
        args.base_sha, args.head_sha, args.source_tree = (self.subject[key] for key in ("base_sha", "head_sha", "source_tree"))
        return self.backend.collect(args, release_context=dict(subject=self.subject, parents=self.parents),
            initialize=self.initialize, stage_preflight=self.preflight, stage_steps=self.stage_steps, finalize=self.finalize,
            artifact_provider=self.public_artifacts if self.subject["stage"] == "public-visitor" else None)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source-root", "action-root", "python", "git", "bash", "output", "scratch", "dependency-lock",
                 "subject", "event-payload", "parents", "parent-report-root", "verdict-canary-old-source", "verdict-canary-new-source"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("candidate-action-root", "advertised-source", "verdict-baseline-source", "release-artifacts",
                 "release-authorization", "platform-acceptance"):
        parser.add_argument("--" + name, type=Path)
    for name in ("collector-source-sha", "dependency-lock-sha256", "subject-sha256", "parents-sha256"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--release-artifacts-sha256")
    parser.add_argument("--release-authorization-sha256")
    parser.add_argument("--platform-acceptance-sha256")
    args = parser.parse_args(argv)
    try:
        return ReleaseCollection(args, load_backend()).collect()
    except (OSError, ValueError, KeyError, TypeError, RecursionError, urllib.error.URLError) as error:
        print(json.dumps(dict(status="collector-error", error=type(error).__name__ + ": " + str(error))))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
