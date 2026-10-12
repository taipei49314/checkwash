"""Eight-input Ubuntu #345 capture. No release or full-cohort acceptance."""
import argparse
import json
import math
import os
from pathlib import Path
import platform
import re
import signal
import statistics
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))  # Explicit trusted candidate tools, never target repo.
import owned_process_capture as cap
import standin_cost_cases as owned

DATA = HERE / "standin_cost_data"
SHA = re.compile(r"[0-9a-f]{40}\Z")
IDENTITY_HASH = "9c900570e479493e3553d4206b760a8f8b509076c0d84c69621dc8dfc25fbd7c"
ARMS = ("base", "candidate")
TIME_BINARY = "/usr/bin/time"
PRLIMIT_BINARY = "/usr/bin/prlimit"


def read(path):
    return json.loads(path.read_bytes())


def require(condition, message):
    if not condition:
        raise ValueError(message)


def require_isolated(observation):
    require(observation.get("cleanup_complete") is True,
            "owned process cleanup unproved; stop the entire capture")


def unique_object(items):
    result = {}
    for key, value in items:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def invalid_constant(value):
    raise ValueError("nonfinite JSON constant: " + value)


def envelope(raw, exit_code):
    """A successful capture of an error is not a verdict."""
    if exit_code not in (0, 1):
        return None
    try:
        value = json.loads(raw, object_pairs_hook=unique_object, parse_constant=invalid_constant)
    except (ValueError, UnicodeError):
        return None
    if not isinstance(value, dict):
        return None
    expected = {0: {"pass", "pass_with_warning"}, 1: {"block"}}[exit_code]
    if value.get("verdict") not in expected or not isinstance(value.get("findings"), list):
        return None
    if not isinstance(value.get("run"), dict) or not isinstance(value.get("checkwash_findings_version"), int):
        return None
    if not isinstance(value.get("summary"), dict) or not isinstance(value.get("skipped_files"), list) or not isinstance(value.get("config_errors"), list):
        return None
    if any(not isinstance(f, dict) or f.get("severity") not in ("info", "warn", "high", "critical")
           or not all(isinstance(f.get(key), str) for key in ("rule", "fingerprint", "path")) for f in value["findings"]):
        return None
    return value


def skeleton(names):
    return [dict(case=name, arm=arm, kind=kind, sample=sample,
                 state="NOT_ATTEMPTED", reason="NOT_STARTED", observation=None, verdict=None)
            for name in names for kind, samples in (("native", 3), ("diagnostic", 1))
            for sample in range(samples) for arm in ARMS]


def clean_env():
    env = {name: os.environ[name] for name in ("PATH", "HOME", "TMPDIR", "TEMP", "TMP") if name in os.environ}
    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
    env["PATH"] = os.pathsep.join(str(p) for value in env["PATH"].split(os.pathsep)
        if value and Path(value).is_absolute() for p in (Path(value).resolve(),)
        if not p.is_relative_to(workspace))
    env.update(LC_ALL="C.UTF-8", LANG="C.UTF-8", GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0", GIT_NO_REPLACE_OBJECTS="1",
        GIT_LFS_SKIP_SMUDGE="1", NO_COLOR="1", PYTHONDONTWRITEBYTECODE="1",
        GIT_AUTHOR_NAME="owned stand-in cost", GIT_COMMITTER_NAME="owned stand-in cost",
        GIT_AUTHOR_EMAIL="owned@example.invalid", GIT_COMMITTER_EMAIL="owned@example.invalid",
        GIT_AUTHOR_DATE="2026-10-11T00:00:00Z", GIT_COMMITTER_DATE="2026-10-11T00:00:00Z",
        GREENWASH_TODAY="2026-10-11", CHECKWASH_TODAY="2026-10-11",
        GITHUB_RUN_ID=os.environ["GITHUB_RUN_ID"], GITHUB_RUN_ATTEMPT=os.environ["GITHUB_RUN_ATTEMPT"])
    return env


