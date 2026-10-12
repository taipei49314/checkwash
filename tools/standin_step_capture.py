"""Fixed 18-child exception diagnostic; acquisition is never product PASS."""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
A = "30cfb8bd39aa702aae0d59bde1d1400654137bad"
B = "6bfa81b0201243c98180d8d08c9415ae343f2feb"
ARMS = {
    "base": (A, "47560377419edd2dd8e73b3c077a50e5a396c04a", "531870030a23838b060cd555be7e9af51e8a4688"),
    "candidate": (B, "ddc07009f11c51e6dc0c551204c4d01986c9be2b", "e68274dec826d87405f287fe07a2530f671a98ae"),
}
CONFIG = {"setup_command_seconds": 900, "stream_bytes": 64_000_000}
CHILD_SECONDS, TOTAL_SECONDS = 240, 3000
KINDS = ("native", "original", "extended")
CASES = (
    {"name": "ordinary_1mb", "base": "ba3695d54b75a5214efcbe997959be644775b9ee",
     "head": "0591c6104f26402f868df66710f4b88625baae36", "path": "tests/test_owned_cost.py",
     "before": (1_000_000, "a9104a78ae1865185e22910a725e3bc755e596947cf83ddc16fd63c34fdfc6bc", "9daceced76986d5d39f5193f57f57f51123935fb"),
     "after": (1_000_000, "f366c4d3467920f8a8e0c5c756f6d899abde2786f5a9c90d00b71caafa0937e3", "94659ac03756092ef0b4d4819106cb9e66dcba35")},
    {"name": "aiohttp_bc504dafce", "base": "2a4247b1adba3c9a6b1cb0bd6135f332f8ff2f3a",
     "head": "bc504dafcecad929eeb20cfcab71d2d66df9e28e", "path": "tests/test_client_functional.py",
     "before": (199168, "4dbdd4f80eb704cf126578b6f14201ca23fe717619c03dc09e36c81493c3f531", "a301b6b82cd0171cdfcd1645b759d1a1a1450fdf"),
     "after": (199244, "c557494bdfb1be55f86eb9e3e0ab4e188f2fa0f38a4df1bc346a498e5f3bb044", "d41d1cba2af7c22471e94509ebde9b513368c6da")},
    {"name": "aiohttp_35754d4642", "base": "b381cb4f18e470a53785bb1ef8846bce692df40a",
     "head": "35754d464295aa35f22781f4389d3dd311f2db4e", "path": "tests/test_client_functional.py",
     "before": (189472, "2f9e5b27b9c97302dc9e3fa148000c65f1536892a9f060c78ef43f17cfc0b4e7", "3433226db49675d521d4b481b6d7237876952ecc"),
     "after": (189382, "a7348deaaa55ffac422d146aae8529d04d6adb72afbc0af98be5722be7fac26c", "5006a7453469700e2460797ff0ffac809d7d7da2")},
)
OWN = ("tools/standin_step_capture.py", "tools/standin_step_diagnostic.py", "tools/standin_step_observation.py",
       "tests/test_standin_step_observation.py", "tests/test_standin_step_capture.py",
       ".github/workflows/standin-step-diagnostic.yml")
HELPERS = ("tools/standin_cost_capture.py", "tools/standin_cost_cases.py", "tools/standin_cost_diagnostic.py",
           "tools/owned_process_capture.py", "tools/release_inventory.py", "tools/standin_cost_data/known-case-identities.json")
FRAME = re.compile(r'(?m)^  File "([^"]+)", line ([0-9]+), in ([^\n]+)\n')
# Exact unchanged statements in the reviewed two-hunk derivation. No other
# harness frame, and no product frame, receives a path or line substitution.
HARNESS_MAP = {("measured", 126): 125, ("main", 160): 143}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "trusted helper loader unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(repo, env, *args):
    proc = subprocess.run(["git", "-C", str(repo), *args], env=env, capture_output=True, timeout=120, check=False)
    require(proc.returncode == 0, "immutable source Git read failed: " + repr(args))
    return proc.stdout


def canonical(repo, revision, path, env):
    file = repo / path
    require(file.is_file() and not file.is_symlink(), "nonregular trusted source file")
    raw = git(repo, env, "cat-file", "blob", revision + ":" + path)
    require(file.read_bytes() == raw, "canonical source bytes differ: " + path)
    return {"sha256": sha(raw), "bytes": len(raw),
            "git_blob": git(repo, env, "rev-parse", revision + ":" + path).decode().strip()}


