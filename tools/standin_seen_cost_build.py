"""Prepare exact A/B artifacts through existing qualification/inventory tools."""
import os
from pathlib import Path
import re
import sys
import tomllib

import r1_cost_capture as cap
import standin_seen_cost_contract as c


def build(output):
    members, shards, groups = c.cohort()
    # This skeleton survives even an unfixed baseline or subsequent tool failure.
    c.write(output / "expected-rows.json", c.expected_rows(members, shards, groups))
    plan = dict(schema_version=1, purpose="STANDIN_345_SEEN_STANDARD_D088_COST", classification="ALREADY_SEEN_NONBLIND",
                primary_distribution="pyz", today=c.DATE, members_sha256=c.MEMBERS_HASH,
                partitions_sha256=c.PARTITIONS_HASH, expected_pairs=c.EXPECTED_PAIRS, expected_arm_rows=c.EXPECTED_ARMS,
                selection_ordinals_sha256=c.SELECTION_HASH, cohort_accounting=c.COHORT_ACCOUNTING,
                phases=c.PHASE_VIEWS, shards=shards, groups=groups,
                build_complete=False, engines={}, cost_qualification="NOT_ADJUDICATED", facts=c.facts())
    plan.update(limits=c.LIMITS, arm_order="alternate_by_original_ordinal")
    c.write(output / "run-manifest.json", plan)
    plan["identity"] = c.event_identity()
    plan["harness_hashes"] = c.tool_hashes()
    c.write(output / "run-manifest.json", plan)
    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
    private = output.parent / "standin-seen-build-private"
    private.mkdir()
    commands = c.Commands(output / "setup", private, c.clean_env())
    try:
        commands.run([sys.executable, "-I", "-c", "import locale; assert locale.getpreferredencoding(False).lower().replace('-', '') == 'utf8'"])
        plan["git_version"] = commands.git(workspace, "--version").decode().strip()
        candidate = c.source(commands, c.ROOT, plan["identity"]["candidate"])
        head_tree = commands.git(c.ROOT, "rev-parse", plan["identity"]["pr_head"] + "^{tree}").decode().strip()
        c.require(candidate["tree"] == head_tree, "PR merge/head trees differ; integration review required")
        plan["pr_head_tree"] = head_tree
        plan["harness_source"] = candidate
        builder = private / "builder"
        commands.run([sys.executable, "-I", "-m", "venv", str(builder)])
        builder_python = builder / "bin/python"
        commands.run([str(builder_python), "-I", "-m", "pip", "--isolated", "install", "--no-input",
                      "--no-cache-dir", "--index-url", "https://pypi.org/simple", "build", "hatchling"])
        commands.run([str(builder_python), "-I", "-m", "pip", "freeze", "--all"])
        for arm in c.ARMS:
            root = workspace / ("base" if arm == "base" else "candidate")
            sha = plan["identity"]["baseline" if arm == "base" else "candidate"]
            source = c.source(commands, root, sha)
            dest = output / "arms" / arm
            dist = dest / "artifacts"
            dist.mkdir(parents=True)
            arm_env = dict(ENGINE_SOURCE=sha, CANDIDATE_SOURCE=plan["identity"]["candidate"])
            # A and B build from their own untouched checkouts. Network/build
            # dependency versions remain raw evidence, not replay CPU timing.
            commands.run([str(builder_python), "-I", "-m", "build", str(root), "--wheel", "--sdist",
                          "--no-isolation", "--outdir", str(dist)], extra_env=arm_env)
            wheels, sdists = list(dist.glob("*.whl")), list(dist.glob("*.tar.gz"))
            c.require(len(wheels) == len(sdists) == 1, "one wheel and sdist per exact arm required")
            pyz = dist / "checkwash.pyz"
            commands.run([sys.executable, "-I", "-m", "zipapp", str(root / "src"),
                          "-m", "checkwash.zipapp_entry:run", "-o", str(pyz), "-c"])
            runtime = private / (arm + "-wheel-runtime")
            commands.run([sys.executable, "-I", "-m", "venv", str(runtime)])
            runtime_python = runtime / "bin/python"
            commands.run([str(runtime_python), "-I", "-m", "pip", "--isolated", "install", "--no-input",
                          "--no-deps", "--no-compile", str(wheels[0])])
            commands.run([str(runtime_python), "-I", "-m", "pip", "freeze", "--all"])
            proofs = {}
            for kind in ("source", "wheel", "pyz"):
                proof = dest / (kind + "-qualification.json")
                inventory = dest / (kind + "-inventory.json")
                argv = [sys.executable, "-I", str(c.HERE / "qualify_assertions.py"), "--source-root", str(root),
                        "--distribution", kind, "--output", str(proof)]
                artifacts = [] if kind == "source" else [wheels[0], sdists[0]] if kind == "wheel" else [pyz]
                if artifacts:
                    argv += ["--artifact", str(artifacts[0])]
                if kind == "wheel":
                    argv += ["--", str(runtime_python), "-I", "-m", "checkwash"]
                commands.run(argv, extra_env=arm_env)
                argv = [sys.executable, "-I", str(c.HERE / "release_inventory.py"), "--source-root", str(root),
                        "--distribution", kind, "--qualification", str(proof), "--output", str(inventory)]
                for artifact in artifacts:
                    argv += ["--artifact", str(artifact)]
                commands.run(argv, extra_env=arm_env)
                q, inventory_data = c.read(proof), c.read(inventory)
                c.require(q["status"] == inventory_data["status"] == "passed"
                          and q["source_commit"] == inventory_data["source_commit"] == sha
                          and inventory_data["source_tree"] == source["tree"]
                          and inventory_data["builder_source_commit"] == plan["identity"]["candidate"],
                          "qualification/inventory source mismatch")
                proofs[kind] = dict(qualification=str(proof.relative_to(output)), qualification_sha256=cap.digest(proof),
                                    inventory=str(inventory.relative_to(output)), inventory_sha256=cap.digest(inventory),
                                    suite_sha256=q["suite_sha256"], package_sha256=q["source_package_sha256"])
            c.require(len({row["suite_sha256"] for row in proofs.values()}) == 1
                      and len({row["package_sha256"] for row in proofs.values()}) == 1,
                      "arm source/wheel/pyz qualification inputs differ")
            c.require(c.source(commands, root, sha) == source, "source changed during qualification")
            schema = re.search(r"^FINDINGS_VERSION\s*=\s*(\d+)\s*$", (root / "src/checkwash/__init__.py").read_text(), re.MULTILINE)
            c.require(schema is not None, "explicit source findings schema version unavailable")
            plan["engines"][arm] = dict(source=source, version=tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"],
                                       findings_version=int(schema.group(1)), artifact_path=str(pyz.relative_to(output)), artifact_sha256=cap.digest(pyz),
                                       artifact_bytes=pyz.stat().st_size, proofs=proofs,
                                       input_trust="UNMODIFIED_EXACT_SOURCE_NO_READER_SUBSTITUTION")
            c.write(output / "run-manifest.json", plan)
        plan["build_complete"] = True
        c.write(output / "run-manifest.json", plan)
        c.validate_plan(plan)
        # All values are fixed, validated identifiers, never corpus output.
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as handle:
            handle.write("matrix=" + c.encoded(dict(include=[dict(group=row["name"]) for row in groups])) + "\n")
            handle.write("manifest_sha256=" + cap.digest(output / "run-manifest.json") + "\n")
        return 0
    except Exception as error:
        plan["build_error"] = repr(error)
        plan["build_complete"] = False
        c.write(output / "run-manifest.json", plan)
        raise
