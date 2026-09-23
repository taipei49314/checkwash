"""T449 only: unchanged candidate full pytest on existing GitHub-hosted Ubuntu.

The auxiliary workflow/producer checkout and fixed candidate checkout are
distinct. A disposable annotated tag stays local. No source edits, public tag,
package publication, workflow dispatch, test selection or budget override.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import signal
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ET
import zipfile


REPOSITORY = "taipei49314/checkwash"
BRANCH = "codex/t449-hosted-pytest"
WORKFLOW = ".github/workflows/release.yml"
PRODUCER = "tools/t449_hosted_pytest.py"
SOURCE = "4b7382fb34175cc1dfb2903fb9b4abf450fb3d33"
TREE = "c3c836f0ad69ecdc61250b19c1ed5e95ed589c40"
TAG = "v0.4.2"
COUNTS = {"tests": 8291, "failures": 0, "errors": 0, "skipped": 0}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def save(path, value):
    path.write_text(json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def owned(root, name):
    require(isinstance(name, str) and name and not name.startswith("/") and "\\" not in name
            and all(part not in {"", ".", ".."} for part in name.split("/")), "unsafe tracked path")
    item = root.joinpath(*name.split("/"))
    require(item.is_file() and not item.is_symlink() and item.resolve().is_relative_to(root), "missing or linked tracked file")
    return item


def context(controller, source, work, existing=False):
    env = os.environ
    require(env.get("GITHUB_ACTIONS") == "true" and env.get("GITHUB_REPOSITORY") == REPOSITORY
            and env.get("GITHUB_ACTOR") == "taipei49314" and env.get("GITHUB_TRIGGERING_ACTOR") == "taipei49314"
            and env.get("GITHUB_EVENT_NAME") == "workflow_dispatch" and env.get("GITHUB_REF") == "refs/heads/" + BRANCH
            and env.get("GITHUB_JOB") == "t449-full-pytest", "exact owner/manual auxiliary workflow required")
    require(env.get("RUNNER_ENVIRONMENT") == "github-hosted" and env.get("RUNNER_OS") == "Linux"
            and os.name == "posix" and platform.system() == "Linux"
            and platform.node().upper() not in {"LAPTOP-01AGNPJU", "LAPTOP-16NUA5I8"}, "GitHub-hosted Linux only")
    require(sys.version_info[:2] == (3, 12), "reviewed Python 3.12 required")
    require(re.fullmatch(r"[0-9a-f]{40}", env.get("GITHUB_SHA", "")), "exact workflow SHA required")
    require(env.get("GITHUB_WORKFLOW_REF") == REPOSITORY + "/" + WORKFLOW + "@refs/heads/" + BRANCH,
            "workflow provenance differs")
    for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"):
        require(re.fullmatch(r"[1-9][0-9]*", env.get(key, "")), "run/attempt missing")
    workspace = Path(env["GITHUB_WORKSPACE"]).resolve(strict=True)
    require(controller == workspace / "orchestrator" and source == workspace / "candidate" and controller != source,
            "separate exact controller and candidate directories required")
    require(Path(__file__).resolve() == owned(controller, PRODUCER), "executing producer is outside its reviewed checkout")
    expected = "t449-hosted-pytest-" + env["GITHUB_RUN_ID"] + "-" + env["GITHUB_RUN_ATTEMPT"]
    require(work.parent == Path(env["RUNNER_TEMP"]).resolve(strict=True) and work.name == expected
            and (work.is_dir() if existing else not work.exists()), "exact runner-owned work directory required")


def emit_evidence(controller, work):
    """Public fallback contains only this producer's known public-source evidence."""
    out = work / "out"
    require(out.is_dir() and not out.is_symlink(), "evidence directory missing or linked")
    names = {"receipt.json", "source-package.json", "pytest.xml", "artifact-manifest.json"}
    names.update(name + suffix for name in ("local-only-tag", "create-venv", "install-candidate-dev", "loaded-candidate", "full-pytest")
                 for suffix in (".stdout", ".stderr"))
    entries = list(out.rglob("*"))
    require(len(entries) <= 32 and all(item.is_file() and not item.is_symlink() and item.parent == out
            and item.name in names for item in entries), "unrecognized, linked or nested evidence refused")
    require(sum(item.stat().st_size for item in entries) <= 64 * 1024 * 1024, "raw evidence exceeds bound")
    files = {item.name: item.read_bytes() for item in entries}
    manifest = json.loads(files["artifact-manifest.json"])
    require(manifest.get("schema_version") == 1 and manifest.get("files") == {
        name: {"sha256": sha(raw), "bytes": len(raw)} for name, raw in files.items() if name != "artifact-manifest.json"},
        "original artifact manifest does not match complete raw evidence")
    receipt = json.loads(files["receipt.json"])
    require(receipt.get("repository") == REPOSITORY and receipt.get("source_sha") == SOURCE and receipt.get("source_tree") == TREE
            and receipt.get("workflow_sha") == os.environ["GITHUB_SHA"] and receipt.get("run_id") == os.environ["GITHUB_RUN_ID"]
            and receipt.get("run_attempt") == os.environ["GITHUB_RUN_ATTEMPT"]
            and receipt.get("producer_sha256") == sha(owned(controller, PRODUCER).read_bytes())
            and receipt.get("workflow_sha256") == sha(owned(controller, WORKFLOW).read_bytes()), "original proof identity differs")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name in sorted(files):
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100600 << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, files[name])
    raw = buffer.getvalue()
    require(0 < len(raw) <= 8 * 1024 * 1024, "compressed evidence exceeds bound")
    require(all((out / name).read_bytes() == data for name, data in files.items()), "evidence changed during transport")
    encoded = base64.b64encode(raw).decode("ascii")
    size = 3500
    count = (len(encoded) + size - 1) // size
    header = {"schema_version": 1, "kind": "hosted-full-pytest-log-transport", "repository": REPOSITORY,
        "run_id": receipt["run_id"], "run_attempt": receipt["run_attempt"], "workflow_sha": receipt["workflow_sha"],
        "source_sha": SOURCE, "source_tree": TREE, "producer_sha256": receipt["producer_sha256"],
        "workflow_sha256": receipt["workflow_sha256"], "manifest_sha256": sha(files["artifact-manifest.json"]),
        "archive_sha256": sha(raw), "archive_bytes": len(raw), "chunk_count": count, "chunk_chars": size,
        "files": len(files), "raw_bytes": sum(map(len, files.values()))}
    header_raw = json.dumps(header, sort_keys=True, separators=(",", ":")).encode()
    footer = {"header_sha256": sha(header_raw), "archive_sha256": sha(raw), "chunk_count": count}
    marker = "CW_T449_HOSTED_PYTEST_V1 "
    print(json.dumps({"evidence_transport": "public-original-hosted-pytest", "original_status": receipt.get("status"),
                      "original_result_modified": False}), flush=True)
    print(marker + "HEADER " + base64.b64encode(header_raw).decode("ascii"), flush=True)
    for index in range(count):
        print(marker + "CHUNK " + str(index) + " " + encoded[index * size:(index + 1) * size], flush=True)
    print(marker + "FOOTER " + base64.b64encode(json.dumps(footer, sort_keys=True, separators=(",", ":")).encode()).decode("ascii"), flush=True)