def normalized_exception(value, original_path, extended_path):
    if value is None:
        return None
    result = copy.deepcopy(value)
    def mapped(function, line):
        require((function, line) in HARNESS_MAP, "unreviewed diagnostic harness frame")
        return HARNESS_MAP[function, line]
    for name in ("first_frames", "last_frames"):
        for frame in result[name]:
            if frame["file"] == extended_path:
                frame["line"] = mapped(frame["function"], frame["line"])
                frame["file"] = original_path
    def replace(match):
        path, line, function = match.groups()
        if path != extended_path:
            return match.group(0)
        return f'  File "{original_path}", line {mapped(function, int(line))}, in {function}\n'
    result["traceback"] = FRAME.sub(replace, result["traceback"])
    return result


def diagnostic_core(value, prefix, original_path, extended_path=None):
    """Keep every non-cost field, including the complete formatted traceback."""
    result = copy.deepcopy(value)
    result.pop("diagnostic_cli_seconds")
    result.pop("process_usage")
    result["standin"].pop("elapsed_seconds")
    if extended_path is not None:
        result["standin"].pop("step_observation")
        result["exception"] = normalized_exception(result["exception"], original_path, extended_path)
        if "exception" in result["standin"]:
            result["standin"]["exception"] = normalized_exception(result["standin"]["exception"], original_path, extended_path)
    # Different receipt basenames are explicitly mapped, never product paths.
    for source in result["sources"]:
        source.pop("standalone_parse_count_seconds", None)
        if "raw_source" in source:
            require(source["raw_source"] == prefix + "-" + source["named_side"] + ".source", "source filename differs")
            source["raw_source"] = "DIAGNOSTIC-" + source["named_side"] + ".source"
        for index, command in enumerate(source["commands"]):
            expected = prefix + "-" + source["named_side"] + f".source-git-{index:02d}"
            require(command["raw_prefix"] == expected, "metadata command filename differs")
            command["raw_prefix"] = "DIAGNOSTIC-" + source["named_side"] + f".source-git-{index:02d}"
    return result


def prove_derivation(original, extended):
    old, new = original.read_text().splitlines(), extended.read_text().splitlines()
    require(sha(original.read_bytes()) == "0e113233d76ccb91f42644179b07ce631ea126a6805fb4e56d9084da6c323977",
            "original diagnostic source changed")
    require(sha(extended.read_bytes()) == "abccd5da39564543a0874d0acffad28ad526a3c98c81552d118db415538487b3",
            "extended diagnostic source changed")
    for (_, after), before in HARNESS_MAP.items():
        require(old[before - 1] == new[after - 1], "mapped harness statement is not exact original text")


def compare(original, extended, original_prefix, extended_prefix, original_path, extended_path, streams, exits):
    """Pure-data comparison; callers preserve the raw values before rejecting."""
    require(set(streams) == set(exits) == set(KINDS), "three child identities required")
    require(all(type(code) is int and code in (0, 1, 2) for code in exits.values()), "invalid child exit")
    require(all(set(value) == {"stdout", "stderr"} and all(type(raw) is bytes for raw in value.values())
                for value in streams.values()), "two byte streams required per child")
    left = diagnostic_core(original, original_prefix, original_path)
    right = diagnostic_core(extended, extended_prefix, original_path, extended_path)
    core_equal = left == right
    raw_equal = streams["original"] == streams["extended"]
    stdout_equal = streams["native"]["stdout"] == streams["original"]["stdout"]
    exits_equal = len(set(exits.values())) == 1
    return {"complete_diagnostic_core_equal": core_equal,
            "original_extended_raw_streams_equal": raw_equal,
            "native_original_stdout_equal": stdout_equal,
            "native_original_extended_exits": dict(exits),
            "transparent": core_equal and raw_equal and stdout_equal and exits_equal,
            "native_stderr_comparison": "NOT_EXPECTED_EQUAL_DIAGNOSTIC_CALLS_PRIVATE_CMD_CHECK"}


def checked_source(commands, root, identity, inventory):
    commit, tree, src = identity
    actual = commands.git(root, "rev-parse", "HEAD").decode().strip()
    require(actual == commit and not commands.git(root, "status", "--porcelain", "--untracked-files=all"), "dirty/moved engine")
    require(commands.git(root, "rev-parse", "HEAD^{tree}").decode().strip() == tree
            and commands.git(root, "rev-parse", "HEAD:src").decode().strip() == src, "engine tree differs")
    entries, proof = inventory.source_inventory(commit)
    actual_paths = set()
    for file in (root / "src").rglob("*"):
        require(not file.is_symlink(), "source symlink outside canonical inventory")
        if file.is_file():
            actual_paths.add(file.relative_to(root / "src").as_posix())
    require(actual_paths == set(entries) and len(entries) == 200, "source member set differs")
    return entries, proof


