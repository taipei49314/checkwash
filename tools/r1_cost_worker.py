"""One ordinary-PR scheduling group, preserving the old logical shard identities."""
import os
from pathlib import Path
import shutil
import sys
import time

import r1_cost_capture as cap
import r1_cost_contract as c


def verify_artifacts(prepared, plan):
    for arm, engine in plan["engines"].items():
        artifact = cap.relative(prepared, engine["artifact_path"])
        c.require(cap.digest(artifact) == engine["artifact_sha256"] and artifact.stat().st_size == engine["artifact_bytes"],
                  "delivered primary artifact differs")
        c.require(set(engine["proofs"]) == {"source", "wheel", "pyz"}, "all three distribution proofs required")
        for kind, proof in engine["proofs"].items():
            qpath, ipath = cap.relative(prepared, proof["qualification"]), cap.relative(prepared, proof["inventory"])
            c.require(cap.digest(qpath) == proof["qualification_sha256"] and cap.digest(ipath) == proof["inventory_sha256"],
                      "qualification/inventory receipt changed")
            q, inventory = c.read(qpath), c.read(ipath)
            c.require(q["status"] == inventory["status"] == "passed" and q["distribution"] == inventory["distribution"] == kind
                      and q["source_commit"] == inventory["source_commit"] == engine["source"]["commit"],
                      "artifact qualification source differs")
            c.require(inventory["source_tree"] == engine["source"]["tree"]
                      and inventory["builder_source_commit"] == plan["identity"]["candidate"]
                      and inventory["run_id"] == plan["identity"]["run_id"]
                      and inventory["attempt"] == plan["identity"]["attempt"], "inventory source/run/builder differs")
            c.require(inventory["qualification"] == dict(path=qpath.name, sha256=proof["qualification_sha256"])
                      and q["suite_sha256"] == proof["suite_sha256"]
                      and q["source_package_sha256"] == proof["package_sha256"]
                      and q["source_package_dirty"] is False and not q["errors"] and not inventory["errors"],
                      "distribution proof input/qualification binding differs")
            c.require(len(inventory["artifacts"]) == {"source": 0, "wheel": 2, "pyz": 1}[kind], "artifact set incomplete")
            for delivered in inventory["artifacts"]:
                c.require(Path(delivered["name"]).name == delivered["name"], "artifact filename is not a basename")
                path = cap.relative(prepared, "arms/" + arm + "/artifacts/" + delivered["name"])
                c.require(path.stat().st_size == delivered["bytes"] and cap.digest(path) == delivered["sha256"], "delivered qualified archive differs")
            if kind != "source":
                c.require(sum(item["sha256"] == q["artifact_sha256"] for item in inventory["artifacts"]) == 1,
                          "qualified distribution archive absent or duplicated")
            if kind == "pyz":
                c.require(q["artifact_sha256"] == engine["artifact_sha256"] == inventory["artifacts"][0]["sha256"], "qualified primary differs")
        c.require(len({proof["suite_sha256"] for proof in engine["proofs"].values()}) == 1
                  and len({proof["package_sha256"] for proof in engine["proofs"].values()}) == 1,
                  "distribution proof suites or package differ")


