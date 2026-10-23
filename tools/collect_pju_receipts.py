"""Collect real, exact-source CheckWash test receipts on the authorized PJU.

Setup: provide a fresh external Python 3.11 venv with a reviewed dependency
lock (plain package-name -> version JSON), Git for Windows, and clean frozen
candidate, collector and pinned-Action checkouts with core.autocrlf=false.
The collector checkout is the directory containing this script. Its SHA is
admitted separately from the candidate. Run with -I -B -X utf8. No credentials
are required; no status checks are published here. Failed packets remain data.

The supplied venv is task-local: this tool installs the candidate editable
there without dependencies/build isolation. Wheel qualification uses a second
fresh venv. Keep --scratch outside the receipt and all source checkouts; its
runtime environments are deliberately not published in the evidence packet.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import locale
import os
from pathlib import Path
import platform
import re
import runpy
import shutil
import subprocess
import sys
import time
import tomllib

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ("tests/data/javascript_assertion_support.json", "tests/data/javascript_foundation_mutations.json")
UTILITIES = ("tools/assertion_contract.py", "tools/qualify_assertions.py", "tools/release_inventory.py")
REPOSITORY = "taipei49314/checkwash"


def load_replayer():
    spec = importlib.util.spec_from_file_location("_trusted_pju_action", ROOT / "tools/replay_pju_action.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def traced_worker(tool, log_root, arguments):
    """Run the audited helper with lossless, offset-indexed subprocess streams.

    This changes no helper commands, inputs, expected cases or exit handling.
    Expected detector exits 1/2 belong in this nested ledger, not in the ten
    top-level success exits. Two append-only byte streams avoid thousands of
    tiny receipt files. Worker subprocesses inherit only the collector allowlist.
    """
    allowed = {"qualify_assertions.py", "release_inventory.py"}
    if tool not in allowed:
        raise ValueError("unsupported trusted helper")
    log_root.mkdir(parents=True, exist_ok=False)
    original = subprocess.run
    ledger = []

    def traced(*args, **kwargs):
        started = datetime.now(timezone.utc).isoformat()
        tick = time.monotonic()
        result = None
        error = None
        # Capture bytes first. The existing qualifier requests text=True with
        # errors=replace; re-encoding that text would erase malformed bytes and
        # CRLF. Decode only the object returned to the unchanged helper.
        binary_kwargs = dict(kwargs)
        text_mode = bool(binary_kwargs.get("text") or binary_kwargs.get("universal_newlines")
                         or binary_kwargs.get("encoding") or binary_kwargs.get("errors"))
        encoding = binary_kwargs.pop("encoding", None) or locale.getpreferredencoding(False)
        errors = binary_kwargs.pop("errors", None) or "strict"
        binary_kwargs.pop("text", None)
        binary_kwargs.pop("universal_newlines", None)
        if text_mode and isinstance(binary_kwargs.get("input"), str):
            binary_kwargs["input"] = binary_kwargs["input"].encode(encoding, errors)

        def decoded(raw):
            if raw is None or not text_mode:
                return raw
            return raw.decode(encoding, errors).replace("\r\n", "\n").replace("\r", "\n")

        try:
            result = original(*args, **binary_kwargs)
        except (OSError, subprocess.SubprocessError) as exc:
            error = exc
        finally:
            row = dict(argv=[str(a) for a in (args[0] if args else kwargs["args"])],
                       cwd=str(kwargs.get("cwd", Path.cwd())), started_at=started,
                       finished_at=datetime.now(timezone.utc).isoformat(), duration_seconds=time.monotonic() - tick,
                       exit_code=getattr(result, "returncode", getattr(error, "returncode", None)),
                       timed_out=isinstance(error, subprocess.TimeoutExpired),
                       error=None if error is None else type(error).__name__)
            for field in ("stdout", "stderr"):
                raw = getattr(result, field, None) if result is not None else getattr(error, field, None)
                if raw is None:
                    raw = b""
                if not isinstance(raw, bytes):
                    raise ValueError("trusted helper subprocess did not return binary output")
                path = log_root / (field + ".bin")
                with path.open("ab") as stream:
                    offset = stream.tell()
                    stream.write(raw)
                row[field] = dict(path=path.name, offset=offset, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
            ledger.append(row)
            (log_root / "commands.json").write_text(json.dumps(ledger, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        if error is not None:
            # subprocess keeps TimeoutExpired output as bytes even in text
            # mode, but CalledProcessError carries the completed text result.
            if isinstance(error, subprocess.CalledProcessError):
                error.output, error.stderr = decoded(error.output), decoded(error.stderr)
            raise error
        return subprocess.CompletedProcess(result.args, result.returncode, decoded(result.stdout), decoded(result.stderr))

    namespace = runpy.run_path(str(ROOT / "tools" / tool), run_name="_audited_receipt_helper")
    subprocess.run = traced
    try:
        if tool == "qualify_assertions.py":
            return namespace["main"](arguments)
        sys.argv = [str(ROOT / "tools" / tool), *arguments]
        return namespace["main"]()
    finally:
        subprocess.run = original


def normalized_packages(value):
    result = {}
    for name, version in value.items():
        key = re.sub(r"[-_.]+", "-", name).lower()
        if key in result or not isinstance(version, str) or not version:
            raise ValueError("invalid/duplicate dependency entry")
        result[key] = version
    return result


def closure(snapshot):
    return {path: row["sha256"] for path, row in snapshot.items()
            if path.startswith(("action/", "src/")) or path == "pyproject.toml"}


def collect(args):
    action = load_replayer()
    require = action.require
    require(os.name == "nt" and platform.node().upper() == action.HOST, "authorized PJU Windows host required")
    require(sys.version_info[:2] == (3, 11) and sys.flags.isolated and sys.dont_write_bytecode and sys.flags.utf8_mode,
            "collector requires Python 3.11 with -I -B -X utf8")
    require(args.repository == REPOSITORY and args.pr > 0, "unexpected repository/PR")
    for value in (args.base_sha, args.head_sha, args.source_tree, args.collector_source_sha):
        require(re.fullmatch(r"[0-9a-f]{40}", value), "full SHA required")
    source = action.absolute_path(args.source_root, directory=True)
    trusted = action.absolute_path(ROOT, directory=True)
    pinned = action.absolute_path(args.action_root, directory=True)
    python, git, bash = (action.absolute_path(path) for path in (args.python, args.git, args.bash))
    require(python == Path(sys.executable).absolute(), "collector must run using the admitted Python")
    output = action.absolute_path(args.output, exists=False)
    scratch = action.absolute_path(args.scratch, exists=False)
    for path in (trusted, pinned, python, git, bash, output, scratch):
        action.outside(path, source)
    for checkout in (trusted, source, pinned):
        action.outside(output, checkout)
        action.outside(scratch, checkout)
    action.outside(scratch, output)
    action.outside(output, scratch)
    lock_path = action.absolute_path(args.dependency_lock)
    lock_raw = lock_path.read_bytes()
    require(action.digest(lock_raw) == args.dependency_lock_sha256, "dependency lock SHA256 mismatch")
    expected_dependencies = json.loads(lock_raw)
    require(type(expected_dependencies) is dict and expected_dependencies, "dependency mapping required")
    normalized_packages(expected_dependencies)
    output.mkdir(parents=True, exist_ok=False)
    scratch.mkdir(parents=True, exist_ok=False)
    env = action.clean_environment(python, git, bash, scratch)
    env["ENGINE_SOURCE"] = args.head_sha
    # Fresh, empty templates prevent user-installed Git hooks in fixture repos.
    template = scratch / "git-template"
    template.mkdir()
    env["GIT_TEMPLATE_DIR"] = str(template)
    reader = action.GitReader(git, env, output / "git-evidence")
    reader.output.mkdir()
    ledger = []
    manifest = dict(schema_version=1, kind="checkwash.pju-receipt.v1", repository=args.repository,
                    pr_number=args.pr, base_sha=args.base_sha, head_sha=args.head_sha, source_tree=args.source_tree,
                    host=action.HOST, provenance="HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL",
                    collector_source_sha=args.collector_source_sha, contract_source_sha=args.collector_source_sha,
                    action_sha=action.ACTION_SHA, status="failed", runtime={}, files=[], raw_exits=ledger,
                    records=dict(dogfood="action/runtime-receipts/check-receipt.json", action_replay="action/replay.json",
                                 candidate_action_coverage="candidate-action-coverage.json", junit="junit.xml",
                                 qualifications={d: f"qualifications/{d}.json" for d in ("source", "wheel", "pyz")},
                                 inventories={d: f"inventories/{d}.json" for d in ("source", "wheel", "pyz")},
                                 contract_descriptor="contract-descriptor.json"))
    errors = []

    def run(name, argv, *, cwd=scratch, timeout=1800):
        row = action.run_record(name, argv, cwd=cwd, env=env, output=output, timeout=timeout, ledger=ledger)
        require(row["exit_code"] == 0 and not row["timed_out"], "command failed: " + name)
        return (output / row["stdout"]).read_bytes()

    py = [str(python), "-I", "-B", "-X", "utf8"]
    try:
        trusted_before = action.snapshot(reader, trusted, args.collector_source_sha)
        source_before = action.snapshot(reader, source, args.head_sha)
        pinned_before = action.snapshot(reader, pinned, action.ACTION_SHA)
        for checkout in (trusted, source, pinned):
            require(not reader.read(checkout, "ls-files", "--others", "--ignored", "--exclude-standard"),
                    "initial checkout contains ignored files; provide a fresh frozen checkout")
        require(reader.text(source, "rev-parse", "HEAD^{tree}") == args.source_tree, "candidate tree mismatch")
        require(reader.text(source, "rev-parse", args.base_sha + "^{commit}") == args.base_sha, "base missing/mismatch")
        # Whole tracked source is byte-checked, including fixtures/Action/packaging.
        for name in (*UTILITIES, *CONTRACTS):
            require(source_before[name] == trusted_before[name], "candidate differs from audited helper/contract: " + name)
        runtime_raw = run("runtime-identity", [*py, "-c",
            "import importlib.metadata as m,json,platform,sys; "
            "print(json.dumps({'python_version':platform.python_version(),'prefix':sys.prefix,'base':sys.base_prefix,"
            "'dependencies':{d.metadata['Name']:d.version for d in m.distributions()}}))"])
        info = json.loads(runtime_raw)
        require(info["prefix"] != info["base"] and Path(info["prefix"]).absolute() == python.parent.parent,
                "fresh external task-local venv required")
        require(info["python_version"].startswith("3.11."), "only Windows Python 3.11 is covered")
        require(normalized_packages(info["dependencies"]) == normalized_packages(expected_dependencies),
                "installed dependencies differ from admitted lock (use a fresh environment)")
        (output / "dependency-lock.json").write_bytes(lock_raw)
        manifest["runtime"] = dict(os="Windows", python_version=info["python_version"],
            python_executable=str(python), python_sha256=action.digest(python.read_bytes()),
            git_executable=str(git), git_sha256=action.digest(git.read_bytes()),
            bash_executable=str(bash), bash_sha256=action.digest(bash.read_bytes()),
            dependencies=info["dependencies"], other_platforms="NOT_RUN")

        cases, inventories = [], []
        for name in CONTRACTS:
            raw = (trusted / name).read_bytes()
            data = json.loads(raw)
            require(data["schema_version"] == 1 and data["mutations"], "empty/unsupported contract")
            rows = data["mutations"]
            cases.extend(rows)
            inventories.append(dict(path=name, sha256=action.digest(raw), mutations=len(rows)))
        require(len({case["id"] for case in cases}) == len(cases), "duplicate case IDs")
        members = {name.removeprefix("src/"): row for name, row in source_before.items() if name.startswith("src/")}
        package = {name: row["sha256"] for name, row in members.items()
                   if name.startswith("checkwash/") and "__pycache__" not in Path(name).parts and not name.endswith(".pyc")}
        project = tomllib.loads((source / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        descriptor = dict(schema_version=1, kind="checkwash.pju-contract.v1", collector_source_sha=args.collector_source_sha,
            contract_source_sha=args.collector_source_sha, source_commit=args.head_sha, source_tree=args.source_tree,
            src_tree=reader.text(source, "rev-parse", args.head_sha + ":src"), source_package_sha256=action.canonical(package),
            version="checkwash " + project["version"], suite_sha256=action.canonical(cases), cases=cases,
            inventories=inventories, source_members=members, builder_sha256=trusted_before["tools/release_inventory.py"]["sha256"])
        action.save_json(output / "contract-descriptor.json", descriptor)

        replay_argv = [*py, str(trusted / "tools/replay_pju_action.py"), "--source-root", str(source),
                      "--base-sha", args.base_sha, "--head-sha", args.head_sha,
                      "--python", str(python), "--git", str(git), "--bash", str(bash)]
        run("action-dogfood", [*replay_argv, "--action-root", str(pinned), "--action-sha", action.ACTION_SHA,
                               "--output", str(output / "action"), "--scratch", str(scratch / "action")], timeout=3600)
        candidate_closure, pinned_closure = closure(source_before), closure(pinned_before)
        same = candidate_closure == pinned_closure
        coverage = dict(schema_version=1, kind="checkwash.pju-candidate-action-coverage.v1",
            collector_source_sha=args.collector_source_sha, candidate_sha=args.head_sha, pinned_action_sha=action.ACTION_SHA,
            closure_paths=["action/", "src/", "pyproject.toml"], candidate_closure=candidate_closure,
            pinned_closure=pinned_closure, candidate_closure_sha256=action.canonical(candidate_closure),
            pinned_closure_sha256=action.canonical(pinned_closure), mode="byte-identical-reuse" if same else "separate-replay",
            replay_path="action/replay.json" if same else "candidate-action/replay.json")
        action.save_json(output / "candidate-action-coverage.json", coverage)
        if not same:
            require(args.candidate_action_root is not None, "different Action closure requires --candidate-action-root")
            candidate_action = action.absolute_path(args.candidate_action_root, directory=True)
            action.outside(candidate_action, source)
            candidate_action_before = action.snapshot(reader, candidate_action, args.head_sha)
            require(candidate_action_before == source_before, "candidate Action checkout differs")
            run("candidate-action-dogfood", [*replay_argv, "--action-root", str(candidate_action), "--action-sha", args.head_sha,
                "--output", str(output / "candidate-action"), "--scratch", str(scratch / "candidate-action")], timeout=3600)
            require(action.snapshot(reader, candidate_action, args.head_sha) == candidate_action_before,
                    "candidate Action checkout changed")

        artifacts = output / "artifacts"
        artifacts.mkdir()
        # Build before pytest can produce ignored caches. Artifact inventory also
        # independently checks exact Git member bytes, metadata and entrypoints.
        run("build-wheel", [*py, "-m", "build", "--no-isolation", "--wheel", "--sdist", "--outdir", str(artifacts), str(source)])
        wheels, sdists = list(artifacts.glob("*.whl")), list(artifacts.glob("*.tar.gz"))
        require(len(wheels) == len(sdists) == 1, "expected exactly one wheel and sdist")
        wheel, sdist = wheels[0], sdists[0]
        pyz = artifacts / "checkwash.pyz"
        run("build-pyz", [*py, "-m", "zipapp", str(source / "src"), "-m", "checkwash.zipapp_entry:run", "-o", str(pyz), "-c"])
        wheel_env = scratch / "wheel-environment"
        run("wheel-venv", [*py, "-m", "venv", str(wheel_env)])
        wheel_python = wheel_env / "Scripts/python.exe"
        run("wheel-install", [str(wheel_python), "-I", "-B", "-X", "utf8", "-m", "pip", "--isolated",
                              "--disable-pip-version-check", "--no-input", "install", "--no-index", "--no-deps",
                              "--no-compile", "--report", str(output / "wheel-install-report.json"), str(wheel)])
        run("test-editable-install", [*py, "-m", "pip", "--isolated", "--disable-pip-version-check", "--no-input",
                                     "install", "--no-index", "--no-deps", "--no-build-isolation", "--no-compile",
                                     "--report", str(output / "test-install-report.json"), "-e", str(source)])
        run("pytest", [*py, "-m", "pytest", "-p", "xdist.plugin", "-n", "2", "--dist", "worksteal",
                       "-p", "no:cacheprovider", "--basetemp", str(scratch / "pytest"),
                       "--junitxml", str(output / "junit.xml"), "tests"], cwd=source, timeout=14400)

        for distribution in ("source", "wheel", "pyz"):
            qualification = output / manifest["records"]["qualifications"][distribution]
            inventory = output / manifest["records"]["inventories"][distribution]
            qualify_args = ["--source-root", str(source), "--distribution", distribution, "--output", str(qualification)]
            artifact = {"source": None, "wheel": wheel, "pyz": pyz}[distribution]
            if artifact:
                qualify_args += ["--artifact", str(artifact)]
            qualify_args += ["--", str(wheel_python if distribution == "wheel" else python)]
            worker = [*py, str(Path(__file__).resolve()), "--internal-helper"]
            run("qualify-" + distribution, [*worker, "qualify_assertions.py",
                str(output / ("nested-qualify-" + distribution)), *qualify_args], timeout=7200)
            inventory_args = ["--source-root", str(source), "--distribution", distribution,
                              "--qualification", str(qualification), "--output", str(inventory)]
            for item in {"source": [], "wheel": [wheel, sdist], "pyz": [pyz]}[distribution]:
                inventory_args += ["--artifact", str(item)]
            run("inventory-" + distribution, [*worker, "release_inventory.py",
                str(output / ("nested-inventory-" + distribution)), *inventory_args], timeout=1800)
        require(action.snapshot(reader, source, args.head_sha) == source_before, "candidate source changed during collection")
        require(action.snapshot(reader, trusted, args.collector_source_sha) == trusted_before, "collector source changed")
        require(action.snapshot(reader, pinned, action.ACTION_SHA) == pinned_before, "pinned Action source changed")
        for name, path in (("python", python), ("git", git), ("bash", bash)):
            require(action.digest(path.read_bytes()) == manifest["runtime"][name + "_sha256"], "runtime executable changed")
        manifest["status"] = "completed"
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        errors.append(type(exc).__name__ + ": " + str(exc))
    finally:
        action.save_json(output / "collection-status.json", dict(status=manifest["status"], errors=errors,
            provenance=manifest["provenance"], other_platforms="NOT_RUN",
            action_build_dependency_scope="Actual Action PEP 517 build dependency resolution is logged, not claimed locked."))
        files = []
        for directory, dirs, names in os.walk(output, followlinks=False):
            action.regular(Path(directory), directory=True)
            for name in dirs:
                action.regular(Path(directory) / name, directory=True)
            for name in names:
                path = Path(directory) / name
                action.regular(path)
                raw = path.read_bytes()
                files.append(dict(path=path.relative_to(output).as_posix(), sha256=action.digest(raw), bytes=len(raw)))
        manifest["files"] = sorted(files, key=lambda row: row["path"])
        action.save_json(output / "manifest.json", manifest)
    print(json.dumps(dict(status=manifest["status"], errors=errors, manifest=str(output / "manifest.json"),
                         manifest_sha256=action.digest((output / "manifest.json").read_bytes()))))
    return 0 if manifest["status"] == "completed" else 1


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--internal-helper"]:
        if len(argv) < 4 or os.name != "nt" or platform.node().upper() != "LAPTOP-01AGNPJU":
            raise ValueError("invalid PJU helper invocation")
        if not sys.flags.isolated or not sys.flags.utf8_mode or not sys.dont_write_bytecode:
            raise ValueError("helper requires -I -B -X utf8")
        return traced_worker(argv[1], Path(argv[2]), argv[3:])
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source-root", "action-root", "python", "git", "bash", "output", "scratch", "dependency-lock"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--candidate-action-root", type=Path)
    for name in ("base-sha", "head-sha", "source-tree", "collector-source-sha", "dependency-lock-sha256"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--repository", default=REPOSITORY)
    parser.add_argument("--pr", type=int, required=True)
    return collect(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
