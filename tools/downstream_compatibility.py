"""One ordinary-PR job: qualified artifacts, 12 owned CLI cells, three real consumers.

Source-only proposal. No downstream checkout, campaign, repin or release action.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import tomllib
import traceback

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
HELPER_SHA = "017d3c0dafb7ac0bf71bec8d514baccc791e03073ed1f86b1ef0018232bfc643"
if hashlib.sha256((HERE / "owned_process_capture.py").read_bytes()).hexdigest() != HELPER_SHA:
    raise RuntimeError("reviewed capture helper differs")
sys.path.insert(0, str(HERE))
import owned_process_capture as cap

OUT = Path(os.environ["RUNNER_TEMP"]).resolve() / "downstream-evidence"
PRIVATE = OUT.parent / "downstream-private"
CLOSURE = HERE / "downstream_dependency_closure.json"
INPUT = HERE / "downstream_owned_input.json"
PROBE = HERE / "downstream_consumer_probe.py"
ARMS = ("source", "wheel", "pyz", "published-pyz")
CASES = ("clean", "weakened", "invalid-ref")
PIN = "4f9c7b836d1e1c40dc0a7b88ef6d63f25d482c8eafda18c05eb5a4fbac9ad949"
PIN_SOURCE = "8c70efbf93975bf3210acb8eafbaf4b38044a770"
TOOLS = ("downstream_compatibility.py", "downstream_consumer_probe.py",
         "downstream_dependency_closure.json", "downstream_owned_input.json",
         "owned_process_capture.py", "qualify_assertions.py", "release_inventory.py")
DEADLINE = time.monotonic() + 2400
sequence = 0
ledger = {}


def require(value, message):
    if not value:
        raise ValueError(message)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    cap.write(path, value)


def ref(path):
    return dict(path=path.relative_to(OUT).as_posix(), sha256=cap.digest(path))


def environment():
    # Explicit public event context; never serialize ambient credentials.
    names = ("PATH", "GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_EVENT_NAME",
             "PR_HEAD_SHA", "PR_BASE_SHA", "RUNNER_TEMP", "ImageOS", "ImageVersion")
    env = {key: os.environ[key] for key in names if key in os.environ}
    env.update(HOME=str(PRIVATE / "home"), TMPDIR=str(PRIVATE / "tmp"),
               LANG="C.UTF-8", LC_ALL="C.UTF-8", GIT_CONFIG_NOSYSTEM="1",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0",
               ENGINE_SOURCE=os.environ["GITHUB_SHA"], CANDIDATE_SOURCE=os.environ["GITHUB_SHA"],
               CHECKWASH_TODAY="2026-01-01", GREENWASH_TODAY="2026-01-01", NO_COLOR="1")
    return env


def launch(argv, cwd, *, label, timeout=120, expected=(0,), optional=False, extra=None, track=None):
    global sequence
    sequence += 1
    directory = OUT / "processes" / f"{sequence:04d}-{label}"
    directory.mkdir(parents=True)
    prefix = directory / "process"
    env = environment() | (extra or {})
    invocation = dict(argv=argv, cwd=str(cwd), environment=env, timeout_seconds=timeout,
                      stream_limit_bytes=4_000_000, expected_exits=list(expected))
    save(directory / "invocation.json", invocation)
    ledger["cleanup_safe"] = False
    save(OUT / "ledger.json", ledger)
    observation = cap.capture(argv, cwd, env, prefix, timeout, 4_000_000, deadline=DEADLINE)
    record = dict(invocation=ref(directory / "invocation.json"), observation=ref(prefix.with_suffix(".observation.json")),
                  stdout=ref(prefix.with_suffix(".stdout")), stderr=ref(prefix.with_suffix(".stderr")),
                  intent=ref(prefix.with_suffix(".intent.json")), capture=observation)
    record["ok"] = (observation["status"] == "EXITED" and observation["capture_complete"] is True
                    and observation["cleanup_complete"] is True and observation["exit_code"] in expected)
    save(directory / "receipt.json", record)
    if track is not None:
        track.update(state="COMPLETE" if record["ok"] else "FAILED", process=record)
    # Record current row before stopping; no next child follows uncertain cleanup.
    ledger["last_process"] = ref(directory / "receipt.json")
    ledger["cleanup_safe"] = observation["cleanup_complete"] is True
    save(OUT / "ledger.json", ledger)
    require(observation["cleanup_complete"] is True, "process cleanup uncertain; remaining cells NOT_ATTEMPTED")
    if not optional:
        require(record["ok"], "required setup/qualification process failed: " + label)
    return record


def stdout(record):
    return (OUT / record["stdout"]["path"]).read_bytes()


def git(repo, *args, extra=None):
    return stdout(launch([str(Path(shutil.which("git")).absolute()), "-C", str(repo), *args],
                         PRIVATE, label="git", timeout=30, extra=extra))


def text_git(repo, *args):
    return git(repo, *args).decode("utf-8").strip()


def source_identity():
    row = dict(head=text_git(ROOT, "rev-parse", "HEAD"), tree=text_git(ROOT, "rev-parse", "HEAD^{tree}"),
               status=text_git(ROOT, "status", "--porcelain", "--untracked-files=all"),
               tools={name: cap.digest(HERE / name) for name in TOOLS},
               package={p.relative_to(ROOT).as_posix(): cap.digest(p)
                        for p in sorted((ROOT / "src/checkwash").rglob("*"))
                        if p.is_file() and "__pycache__" not in p.parts and p.suffix not in {".pyc", ".pyo"}})
    save(OUT / ("source-initial.json" if "source" not in ledger else "source-final.json"), row)
    require(row["head"] == os.environ["GITHUB_SHA"] and not row["status"], "candidate HEAD/dirty mismatch")
    for name in TOOLS:
        require(git(ROOT, "show", row["head"] + ":tools/" + name) == (HERE / name).read_bytes(),
                "tool bytes differ from canonical Git source")
    return row


def download(url, destination, limit):
    destination.parent.mkdir(parents=True, exist_ok=True)
    receipt = dict(url=url, limit_bytes=limit, state="STARTED")
    metadata = OUT / "downloads" / (hashlib.sha256(url.encode()).hexdigest() + ".json")
    save(metadata, receipt)
    try:
        # The unchanged capture helper supplies a real whole-process bound,
        # rather than treating urllib's socket idle timeout as a total deadline.
        fetch = (
            "import json,sys,urllib.request; from pathlib import Path; "
            "url,path,limit=sys.argv[1:]; limit=int(limit); "
            "request=urllib.request.Request(url,headers={'User-Agent':'checkwash-owned-compatibility'}); "
            "response=urllib.request.urlopen(request,timeout=30); "
            "raw=response.read(limit+1); Path(path).write_bytes(raw); "
            "print(json.dumps({'status':response.status,'final_url':response.url,'headers':dict(response.headers)})); "
            "response.close(); "
            "sys.exit(0 if len(raw)<=limit else 2)"
        )
        captured = launch([sys.executable, "-I", "-B", "-X", "utf8", "-c", fetch,
                           url, str(destination), str(limit)], PRIVATE, label="download", timeout=60)
        receipt.update(json.loads(stdout(captured)))
        receipt.update(bytes=destination.stat().st_size, sha256=cap.digest(destination), process=captured)
        require(destination.stat().st_size <= limit, "download exceeds declared bound")
        receipt["state"] = "COMPLETE"
    except BaseException:
        receipt.update(state="FAILED", error=traceback.format_exc())
        raise
    finally:
        save(metadata, receipt)


def consumers():
    closure = read(CLOSURE)
    require(len(closure["files"]) == 24 and len({r["path"] for r in closure["files"]}) == 24,
            "consumer closure denominator differs")
    destination = OUT / "consumers"
    for row in closure["files"]:
        repository, relative = row["path"].split("/", 1)
        owner_repo = {"smallestlie": "taipei49314/smallestlie", "corpus": "taipei49314/checkwash-corpus"}[repository]
        path = destination / row["path"]
        require(path.resolve().is_relative_to(destination.resolve()), "consumer path escapes closure")
        download(f"https://raw.githubusercontent.com/{owner_repo}/{closure['commits'][repository]}/{relative}", path, row["bytes"])
        raw = path.read_bytes()
        require(len(raw) == row["bytes"] and cap.digest(path) == row["sha256"]
                and hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == row["git_blob"],
                "immutable consumer source mismatch")
    require({p.relative_to(destination).as_posix() for p in destination.rglob("*") if p.is_file()}
            == {row["path"] for row in closure["files"]}, "materialized consumer file set differs")
    return destination


def package_files(directory):
    return {p.relative_to(directory).as_posix(): cap.digest(p) for p in sorted(directory.rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts and p.suffix not in {".pyc", ".pyo"}}


def build():
    dist = OUT / "candidate"
    dist.mkdir()
    builder = PRIVATE / "builder"
    wheel_runtime = PRIVATE / "wheel-runtime"
    probe_runtime = PRIVATE / "probe-runtime"
    for runtime in (builder, wheel_runtime, probe_runtime):
        launch([sys.executable, "-I", "-m", "venv", str(runtime)], PRIVATE, label="venv")
    build_python, wheel_python, probe_python = [str(p / "bin/python") for p in (builder, wheel_runtime, probe_runtime)]
    launch([build_python, "-I", "-m", "pip", "--isolated", "install", "--no-input", "--no-cache-dir",
            "--index-url", "https://pypi.org/simple", "--report", str(OUT / "build-install.json"), "build", "hatchling"],
           PRIVATE, label="build-install")
    launch([build_python, "-I", "-m", "pip", "freeze", "--all"], PRIVATE, label="build-freeze")
    launch([build_python, "-I", "-m", "build", str(ROOT), "--wheel", "--sdist", "--no-isolation", "--outdir", str(dist)],
           PRIVATE, label="build", timeout=300)
    wheels, sdists = list(dist.glob("*.whl")), list(dist.glob("*.tar.gz"))
    require(len(wheels) == len(sdists) == 1, "exactly one wheel and sdist required")
    pyz = dist / "checkwash.pyz"
    launch([sys.executable, "-I", "-B", "-m", "zipapp", str(ROOT / "src"), "-m", "checkwash.zipapp_entry:run",
            "-o", str(pyz), "-c"], PRIVATE, label="zipapp")
    launch([wheel_python, "-I", "-m", "pip", "--isolated", "install", "--no-deps", "--no-compile",
            "--report", str(OUT / "wheel-install.json"), str(wheels[0])], PRIVATE, label="wheel-install")
    launch([wheel_python, "-I", "-m", "pip", "freeze", "--all"], PRIVATE, label="wheel-freeze")
    dependency = OUT / "dependencies"
    dependency.mkdir()
    launch([probe_python, "-I", "-m", "pip", "--isolated", "download", "--no-deps", "--only-binary=:all:",
            "--index-url", "https://pypi.org/simple", "--dest", str(dependency), "PyYAML==6.0.2"], PRIVATE, label="yaml-download")
    yaml_wheels = list(dependency.glob("*.whl"))
    require(len(yaml_wheels) == 1, "one exact PyYAML wheel required")
    launch([probe_python, "-I", "-m", "pip", "--isolated", "install", "--no-index", "--no-deps", "--no-compile",
            "--report", str(OUT / "probe-install.json"), str(yaml_wheels[0])], PRIVATE, label="probe-install")
    launch([probe_python, "-I", "-m", "pip", "freeze", "--all"], PRIVATE, label="probe-freeze")
    proofs = {}
    for kind in ("source", "wheel", "pyz"):
        proof, inventory = dist / (kind + "-qualification.json"), dist / (kind + "-inventory.json")
        artifacts = [] if kind == "source" else [wheels[0], sdists[0]] if kind == "wheel" else [pyz]
        argv = [sys.executable, "-I", "-B", str(HERE / "qualify_assertions.py"), "--source-root", str(ROOT),
                "--distribution", kind, "--output", str(proof)]
        if artifacts:
            argv += ["--artifact", str(artifacts[0])]
        if kind == "wheel":
            argv += ["--", wheel_python, "-I", "-m", "checkwash"]
        launch(argv, PRIVATE, label="qualify-" + kind, timeout=600 if kind == "pyz" else 300)
        argv = [sys.executable, "-I", "-B", str(HERE / "release_inventory.py"), "--source-root", str(ROOT),
                "--distribution", kind, "--qualification", str(proof), "--output", str(inventory)]
        for artifact in artifacts:
            argv += ["--artifact", str(artifact)]
        launch(argv, PRIVATE, label="inventory-" + kind, timeout=300)
        q, inv = read(proof), read(inventory)
        require(q["status"] == inv["status"] == "passed"
                and q["source_commit"] == inv["source_commit"] == ledger["source"]["head"]
                and inv["source_tree"] == ledger["source"]["tree"]
                and inv["builder_source_commit"] == ledger["source"]["head"], "artifact/source qualification differs")
        proofs[kind] = dict(qualification=ref(proof), inventory=ref(inventory),
                            suite=q["suite_sha256"], package=q["source_package_sha256"])
    require(len({v["suite"] for v in proofs.values()}) == len({v["package"] for v in proofs.values()}) == 1,
            "candidate qualification suites/package bytes differ")
    installed = list((wheel_runtime / "lib").glob("python*/site-packages/checkwash"))
    require(len(installed) == 1 and package_files(installed[0]) == package_files(ROOT / "src/checkwash"),
            "qualified wheel installation bytes differ from exact source")
    published = OUT / "published" / "checkwash.pyz"
    download("https://github.com/taipei49314/checkwash/releases/download/v0.6.0/checkwash.pyz", published, 20_000_000)
    require(cap.digest(published) == PIN, "original published pin hash differs")
    bootstrap = "import sys; sys.path.insert(0, " + repr(str(ROOT / "src")) + "); from checkwash.cli import main; raise SystemExit(main())"
    commands = {"source": [sys.executable, "-I", "-B", "-c", bootstrap],
                "wheel": [wheel_python, "-B", "-I", "-m", "checkwash"],
                "pyz": [sys.executable, "-B", "-I", str(pyz)],
                "published-pyz": [sys.executable, "-B", "-I", str(published)]}
    ledger["artifacts"] = dict(candidate=ref(pyz), wheel=ref(wheels[0]), sdist=ref(sdists[0]),
                               published=ref(published), published_source=PIN_SOURCE,
                               proofs=proofs, yaml=ref(yaml_wheels[0]), commands=commands,
                               installed_wheel=dict(path=str(installed[0]), files=package_files(installed[0])))
    save(OUT / "ledger.json", ledger)
    return commands, probe_python


def owned_repo():
    specification = read(INPUT)
    extractor = specification["extractor"]
    raw = git(ROOT, "show", extractor["commit"] + ":" + extractor["path"])
    require(hashlib.sha256(raw).hexdigest() == extractor["sha256"]
            and hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == extractor["git_blob"],
            "original invoice extractor source differs")
    require(set(specification["before"]) == set(specification["after"])
            == {"billing.py", "tests/test_billing.py", "OWNED-COMPATIBILITY.txt"}, "owned path denominator differs")
    for side in ("before", "after"):
        for name, text in specification[side].items():
            original = text.encode("utf-8")
            require(specification["hashes"][side][name] == dict(bytes=len(original), sha256=hashlib.sha256(original).hexdigest()),
                    "copied owned input byte manifest differs")
    repo = PRIVATE / "subject"
    repo.mkdir()
    git(repo, "init", "--object-format=sha1", "-b", "main")
    for key, value in (("user.name", "Owned downstream compatibility"), ("user.email", "compatibility@example.invalid"),
                       ("commit.gpgsign", "false"), ("core.autocrlf", "false")):
        git(repo, "config", key, value)
    refs, trees = {}, {}
    for side in ("before", "after"):
        for name, text in specification[side].items():
            path = repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))
        git(repo, "add", "--all")
        git(repo, "commit", "-m", "owned " + side,
            extra={"GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z"})
        refs[side] = text_git(repo, "rev-parse", "HEAD")
        require(re.fullmatch(r"[0-9a-f]{40}", refs[side]), "full owned ref required")
        trees[side] = text_git(repo, "rev-parse", "HEAD^{tree}")
        require(set(text_git(repo, "ls-tree", "-r", "--name-only", refs[side]).splitlines()) == set(specification[side]),
                "owned policy/file inventory differs")
        for name, text in specification[side].items():
            require(git(repo, "show", refs[side] + ":" + name) == text.encode("utf-8"), "owned committed source differs")
    labels = {}
    for side, oid in refs.items():
        label = text_git(repo, "rev-parse", "--short", oid)
        require(re.fullmatch(r"[0-9a-f]{4,40}", label)
                and text_git(repo, "rev-parse", "--verify", "--end-of-options", label + "^{commit}") == oid,
                "owned report label does not resolve to exact full ref")
        labels[side] = label
    (OUT / "owned.diff").write_bytes(git(repo, "diff", "--binary", refs["before"], refs["after"]))
    ledger["owned"] = dict(repo=str(repo), full_refs=refs, report_labels=labels, trees=trees, input=ref(INPUT_COPY))
    for case in ("clean", "weakened"):
        save(OUT / (case + "-fixture.json"), dict(before=specification["before"],
             after=specification["before" if case == "clean" else "after"], modules=["billing"]))
    return repo, refs, labels


def differences(left, right, path=""):
    if type(left) is not type(right):
        return [dict(path=path, published=left, candidate=right)]
    if isinstance(left, dict):
        rows = []
        for key in sorted(left.keys() | right.keys()):
            if key not in left or key not in right:
                rows.append(dict(path=path + "/" + key, published=left.get(key), candidate=right.get(key), missing=True))
            else:
                rows.extend(differences(left[key], right[key], path + "/" + key))
        return rows
    if isinstance(left, list):
        if len(left) != len(right):
            return [dict(path=path, published=left, candidate=right)]
        return [row for i, pair in enumerate(zip(left, right))
                for row in differences(pair[0], pair[1], path + "/" + str(i))]
    return [] if left == right else [dict(path=path, published=left, candidate=right)]


def execute_cells(commands, probe_python, consumer_root, repo, refs, labels):
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    require(version != "0.6.0", "candidate and unchanged published version controls must be distinct")
    captures = []
    for arm in ARMS:
        for case in CASES:
            key = arm + "/" + case
            head = refs["before" if case == "clean" else "after"]
            base = "MISSING_OWNED_COMPATIBILITY_REF" if case == "invalid-ref" else refs["before"]
            expected = {"clean": 0, "weakened": 1, "invalid-ref": 2}[case]
            argv = commands[arm] + ["check", base + ".." + head, "--format", "json"]
            row = ledger["cli"][key]
            row.update(state="STARTED", argv=argv, cwd=str(repo), full_refs=dict(base=base, head=head))
            save(OUT / "ledger.json", ledger)
            process = launch(argv, repo, label=arm + "-" + case, expected=(expected,), optional=True, track=row)
            row.update(state="COMPLETE" if process["ok"] else "FAILED", process=process)
            capture = dict(id=key, expected_exit=expected, expected_version="0.6.0" if arm == "published-pyz" else version,
                           base=labels["before"], head=labels["before" if case == "clean" else "after"],
                           argv=argv, cwd=str(repo), **{k: process[k] for k in ("observation", "stdout", "stderr")})
            captures.append(capture)
            save(OUT / "ledger.json", ledger)
            require(not text_git(repo, "status", "--porcelain"), "CLI modified owned source")
    require(len(captures) == 12, "CLI denominator differs")
    request = dict(binding=ledger["binding"], published_pyz=ledger["artifacts"]["published"],
                   candidate_pyz=ledger["artifacts"]["candidate"], captures=captures)
    requests = {"smallestlie": request}
    for arm in ("published-pyz", "pyz"):
        requests["corpus-" + arm] = dict(binding=ledger["binding"],
            pyz=ledger["artifacts"]["published" if arm == "published-pyz" else "candidate"],
            expected_version="0.6.0" if arm == "published-pyz" else version,
            cases=[dict(id=case, fixture=ref(OUT / (case + "-fixture.json")),
                        cli=next(c for c in captures if c["id"] == arm + "/" + case)) for case in ("clean", "weakened")])
    for name, request in requests.items():
        path, result = OUT / (name + "-request.json"), OUT / (name + "-result.json")
        save(path, request)
        ledger["probes"][name].update(state="STARTED", request=ref(path))
        save(OUT / "ledger.json", ledger)
        record = launch([probe_python, "-I", "-B", "-X", "utf8", str(PROBE),
                         "smallestlie" if name == "smallestlie" else "corpus", "--consumers", str(consumer_root),
                         "--closure", str(CLOSURE), "--inputs", str(OUT), "--request", str(path), "--output", str(result)],
                        PRIVATE, label=name, optional=True, track=ledger["probes"][name])
        complete = record["ok"] and result.is_file() and read(result).get("status") == "PASSED"
        ledger["probes"][name].update(state="COMPLETE" if complete else "FAILED", process=record,
                                     result=ref(result) if result.is_file() else None)
        save(OUT / "ledger.json", ledger)
    comparisons = {}
    for case in CASES:
        raw = {arm: (OUT / next(c["stdout"]["path"] for c in captures if c["id"] == arm + "/" + case)).read_bytes()
               for arm in ARMS}
        row = dict(candidate_bytes_equal=raw["source"] == raw["wheel"] == raw["pyz"])
        if case != "invalid-ref":
            row["published_candidate_differences"] = differences(json.loads(raw["published-pyz"]), json.loads(raw["pyz"]))
            row["needs_disposition"] = any(d["path"] != "/run/checkwash_version" for d in row["published_candidate_differences"])
        else:
            row.update(invalid_ref_stdout_empty=all(not value for value in raw.values()),
                       published_candidate_differences="ERROR_STREAMS_RETAINED_NOT_ORDINARY_JSON")
        comparisons[case] = row
    save(OUT / "comparisons.json", comparisons)
    require(all(row["candidate_bytes_equal"] and not row.get("needs_disposition", False)
                and row.get("invalid_ref_stdout_empty", True) for row in comparisons.values()),
            "distribution mismatch or cross-version finding/metadata change needs disposition")
    require(all(row["state"] == "COMPLETE" for row in ledger["cli"].values())
            and all(row["state"] == "COMPLETE" for row in ledger["probes"].values()), "CLI or consumer cell failed")


INPUT_COPY = OUT / "owned-input.json"


def main():
    OUT.mkdir()
    PRIVATE.mkdir()
    for name in ("home", "tmp"):
        (PRIVATE / name).mkdir()
    ledger.update(status="INCOMPLETE", purpose="BOUNDED_CONSUMER_COMPATIBILITY_NOT_ADOPTION",
                  cli={a + "/" + c: dict(state="NOT_ATTEMPTED") for a in ARMS for c in CASES},
                  probes={name: dict(state="NOT_ATTEMPTED") for name in ("smallestlie", "corpus-published-pyz", "corpus-pyz")},
                  errors=[], cleanup_safe=True)
    save(OUT / "ledger.json", ledger)
    try:
        require(os.environ["GITHUB_EVENT_NAME"] == "pull_request" and sys.version_info[:2] == (3, 12)
                and sys.platform == "linux", "ordinary Ubuntu/Python3.12 PR required")
        ledger["binding"] = dict(run_id=os.environ["GITHUB_RUN_ID"], attempt=os.environ["GITHUB_RUN_ATTEMPT"],
             candidate_sha=os.environ["GITHUB_SHA"], pr_head_sha=os.environ["PR_HEAD_SHA"], pr_base_sha=os.environ["PR_BASE_SHA"])
        require(all(re.fullmatch(r"[0-9a-f]{40}", ledger["binding"][key])
                    for key in ("candidate_sha", "pr_head_sha", "pr_base_sha")), "exact source SHAs required")
        ledger["python"] = dict(executable=sys.executable, realpath=str(Path(sys.executable).resolve()), version=sys.version)
        ledger["source"] = source_identity()
        INPUT_COPY.write_bytes(INPUT.read_bytes())
        (OUT / "dependency-closure.json").write_bytes(CLOSURE.read_bytes())
        consumer_root = consumers()
        commands, probe_python = build()
        repo, refs, labels = owned_repo()
        execute_cells(commands, probe_python, consumer_root, repo, refs, labels)
        ledger["status"] = "PASSED_BOUNDED_CONTRACTS_NOT_ADOPTION"
    except BaseException:
        ledger["errors"].append(traceback.format_exc())
    finally:
        # Source/artifact final readback still occurs after completed failures.
        # An uncertain child cleanup or expired deadline permits no new process.
        try:
            if "source" in ledger and ledger["cleanup_safe"] and time.monotonic() < DEADLINE:
                require(source_identity() == ledger["source"], "source/tool identity changed during job")
                ledger["final_source_identity"] = "UNCHANGED"
            else:
                ledger["final_source_identity"] = "INCOMPLETE_NO_NEW_CHILD_ALLOWED"
                ledger["status"] = "INCOMPLETE"
            if "consumer_root" in locals():
                for row in read(CLOSURE)["files"]:
                    require(cap.digest(consumer_root / row["path"]) == row["sha256"], "consumer source changed")
                require({p.relative_to(consumer_root).as_posix() for p in consumer_root.rglob("*") if p.is_file()}
                        == {r["path"] for r in read(CLOSURE)["files"]}, "consumer file set changed")
            if "artifacts" in ledger:
                for name in ("candidate", "wheel", "sdist", "published", "yaml"):
                    row = ledger["artifacts"][name]
                    require(cap.digest(OUT / row["path"]) == row["sha256"], "artifact changed")
                installed = ledger["artifacts"]["installed_wheel"]
                require(package_files(Path(installed["path"])) == installed["files"], "installed wheel changed")
                for proof in ledger["artifacts"]["proofs"].values():
                    for name in ("qualification", "inventory"):
                        require(cap.digest(OUT / proof[name]["path"]) == proof[name]["sha256"], "qualification evidence changed")
        except BaseException:
            ledger["status"] = "INCOMPLETE"
            ledger["errors"].append(traceback.format_exc())
        save(OUT / "ledger.json", ledger)
        save(OUT / "evidence-files.json", {p.relative_to(OUT).as_posix(): cap.digest(p)
             for p in sorted(OUT.rglob("*")) if p.is_file() and p.name != "evidence-files.json"})
    return 0 if ledger["status"] == "PASSED_BOUNDED_CONTRACTS_NOT_ADOPTION" else 1


if __name__ == "__main__":
    raise SystemExit(main())
