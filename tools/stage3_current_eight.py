"""Candidate-only adapter for original eight-input primitives; blocked draft."""
import hashlib
import json
import os
import platform
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
WORKSPACE = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
OUT = WORKSPACE / "stage3-current-eight-evidence"
CATALOG = TOOLS / "stage3_current_eight_catalog.json"
SHA = re.compile(r"[0-9a-f]{40}\Z")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def main():
    catalog = read(CATALOG)
    validating = "--validate" in sys.argv
    OUT.mkdir(exist_ok=True)
    rows = [{"case": case["name"], "arm": "candidate", "kind": kind, "sample": sample,
             "state": "NOT_ATTEMPTED", "reason": "NOT_STARTED", "observation": None, "verdict": None}
            for case in catalog["cases"] for kind, count in (("native", 3), ("diagnostic", 1))
            for sample in range(count)]
    report = {"status": "PROMOTION_BLOCKED", "repair_qualification": "NOT_ADJUDICATED",
              "catalog_sha256": digest(CATALOG), "rows": rows, "errors": [], "cases": [],
              "historical_receipts": catalog["historical_receipts"],
              "identity": {"run_id": os.environ["GITHUB_RUN_ID"], "attempt": os.environ["GITHUB_RUN_ATTEMPT"],
                           "candidate": catalog["candidate_sha"], "pr_head": os.environ["PR_HEAD_SHA"],
                           "diagnostic": os.environ["DIAGNOSTIC_SHA"]},
              "facts": {"python": sys.version, "executable": sys.executable, "platform": platform.platform(),
                        "recursion_limit": sys.getrecursionlimit(), "image_os": os.environ.get("ImageOS"),
                        "image_version": os.environ.get("ImageVersion"),
                        "workflow_ref": os.environ["GITHUB_WORKFLOW_REF"],
                        "workflow_sha": os.environ["GITHUB_WORKFLOW_SHA"]},
              "engines": {}, "limits": catalog["limits"]}

    def flush():
        target = "readback-error.json" if validating else "report.json"
        (OUT / target).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if not validating:
        flush()
    if (catalog["status"] != "PROMOTION_FROZEN_READY_FOR_HOSTED_ACQUISITION"
            or not SHA.fullmatch(catalog["candidate_sha"])
            or not SHA.fullmatch(catalog["candidate_package_tree"])
            or os.environ["CANDIDATE_SHA"] != catalog["candidate_sha"]):
        for row in rows:
            row["reason"] = "CANDIDATE_SOURCE_NOT_FROZEN_PROMOTION_BLOCKED"
        flush()
        return 2
    if os.environ.get("GITHUB_EVENT_NAME") != "pull_request" or os.environ["GITHUB_RUN_ATTEMPT"] != "1":
        report["status"] = "EVENT_BLOCKED"
        for row in rows:
            row["reason"] = "NOT_FIRST_AUTOMATIC_PR_ATTEMPT"
        flush()
        return 2
    if "--preflight" in sys.argv:
        report["status"] = "PROMOTION_BOUND_NOT_YET_EXECUTED"
        flush()
        return 0
    # Original trusted tools are byte-checked before importing any primitive.
    try:
        for helper in catalog["original_helpers"]:
            path = ROOT / helper["path"]
            if path.stat().st_size != helper["bytes"] or digest(path) != helper["sha256"]:
                raise ValueError("original helper bytes differ: " + helper["path"])
    except (OSError, ValueError) as error:
        report["status"] = "BLOCKED_IDENTITY"
        report["errors"].append(repr(error))
        for row in rows:
            row["reason"] = "BLOCKED_IDENTITY_NOT_LAUNCHED"
        flush()
        return 2
    sys.path.insert(0, str(TOOLS))
    import standin_cost_capture as original

    cap = original.cap

    def require_identity(condition, message):
        if not condition:
            report["status"] = "BLOCKED_IDENTITY"
        original.require(condition, message)

    def bind_source(commands, root, expected):
        try:
            return original.source(commands, root, expected)
        except Exception:
            report["status"] = "BLOCKED_IDENTITY"
            raise
    if validating:
        try:
            retained = read(OUT / "report.json")
            keys = lambda items: [(row["case"], row["kind"], row["sample"], row["arm"]) for row in items]
            original.require(len(retained["rows"]) == len(set(keys(retained["rows"]))) == 32
                             and keys(retained["rows"]) == keys(rows),
                              "missing/duplicate/substituted retained candidate slots")
            original.require(retained["catalog_sha256"] == digest(CATALOG)
                             and retained["identity"] == report["identity"], "retained source/catalog/run/attempt/PR binding differs")
            original.require(retained["facts"]["executable"] == sys.executable
                             and retained["measurement_environment"] == original.clean_env(),
                             "measurement interpreter/environment differs")
            for key, value in report["facts"].items():
                original.require(retained["facts"][key] == value, "current reader/platform/workflow facts differ: " + key)
            interpreter = Path(sys.executable)
            original.require(retained["facts"]["interpreter"] == {
                "launch": str(interpreter), "resolved": str(interpreter.resolve()),
                "bytes": interpreter.stat().st_size, "sha256": digest(interpreter)}, "interpreter binary differs")
            original.require(retained["diagnostic_source"]["commit"] == report["identity"]["diagnostic"]
                             and retained["diagnostic_files"] == {path: digest(ROOT / path) for path in
                                 ("tools/stage3_current_eight.py", "tools/stage3_current_eight_catalog.json",
                                  ".github/workflows/stage3-current-eight.yml")}, "diagnostic source/files differ")
            original.require(retained["package"]["tree"] == catalog["candidate_package_tree"]
                             and retained["package"]["files"] == catalog["package_files"]
                             and retained["package"]["critical_paths"] == catalog["expected_product_paths"],
                             "retained package identity differs")
            original.require([case["name"] for case in retained["cases"]]
                             == [case["name"] for case in catalog["cases"]], "fixed input names/order differs")
            for case, fixed in zip(retained["cases"], catalog["cases"]):
                original.require(all(case[key] == fixed[key] for key in ("name", "base", "head", "path")),
                                 "retained input full identity differs")
                if case["cohort"] == "OWNED_NOT_HISTORICAL":
                    for side, label in (("before", "base"), ("after", "head")):
                        fact = next(item for item in fixed["sources"] if item["label"] == label)
                        original.require(case["source"][side] == {"bytes": fact["bytes"], "sha256": fact["sha256"]},
                                         "retained owned generator bytes differ")
            for path, fact in read(OUT / "files.json").items():
                file = OUT / path
                original.require(file.resolve().is_relative_to(OUT.resolve()) and file.is_file(), "missing or escaped raw file")
                original.require(file.stat().st_size == fact["bytes"] and digest(file) == fact["sha256"],
                                  "retained artifact bytes differ")
            engine = retained["engines"]["candidate"]
            original.require(set(retained["engines"]) == {"candidate"}
                             and set(engine["proofs"]) == {"source", "pyz"}
                             and engine["source"]["commit"] == catalog["candidate_sha"]
                             and engine["artifact"] == str(OUT / "arms" / "candidate" / "checkwash.pyz"),
                             "candidate source/artifact path differs")
            artifact = Path(engine["artifact"])
            original.require(artifact.stat().st_size == engine["artifact_bytes"]
                             and digest(artifact) == engine["artifact_sha256"], "candidate pyz changed")
            for distribution, proof in engine["proofs"].items():
                original.require(digest(artifact.parent / (distribution + "-qualification.json")) == proof["qualification_sha256"]
                                 and digest(artifact.parent / (distribution + "-inventory.json")) == proof["inventory_sha256"],
                                 "candidate source/pyz qualification bytes differ")
            original.require(set(retained["native_tools"]) == {original.TIME_BINARY, original.PRLIMIT_BINARY},
                             "trusted accounting binary set differs")
            for binary, fact in retained["native_tools"].items():
                path = Path(binary)
                original.require(str(path.resolve()) == fact["resolved"] and path.stat().st_size == fact["bytes"]
                                 and digest(path) == fact["sha256"], "accounting binary changed")
            for row in retained["rows"]:
                observation = row.get("observation")
                if observation is not None:
                    case = next(case for case in retained["cases"] if case["name"] == row["case"])
                    original.require(row["base"] == case["base"] and row["head"] == case["head"]
                                     and row["engine_sha"] == engine["source"]["commit"]
                                     and row["artifact_sha256"] == engine["artifact_sha256"]
                                     and row["run_id"] == retained["identity"]["run_id"]
                                     and row["attempt"] == retained["identity"]["attempt"], "row source/ref/run identity differs")
                    for stream in row["observation"]["streams"].values():
                        path = OUT / stream["path"]
                        original.require(path.name == stream["path"] and path.is_file()
                                         and path.stat().st_size == stream["bytes"] and digest(path) == stream["sha256"],
                                         "raw observation stream differs")
                if (observation or {}).get("spawned"):
                    case = next(case for case in retained["cases"] if case["name"] == row["case"])
                    prefix = original.validate_measurement(row, case, engine, OUT, retained["identity"],
                                                          retained["facts"]["executable"], retained["measurement_environment"], catalog["limits"])
                    payload = (original.envelope(prefix.with_suffix(".stdout").read_bytes(), row["observation"]["exit_code"])
                               if row["observation"]["capture_complete"] and not row.get("capture_limit") else None)
                    original.require(payload == row["stdout_payload"]
                                     and (payload["verdict"] if payload else None) == row["verdict"], "raw native/diagnostic outcome differs")
                    if row["observation"]["capture_complete"] and not row.get("capture_limit"):
                        original.require(row["state"] == ("VERDICT" if payload else "ERROR_OR_NO_VERDICT"),
                                         "native outcome state differs")
                    if row["kind"] == "diagnostic":
                        trace = prefix.with_suffix(".git-trace2.jsonl")
                        original.require(trace.is_file() and trace.stat().st_size < catalog["limits"]["stream_bytes"]
                                         and trace.stat().st_size == row["git_trace_file"]["bytes"]
                                         and digest(trace) == row["git_trace_file"]["sha256"]
                                         and original.has_git_trace(trace.read_bytes()), "diagnostic trace missing/misbound/limited")
                        original.require(original.trace_facts(trace.read_bytes()) == row["diagnostic_git_trace"],
                                         "diagnostic trace summary differs")
                        diagnostic = read(prefix.with_suffix(".diagnostic.json"))
                        original.require(diagnostic == row["diagnostic"] and all(diagnostic[key] == row[key]
                                         for key in ("engine_sha", "artifact_sha256", "run_id", "attempt", "base", "head")),
                                         "full diagnostic receipt/binding differs")
            complete = (retained["status"] == "CAPTURE_COMPLETE" and not retained["errors"]
                        and all(original.complete(row) for row in retained["rows"]))
            cap.write(OUT / "readback.json", {"slots": 32, "capture_complete": complete,
                                             "capture_errors": retained["errors"],
                                             "repair_qualification": "NOT_ADJUDICATED"})
            return 0 if complete else 2
        except Exception as error:
            cap.write(OUT / "readback.json", {"capture_complete": False, "error": repr(error),
                                            "repair_qualification": "NOT_ADJUDICATED"})
            return 2
        finally:
            cap.write(OUT / "files.json", {path.relative_to(OUT).as_posix(): {"bytes": path.stat().st_size, "sha256": digest(path)}
                                          for path in sorted(OUT.rglob("*")) if path.is_file() and path.name != "files.json"})
    deadline = time.monotonic() + catalog["limits"]["total_seconds"]
    try:
        original.require(os.name == "posix" and sys.platform == "linux" and sys.version_info[:2] == (3, 12)
                         and os.environ["GITHUB_RUN_ATTEMPT"] == "1", "first Ubuntu CPython3.12 PR attempt only")
        report["status"] = "INCOMPLETE"
        env = original.clean_env()
        report["measurement_environment"] = env
        interpreter = Path(sys.executable)
        report["facts"]["interpreter"] = {"launch": str(interpreter), "resolved": str(interpreter.resolve()),
                                            "bytes": interpreter.stat().st_size, "sha256": digest(interpreter)}
        report["installation"] = {"route": "ORIGINAL_QUALIFIED_SOURCE_AND_STANDALONE_PYZ_BUILD",
                                    "pip_product_install": False, "historical_arm_install": False}
        commands = original.Commands(OUT / "setup", env, deadline, catalog["limits"])
        diagnostic = bind_source(commands, ROOT, report["identity"]["diagnostic"])
        report["diagnostic_source"] = diagnostic
        report["diagnostic_files"] = {path: digest(ROOT / path) for path in
                                      ("tools/stage3_current_eight.py", "tools/stage3_current_eight_catalog.json",
                                       ".github/workflows/stage3-current-eight.yml")}
        candidate = WORKSPACE / "candidate"
        expected = catalog["candidate_sha"]
        bind_source(commands, candidate, expected)
        package_tree = commands.git(candidate, "rev-parse", expected + ":src/checkwash").decode().strip()
        require_identity(package_tree == catalog["candidate_package_tree"], "frozen package tree differs")
        entries = commands.git(candidate, "ls-tree", "-r", "--name-only", expected, "--", "src/checkwash").decode().splitlines()
        require_identity(len(entries) == catalog["package_files"], "package file count differs")
        changed = commands.git(candidate, "diff", "--name-only", catalog["anchor_source"], expected, "--", "src").decode().splitlines()
        require_identity(sorted(changed) == sorted(catalog["allowed_src_diff_from_anchor"]), "unexpected product source stacking")
        for fact in catalog["expected_product_paths"]:
            file = candidate / fact["path"]
            require_identity(file.stat().st_size == fact["bytes"] and digest(file) == fact["sha256"],
                             "frozen critical after bytes differ")
        report["package"] = {"tree": package_tree, "files": len(entries), "critical_paths": catalog["expected_product_paths"]}
        private = Path(os.environ["RUNNER_TEMP"]) / "stage3-current-eight-private"
        private.mkdir()
        report["git_version"] = commands.git(candidate, "--version").decode().strip()
        report["native_tools"] = {}
        for binary in (original.TIME_BINARY, original.PRLIMIT_BINARY):
            path = Path(binary)
            report["native_tools"][binary] = {"resolved": str(path.resolve()), "bytes": path.stat().st_size, "sha256": digest(path)}
            commands.run([binary, "--version"], private)
        report["engines"]["candidate"] = original.build_arm(commands, candidate, expected,
                                                             diagnostic["commit"], OUT / "arms" / "candidate")
        known_file = TOOLS / "standin_cost_data/known-case-identities.json"
        require_identity(digest(known_file) == catalog["known_identity_sha256"], "known input catalog changed")
        report["cases"] = original.prepare_cases(commands, private, read(known_file)["rows"])
        require_identity(len(report["cases"]) == 8 and {case["name"] for case in report["cases"]}
                         == {case["name"] for case in catalog["cases"]}, "eight original input identities differ")
        for case in report["cases"]:
            fixed = next(item for item in catalog["cases"] if item["name"] == case["name"])
            require_identity(case["base"] == fixed["base"] and case["head"] == fixed["head"], "original input refs differ")
            repo = Path(case["repo"])
            for fact in fixed["sources"]:
                revision = fact["commit"]
                tree = commands.git(repo, "rev-parse", revision + "^{tree}").decode().strip()
                blob = commands.git(repo, "rev-parse", revision + ":" + case["path"]).decode().strip()
                raw = commands.git(repo, "cat-file", "blob", blob)
                require_identity(tree == fact["tree"] and blob == fact["blob"] and len(raw) == fact["bytes"]
                                 and hashlib.sha256(raw).hexdigest() == fact["sha256"], "original input tree/blob/bytes differ")
            for side in ("base", "head"):
                case[side + "_label"] = commands.git(repo, "rev-parse", "--short", case[side]).decode().strip()
        flush()
        for case in report["cases"]:
            commands.git(Path(case["repo"]), "checkout", "--detach", case["head"])
            original.require(not commands.git(Path(case["repo"]), "status", "--porcelain").strip(), "input checkout dirty")
            for row in (row for row in rows if row["case"] == case["name"]):
                if time.monotonic() >= deadline:
                    row["reason"] = "TOTAL_DEADLINE_NOT_LAUNCHED"
                else:
                    original.sample(row, case, report["engines"]["candidate"], OUT, env, deadline,
                                    catalog["limits"], report["identity"], flush, report["native_tools"])
                flush()
        report["status"] = "CAPTURE_COMPLETE" if all(original.complete(row) for row in rows) else "INCOMPLETE"
        return 0 if report["status"] == "CAPTURE_COMPLETE" else 2
    except Exception as error:
        report["errors"].append(repr(error))
        for row in rows:
            if row["state"] == "NOT_ATTEMPTED" and row["reason"] == "NOT_STARTED":
                row["reason"] = "BLOCKED_IDENTITY_NOT_LAUNCHED" if report["status"] == "BLOCKED_IDENTITY" else "CAPTURE_ABORTED_NOT_LAUNCHED"
        return 2
    finally:
        flush()
        cap.write(OUT / "files.json", {path.relative_to(OUT).as_posix(): {"bytes": path.stat().st_size, "sha256": digest(path)}
                                      for path in sorted(OUT.rglob("*")) if path.is_file() and path.name != "files.json"})


if __name__ == "__main__":
    raise SystemExit(main())
