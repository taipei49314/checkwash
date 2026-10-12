"""Independent raw receipt validation and full fixed-denominator accounting."""
import json
import math
import os
from collections import Counter, defaultdict
from pathlib import PurePosixPath

import r1_cost_capture as cap
import standin_seen_cost_contract as c
from standin_seen_cost_worker import verify_artifacts

SEMANTIC_FIELDS = ("rule", "severity", "path", "unit", "before", "after", "fingerprint",
                   "allowlisted", "escalators", "deescalators", "strength_drop", "strength_after",
                   "subject_changed", "shape")


def semantics(finding):
    return {key: {"present": key in finding, "value": finding.get(key)} for key in SEMANTIC_FIELDS}


def finding_delta(left, right):
    a = Counter(c.encoded(semantics(item)) for item in left)
    b = Counter(c.encoded(semantics(item)) for item in right)
    return {"added": [json.loads(item) for item, n in (b - a).items() for _ in range(n)],
                "removed": [json.loads(item) for item, n in (a - b).items() for _ in range(n)]}


def streams(root, prefix, observation, argv, resolved):
    cap.validate_capture(observation)
    path = cap.relative(root, prefix)
    intent = c.read(path.with_suffix(".intent.json"))
    terminal = c.read(path.with_suffix(".observation.json"))
    c.require(terminal == observation and intent["argv"] == argv == observation["argv"], "intent/terminal/argv mismatch")
    c.require(intent["state"] == ("LAUNCHED" if observation["spawned"] else "LAUNCH_INTENT"), "intent launch state mismatch")
    if observation["spawned"]:
        c.require(intent["executable"] == observation["executable"] == resolved, "resolved executable differs")
        c.require(intent["launch_executable"] == argv[0], "original executable launch path differs")
    raw = {}
    for name in ("stdout", "stderr"):
        record = observation["streams"][name]
        c.require(record["path"] == path.with_suffix("." + name).name
                  and intent["streams"][name] == record["path"], "raw stream path differs")
        file = path.with_suffix("." + name)
        raw[name] = file.read_bytes()
        c.require(cap.digest(file) == record["sha256"] and len(raw[name]) == record["bytes"], "raw stream bytes/hash differ")
    return raw


def git_proof(root, ledger, commands, index, suffix):
    c.require(type(index) is int and 0 <= index < len(commands), "Git proof index invalid")
    row = commands[index]
    expected = [ledger["git_executable"], "-c", "core.hooksPath=/dev/null", "-c", "core.autocrlf=false",
                "-C", ledger["repository_path"], *suffix]
    c.require(row["argv"] == expected and row["cwd"] == str(PurePosixPath(ledger["repository_path"]).parent), "Git proof invocation differs")
    observation = row["observation"]
    c.require(observation and observation["capture_complete"] and observation["exit_code"] == 0, "Git proof failed")
    # The original executable may be a symlink; the launch records its resolution.
    raw = streams(root / "setup", row["raw_prefix"], observation, expected, ledger["resolved_git"])
    return raw["stdout"]


def validate_commands(root, commands):
    for index, row in enumerate(commands):
        c.require(row["raw_prefix"] == f"command-{index:04d}" and row["observation"] is not None,
                  "tool command terminal evidence missing/duplicated")
        observation = row["observation"]
        streams(root, row["raw_prefix"], observation, row["argv"], observation["executable"])


def labels_for(root, ledger, member, commands):
    proof = ledger["labels"][member["commit"]]
    labels = {}
    for side, full in (("base", member["parent"]), ("head", member["commit"])):
        item = proof[side]
        c.require(item["full"] == full and isinstance(item["short"], str)
                  and len(item["short"]) >= 7 and full.startswith(item["short"]), "label full binding differs")
        c.require(git_proof(root, ledger, commands, item["object_command"], ["rev-parse", "--verify", full + "^{commit}"]).decode().strip() == full, "full object proof differs")
        c.require(git_proof(root, ledger, commands, item["short_command"], ["rev-parse", "--short", full]).decode().strip() == item["short"], "short label proof differs")
        c.require(git_proof(root, ledger, commands, item["resolve_command"], ["rev-parse", "--verify", item["short"] + "^{commit}"]).decode().strip() == full, "ambiguous short label proof")
        labels[side] = item["short"]
    header = git_proof(root, ledger, commands, proof["parent_command"], ["cat-file", "commit", member["commit"]]).split(b"\n\n", 1)[0]
    c.require([line[7:].decode("ascii") for line in header.splitlines() if line.startswith(b"parent ")] == member["parents"], "frozen parent proof differs")
    return labels