def prepare(commands, scratch, owned):
    repos = {}
    for case in CASES:
        repo = scratch / case["name"]
        repo.mkdir()
        commands.git(repo, "init", "-b", "main")
        if case["name"] == owned.ORDINARY:
            for path, raw in owned.COMMON.items():
                file = repo / path
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(raw)
            target = repo / owned.PATH
            target.parent.mkdir(parents=True)
            for label, raw, revision in zip(("before", "after"), owned.pair(owned.ORDINARY), (case["base"], case["head"]), strict=True):
                target.write_bytes(raw)
                commands.git(repo, "add", "--all")
                commands.git(repo, "commit", "-m", label)
                require(commands.git(repo, "rev-parse", "HEAD").decode().strip() == revision, "original owned commit differs")
        else:
            commands.git(repo, "remote", "add", "origin", "https://github.com/aio-libs/aiohttp.git")
            commands.git(repo, "fetch", "--no-tags", "--depth=1", "origin", case["base"], case["head"])
        header = commands.git(repo, "cat-file", "commit", case["head"]).split(b"\n\n", 1)[0]
        parents = [line[7:].decode("ascii") for line in header.splitlines() if line.startswith(b"parent ")]
        require(parents and parents[0] == case["base"], "fixed first parent differs")
        for side, revision in (("before", case["base"]), ("after", case["head"])):
            size, digest, oid = case[side]
            require(commands.git(repo, "ls-tree", "-z", revision, "--", case["path"])
                    == f"100644 blob {oid}\t{case['path']}\0".encode(), "fixed blob entry differs")
            raw = commands.git(repo, "cat-file", "blob", oid)
            require(len(raw) == size and sha(raw) == digest, "fixed source bytes differ")
        repos[case["name"]] = repo
    return repos