class Commands:
    def __init__(self, output, env, deadline, config):
        self.output, self.env, self.deadline, self.config = output, env, deadline, config
        self.rows = []
        output.mkdir()

    def run(self, argv, cwd, extra=None):
        prefix = self.output / f"command-{len(self.rows):04d}"
        row = dict(argv=list(map(str, argv)), cwd=str(cwd), observation=None)
        self.rows.append(row)
        cap.write(self.output / "commands.json", self.rows)
        observation = cap.capture(row["argv"], cwd, dict(self.env, **(extra or {})), prefix,
            self.config["setup_command_seconds"], self.config["stream_bytes"], self.deadline)
        row["observation"] = observation
        cap.write(self.output / "commands.json", self.rows)
        require_isolated(observation)
        require(observation["capture_complete"] and observation["exit_code"] == 0,
                "setup command failed; original raw receipt retained: " + prefix.name)
        return prefix.with_suffix(".stdout").read_bytes()

    def git(self, repo, *args):
        return self.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "core.autocrlf=false",
                         "-c", "commit.gpgsign=false", "-C", repo, *args], repo)


def source(commands, root, expected):
    # Retain observed values in commands.json before rejecting dirty/moved refs.
    head = commands.git(root, "rev-parse", "HEAD").decode().strip()
    status = commands.git(root, "status", "--porcelain").decode()
    tree = commands.git(root, "rev-parse", "HEAD^{tree}").decode().strip()
    require(head == expected and not status, "engine source HEAD/cleanliness differs")
    return dict(commit=head, tree=tree, status=status)


def build_arm(commands, root, expected, candidate, output):
    identity = source(commands, root, expected)
    output.mkdir(parents=True)
    artifact = output / "checkwash.pyz"
    commands.run([sys.executable, "-I", "-B", "-m", "zipapp", root / "src",
                  "-m", "checkwash.zipapp_entry:run", "-c", "-o", artifact], output)
    proofs = {}
    for distribution in ("source", "pyz"):
        proof, inventory = output / (distribution + "-qualification.json"), output / (distribution + "-inventory.json")
        argv = [sys.executable, "-I", "-B", HERE / "qualify_assertions.py", "--source-root", root,
                "--distribution", distribution, "--output", proof]
        if distribution == "pyz":
            argv += ["--artifact", artifact]
        extra = dict(ENGINE_SOURCE=expected, CANDIDATE_SOURCE=candidate)
        commands.run(argv, output, extra)
        argv = [sys.executable, "-I", "-B", HERE / "release_inventory.py", "--source-root", root,
                "--distribution", distribution, "--qualification", proof, "--output", inventory]
        if distribution == "pyz":
            argv += ["--artifact", artifact]
        commands.run(argv, output, extra)
        q, inv = read(proof), read(inventory)
        require(q["status"] == inv["status"] == "passed" and q["source_commit"] == inv["source_commit"] == expected
                and inv["source_tree"] == identity["tree"] and inv["builder_source_commit"] == candidate,
                "source/artifact qualification identity differs")
        proofs[distribution] = dict(qualification_sha256=cap.digest(proof), inventory_sha256=cap.digest(inventory),
            suite_sha256=q["suite_sha256"], package_sha256=q["source_package_sha256"])
    require(proofs["source"]["suite_sha256"] == proofs["pyz"]["suite_sha256"]
            and proofs["source"]["package_sha256"] == proofs["pyz"]["package_sha256"], "arm proof inputs differ")
    require(source(commands, root, expected) == identity, "source moved during qualification")
    schema = re.search(r"^FINDINGS_VERSION\s*=\s*(\d+)\s*$", (root / "src/checkwash/__init__.py").read_text(), re.MULTILINE)
    require(schema is not None, "findings schema identity absent")
    return dict(source=identity, artifact=str(artifact), artifact_bytes=artifact.stat().st_size,
                artifact_sha256=cap.digest(artifact), proofs=proofs, untouched_arm_reader=True,
                version=q["version"].removeprefix("checkwash "), findings_version=int(schema.group(1)))