def validate_row(root, ledger, row, expected, plan, commands):
    for key in ("member", "arm", "shard", "group"):
        c.require(row[key] == expected[key], "row identity differs: " + key)
    observation = row.get("observation")
    if observation is None:
        c.require(row["outcome"] in ("NOT_ATTEMPTED", "LAUNCH_UNKNOWN"), "unobserved result invented")
        if row["outcome"] == "NOT_ATTEMPTED":
            c.require(isinstance(row.get("reason"), str) and row["reason"], "nonlaunch reason missing")
        else:
            # A worker-level intent is written before the capture routine's
            # intent. The former can survive interruption before the latter.
            c.require(row.get("stage") == "LAUNCH_INTENT" and isinstance(row.get("argv"), list)
                      and row.get("raw_prefix"), "unknown launch has no durable worker intent")
        return {"outcome": row["outcome"], "reason": row.get("reason"), "observation": None, "payload": None}
    member, arm = row["member"], row["arm"]
    engine = plan["engines"][arm]
    c.require(row["engine"] == engine, "row engine differs")
    artifact = str(PurePosixPath(ledger["prepared_root"]) / engine["artifact_path"])
    argv = [ledger["interpreter"], "-I", artifact, "check", member["parent"] + ".." + member["commit"],
            "--repo", ledger["repository_path"], "--format", "json"]
    c.require(row["argv"] == argv and row["cwd"] == str(PurePosixPath(ledger["repository_path"]).parent), "full CLI argv/cwd differs")
    c.require(row["artifact_read"] == {"sha256": engine["artifact_sha256"], "bytes": engine["artifact_bytes"]}, "prelaunch artifact read differs")
    order = c.ARMS if member["ordinal"] % 2 == 0 else tuple(reversed(c.ARMS))
    c.require(row["order_index"] == order.index(arm), "original ordinal arm order differs")
    labels = labels_for(root, ledger, member, commands)
    c.require(row["reported_labels"] == labels, "reported short labels differ")
    raw = streams(root, row["raw_prefix"], observation, argv, ledger["facts"]["resolved_interpreter"])
    payload = None
    try:
        payload = cap.decode(raw["stdout"])
    except (ValueError, UnicodeError):
        pass
    metadata = {key: value for key, value in payload.items() if key != "findings"} if isinstance(payload, dict) else None
    count = len(payload["findings"]) if isinstance(payload, dict) and isinstance(payload.get("findings"), list) else None
    c.require(row["payload"] == metadata and row["finding_count"] == count, "parsed row differs from raw JSON")
    outcome = cap.classify(observation, payload, member, engine, labels)
    c.require(row["outcome"] == outcome, "classification differs from raw evidence")
    return {"outcome": outcome, "observation": observation, "payload": payload,
                "raw_prefix": str(root / row["raw_prefix"]),
                "stdout_sha256": observation["streams"]["stdout"]["sha256"], "stderr_sha256": observation["streams"]["stderr"]["sha256"]}


def difference(member, before, after):
    def reported(row):
        value = row.get("payload")
        return value if isinstance(value, dict) else {}
    a, b = reported(before), reported(after)
    av, bv = before.get("observation") or {}, after.get("observation") or {}
    changed = (before["outcome"] != after["outcome"] or av.get("exit_code") != bv.get("exit_code")
               or before.get("stdout_sha256") != after.get("stdout_sha256")
               or before.get("stderr_sha256") != after.get("stderr_sha256"))
    if not changed:
        return None
    af, bf = a.get("findings"), b.get("findings")
    delta = (finding_delta(af, bf) if isinstance(af, list) and isinstance(bf, list)
             and all(isinstance(item, dict) for item in af + bf) else None)
    return {"member": member, "before_outcome": before["outcome"], "after_outcome": after["outcome"],
                "before_exit": av.get("exit_code"), "after_exit": bv.get("exit_code"),
                "before_verdict": a.get("verdict"), "after_verdict": b.get("verdict"),
                "before_raw": before.get("raw_prefix"), "after_raw": after.get("raw_prefix"),
                "stdout_changed": before.get("stdout_sha256") != after.get("stdout_sha256"),
                "stderr_changed": before.get("stderr_sha256") != after.get("stderr_sha256"),
                "diagnostics_changed": any(a.get(key) != b.get(key) for key in ("config_errors", "skipped_files")),
                "findings": delta, "disposition": "PENDING_SOURCE_ADJUDICATION"}


def statistics(values):
    values = sorted(values)
    if not values:
        return {"n": 0}
    return {"n": len(values), "min": values[0], "median": values[math.ceil(.5 * len(values)) - 1],
                "p95": values[math.ceil(.95 * len(values)) - 1], "max": values[-1], "total": sum(values)}