class Run:
    def __init__(self, controller, source, work):
        self.controller, self.source, self.work = controller, source, work
        self.out = work / "out"
        self.out.mkdir(parents=True, exist_ok=False)
        (work / "home").mkdir()
        (work / "tmp").mkdir()
        # Children receive no GitHub/Actions tokens, credential helpers, user
        # pip/Git config, PYTHONPATH, PYTEST_ADDOPTS, or test-budget overrides.
        self.env = {"PATH": os.environ["PATH"], "HOME": str(work / "home"), "TMPDIR": str(work / "tmp"),
                    "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONNOUSERSITE": "1", "PIP_CONFIG_FILE": os.devnull, "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0", "NO_COLOR": "1"}
        # setup-python's Linux build may need its own shared-library directory.
        # Derive that single trusted directory; do not inherit loader paths.
        library = Path(sys.base_prefix).resolve() / "lib"
        require(library.is_dir(), "setup-python library directory missing")
        self.env["LD_LIBRARY_PATH"] = str(library)
        self.python = work / "venv/bin/python"
        self.receipt = {"schema_version": 1, "task": "T-449", "kind": "hosted-full-pytest", "version": "0.4.2",
            "status": "running", "repository": REPOSITORY, "workflow": WORKFLOW,
            "workflow_sha": os.environ["GITHUB_SHA"], "workflow_ref": os.environ["GITHUB_WORKFLOW_REF"],
            "producer": PRODUCER, "producer_sha256": sha(owned(controller, PRODUCER).read_bytes()),
            "workflow_sha256": sha(owned(controller, WORKFLOW).read_bytes()),
            "run_id": os.environ["GITHUB_RUN_ID"], "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
            "job": os.environ["GITHUB_JOB"], "host": platform.node(), "runner_environment": os.environ["RUNNER_ENVIRONMENT"],
            "runner_os": os.environ["RUNNER_OS"], "runner_name": os.environ.get("RUNNER_NAME"), "python": sys.version,
            "source_sha": SOURCE, "source_tree": TREE, "commands": [], "started_at": utc(),
            "publication_performed": False, "test_selection_modified": False, "test_budgets_modified": False,
            "limits": ["Only this unchanged candidate's complete pytest suite; actual public tag CI remains a separate gate.",
                       "The annotated v0.4.2 tag is disposable and never pushed."]}
        self.flush()

    def flush(self):
        save(self.out / "receipt.json", self.receipt)

    def git(self, root, *args, allowed=(0,)):
        process = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-C", str(root), *args],
                                 env=self.env, capture_output=True, timeout=60)
        require(process.returncode in allowed, "Git metadata observation failed")
        return process.stdout.decode("utf-8").strip()

    def snapshot(self, root):
        require(not self.git(root, "status", "--porcelain=v1", "--untracked-files=normal"), "tracked checkout must be clean")
        require(not self.git(root, "config", "--local", "--name-only", "--get-regexp", r"http\..*\.extraheader", allowed=(0, 1)),
                "persisted Git HTTP credentials refused")
        require(self.git(root, "remote", "get-url", "origin") in
                {"https://github.com/" + REPOSITORY, "https://github.com/" + REPOSITORY + ".git"}, "credential-free source remote required")
        names = [name for name in self.git(root, "ls-files", "-z").split("\0") if name]
        return {"commit": self.git(root, "rev-parse", "HEAD"), "tree": self.git(root, "rev-parse", "HEAD^{tree}"),
                "files": {name: sha(owned(root, name).read_bytes()) for name in names}}

    def command(self, name, argv, cwd=None, timeout=300):
        argv = [str(item) for item in argv]
        row = {"name": name, "argv": argv, "cwd": str(cwd or self.work), "started_at": utc(),
               "stdout": name + ".stdout", "stderr": name + ".stderr", "exit_code": None, "timeout": False}
        self.receipt["commands"].append(row)
        self.flush()
        try:
            with (self.out / row["stdout"]).open("wb") as stdout, (self.out / row["stderr"]).open("wb") as stderr:
                process = subprocess.Popen(argv, cwd=cwd or self.work, env=self.env, stdout=stdout, stderr=stderr, start_new_session=True)
                try:
                    row["exit_code"] = process.wait(timeout=timeout)
                except (subprocess.TimeoutExpired, KeyboardInterrupt):
                    row["timeout"] = True
                    os.killpg(process.pid, signal.SIGKILL)
                    row["exit_code"] = process.wait()
                    raise
        finally:
            row["finished_at"] = utc()
            row["passed"] = row["exit_code"] == 0 and row["timeout"] is False
            for key in ("stdout", "stderr"):
                target = self.out / row[key]
                if target.exists():
                    row[key + "_sha256"] = sha(target.read_bytes())
            self.flush()
        return row

    def required(self, name, argv, cwd=None, timeout=300):
        row = self.command(name, argv, cwd, timeout)
        require(row["passed"], name + " did not pass")
        return (self.out / row["stdout"]).read_text(encoding="utf-8")

    def tag(self):
        return {"name": TAG, "type": self.git(self.source, "cat-file", "-t", TAG),
                "object": self.git(self.source, "rev-parse", TAG), "commit": self.git(self.source, "rev-parse", TAG + "^{commit}"),
                "public": False}

    def prepare(self):
        self.receipt["controller_before"] = self.snapshot(self.controller)
        require(self.receipt["controller_before"]["commit"] == self.receipt["workflow_sha"], "auxiliary producer checkout SHA differs")
        before = self.snapshot(self.source)
        require(before["commit"] == SOURCE and before["tree"] == TREE and self.git(self.source, "rev-parse", "--is-shallow-repository") == "false",
                "candidate must be exactly the fixed source/tree with full history")
        project = tomllib.loads(owned(self.source, "pyproject.toml").read_text(encoding="utf-8"))["project"]
        require(project.get("name") == "checkwash" and project.get("version") == "0.4.2", "candidate package version differs")
        self.receipt["source_before"] = before
        package = {name.removeprefix("src/"): digest for name, digest in before["files"].items() if name.startswith("src/checkwash/")}
        require(package, "empty candidate package inventory")
        self.receipt["source_package_sha256"] = sha(json.dumps(package, sort_keys=True, separators=(",", ":")).encode())
        save(self.out / "source-package.json", package)
        require(not self.git(self.source, "tag", "--list", TAG), "temporary tag must not replace an existing tag")
        self.required("local-only-tag", ["git", "-c", "core.hooksPath=/dev/null", "-c", "user.name=T449 hosted qualification",
            "-c", "user.email=t449@example.invalid", "-c", "tag.gpgsign=false", "tag", "-a", TAG,
            "-m", "T-449 disposable hosted full pytest; not published", SOURCE], self.source)
        self.receipt["local_tag_before"] = self.tag()
        require(self.receipt["local_tag_before"]["type"] == "tag" and self.receipt["local_tag_before"]["commit"] == SOURCE,
                "temporary annotated tag target differs")
        self.flush()
        self.required("create-venv", [sys.executable, "-I", "-m", "venv", self.work / "venv"])
        self.required("install-candidate-dev", [self.python, "-I", "-m", "pip", "install", "--no-cache-dir",
            "--index-url", "https://pypi.org/simple", "-e", str(self.source) + "[dev]"], timeout=600)
        loaded = json.loads(self.required("loaded-candidate", [self.python, "-I", "-c",
            "import checkwash,json,pathlib; print(json.dumps({'path':str(pathlib.Path(checkwash.__file__).resolve()),'version':checkwash.__version__}))"]))
        require(loaded == {"path": str(self.source / "src/checkwash/__init__.py"), "version": "0.4.2"}, "installed engine differs from fixed candidate")
        self.receipt["loaded_candidate"] = loaded
        require(self.snapshot(self.source) == before, "candidate changed during installation")
        self.flush()

    def tests(self):
        row = self.command("full-pytest", [self.python, "-I", "-m", "pytest", "--junitxml=" + str(self.out / "pytest.xml")],
                           self.source, timeout=1500)
        raw = (self.out / "pytest.xml").read_bytes()
        require(b"<!DOCTYPE" not in raw.upper() and b"<!ENTITY" not in raw.upper(), "JUnit declarations forbidden")
        root = ET.fromstring(raw)
        suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
        require(root.tag in {"testsuite", "testsuites"} and len(suites) == 1, "one complete JUnit suite required")
        cases = suites[0].findall("testcase")
        counts = {"tests": len(cases), **{key: sum(case.find(tag) is not None for case in cases)
                  for key, tag in (("failures", "failure"), ("errors", "error"), ("skipped", "skipped"))}}
        declared = {key: int(suites[0].get(key, "-1")) for key in COUNTS}
        self.receipt["pytest"] = {"path": "pytest.xml", "sha256": sha(raw), "bytes": len(raw),
                                  "counts": counts, "declared_counts": declared, "exit_code": row["exit_code"]}
        self.flush()
        require(row["passed"] and counts == declared == COUNTS, "unchanged full suite did not pass exactly 8291 tests with zero skips")

    def finish(self):
        after = self.snapshot(self.source)
        self.receipt["source_after"] = after
        self.receipt["source_unchanged"] = after == self.receipt.get("source_before")
        controller = self.snapshot(self.controller)
        self.receipt["controller_after"] = controller
        self.receipt["controller_unchanged"] = controller == self.receipt.get("controller_before")
        tag = self.tag()
        self.receipt["local_tag_after"] = tag
        self.receipt["local_tag_unchanged"] = tag == self.receipt.get("local_tag_before")
        self.flush()
        require(self.receipt["source_unchanged"] and self.receipt["controller_unchanged"] and self.receipt["local_tag_unchanged"],
                "source, reviewed workflow/producer or disposable local tag changed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--controller", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--work", required=True, type=Path)
    parser.add_argument("--emit-evidence", action="store_true", help="metadata-only original evidence fallback; runs no product")
    args = parser.parse_args()
    controller, source, work = args.controller.resolve(), args.source.resolve(), args.work.resolve()
    run = None
    try:
        context(controller, source, work, existing=args.emit_evidence)
        if args.emit_evidence:
            emit_evidence(controller, work)
            return 0
        run = Run(controller, source, work)
        run.prepare()
        run.tests()
        run.receipt["status"] = "passed"
    except Exception as exc:
        if run is None:
            print(json.dumps({"status": "refused", "error": str(exc), "publication_performed": False}))
            return 2
        run.receipt.update(status="failed", error=str(exc))
    finally:
        if run is not None:
            try:
                if "source_before" in run.receipt and "local_tag_before" in run.receipt:
                    run.finish()
            except Exception as exc:
                run.receipt.update(status="failed", final_identity_error=str(exc))
            run.receipt["finished_at"] = utc()
            run.flush()
            files = {item.relative_to(run.out).as_posix(): {"sha256": sha(item.read_bytes()), "bytes": item.stat().st_size}
                     for item in sorted(run.out.rglob("*")) if item.is_file() and not item.is_symlink() and item.name != "artifact-manifest.json"}
            save(run.out / "artifact-manifest.json", {"schema_version": 1, "files": files})
    print(json.dumps({"status": run.receipt["status"], "source_sha": SOURCE, "pytest": run.receipt.get("pytest"), "publication_performed": False}, sort_keys=True))
    return 0 if run.receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