def prepare_cases(commands, private, known):
    cases = []
    for name in owned.NAMES:
        repo = private / name
        repo.mkdir()
        commands.git(repo, "init", "-b", "main")
        for path, raw in owned.COMMON.items():
            file = repo / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(raw)
        target = repo / owned.PATH
        target.parent.mkdir(parents=True)
        before, after = owned.pair(name)
        require(name == owned.SIBLING or len(before) == len(after) == 1_000_000, "mandatory owned byte length differs")
        for label, raw in (("before", before), ("after", after)):
            target.write_bytes(raw)
            commands.git(repo, "add", "--all")
            commands.git(repo, "commit", "-m", label)
            revision = commands.git(repo, "rev-parse", "HEAD").decode().strip()
            stored = commands.git(repo, "cat-file", "blob", revision + ":" + owned.PATH)
            require(stored == raw, "owned source bytes changed on Git storage")
            if label == "before":
                base = revision
            else:
                head = revision
        cases.append(dict(name=name, repo=str(repo), base=base, head=head, path=owned.PATH,
                          source=owned.metadata(name), cohort="OWNED_NOT_HISTORICAL"))
    repo = private / "aiohttp"
    repo.mkdir()
    commands.git(repo, "init", "-b", "main")
    commands.git(repo, "remote", "add", "origin", "https://github.com/aio-libs/aiohttp.git")
    for row in known:
        require(row["repository"] == "aio-libs/aiohttp"
                and SHA.fullmatch(row["parent"]) and SHA.fullmatch(row["commit"]), "unknown real source identity")
        commands.git(repo, "fetch", "--no-tags", "--depth=1", "origin", row["parent"], row["commit"])
        for field in ("parent", "commit"):
            require(commands.git(repo, "rev-parse", row[field] + "^{commit}").decode().strip() == row[field], "target ref differs")
        # Fixed full parent is verified against the commit object, not inferred
        # from a shallow graph walk that may hide its real parent list.
        commit = commands.git(repo, "cat-file", "commit", row["commit"]).decode("utf-8")
        parents = [line[7:] for line in commit.split("\n\n", 1)[0].splitlines() if line.startswith("parent ")]
        require(parents and parents[0] == row["parent"], "fixed first parent differs")
        cases.append(dict(name="aiohttp_" + row["issue_prefix"], repo=str(repo), base=row["parent"],
            head=row["commit"], path="tests/test_client_functional.py", cohort=row["status"]))
    return cases


def parse_usage(path):
    if not path.exists():
        return dict(state="UNKNOWN", reason="GNU time receipt missing")
    raw = path.read_text(encoding="utf-8", errors="replace")
    try:
        memory, user, system, code = raw.splitlines()[-1].split("\t")
        memory, user, system, code = int(memory), float(user), float(system), int(code)
        require(memory >= 0 and all(math.isfinite(value) and value >= 0 for value in (user, system)),
                "invalid GNU time values")
        return dict(state="RECORDED", peak_rss_kib=memory, user_seconds=user,
            system_seconds=system, reported_exit=code, raw=raw,
            scope="GNU time invocation accounting; not stand-in-only or summed Git memory")
    except (IndexError, ValueError):
        return dict(state="UNKNOWN", reason="GNU time receipt malformed", raw=raw)


def trace_facts(raw):
    # Git's documented SID identifies one process instance. A newline or start
    # alone cannot prove shutdown; retain unknown/truncated sessions as such.
    sessions, malformed, protocol_errors = {}, 0, 0
    for line in raw.splitlines():
        try:
            event = json.loads(line, object_pairs_hook=unique_object, parse_constant=invalid_constant)
        except (ValueError, UnicodeError):
            malformed += 1
            continue
        if (not isinstance(event, dict) or not isinstance(event.get("sid"), str)
                or not event["sid"] or not isinstance(event.get("event"), str)):
            malformed += 1
            continue
        state = sessions.setdefault(event["sid"], dict(start=0, exit=0, atexit=0, last=None,
                                                     exit_code=None, exit_time=None))
        kind = event["event"]
        if state["last"] == "atexit" or kind in ("signal", "too_many_files"):
            protocol_errors += 1
        if kind == "start":
            state["start"] += 1
            if (state["start"] != 1 or state["exit"] or not event.get("argv")
                    or not isinstance(event["argv"], list)
                    or not all(isinstance(value, str) for value in event["argv"])):
                protocol_errors += 1
        elif kind in ("exit", "atexit"):
            state[kind] += 1
            elapsed = event.get("t_abs")
            if (state["start"] != 1 or state[kind] != 1 or type(event.get("code")) is not int
                    or type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0):
                protocol_errors += 1
            if kind == "exit":
                state["exit_code"], state["exit_time"] = event.get("code"), elapsed
            elif (state["exit"] != 1 or event.get("code") != state["exit_code"]
                  or type(elapsed) not in (int, float) or type(state["exit_time"]) not in (int, float)
                  or elapsed < state["exit_time"]):
                protocol_errors += 1
        state["last"] = kind
    incomplete = sorted(sid for sid, state in sessions.items()
                        if (state["start"], state["exit"], state["atexit"], state["last"]) != (1, 1, 1, "atexit"))
    return dict(start_events=sum(state["start"] for state in sessions.values()),
                session_count=len(sessions), incomplete_sids=incomplete,
                malformed_lines=malformed, protocol_errors=protocol_errors,
                complete=bool(sessions and not incomplete and not malformed and not protocol_errors and raw.endswith(b"\n")),
                completeness="per observed SID start/exit/final atexit; missing/duplicate/truncated sessions are incomplete",
                scope="extra instrumented CLI only; not primary native samples or metadata parse",
                git_phase_time="UNKNOWN; raw events retained for independent analysis")