def worker(output, prepared, name):
    entered = time.monotonic()
    plan = c.read(prepared / "run-manifest.json")
    c.require(cap.digest(prepared / "run-manifest.json") == os.environ["R1_MANIFEST_SHA256"], "run manifest digest differs")
    members, shards, groups = c.validate_plan(plan)
    group = next(row for row in groups if row["name"] == name)
    records = [row for row in c.expected_rows(members, shards, groups) if row["group"] == name]
    ledger = dict(identity=plan["identity"], manifest_sha256=cap.digest(prepared / "run-manifest.json"),
                  group=group, records=records, labels={}, setup_complete=False, capture_complete=False,
                  facts=c.facts(), interpreter=sys.executable, prepared_root=str(prepared.resolve()),
                  cost_qualification="NOT_ADJUDICATED")
    c.write(output / "result.json", ledger)
    deadline = entered + c.WORKER_SECONDS
    work = output.parent / ("work-" + name)
    work.mkdir()
    repo = work / "corpus.git"
    ledger["repository_path"] = str(repo.resolve())
    commands = c.Commands(output / "setup", work, c.clean_env(), deadline)
    ledger["git_executable"] = shutil.which("git", path=commands.env["PATH"])
    ledger["resolved_git"] = str(Path(ledger["git_executable"]).resolve()) if ledger["git_executable"] else None
    selected = [members[n] for n in group["member_ordinals"]]
    c.write(output / "result.json", ledger)
    try:
        verify_artifacts(prepared, plan)
        c.require(c.source(commands, c.ROOT, plan["identity"]["candidate"]) == plan["harness_source"], "worker harness checkout differs")
        commands.run([sys.executable, "-I", "-c", "import locale; assert locale.getpreferredencoding(False).lower().replace('-', '') == 'utf8'"])
        ledger["git_version"] = commands.git(work, "--version").decode().strip()
        commands.git(work, "init", "--bare", str(repo))
        commands.git(repo, "remote", "add", "origin", "https://github.com/" + group["repository"] + ".git")
        ids = sorted({pin for row in selected for pin in (row["commit"], row["parent"])})
        commands.git(repo, "fetch", "--no-tags", "--depth=2", "origin", *ids)
        c.require(not commands.git(repo, "for-each-ref", "refs/replace").strip() and not (repo / "info/grafts").exists(), "unexpected replacement/graft")
        for member in selected:
            proof = {}
            for side, pin in (("base", member["parent"]), ("head", member["commit"])):
                index = len(commands.rows)
                c.require(commands.git(repo, "rev-parse", "--verify", pin + "^{commit}").decode().strip() == pin, "wrong corpus object")
                short_index = len(commands.rows)
                short = commands.git(repo, "rev-parse", "--short", pin).decode().strip()
                resolve_index = len(commands.rows)
                c.require(len(short) >= 7 and pin.startswith(short)
                          and commands.git(repo, "rev-parse", "--verify", short + "^{commit}").decode().strip() == pin,
                          "ambiguous formatter label")
                proof[side] = dict(full=pin, short=short, object_command=index,
                                   short_command=short_index, resolve_command=resolve_index)
            parent_index = len(commands.rows)
            raw_header = commands.git(repo, "cat-file", "commit", member["commit"]).split(b"\n\n", 1)[0]
            parents = [line[7:].decode("ascii") for line in raw_header.splitlines() if line.startswith(b"parent ")]
            c.require(parents == member["parents"], "original full parent mismatch")
            proof["parent_command"] = parent_index
            ledger["labels"][member["commit"]] = proof
            c.write(output / "result.json", ledger)
        ledger["setup_complete"] = True
        c.write(output / "result.json", ledger)
        indexed = {(row["member"]["ordinal"], row["arm"]): row for row in records}
        raw_dir = output / "raw"
        raw_dir.mkdir()
        for member in selected:
            order = c.ARMS if member["ordinal"] % 2 == 0 else tuple(reversed(c.ARMS))
            for order_index, arm in enumerate(order):
                row = indexed[(member["ordinal"], arm)]
                c.require(time.monotonic() < deadline, "worker deadline; no further launch")
                engine = plan["engines"][arm]
                artifact = cap.relative(prepared, engine["artifact_path"])
                c.require(cap.digest(artifact) == engine["artifact_sha256"] and artifact.stat().st_size == engine["artifact_bytes"], "artifact changed before launch")
                c.require(time.monotonic() < deadline, "worker deadline after artifact hash")
                prefix = raw_dir / f"pair-{member['ordinal']:04d}-{arm}"
                argv = [sys.executable, "-I", str(artifact), "check", member["parent"] + ".." + member["commit"],
                        "--repo", str(repo), "--format", "json"]
                row.update(stage="LAUNCH_INTENT", outcome="LAUNCH_UNKNOWN", reason=None, argv=argv,
                           cwd=str(work), raw_prefix=str(prefix.relative_to(output)), order_index=order_index,
                           engine=engine, artifact_read=dict(sha256=cap.digest(artifact), bytes=artifact.stat().st_size),
                           reported_labels={side: ledger["labels"][member["commit"]][side]["short"] for side in ("base", "head")})
                c.write(output / "result.json", ledger)
                row["observation"] = cap.capture(argv, work, commands.env, prefix, c.ENGINE_TIMEOUT, c.STREAM_LIMIT, deadline)
                row["stage"] = "OBSERVED"
                payload = None
                try:
                    payload = cap.decode(prefix.with_suffix(".stdout").read_bytes())
                except (ValueError, UnicodeError) as error:
                    row["parse_error"] = str(error)
                row["payload"] = {key: value for key, value in payload.items() if key != "findings"} if isinstance(payload, dict) else None
                row["finding_count"] = len(payload["findings"]) if isinstance(payload, dict) and isinstance(payload.get("findings"), list) else None
                row["outcome"] = cap.classify(row["observation"], payload, member, engine, row["reported_labels"])
                c.write(output / "result.json", ledger)
                c.require(row["observation"]["cleanup_complete"], "uncertain tree cleanup; stop this worker")
        ledger["capture_complete"] = all(row["observation"] and row["observation"]["capture_complete"] for row in records)
        c.write(output / "result.json", ledger)
        return 0 if ledger["capture_complete"] else 3
    except Exception as error:
        ledger["worker_error"] = repr(error)
        for row in records:
            if row["outcome"] == "NOT_ATTEMPTED":
                row.update(reason=repr(error), stage="STOPPED_BEFORE_LAUNCH")
        c.write(output / "result.json", ledger)
        return 3