def run(base, candidate, output):
    require(sys.platform == "linux" and sys.version_info[:2] == (3, 12), "Ubuntu Python 3.12 only")
    base, candidate, output = base.resolve(), candidate.resolve(), output.absolute()
    temporary = Path(os.environ["RUNNER_TEMP"]).resolve()
    require(not output.exists() and output.resolve().is_relative_to(temporary), "fresh runner-temp output required")
    require(all(not output.resolve().is_relative_to(root) for root in (ROOT, base, candidate)), "output overlaps checkout")
    output.mkdir(parents=True)
    scratch = output.parent / (output.name + "-scratch")
    scratch.mkdir()
    original_environment = dict(os.environ)
    bootstrap_env = {key: original_environment[key] for key in ("PATH", "HOME")}
    bootstrap_env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0", GIT_NO_REPLACE_OBJECTS="1")
    report = {"purpose": "STANDIN_STEP_EXCEPTION_OBSERVATION_NOT_ACCEPTANCE", "state": "INCOMPLETE",
              "expected_children": 18, "cases": CASES, "source_commits": {name: arm[0] for name, arm in ARMS.items()},
              "helpers": None, "limits": dict(CONFIG, per_child_seconds=CHILD_SECONDS, total_seconds=TOTAL_SECONDS),
              "environment": None, "rows": [{"case": case["name"], "arm": arm, "kind": kind,
              "state": "NOT_ATTEMPTED", "observation": None} for case in CASES for arm in ARMS for kind in KINDS],
              "comparisons": [], "failure": None}
    save(output / "acquisition.json", report)
    try:
        report["helpers"] = {path: canonical(candidate, B, path, bootstrap_env) for path in HELPERS}
        require(git(candidate, bootstrap_env, "rev-parse", "HEAD").decode().strip() == B, "builder is not fixed B")
        # This loads the exact original capture utility, not its scheduler/main.
        original = load(candidate / "tools/standin_cost_capture.py", "step_original_capture")
        cap = original.cap
        env = original.clean_env()
        report["environment"] = env
        run_id, attempt, hosted = (original_environment[key] for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_SHA"))
        require(run_id.isdecimal() and attempt.isdecimal() and re.fullmatch(r"[0-9a-f]{40}", hosted), "invalid run identity")
        event = json.loads(Path(original_environment["GITHUB_EVENT_PATH"]).read_bytes())["pull_request"]
        require(event["base"]["sha"] == A and re.fullmatch(r"[0-9a-f]{40}", event["head"]["sha"]), "diagnostic base differs")
        require(git(ROOT, env, "rev-parse", "HEAD").decode().strip() == hosted, "diagnostic checkout differs")
        header = git(ROOT, env, "cat-file", "commit", hosted).split(b"\n\n", 1)[0]
        parents = [line[7:].decode() for line in header.splitlines() if line.startswith(b"parent ")]
        require(parents == [A, event["head"]["sha"]], "diagnostic merge parent identity differs")
        require(git(ROOT, env, "rev-parse", "HEAD^{tree}") == git(ROOT, env, "rev-parse", event["head"]["sha"] + "^{tree}"), "merge/head tree differs")
        report["hosted"] = {"run_id": run_id, "attempt": attempt, "checkout": hosted, "parents": parents,
            "tree": git(ROOT, env, "rev-parse", "HEAD^{tree}").decode().strip(), "pull_request": event["number"],
            "runtime": {"python": sys.version, "executable": sys.executable},
            "image": {key: original_environment.get(key) for key in ("RUNNER_OS", "RUNNER_ARCH", "ImageOS", "ImageVersion")}}
        report["diagnostic_files"] = {path: canonical(ROOT, hosted, path, env) for path in OWN}
        require(not git(ROOT, env, "status", "--porcelain", "--untracked-files=all"), "dirty diagnostic checkout")
        old_script, new_script = candidate / "tools/standin_cost_diagnostic.py", ROOT / "tools/standin_step_diagnostic.py"
        prove_derivation(old_script, new_script)
        os.environ.clear()
        os.environ.update(env)
        deadline = time.monotonic() + TOTAL_SECONDS
        commands = original.Commands(output / "setup", env, deadline, CONFIG)
        roots, artifacts, inventories = {"base": base, "candidate": candidate}, {}, {}
        report["arms"] = {}
        for arm, identity in ARMS.items():
            root = roots[arm]
            report["arms"][arm] = {"inventory_helper": canonical(root, identity[0], "tools/release_inventory.py", env)}
            inventory = load(root / "tools/release_inventory.py", "step_inventory_" + arm)
            entries, proof = checked_source(commands, root, identity, inventory)
            artifact = output / (arm + ".pyz")
            commands.run([sys.executable, "-I", "-B", "-m", "zipapp", root / "src", "-m", "checkwash.zipapp_entry:run", "-c", "-o", artifact], scratch)
            archive = inventory.archive_inventory(artifact, entries)
            report["arms"][arm].update(source_before=proof, archive=archive, artifact_sha256=cap.digest(artifact), artifact_bytes=artifact.stat().st_size,
                                      qualification="EXACT_SOURCE_AND_ARCHIVE_IDENTITY_ONLY_PRIOR_QUALIFICATION_SEPARATE")
            artifacts[arm], inventories[arm] = artifact, inventory
        repos = prepare(commands, scratch, original.owned)
        cap.write(output / "acquisition.json", report)
        for row in report["rows"]:
            case = next(case for case in CASES if case["name"] == row["case"])
            arm, kind = row["arm"], row["kind"]
            prefix = output / (case["name"] + "-" + arm + "-" + kind)
            artifact = artifacts[arm]
            if kind == "native":
                argv = [sys.executable, "-I", "-B", "-X", "utf8", str(artifact), "check", case["base"] + ".." + case["head"],
                        "--repo", str(repos[case["name"]]), "--fail-on", "high", "--format", "json"]
            else:
                script = old_script if kind == "original" else new_script
                argv = [sys.executable, "-I", "-B", "-X", "utf8", str(script), "--artifact", str(artifact),
                        "--artifact-sha", report["arms"][arm]["artifact_sha256"], "--engine-sha", ARMS[arm][0],
                        "--repo", str(repos[case["name"]]), "--base", case["base"], "--head", case["head"], "--path", case["path"],
                        "--output", str(prefix.with_suffix(".diagnostic.json")), "--run", run_id, "--attempt", attempt]
            row.update(state="STARTED", argv=argv, cwd=str(scratch), raw_prefix=prefix.name)
            cap.write(output / "acquisition.json", report)
            observation = cap.capture(argv, scratch, env, prefix, CHILD_SECONDS, CONFIG["stream_bytes"], deadline)
            row.update(state=observation["status"], observation=observation)
            cap.write(output / "acquisition.json", report)
            require(observation.get("cleanup_complete") is True, "child cleanup unproved; stop before next child")
            require(observation.get("capture_complete") is True, "child capture incomplete; remaining rows NOT_ATTEMPTED")
            require(type(observation["exit_code"]) is int and observation["exit_code"] in (0, 1, 2), "unexpected child exit")
            if kind != "native":
                diagnostic_path = prefix.with_suffix(".diagnostic.json")
                diagnostic = json.loads(diagnostic_path.read_bytes())
                row["diagnostic_sha256"] = cap.digest(diagnostic_path)
                row["diagnostic"] = diagnostic
                require(diagnostic["complete"] is True and not diagnostic["recorder_errors"]
                        and diagnostic["exit_code"] == diagnostic["diagnostic_cli_outcome_exit"] == observation["exit_code"], "diagnostic incomplete/exit mismatch")
                require(diagnostic["engine_sha"] == ARMS[arm][0] and diagnostic["artifact_sha256"] == cap.digest(artifact)
                        and diagnostic["base"] == case["base"] and diagnostic["head"] == case["head"]
                        and diagnostic["run_id"] == run_id and diagnostic["attempt"] == attempt, "diagnostic binding differs")
                if kind == "extended":
                    step = diagnostic["standin"]["step_observation"]
                    state = step["state"]
                    expected = ("STEP_FRAME_OBSERVED", "NO_STEP_FRAME") if diagnostic["standin"]["state"] == "RAISED" else ("NOT_OBSERVED",)
                    require(state in expected, "step observation failed/inconsistent")
                    if state != "NOT_OBSERVED":
                        require(step["source_sha256"] == report["arms"][arm]["source_before"]["checkwash/frontends/python/standin_installations.py"]["sha256"]
                                and step["observer_sha256"] == report["diagnostic_files"]["tools/standin_step_observation.py"]["sha256"], "observation source binding differs")
                    rows = {r["kind"]: r for r in report["rows"] if r["case"] == case["name"] and r["arm"] == arm}
                    old, new = rows["original"], rows["extended"]
                    streams = {key: {stream: (output / (r["raw_prefix"] + "." + stream)).read_bytes()
                                     for stream in ("stdout", "stderr")} for key, r in rows.items()}
                    exits = {key: r["observation"]["exit_code"] for key, r in rows.items()}
                    comparison = compare(old["diagnostic"], new["diagnostic"], old["raw_prefix"] + ".diagnostic",
                                         new["raw_prefix"] + ".diagnostic", str(old_script), str(new_script), streams, exits)
                    report["comparisons"].append({"case": case["name"], "arm": arm, **comparison,
                                                  "step_state": state, "step_counter_observed": state == "STEP_FRAME_OBSERVED"})
                    require(comparison["transparent"], "original/extended transparency differs; raw retained")
            cap.write(output / "acquisition.json", report)
        for arm, identity in ARMS.items():
            entries, proof = checked_source(commands, roots[arm], identity, inventories[arm])
            require(proof == report["arms"][arm]["source_before"], "engine source moved")
            require(inventories[arm].archive_inventory(artifacts[arm], entries) == report["arms"][arm]["archive"]
                    and cap.digest(artifacts[arm]) == report["arms"][arm]["artifact_sha256"], "artifact moved")
            report["arms"][arm]["source_after"] = proof
        require(report["helpers"] == {path: canonical(candidate, B, path, env) for path in HELPERS}, "original helpers moved")
        require(report["diagnostic_files"] == {path: canonical(ROOT, hosted, path, env) for path in OWN}, "diagnostic files moved")
        require(len(report["comparisons"]) == 6 and all(row["state"] == "EXITED" for row in report["rows"]), "18-child accounting incomplete")
        report["state"] = "CAPTURE_COMPLETE_NOT_PRODUCT_PASS"
    except BaseException as error:
        report["failure"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        save(output / "acquisition.json", report)
        files = {path.relative_to(output).as_posix(): {"bytes": path.stat().st_size, "sha256": sha(path.read_bytes())}
                 for path in sorted(output.rglob("*")) if path.is_file() and path.name != "upload-manifest.json"}
        save(output / "upload-manifest.json", files)
        os.environ.clear()
        os.environ.update(original_environment)
    return 0 if report["state"] == "CAPTURE_COMPLETE_NOT_PRODUCT_PASS" else 2


def main():
    parser = argparse.ArgumentParser()
    for key in ("base", "candidate", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    args = parser.parse_args()
    return run(args.base, args.candidate, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