def has_git_trace(raw):
    return trace_facts(raw)["complete"]


def complete(row):
    observation = row.get("observation")
    diagnostic = row.get("diagnostic")
    diagnostic_complete = row["kind"] == "native" or (
        isinstance(diagnostic, dict) and diagnostic.get("complete") is True
        and not diagnostic.get("recorder_errors") and len(diagnostic.get("sources", [])) == 2
        and all(source.get("state") != "METADATA_ERROR" for source in diagnostic["sources"]))
    return bool(observation and observation["capture_complete"]
                and observation.get("cleanup_complete") is True
                and not row.get("capture_limit")
                and row.get("usage", {}).get("state") == "RECORDED"
                and row["usage"]["reported_exit"] == observation["exit_code"]
                and (row["kind"] == "native" or row.get("git_trace_observed"))
                and diagnostic_complete)


def summaries(rows, names):
    result = {}
    for name in names:
        entry = {}
        for arm in ARMS:
            selected = sorted((r for r in rows if r["case"] == name and r["arm"] == arm and r["kind"] == "native"), key=lambda r: r["sample"])
            samples = [r["observation"]["elapsed_seconds"] if r["observation"] else None for r in selected]
            entry[arm] = dict(samples_seconds=samples, states=[r["state"] for r in selected],
                median_seconds=statistics.median(samples) if len(selected) == 3 and all(complete(r) for r in selected) else None)
        medians = [entry[arm]["median_seconds"] for arm in ARMS]
        entry["candidate_minus_base_seconds"] = medians[1] - medians[0] if all(x is not None for x in medians) else None
        entry["interpretation"] = "Descriptive native CLI cost including GNU time/capture overhead, no TRACE2/prlimit; outcomes remain separate; no budget acceptance"
        result[name] = entry
    return result


def expected_command(row, case, arm, output, identity, python):
    """One exact argv contract shared by launch and retained-evidence validation."""
    prefix = output / f"{row['case']}-{row['kind']}-{row['sample']}-{row['arm']}"
    artifact = Path(arm["artifact"])
    require(row["kind"] in ("native", "diagnostic"), "unknown invocation kind")
    argv = [python, "-I", "-B", "-X", "utf8", str(artifact), "check", case["base"] + ".." + case["head"],
            "--repo", case["repo"], "--fail-on", "high", "--format", "json"]
    if row["kind"] == "diagnostic":
        argv = [python, "-I", "-B", "-X", "utf8", str(HERE / "standin_cost_diagnostic.py"),
            "--artifact", str(artifact), "--artifact-sha", arm["artifact_sha256"],
            "--engine-sha", arm["source"]["commit"], "--repo", case["repo"],
            "--base", case["base"], "--head", case["head"], "--path", case["path"],
            "--output", str(prefix.with_suffix(".diagnostic.json")), "--run", identity["run_id"], "--attempt", identity["attempt"]]
    usage = prefix.with_suffix(".time.txt")
    trace = prefix.with_suffix(".git-trace2.jsonl")
    timed = [TIME_BINARY, "-f", "%M\t%U\t%S\t%x", "-o", str(usage), "--", *argv]
    additions = {}
    if row["kind"] == "diagnostic":
        timed = [PRLIMIT_BINARY, "--fsize=64000000:64000000", "--", *timed]
        additions["GIT_TRACE2_EVENT"] = str(trace)
    return prefix, timed, additions


