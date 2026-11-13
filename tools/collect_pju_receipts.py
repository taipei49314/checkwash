"""Collect real, exact-source receipts on an authorized local Windows host.

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
import concurrent.futures
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import locale
import os
from pathlib import Path, PurePosixPath
import platform
import re
import runpy
import shutil
import subprocess
import sys
import threading
import time
import tomllib

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ("tests/data/javascript_assertion_support.json", "tests/data/javascript_foundation_mutations.json")
UTILITIES = ("tools/assertion_contract.py", "tools/qualify_assertions.py", "tools/release_inventory.py")
REPOSITORY = "taipei49314/checkwash"
# Full-suite xdist workers on the 24-core receipt host; both bridges require
# exactly this count (receipt speed-up, D-198).
PYTEST_WORKERS = "8"
# Compact PR digest receipts use 16 xdist workers on the 24-core receipt host (D-209).
COMPACT_PYTEST_WORKERS = "16"
# traced_worker rewrites a helper's nested commands.json every this many rows
# and when the helper ends, not after every row.
NESTED_FLUSH_ROWS = 500


def load_replayer():
    spec = importlib.util.spec_from_file_location("_trusted_pju_action", ROOT / "tools/replay_pju_action.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_trusted_module(alias, filename):
    spec = importlib.util.spec_from_file_location(alias, ROOT / "tools" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def traced_worker(tool, log_root, arguments):
    """Run the audited helper with lossless, offset-indexed subprocess streams.

    This changes no helper commands, inputs, expected cases or exit handling.
    Expected detector exits 1/2 belong in this nested ledger, not in the ten
    top-level success exits. Two append-only byte streams avoid thousands of
    tiny receipt files. Worker subprocesses inherit only the collector allowlist.
    A helper may run subprocesses on several threads (``verdict_gate.py
    --jobs``): one lock covers each row's stream appends and ledger append, so
    every recorded offset is exact; the subprocesses themselves run at once.
    ``commands.json`` is rewritten every ``NESTED_FLUSH_ROWS`` rows and when
    the helper ends, not after every row: a 4,000-row gate ledger rewritten
    per row cost minutes inside that lock (D-198 review).
    """
    allowed = {"qualify_assertions.py", "release_inventory.py", "verdict_gate.py",
               "verify_published_source.py", "qualify_zipapp.py"}
    if tool not in allowed:
        raise ValueError("unsupported trusted helper")
    log_root.mkdir(parents=True, exist_ok=False)
    original = subprocess.run
    ledger = []
    record = threading.Lock()

    def flush():
        (log_root / "commands.json").write_text(json.dumps(ledger, sort_keys=True, indent=2) + "\n", encoding="utf-8")

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
            with record:
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
                if len(ledger) % NESTED_FLUSH_ROWS == 0:
                    flush()
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
        with record:
            if ledger:
                flush()


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


def collect(args, *, release_context=None, stage_preflight=None, stage_steps=None, artifact_provider=None, initialize=None, finalize=None):
    """Collect PR evidence, or an explicitly distinct release-stage packet.

    Release callers provide their own admitted subject and stage operations.
    There is no synthetic PR number and no conversion of an old PR packet.
    Every invocation runs a fresh development/qualification collection.
    """
    action = load_replayer()
    require = action.require
    route = action.execution_route()
    require(sys.version_info[:2] == (3, 11) and sys.flags.isolated and sys.dont_write_bytecode and sys.flags.utf8_mode,
            "collector requires Python 3.11 with -I -B -X utf8")
    require(args.repository == REPOSITORY, "unexpected repository")
    if release_context is None:
        require(type(args.pr) is int and args.pr > 0, "unexpected PR")
    else:
        require(type(release_context) is dict and callable(stage_steps), "release-stage context/operations required")
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
                    pr_number=getattr(args, "pr", None), base_sha=args.base_sha, head_sha=args.head_sha, source_tree=args.source_tree,
                    host=route["host"], provenance=route["provenance"],
                    collector_source_sha=args.collector_source_sha, contract_source_sha=args.collector_source_sha,
                    action_sha=action.ACTION_SHA, status="failed", runtime={}, files=[], raw_exits=ledger,
                    records=dict(dogfood="action/runtime-receipts/check-receipt.json", action_replay="action/replay.json",
                                 candidate_action_coverage="candidate-action-coverage.json", junit="junit.xml",
                                 qualifications={d: f"qualifications/{d}.json" for d in ("source", "wheel", "pyz")},
                                 inventories={d: f"inventories/{d}.json" for d in ("source", "wheel", "pyz")},
                                 contract_descriptor="contract-descriptor.json"))
    if release_context is not None:
        manifest.pop("pr_number")
        manifest.update(kind="checkwash.pju-release-receipt.v1", **release_context)
    errors = []
    ledger_lock = threading.Lock()

    def run(name, argv, *, cwd=scratch, timeout=1800):
        row = action.run_record(name, argv, cwd=cwd, env=env, output=output, timeout=timeout, ledger=ledger,
                                lock=ledger_lock)
        require(row["exit_code"] == 0 and not row["timed_out"], "command failed: " + name)
        return (output / row["stdout"]).read_bytes()

    py = [str(python), "-I", "-B", "-X", "utf8"]
    context = dict(args=args, action=action, require=require, source=source, trusted=trusted,
                   python=python, git=git, bash=bash, output=output, scratch=scratch,
                   env=env, py=py, reader=reader, run=run, manifest=manifest)
    try:
        if initialize is not None:
            initialize(context)
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
        context.update(source_before=source_before, trusted_before=trusted_before, project=project)
        if stage_preflight is not None:
            stage_preflight(context)
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
        context.update(source_before=source_before, trusted_before=trusted_before, project=project)
        if artifact_provider is None:
            run("build-wheel", [*py, "-m", "build", "--no-isolation", "--wheel", "--sdist", "--outdir", str(artifacts), str(source)])
        else:
            artifact_provider(context)
        wheels, sdists = list(artifacts.glob("*.whl")), list(artifacts.glob("*.tar.gz"))
        require(len(wheels) == len(sdists) == 1, "expected exactly one wheel and sdist")
        wheel, sdist = wheels[0], sdists[0]
        pyz = artifacts / "checkwash.pyz"
        if artifact_provider is None:
            run("build-pyz", [*py, "-m", "zipapp", str(source / "src"), "-m", "checkwash.zipapp_entry:run", "-o", str(pyz), "-c"])
        require(pyz.is_file(), "zipapp missing")
        context.update(wheel=wheel, sdist=sdist, pyz=pyz)
        wheel_env = scratch / "wheel-environment"
        run("wheel-venv", [*py, "-m", "venv", str(wheel_env)])
        wheel_python = wheel_env / "Scripts/python.exe"
        run("wheel-install", [str(wheel_python), "-I", "-B", "-X", "utf8", "-m", "pip", "--isolated",
                              "--disable-pip-version-check", "--no-input", "install", "--no-index", "--no-deps",
                              "--no-compile", "--report", str(output / "wheel-install-report.json"), str(wheel)])
        run("test-editable-install", [*py, "-m", "pip", "--isolated", "--disable-pip-version-check", "--no-input",
                                     "install", "--no-index", "--no-deps", "--no-build-isolation", "--no-compile",
                                     "--report", str(output / "test-install-report.json"), "-e", str(source)])
        run("pytest", [*py, "-m", "pytest", "-p", "xdist.plugin", "-n", PYTEST_WORKERS, "--dist", "worksteal",
                       "-p", "no:cacheprovider", "--basetemp", str(scratch / "pytest"),
                       "--junitxml", str(output / "junit.xml"), "tests"], cwd=source, timeout=14400)

        worker = [*py, str(Path(__file__).resolve()), "--internal-helper"]

        def qualify_and_inventory(distribution):
            qualification = output / manifest["records"]["qualifications"][distribution]
            inventory = output / manifest["records"]["inventories"][distribution]
            qualify_args = ["--source-root", str(source), "--distribution", distribution, "--output", str(qualification)]
            artifact = {"source": None, "wheel": wheel, "pyz": pyz}[distribution]
            if artifact:
                qualify_args += ["--artifact", str(artifact)]
            qualify_args += ["--", str(wheel_python if distribution == "wheel" else python)]
            run("qualify-" + distribution, [*worker, "qualify_assertions.py",
                str(output / ("nested-qualify-" + distribution)), *qualify_args], timeout=7200)
            inventory_args = ["--source-root", str(source), "--distribution", distribution,
                              "--qualification", str(qualification), "--output", str(inventory)]
            for item in {"source": [], "wheel": [wheel, sdist], "pyz": [pyz]}[distribution]:
                inventory_args += ["--artifact", str(item)]
            run("inventory-" + distribution, [*worker, "release_inventory.py",
                str(output / ("nested-inventory-" + distribution)), *inventory_args], timeout=1800)

        # The three chains are independent: each writes only its own records,
        # logs and nested ledger, and each inventory reads only its own
        # qualification. They run at once; after all three have finished,
        # every failed chain's error is recorded, in distribution order, and
        # the collection fails.
        distributions = ("source", "wheel", "pyz")
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(distributions)) as pool:
            chains = [pool.submit(qualify_and_inventory, d) for d in distributions]
        failed = [(d, chain.exception()) for d, chain in zip(distributions, chains) if chain.exception() is not None]
        errors.extend(f"{d} chain: {type(exc).__name__}: {exc}" for d, exc in failed)
        require(not failed, "qualification chain failed: " + ", ".join(d for d, _ in failed))
        if stage_steps is not None:
            stage_steps(context)
        require(action.snapshot(reader, source, args.head_sha) == source_before, "candidate source changed during collection")
        require(action.snapshot(reader, trusted, args.collector_source_sha) == trusted_before, "collector source changed")
        require(action.snapshot(reader, pinned, action.ACTION_SHA) == pinned_before, "pinned Action source changed")
        for name, path in (("python", python), ("git", git), ("bash", bash)):
            require(action.digest(path.read_bytes()) == manifest["runtime"][name + "_sha256"], "runtime executable changed")
        manifest["status"] = "completed"
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        errors.append(type(exc).__name__ + ": " + str(exc))
    finally:
        if finalize is not None:
            finalize(context, errors)
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


def _summarize_action_replay(action_dir, *, expected_action_sha, base_sha, head_sha, python_version, route, action):
    replay_raw = (action_dir / "replay.json").read_bytes()
    replay = json.loads(replay_raw)
    require = action.require
    require(replay["status"] == "completed" and replay["errors"] == []
            and replay["action_sha"] == expected_action_sha
            and replay["base_sha"] == base_sha and replay["head_sha"] == head_sha
            and replay["fail_on"] == "high" and replay["comment_pr"] is False
            and replay["host"] == route["host"] and replay["provenance"] == route["action_provenance"],
            "Action replay did not complete cleanly")
    steps = replay["steps"]
    require([s.get("id") for s in steps] == ["install", "check"]
            and all(s.get("exit_code") == 0 for s in steps)
            and str(replay["resolved_outputs"].get("exit-code")) == "0", "Action replay steps failed")
    check_raw = (action_dir / replay["files"]["check_receipt"]).read_bytes()
    check_receipt = json.loads(check_raw)
    identity = json.loads((action_dir / replay["files"]["identity"]).read_bytes())
    install = json.loads((action_dir / replay["files"]["install_report"]).read_bytes())
    require(check_receipt["exit_code"] == 0 and check_receipt["analysis_exit_code"] == 0
            and check_receipt["error"] is None and check_receipt["base"] == base_sha
            and check_receipt["head"] == head_sha and check_receipt["fail_on"] == "high",
            "Action check receipt failed")
    require(check_receipt["identity"] == identity
            and all(identity.get(k) is True for k in ("isolated", "utf8", "bytecode_writes_disabled"))
            and identity.get("python_version") == python_version, "Action identity receipt mismatch")
    require(install.get("version") == "1" and len(install.get("install", [])) == 1
            and install["install"][0].get("metadata", {}).get("name") == "checkwash"
            and install["install"][0]["metadata"].get("version") == identity["version"],
            "Action pip install report mismatch")
    return dict(
        action_sha=expected_action_sha,
        action_tree=replay["action_tree"],
        action_yaml_sha256=replay["action_yaml_sha256"],
        install_run_sha256=steps[0]["run_sha256"],
        check_run_sha256=steps[1]["run_sha256"],
        source_digest=identity["source_digest"],
        runtime_files=identity["runtime_files"],
        version=identity["version"],
        base_sha=base_sha,
        head_sha=head_sha,
        fail_on="high",
        comment_pr=False,
        exit_code=0,
        analysis_exit_code=0,
        host=route["host"],
        provenance=route["action_provenance"],
        check_receipt_sha256=action.digest(check_raw),
        replay_sha256=action.digest(replay_raw),
    )


def collect_compact(args):
    """Collect a compact PJU digest receipt without 3x283 CLI duplication or 53 MiB Git trees."""
    action = load_replayer()
    bridge = load_trusted_module("_trusted_pju_bridge", "pju_receipt_bridge.py")
    inventory_mod = load_trusted_module("_trusted_release_inventory", "release_inventory.py")
    qualify_mod = load_trusted_module("_trusted_qualify_assertions", "qualify_assertions.py")
    require = action.require
    route = action.execution_route()
    require(sys.version_info[:2] == (3, 11) and sys.flags.isolated and sys.dont_write_bytecode and sys.flags.utf8_mode,
            "collector requires Python 3.11 with -I -B -X utf8")
    require(args.repository == REPOSITORY, "unexpected repository")
    require(type(args.pr) is int and args.pr > 0, "unexpected PR")
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
    normalized_lock = normalized_packages(expected_dependencies)
    output.mkdir(parents=True, exist_ok=False)
    scratch.mkdir(parents=True, exist_ok=False)
    env = action.clean_environment(python, git, bash, scratch)
    env["ENGINE_SOURCE"] = args.head_sha
    template = scratch / "git-template"
    template.mkdir()
    env["GIT_TEMPLATE_DIR"] = str(template)
    reader = action.GitReader(git, env, output / "git-evidence")
    reader.output.mkdir()

    def _clean_git(repo_root, *git_args):
        res = subprocess.run(
            [str(git), "-c", "core.hooksPath=" + os.devnull, "-c", "core.fsmonitor=false",
             "-c", "core.untrackedCache=false", "-C", str(repo_root), *git_args],
            cwd=scratch, env=env, capture_output=True, timeout=120,
        )
        require(res.returncode == 0, "Git read failed: " + " ".join(git_args))
        return res.stdout

    orig_inv_git = inventory_mod.git
    orig_bridge_git = bridge.git
    inventory_mod.git = lambda *git_args: _clean_git(source, *git_args)
    bridge.git = _clean_git
    ledger = []
    ledger_lock = threading.Lock()
    errors = []
    compact = dict(
        schema_version=1,
        kind="checkwash.pju-compact-receipt.v1",
        status="failed",
        repository=args.repository,
        pr_number=args.pr,
        base_sha=args.base_sha,
        head_sha=args.head_sha,
        source_tree=args.source_tree,
        src_tree="",
        host=route["host"],
        provenance=route["provenance"],
        collector_source_sha=args.collector_source_sha,
        action_sha=action.ACTION_SHA,
        version="",
        runtime={},
        contracts={},
        action_dogfood={},
        candidate_action={},
        distributions={},
        junit={},
        pytest_argv=[],
        raw_exits=[],
    )

    def run(name, argv, *, cwd=scratch, timeout=1800):
        row = action.run_record(name, argv, cwd=cwd, env=env, output=output, timeout=timeout, ledger=ledger,
                                lock=ledger_lock)
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
        normalized_installed = normalized_packages(info["dependencies"])
        require(normalized_installed == normalized_lock,
                "installed dependencies differ from admitted lock (use a fresh environment)")
        pytest_version = normalized_installed.get("pytest", "")
        compact["runtime"] = dict(
            os="Windows",
            python_version=info["python_version"],
            python_executable=str(python),
            python_sha256=action.digest(python.read_bytes()),
            git_executable=str(git),
            git_sha256=action.digest(git.read_bytes()),
            bash_executable=str(bash),
            bash_sha256=action.digest(bash.read_bytes()),
            dependency_lock_sha256=args.dependency_lock_sha256,
            dependencies_sha256=action.canonical(normalized_installed),
            pytest_version=pytest_version,
            xdist_workers=COMPACT_PYTEST_WORKERS,
            other_platforms="NOT_RUN",
        )

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
        source_package_sha256 = action.canonical(package)
        project = tomllib.loads((source / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        compact["src_tree"] = reader.text(source, "rev-parse", args.head_sha + ":src")
        compact["version"] = "checkwash " + project["version"]
        compact["contracts"] = dict(
            source_package_sha256=source_package_sha256,
            builder_sha256=trusted_before["tools/release_inventory.py"]["sha256"],
            suite_sha256=action.canonical(cases),
            inventories=inventories,
        )

        candidate_closure, pinned_closure = closure(source_before), closure(pinned_before)
        same_closure = candidate_closure == pinned_closure
        candidate_action = None
        candidate_action_before = None
        if not same_closure:
            require(args.candidate_action_root is not None, "different Action closure requires --candidate-action-root")
            candidate_action = action.absolute_path(args.candidate_action_root, directory=True)
            for path in (output, scratch):
                action.outside(path, candidate_action)
            action.outside(candidate_action, source)
            candidate_action_before = action.snapshot(reader, candidate_action, args.head_sha)
            require(candidate_action_before == source_before, "candidate Action checkout differs")
            require(not reader.read(candidate_action, "ls-files", "--others", "--ignored", "--exclude-standard"),
                    "candidate Action checkout contains ignored files")

        replay_argv = [*py, str(trusted / "tools/replay_pju_action.py"), "--source-root", str(source),
                       "--base-sha", args.base_sha, "--head-sha", args.head_sha,
                       "--python", str(python), "--git", str(git), "--bash", str(bash)]
        if same_closure:
            run("action-dogfood", [*replay_argv, "--action-root", str(pinned), "--action-sha", action.ACTION_SHA,
                                   "--output", str(output / "action"), "--scratch", str(scratch / "action")], timeout=3600)
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                futs = [
                    pool.submit(
                        run, "action-dogfood",
                        [*replay_argv, "--action-root", str(pinned), "--action-sha", action.ACTION_SHA,
                         "--output", str(output / "action"), "--scratch", str(scratch / "action")],
                        timeout=3600,
                    ),
                    pool.submit(
                        run, "candidate-action-dogfood",
                        [*replay_argv, "--action-root", str(candidate_action), "--action-sha", args.head_sha,
                         "--output", str(output / "candidate-action"), "--scratch", str(scratch / "candidate-action")],
                        timeout=3600,
                    ),
                ]
            replay_failures = [str(fut.exception()) for fut in futs if fut.exception() is not None]
            require(not replay_failures, "; ".join(replay_failures))
            require(action.snapshot(reader, candidate_action, args.head_sha) == candidate_action_before,
                    "candidate Action checkout changed")

        compact["action_dogfood"] = _summarize_action_replay(
            output / "action", expected_action_sha=action.ACTION_SHA, base_sha=args.base_sha, head_sha=args.head_sha,
            python_version=info["python_version"], route=route, action=action)
        compact["candidate_action"] = dict(
            candidate_closure_sha256=action.canonical(candidate_closure),
            pinned_closure_sha256=action.canonical(pinned_closure),
            mode="byte-identical-reuse" if same_closure else "separate-replay",
            replay=None if same_closure else _summarize_action_replay(
                output / "candidate-action", expected_action_sha=args.head_sha, base_sha=args.base_sha, head_sha=args.head_sha,
                python_version=info["python_version"], route=route, action=action),
        )

        artifacts = scratch / "artifacts"
        artifacts.mkdir()
        run("build-wheel", [*py, "-m", "build", "--no-isolation", "--wheel", "--sdist", "--outdir", str(artifacts), str(source)])
        wheels, sdists = list(artifacts.glob("*.whl")), list(artifacts.glob("*.tar.gz"))
        require(len(wheels) == len(sdists) == 1, "expected exactly one wheel and sdist")
        wheel, sdist = wheels[0], sdists[0]
        pyz = artifacts / "checkwash.pyz"
        run("build-pyz", [*py, "-m", "zipapp", str(source / "src"), "-m", "checkwash.zipapp_entry:run", "-o", str(pyz), "-c"])
        require(pyz.is_file(), "zipapp missing")

        inventory_mod.ROOT = source
        entries, _proof = inventory_mod.source_inventory(args.head_sha)
        distributions = {}
        for kind, artifact in (("wheel", wheel), ("sdist", sdist), ("pyz", pyz)):
            raw_art = artifact.read_bytes()
            art_members = inventory_mod.archive_inventory(artifact, entries)
            if kind == "sdist":
                sdist_root = next(iter({PurePosixPath(p).parts[0] for p in art_members}))
                pkg_prefix = sdist_root + "/src/"
            else:
                pkg_prefix = ""
            pkg_hashes = {
                p[len(pkg_prefix):]: row["sha256"]
                for p, row in art_members.items()
                if p.startswith(pkg_prefix + "checkwash/") and "__pycache__" not in PurePosixPath(p).parts and not p.endswith(".pyc")
            }
            pkg_digest = action.canonical(pkg_hashes)
            require(pkg_digest == source_package_sha256, "artifact package digest mismatch: " + kind)
            distributions[kind] = dict(
                name=artifact.name,
                sha256=action.digest(raw_art),
                bytes=len(raw_art),
                members_sha256=action.canonical(art_members),
                package_sha256=pkg_digest,
            )
        compact["distributions"] = distributions

        wheel_env = scratch / "wheel-environment"
        run("wheel-venv", [*py, "-m", "venv", str(wheel_env)])
        wheel_python = wheel_env / "Scripts/python.exe"
        run("wheel-install", [str(wheel_python), "-I", "-B", "-X", "utf8", "-m", "pip", "--isolated",
                              "--disable-pip-version-check", "--no-input", "install", "--no-index", "--no-deps",
                              "--no-compile", "--report", str(output / "wheel-install-report.json"), str(wheel)])
        wheel_probe_raw = run("wheel-import-check", [str(wheel_python), "-I", "-B", "-X", "utf8", "-c",
            "import json,sys,checkwash; print(json.dumps({'package':checkwash.__file__,'prefix':sys.prefix,'base':sys.base_prefix}))"])
        wheel_probe = json.loads(wheel_probe_raw)
        wheel_pkg_dir = Path(wheel_probe["package"]).resolve().parent
        wheel_prefix = Path(wheel_probe["prefix"]).resolve()
        require(wheel_probe["prefix"] != wheel_probe["base"] and wheel_pkg_dir.is_relative_to(wheel_prefix),
                "wheel must load inside its fresh venv")
        require(qualify_mod.package_files(wheel_pkg_dir) == package, "installed wheel package differs from source")
        wheel_demo_out = run("wheel-demo", [str(wheel_python), "-I", "-B", "-X", "utf8", "-m", "checkwash", "demo"])
        require(b"tampering cases blocked" in wheel_demo_out, "wheel demo did not execute packaged cases")
        pyz_demo_out = run("pyz-demo", [*py, str(pyz), "demo"])
        require(b"tampering cases blocked" in pyz_demo_out, "pyz demo did not execute packaged cases")

        run("test-editable-install", [*py, "-m", "pip", "--isolated", "--disable-pip-version-check", "--no-input",
                                     "install", "--no-index", "--no-deps", "--no-build-isolation", "--no-compile",
                                     "--report", str(output / "test-install-report.json"), "-e", str(source)])
        pytest_argv = [*py, "-m", "pytest", "-p", "xdist.plugin", "-n", COMPACT_PYTEST_WORKERS, "--dist", "worksteal",
                       "-p", "no:cacheprovider", "--basetemp", str(scratch / "pytest"),
                       "--junitxml", str(output / "junit.xml"), "tests"]
        compact["pytest_argv"] = pytest_argv
        pytest_stdout = run("pytest", pytest_argv, cwd=source, timeout=14400)
        junit_raw = (output / "junit.xml").read_bytes()
        junit_parsed = bridge.validate_junit(junit_raw, pytest_stdout=pytest_stdout, pytest_version=pytest_version)
        expected_tests = bridge.documented_test_count(source, args.head_sha)
        require(junit_parsed["tests"] == expected_tests,
                f"JUnit test count {junit_parsed['tests']} differs from documented suite count {expected_tests}")
        compact["junit"] = dict(
            sha256=action.digest(junit_raw),
            bytes=len(junit_raw),
            tests=junit_parsed["tests"],
            passed=junit_parsed["tests"] - junit_parsed["skipped"],
            skipped=junit_parsed["skipped"],
            failures=0,
            errors=0,
            passed_subtests=junit_parsed.get("passed_subtests", 0),
            pytest_stdout_sha256=action.digest(pytest_stdout),
        )

        require(action.snapshot(reader, source, args.head_sha) == source_before, "candidate source changed during collection")
        require(action.snapshot(reader, trusted, args.collector_source_sha) == trusted_before, "collector source changed")
        require(action.snapshot(reader, pinned, action.ACTION_SHA) == pinned_before, "pinned Action source changed")
        for name, path in (("python", python), ("git", git), ("bash", bash)):
            require(action.digest(path.read_bytes()) == compact["runtime"][name + "_sha256"], "runtime executable changed")
        compact["status"] = "completed"
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        errors.append(type(exc).__name__ + ": " + str(exc))
    finally:
        inventory_mod.git = orig_inv_git
        bridge.git = orig_bridge_git
        compact["raw_exits"] = [
            dict(
                name=row["name"],
                duration_seconds=row["duration_seconds"],
                exit_code=row["exit_code"],
                timed_out=row["timed_out"],
                stdout_sha256=action.digest((output / row["stdout"]).read_bytes()),
                stderr_sha256=action.digest((output / row["stderr"]).read_bytes()),
            )
            for row in ledger
        ]
        action.save_json(output / "collection-status.json", dict(
            status=compact["status"], errors=errors, provenance=compact["provenance"], other_platforms="NOT_RUN",
            mode="compact-receipt",
        ))
        action.save_json(output / "compact-receipt-pretty.json", compact)
        compact_raw = json.dumps(compact, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        compact_path = output / "compact-receipt.json"
        compact_path.write_bytes(compact_raw)
    print(json.dumps(dict(
        status=compact["status"],
        errors=errors,
        compact_receipt=str(output / "compact-receipt.json"),
        manifest_sha256=action.digest(compact_raw),
        bytes=len(compact_raw),
    )))
    return 0 if compact["status"] == "completed" else 1


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--internal-helper"]:
        if len(argv) < 4:
            raise ValueError("invalid local receipt helper invocation")
        load_replayer().execution_route()
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
    parser.add_argument("--compact", action="store_true",
                        help="collect a single-line compact digest receipt without evidence-branch archive files")
    parsed = parser.parse_args(argv)
    return collect_compact(parsed) if parsed.compact else collect(parsed)


if __name__ == "__main__":
    raise SystemExit(main())