def worker_rows(ledger, group, wanted, identity, manifest_hash):
    c.require(ledger["identity"] == identity and ledger["group"] == group
              and ledger["manifest_sha256"] == manifest_hash, "worker source/run/group mismatch")
    rows = ledger["records"]
    keys = [(row["member"]["ordinal"], row["arm"]) for row in rows]
    c.require(len(keys) == len(set(keys)) and set(keys) == set(wanted), "missing/duplicate/unexpected worker rows")
    return rows


def aggregate(output, inputs):
    members, shards, groups = c.cohort()
    expected = c.expected_rows(members, shards, groups)
    results = {(row["member"]["ordinal"], row["arm"]): {"outcome": "MISSING_WORKER", "observation": None, "payload": None} for row in expected}
    errors = []
    prepared = inputs / "standin-seen-cost-prepared-attempt-1"
    plan = None
    try:
        plan = c.read(prepared / "run-manifest.json")
        c.require(cap.digest(prepared / "run-manifest.json") == os.environ["STANDIN_SEEN_MANIFEST_SHA256"], "manifest digest differs")
        c.validate_plan(plan)
        verify_artifacts(prepared, plan)
    except Exception as error:
        errors.append({"stage": "PLAN_OR_BUILD", "error": repr(error)})
        plan = None
    if plan is not None:
        expected_dirs = {"standin-seen-cost-prepared-attempt-1"} | {"standin-seen-cost-" + group["name"] + "-attempt-1" for group in groups}
        unexpected = [path.name for path in inputs.iterdir() if path.is_dir() and path.name not in expected_dirs]
        if unexpected:
            errors.append({"stage": "UNEXPECTED_ARTIFACT", "paths": unexpected})
        for group in groups:
            root = inputs / ("standin-seen-cost-" + group["name"] + "-attempt-1")
            try:
                ledger = c.read(root / "result.json")
                wanted = {(row["member"]["ordinal"], row["arm"]): row for row in expected if row["group"] == group["name"]}
                rows = worker_rows(ledger, group, wanted, plan["identity"], cap.digest(prepared / "run-manifest.json"))
                for key in ("repository_path", "prepared_root", "interpreter", "git_executable", "resolved_git"):
                    path = PurePosixPath(ledger[key])
                    c.require(path.is_absolute() and ".." not in path.parts, "worker path is not absolute/safe")
                c.require(ledger["facts"]["os_name"] == "posix" and ledger["interpreter"] == ledger["facts"]["interpreter"], "worker platform/interpreter mismatch")
                commands = c.read(root / "setup/commands.json") if (root / "setup/commands.json").exists() else []
                validate_commands(root / "setup", commands)
                if ledger.get("worker_error"):
                    errors.append({"group": group["name"], "stage": "WORKER_REPORTED_FAILURE", "error": ledger["worker_error"]})
                observed = [row.get("observation") for row in rows]
                if ledger.get("capture_complete") is not all(item and item.get("capture_complete") for item in observed):
                    errors.append({"group": group["name"], "stage": "WORKER_CAPTURE_CLAIM", "error": "terminal completeness claim differs"})
                for row in rows:
                    key = (row["member"]["ordinal"], row["arm"])
                    try:
                        results[key] = validate_row(root, ledger, row, wanted[key], plan, commands)
                    except Exception as error:
                        results[key] = {"outcome": "QUARANTINED_ROW", "reason": repr(error), "raw_worker": str(root), "observation": None, "payload": None}
                        errors.append({"group": group["name"], "key": key, "error": repr(error)})
            except Exception as error:
                errors.append({"group": group["name"], "stage": "WORKER", "error": repr(error)})
                if root.exists():
                    for row in expected:
                        if row["group"] == group["name"]:
                            results[(row["member"]["ordinal"], row["arm"])] = {
                                "outcome": "QUARANTINED_WORKER", "reason": repr(error), "raw_worker": str(root), "observation": None, "payload": None}
    counts, phase_counts, repo_counts, transitions = defaultdict(Counter), defaultdict(lambda: defaultdict(Counter)), defaultdict(lambda: defaultdict(Counter)), Counter()
    reported_verdicts = Counter()
    attempted, captures, clean_pairs = 0, 0, 0
    elapsed, repo_elapsed, phase_elapsed, paired = defaultdict(list), defaultdict(list), defaultdict(list), []
    differences = []
    with (output / "records.jsonl").open("x", encoding="utf-8") as records, (output / "per-commit-cost.jsonl").open("x", encoding="utf-8") as costs:
        for member in members:
            pair = {arm: results[(member["ordinal"], arm)] for arm in c.ARMS}
            for arm, row in pair.items():
                observation = row.get("observation")
                counts[arm][row["outcome"]] += 1
                repo_counts[member["repository"]][arm][row["outcome"]] += 1
                for phase in member["phases"]:
                    view = "targeted_cotag_only" if phase == "targeted" else phase
                    phase_counts[view][arm][row["outcome"]] += 1
                if observation is not None:
                    attempted += int(observation["spawned"])
                    captures += int(observation["capture_complete"])
                    elapsed[(arm, row["outcome"])].append(observation["elapsed_seconds"])
                    repo_elapsed[(member["repository"], arm, row["outcome"])].append(observation["elapsed_seconds"])
                    for phase in member["phases"]:
                        view = "targeted_cotag_only" if phase == "targeted" else phase
                        phase_elapsed[(view, arm, row["outcome"])].append(observation["elapsed_seconds"])
                # Full findings are already preserved in raw stdout; links and
                # their exact hashes remain here along with the original metadata.
                saved = dict(row)
                if isinstance(saved.get("payload"), dict):
                    saved["payload"] = {key: value for key, value in saved["payload"].items() if key != "findings"}
                records.write(c.encoded(dict(member=member, arm=arm, **saved)) + "\n")
            a, b = pair["base"], pair["candidate"]
            transitions[a["outcome"] + "->" + b["outcome"]] += 1
            if all(isinstance(row.get("payload"), dict) and row["payload"].get("verdict") in ("pass", "block") for row in (a, b)):
                reported_verdicts[a["payload"]["verdict"] + "->" + b["payload"]["verdict"]] += 1
            clean_pairs += int(all(row["outcome"] in ("ANALYZED_PASS", "ANALYZED_BLOCK") for row in (a, b)))
            times = {arm: row["observation"]["elapsed_seconds"] if row.get("observation") else None for arm, row in pair.items()}
            delta = times["candidate"] - times["base"] if all(value is not None for value in times.values()) else None
            if delta is not None:
                paired.append(delta)
            costs.write(c.encoded({"member": member, "outcomes": {arm: row["outcome"] for arm, row in pair.items()}, "seconds": times, "candidate_minus_base": delta}) + "\n")
            changed = difference(member, a, b)
            if changed:
                differences.append(changed)
    with (output / "differences.jsonl").open("x", encoding="utf-8") as handle:
        for row in differences:
            handle.write(c.encoded(row) + "\n")
    complete = attempted == captures == c.EXPECTED_ARMS and not errors
    summary = {"expected_pairs": c.EXPECTED_PAIRS, "expected_arm_rows": c.EXPECTED_ARMS, "accounted_arm_rows": sum(sum(v.values()) for v in counts.values()),
                   "phase_denominators": c.PHASE_VIEWS, "cohort_accounting": c.COHORT_ACCOUNTING,
                   "attempts": attempted, "complete_captures": captures, "execution_complete": complete, "clean_comparable_pairs": clean_pairs,
                   "counts": counts, "phases": phase_counts, "repositories": repo_counts, "outcome_transitions": transitions,
                   "reported_verdict_transitions_including_diagnostics": reported_verdicts,
                   "differences": len(differences), "cost_qualification": "NOT_ADJUDICATED", "errors": errors,
                   "elapsed": [dict(arm=arm, outcome=kind, **statistics(values)) for (arm, kind), values in sorted(elapsed.items())],
                   "repository_elapsed": [dict(repository=repo, arm=arm, outcome=kind, **statistics(values))
                                       for (repo, arm, kind), values in sorted(repo_elapsed.items())],
                   "phase_elapsed": [dict(phase=phase, arm=arm, outcome=kind, **statistics(values))
                                  for (phase, arm, kind), values in sorted(phase_elapsed.items())],
                   "paired_attempt_candidate_minus_base": statistics(paired),
                   "identity": plan["identity"] if plan else None, "manifest_sha256": cap.digest(prepared / "run-manifest.json") if (prepared / "run-manifest.json").exists() else None,
                   "files": {name: cap.digest(output / name) for name in ("records.jsonl", "per-commit-cost.jsonl", "differences.jsonl")},
                   "limitations": ["capture completeness is not engine PASS", "all changed results require source adjudication",
                                "seen standard/D088 union only; 45 overlap members execute once per arm",
                                "targeted_cotag_only is 119 selected members, not the full 1372 targeted view",
                                "original aiohttp142 membership remains UNKNOWN and is not replaced",
                                "median uses nearest-rank lower-middle, not interpolated midpoint",
                                "CLI time includes capture and startup; build/Git setup excluded",
                                "original A readers unchanged; errors are not repaired or removed", "no automatic retry or replacement attempt"]}
    c.write(output / "summary.json", summary)
    return 0 if complete else 3