def validate_measurement(row, case, arm, output, identity, python, env, config):
    prefix, argv, additions = expected_command(row, case, arm, output, identity, python)
    require(row["raw_prefix"] == prefix.name, "measurement prefix differs")
    require(not any(name.startswith("GIT_TRACE") for name in env), "primary environment contains Git tracing")
    intended = dict(argv=argv, cwd=str(output), environment=dict(env, **additions))
    require(read(prefix.with_suffix(".measurement-intent.json")) == intended, "measurement argv/cwd/environment intent differs")
    observation = read(prefix.with_suffix(".observation.json"))
    require(observation == row["observation"], "raw observation differs")
    require(observation["argv"] == argv, "observed arm/artifact/CLI/ref argv differs")
    require_isolated(observation)
    intent = read(prefix.with_suffix(".intent.json"))
    require(intent["argv"] == argv and intent["state"] == "LAUNCHED"
            and intent["timeout_seconds"] == config["per_child_seconds"]
            and intent["streams"] == {name: prefix.with_suffix("." + name).name for name in ("stdout", "stderr")},
            "raw subprocess launch intent differs")
    require(row["usage"] == parse_usage(prefix.with_suffix(".time.txt")), "raw GNU time usage differs")
    return prefix


def sample(row, case, arm, output, env, deadline, config, identity, flush, tool_facts=None):
    artifact = Path(arm["artifact"])
    require(cap.digest(artifact) == arm["artifact_sha256"], "artifact changed before launch")
    for binary in (TIME_BINARY,) if row["kind"] == "native" else (TIME_BINARY, PRLIMIT_BINARY):
        require(tool_facts is not None and cap.digest(Path(binary)) == tool_facts[binary]["sha256"], "trusted accounting binary changed")
    prefix, timed, additions = expected_command(row, case, arm, output, identity, sys.executable)
    usage, trace = prefix.with_suffix(".time.txt"), prefix.with_suffix(".git-trace2.jsonl")
    require(not any(name.startswith("GIT_TRACE") for name in env), "primary environment contains Git tracing")
    require(not any(path.exists() for path in (usage, trace, prefix.with_suffix(".diagnostic.json"))), "measurement output already exists")
    child_env = dict(env, **additions)
    cap.write(prefix.with_suffix(".measurement-intent.json"), dict(argv=timed, cwd=str(output), environment=child_env))
    row.update(state="LAUNCH_INTENT", reason=None, engine_sha=arm["source"]["commit"], artifact_sha256=arm["artifact_sha256"],
        base=case["base"], head=case["head"], run_id=identity["run_id"], attempt=identity["attempt"],
        raw_prefix=prefix.name, phase="NATIVE_CLI" if row["kind"] == "native" else "INSTRUMENTED_DIAGNOSTIC",
        git_trace="separate diagnostic TRACE2 sidecar under RLIMIT_FSIZE" if row["kind"] == "diagnostic" else "NOT_ENABLED_PRIMARY_NATIVE",
        primary_git_calls="UNKNOWN", primary_git_phase_time="UNKNOWN")
    flush()
    result = cap.capture(timed, output, child_env, prefix,
                         config["per_child_seconds"], config["stream_bytes"], deadline)
    row.update(state="CAPTURED_PENDING_VALIDATION", observation=result)
    flush()
    # Preserve this raw row before aborting the entire schedule. A timeout with
    # confirmed cleanup may continue; unproved isolation must never do so.
    if result.get("cleanup_complete") is not True:
        row.update(state="CAPTURE_FAILED", reason="PROCESS_ISOLATION_UNPROVED_ABORT_ALL")
        flush()
        require_isolated(result)
    payload = envelope(prefix.with_suffix(".stdout").read_bytes(), result["exit_code"]) if result["capture_complete"] else None
    if payload is not None:
        require(payload["run"].get("base") == case["base_label"] and payload["run"].get("head") == case["head_label"], "reported analysis revision labels differ")
        require(payload["run"].get("checkwash_version") == arm["version"]
                and payload["checkwash_findings_version"] == arm["findings_version"], "reported engine/schema identity differs")
    row.update(observation=result, usage=parse_usage(usage), verdict=payload["verdict"] if payload else None,
        state="VERDICT" if payload else "ERROR_OR_NO_VERDICT" if result["capture_complete"] else result["status"],
        stdout_payload=payload)
    if row["kind"] == "diagnostic":
        size = trace.stat().st_size if trace.exists() else None
        limited = size is not None and size >= config["stream_bytes"]
        limited = limited or result["exit_code"] in (-signal.SIGXFSZ, 128 + signal.SIGXFSZ)
        row["capture_limit"] = "TRACE_SIZE_OR_SIGXFSZ" if limited else None
        row["git_trace_file"] = dict(path=trace.name, bytes=size, sha256=cap.digest(trace) if trace.exists() else None)
        row["diagnostic_git_trace"] = trace_facts(trace.read_bytes()) if trace.exists() and not limited else None
        row["git_trace_observed"] = bool(row["diagnostic_git_trace"] and row["diagnostic_git_trace"]["complete"])
        if limited:
            row.update(state="CAPTURE_LIMIT", verdict=None, stdout_payload=None,
                       reason="instrumentation resource cap; do not attribute to engine behavior")
    require(cap.digest(artifact) == arm["artifact_sha256"], "artifact changed during launch")
    if row["kind"] == "diagnostic":
        path = prefix.with_suffix(".diagnostic.json")
        try:
            row["diagnostic"] = read(path) if path.exists() else None
        except (OSError, ValueError) as error:
            row["diagnostic"] = None
            row["diagnostic_receipt_error"] = repr(error)
        if row["diagnostic"] is not None:
            d = row["diagnostic"]
            require(isinstance(d, dict), "diagnostic receipt is not an object")
            require(all(d[key] == row[key] for key in ("engine_sha", "artifact_sha256", "run_id", "attempt", "base", "head")), "diagnostic binding differs")
    return row


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    config = read(DATA / "contract.json")
    known = read(DATA / "known-case-identities.json")["rows"]
    names = [*owned.NAMES, *("aiohttp_" + row["issue_prefix"] for row in known)]
    report = dict(purpose=config["purpose"], status="INCOMPLETE", repair_qualification="NOT_ADJUDICATED",
        rows=skeleton(names), limits=config, identity={}, engines={}, cases=[], errors=[],
        facts=dict(python=sys.version, executable=sys.executable, platform=platform.platform(),
                   recursion_limit=sys.getrecursionlimit()), collection_scope="3 owned + 5 known issue refs; not aio142/466/4271 sweep")
    def flush():
        cap.write(output / "report.json", report)
    flush()
    deadline = time.monotonic() + config["total_seconds"]
    try:
        require(os.name == "posix" and sys.platform == "linux" and sys.version_info[:2] == (3, 12), "Ubuntu Python3.12 only")
        require(os.environ.get("GITHUB_EVENT_NAME") == "pull_request" and os.environ.get("GITHUB_RUN_ATTEMPT") == "1", "first ordinary PR attempt only")
        fixed = config["baseline_sha"]
        require(isinstance(fixed, str) and SHA.fullmatch(fixed), "root must pin final baseline before promotion")
        identity = dict(run_id=os.environ["GITHUB_RUN_ID"], attempt=os.environ["GITHUB_RUN_ATTEMPT"],
            candidate=os.environ["GITHUB_SHA"], pr_head=os.environ["PR_HEAD_SHA"], baseline=os.environ["PR_BASE_SHA"])
        require(identity["baseline"] == fixed and all(SHA.fullmatch(identity[x]) for x in ("candidate", "pr_head", "baseline")), "event source mismatch")
        require(config["native_samples_per_arm"] == 3 and config["diagnostic_samples_per_arm"] == 1
                and config["per_child_seconds"] == 240 and config["setup_command_seconds"] == 900
                and config["total_seconds"] == 3000 and config["stream_bytes"] == 64_000_000,
                "reviewed measurement schedule/bounds differ")
        require(len(known) == 5 and len(set(names)) == 8 and cap.digest(DATA / "known-case-identities.json") == IDENTITY_HASH,
                "fixed known inputs changed")
        report["identity"] = identity
        report["order"] = "native sample 0/1/2: AB/BA/AB on even input ordinal, BA/AB/BA on odd; one diagnostic pair after native samples"
        report["cache_control"] = "No cache flush; same-job alternating process launches, not guaranteed cold starts"
        report["input_metadata_hashes"] = {name: cap.digest(DATA / name) for name in ("contract.json", "known-case-identities.json")}
        report["collector_hashes"] = {name: cap.digest(HERE / name) for name in (
            "standin_cost_capture.py", "standin_cost_diagnostic.py", "standin_cost_cases.py", "owned_process_capture.py",
            "qualify_assertions.py", "release_inventory.py", "assertion_contract.py")}
        env = clean_env()
        report["measurement_environment"] = env
        commands = Commands(output / "setup", env, deadline, config)
        report["git_version"] = commands.git(ROOT, "--version").decode().strip()
        private = output.parent / "standin-cost-private"
        private.mkdir()
        workspace = Path(os.environ["GITHUB_WORKSPACE"])
        require(source(commands, ROOT, identity["candidate"])["tree"] == commands.git(ROOT, "rev-parse", identity["pr_head"] + "^{tree}").decode().strip(),
                "merge/head source trees differ; integration review required")
        report["native_tools"] = {}
        for binary in (TIME_BINARY, PRLIMIT_BINARY):
            path = Path(binary)
            require(path.is_file(), "required accounting binary absent: " + binary)
            report["native_tools"][binary] = dict(resolved=str(path.resolve()), bytes=path.stat().st_size, sha256=cap.digest(path))
            commands.run([binary, "--version"], private)
        for arm in ARMS:
            sha = identity["baseline"] if arm == "base" else identity["candidate"]
            report["engines"][arm] = build_arm(commands, workspace / arm, sha, identity["candidate"], output / "arms" / arm)
            flush()
        report["cases"] = prepare_cases(commands, private, known)
        for case in report["cases"]:
            for side in ("base", "head"):
                case[side + "_label"] = commands.git(Path(case["repo"]), "rev-parse", "--short", case[side]).decode().strip()
        flush()
        for ordinal, case in enumerate(report["cases"]):
            commands.git(Path(case["repo"]), "checkout", "--detach", case["head"])
            require(not commands.git(Path(case["repo"]), "status", "--porcelain").strip(), "target checkout dirty")
            for kind, count in (("native", 3), ("diagnostic", 1)):
                for number in range(count):
                    order = ARMS if (ordinal + number) % 2 == 0 else tuple(reversed(ARMS))
                    for arm in order:
                        row = next(r for r in report["rows"] if (r["case"], r["kind"], r["sample"], r["arm"]) == (case["name"], kind, number, arm))
                        if time.monotonic() >= deadline:
                            row["reason"] = "TOTAL_DEADLINE_NOT_LAUNCHED"
                        else:
                            sample(row, case, report["engines"][arm], output, env, deadline, config, identity, flush, report["native_tools"])
                        flush()
        report["status"] = "CAPTURE_COMPLETE" if all(complete(r) for r in report["rows"]) else "INCOMPLETE"
        # This flag is not a global PASS: owned depth rejection/NOT_REACHED,
        # missing positive stand-in effects and later independent limits remain.
        real = [r for r in report["rows"] if r["case"].startswith("aiohttp_") and r["arm"] == "candidate" and r["kind"] == "native"]
        report["candidate_real_verdicts_complete"] = len(real) == 15 and all(r["state"] == "VERDICT" for r in real)
        report["native_cost_summary"] = summaries(report["rows"], names)
        flush()
        return 0 if report["status"] == "CAPTURE_COMPLETE" else 2
    except Exception as error:
        report["errors"].append(repr(error))
        for row in report["rows"]:
            if row["state"] == "NOT_ATTEMPTED" and row["reason"] == "NOT_STARTED":
                row["reason"] = "CAPTURE_ABORTED_NOT_LAUNCHED"
        flush()
        return 2
    finally:
        entries = {p.relative_to(output).as_posix(): dict(bytes=p.stat().st_size, sha256=cap.digest(p))
                   for p in sorted(output.rglob("*")) if p.is_file() and p.name != "files.json"}
        cap.write(output / "files.json", entries)


def validate(output):
    # Re-read retained bytes in a separate workflow step. This is capture
    # completeness only; ENGINE_ERROR may be completely captured, never PASS.
    report = read(output / "report.json")
    identity = report["identity"]
    require(identity.get("candidate") == os.environ["GITHUB_SHA"]
            and identity.get("run_id") == os.environ["GITHUB_RUN_ID"]
            and identity.get("attempt") == os.environ["GITHUB_RUN_ATTEMPT"], "run/attempt/candidate mismatch")
    config = read(DATA / "contract.json")
    require(identity["baseline"] == config["baseline_sha"] == os.environ["PR_BASE_SHA"]
            and identity["pr_head"] == os.environ["PR_HEAD_SHA"], "base/head identity mismatch")
    require(report["facts"]["executable"] == sys.executable and report["measurement_environment"] == clean_env(),
            "measurement interpreter/environment differs")
    require(report["input_metadata_hashes"] == {name: cap.digest(DATA / name) for name in ("contract.json", "known-case-identities.json")}
            and cap.digest(DATA / "known-case-identities.json") == IDENTITY_HASH, "fixed metadata identity differs")
    require(all(cap.digest(HERE / name) == digest for name, digest in report["collector_hashes"].items()), "collector source differs")
    files = read(output / "files.json")
    for name, facts in files.items():
        path = output / name
        require(path.resolve().is_relative_to(output.resolve()) and path.is_file(), "missing or escaped raw file")
        require(path.stat().st_size == facts["bytes"] and cap.digest(path) == facts["sha256"], "retained bytes changed")
    names = [case["name"] for case in report["cases"]]
    known = read(DATA / "known-case-identities.json")["rows"]
    require(names == [*owned.NAMES, *("aiohttp_" + row["issue_prefix"] for row in known)], "fixed input names/order differs")
    for case, source_row in zip(report["cases"][3:], known):
        require(case["base"] == source_row["parent"] and case["head"] == source_row["commit"], "known case full refs differ")
    for case in report["cases"][:3]:
        require(case["source"] == owned.metadata(case["name"]), "owned generator input bytes differ")
    expected = {(r["case"], r["kind"], r["sample"], r["arm"]) for r in skeleton(names)}
    keys = [(r["case"], r["kind"], r["sample"], r["arm"]) for r in report["rows"]]
    require(len(names) == 8 and len(keys) == 64 and len(set(keys)) == 64 and set(keys) == expected, "missing/duplicate sample")
    require(report["status"] == "CAPTURE_COMPLETE" and all(complete(row) for row in report["rows"]), "incomplete capture")
    for row in report["rows"]:
        arm = report["engines"][row["arm"]]
        case = next(c for c in report["cases"] if c["name"] == row["case"])
        require(row["base"] == case["base"] and row["head"] == case["head"]
                and arm["source"]["commit"] == identity["baseline" if row["arm"] == "base" else "candidate"], "row full source/ref identity differs")
        require(row["run_id"] == identity["run_id"] and row["attempt"] == identity["attempt"]
                and row["engine_sha"] == arm["source"]["commit"] and row["artifact_sha256"] == arm["artifact_sha256"], "row identity differs")
        require(arm["artifact"] == str(output / "arms" / row["arm"] / "checkwash.pyz"), "artifact is not this arm's qualified path")
        for stream in row["observation"]["streams"].values():
            path = output / stream["path"]
            require(path.name == stream["path"] and cap.digest(path) == stream["sha256"]
                    and path.stat().st_size == stream["bytes"], "raw stream differs")
        require(cap.digest(Path(arm["artifact"])) == arm["artifact_sha256"], "arm artifact differs")
        prefix = validate_measurement(row, case, arm, output, identity, report["facts"]["executable"],
                                      report["measurement_environment"], config)
        payload = envelope(prefix.with_suffix(".stdout").read_bytes(), row["observation"]["exit_code"])
        require(payload == row["stdout_payload"] and (payload["verdict"] if payload else None) == row["verdict"], "raw native/diagnostic outcome differs")
        if row["kind"] == "diagnostic":
            trace = prefix.with_suffix(".git-trace2.jsonl")
            require(trace.is_file() and trace.stat().st_size < config["stream_bytes"]
                    and cap.digest(trace) == row["git_trace_file"]["sha256"] and has_git_trace(trace.read_bytes()), "diagnostic trace missing/misbound/limited")
            require(trace_facts(trace.read_bytes()) == row["diagnostic_git_trace"], "diagnostic trace summary differs")
            require(read(prefix.with_suffix(".diagnostic.json")) == row["diagnostic"], "diagnostic receipt differs")
    cap.write(output / "capture-validation.json", dict(status="CAPTURE_COMPLETE",
        repair_qualification="NOT_ADJUDICATED", input_count=8, native_samples=48, diagnostic_samples=16,
        candidate_real_verdicts_complete=report["candidate_real_verdicts_complete"],
        error_or_no_verdict_rows=sum(row["state"] != "VERDICT" for row in report["rows"]), identity=identity))
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("capture", "validate"))
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    return (run if args.mode == "capture" else validate)(args.output.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
