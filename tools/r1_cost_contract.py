"""Fixed R1 seen-cost contract and CLI; never import an engine or corpus module."""
from __future__ import annotations

from collections import Counter, defaultdict
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sys
import time

# -I excludes the script directory; add only this exact reviewed tools directory.
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import r1_cost_capture as cap

ROOT = HERE.parent
DATA = HERE / "r1_seen_cost_data"
SHA = re.compile(r"[0-9a-f]{40}\Z")
MEMBERS_HASH = "a628d15de4024ecc91e479b532f9c3df2ee86f43542d39dd6c6a71d708780e19"
MEMBERS_BYTES = 1_467_316
MEMBERS_GZIP_HASH = "a61a97a91f923a7909533d2112afca905b874156fba3718669611ec2f1e52b13"
PARTITIONS_HASH = "907095c3c5ebffadcfbf7642d1c40086683f24bbf16e67a012f7724f84890a27"
DATE = "2026-10-11"
ARMS = ("base", "candidate")
ENGINE_TIMEOUT = 240
GIT_TIMEOUT = 900
WORKER_SECONDS = 6600
STREAM_LIMIT = 64_000_000
LIMITS = dict(invocation_seconds=ENGINE_TIMEOUT, git_seconds=GIT_TIMEOUT,
              worker_seconds=WORKER_SECONDS, stream_bytes=STREAM_LIMIT, max_parallel=4)
TOOL_NAMES = ("r1_cost_contract.py", "r1_cost_capture.py", "r1_cost_build.py",
              "r1_cost_worker.py", "r1_cost_aggregate.py", "qualify_assertions.py",
              "release_inventory.py")


def read(path):
    return cap.decode(Path(path).read_bytes())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cap.write(path, value)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def object_hash(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def member_document():
    # Keep the original CRLF receipt byte-identical while keeping its checked-in
    # container below the engine's existing single-blob input limit.
    archive = DATA / "python-pairs.json.gz"
    require(cap.digest(archive) == MEMBERS_GZIP_HASH, "fixed member archive changed")
    with gzip.open(archive, "rb") as stream:
        raw = stream.read(MEMBERS_BYTES + 1)
    require(len(raw) == MEMBERS_BYTES, "fixed member byte count changed")
    require(hashlib.sha256(raw).hexdigest() == MEMBERS_HASH, "fixed members changed")
    return cap.decode(raw)


def cohort():
    require(cap.digest(DATA / "python-partitions.json") == PARTITIONS_HASH, "fixed partitions changed")
    document, partition = member_document(), read(DATA / "python-partitions.json")
    members = document["members"]
    require(document["count"] == len(members) == 4271, "wrong full denominator")
    require(members == sorted(members, key=lambda row: (row["repository"].lower(), row["commit"])), "member order changed")
    keys, phases, grouped = set(), Counter(), defaultdict(list)
    for ordinal, source in enumerate(members):
        row = dict(source, ordinal=ordinal)
        key = (row["repository"], row["commit"])
        require(key not in keys and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", key[0]), "duplicate/invalid repository member")
        require(SHA.fullmatch(key[1]) and SHA.fullmatch(row["parent"]) and row["parents"] == [row["parent"]], "invalid fixed parent")
        require(set(row["phases"]) <= {"standard", "d088", "targeted"}, "unknown phase")
        keys.add(key)
        phases.update(row["phases"])
        grouped[row["repository"]].append(row)
    require(phases == Counter(standard=1800, d088=1263, targeted=1372), "phase denominator changed")
    shards = []
    groups = []
    for repo_index, (repo, rows) in enumerate(sorted(grouped.items(), key=lambda item: item[0].lower())):
        repo_shards = []
        for offset in range(0, len(rows), 10):
            item = dict(name=f"r{repo_index:02d}-{offset // 10:03d}", batch=len(shards) // 64,
                        repository=repo, member_ordinals=[row["ordinal"] for row in rows[offset:offset + 10]])
            shards.append(item)
            repo_shards.append(item)
        for offset in range(0, len(repo_shards), 10):
            selected = repo_shards[offset:offset + 10]
            groups.append(dict(name=f"r{repo_index:02d}-g{offset // 10:02d}", repository=repo,
                               shards=[row["name"] for row in selected],
                               member_ordinals=[n for row in selected for n in row["member_ordinals"]]))
    require(partition == dict(schema_version=1, cohort="python", members_sha256=MEMBERS_HASH,
                              member_count=4271, shard_count=432, batch_count=7, shards=shards), "original logical partition differs")
    require(len(groups) == 48, "hosted grouping changed")
    return [dict(row, ordinal=i) for i, row in enumerate(members)], shards, groups


def expected_rows(members, shards, groups):
    shard_of = {n: shard["name"] for shard in shards for n in shard["member_ordinals"]}
    group_of = {n: group["name"] for group in groups for n in group["member_ordinals"]}
    return [dict(member=member, arm=arm, shard=shard_of[member["ordinal"]], group=group_of[member["ordinal"]],
                 stage="PLANNED", outcome="NOT_ATTEMPTED", reason="NOT_STARTED", observation=None)
            for member in members for arm in ARMS]


def event_identity(env=os.environ):
    require(env.get("GITHUB_EVENT_NAME") == "pull_request", "ordinary PR event required")
    require(env.get("GITHUB_RUN_ATTEMPT") == "1", "automatic rerun is not first observation")
    values = {name: env.get(name, "") for name in ("GITHUB_SHA", "PR_HEAD_SHA", "PR_BASE_SHA")}
    require(all(SHA.fullmatch(value) for value in values.values()), "exact event SHAs required")
    fixed = read(DATA / "contract.json")["baseline_sha"]
    require(isinstance(fixed, str) and SHA.fullmatch(fixed), "final Quality main baseline SHA not fixed")
    require(values["PR_BASE_SHA"] == fixed, "PR base differs from fixed final Quality main")
    require(re.fullmatch(r"[0-9]+", env.get("GITHUB_RUN_ID", "")), "run ID required")
    return dict(run_id=env["GITHUB_RUN_ID"], attempt="1", event="pull_request",
                candidate=values["GITHUB_SHA"], pr_head=values["PR_HEAD_SHA"], baseline=fixed)


def tool_hashes():
    return {name: cap.digest(HERE / name) for name in TOOL_NAMES}


def clean_env():
    # The corpus is never executed. Keep even trusted tool children out of ambient
    # Python/Git/pip configuration and remove all authentication material.
    result = {name: os.environ[name] for name in ("PATH", "HOME", "TMPDIR", "TEMP", "TMP") if name in os.environ}
    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
    paths = [Path(value).resolve() for value in result["PATH"].split(os.pathsep) if value and Path(value).is_absolute()]
    result["PATH"] = os.pathsep.join(str(path) for path in paths if not path.is_relative_to(workspace))
    result.update(LC_ALL="C.UTF-8", LANG="C.UTF-8", GIT_CONFIG_GLOBAL=os.devnull,
                  GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0", GIT_NO_REPLACE_OBJECTS="1",
                  GIT_LFS_SKIP_SMUDGE="1", PIP_CONFIG_FILE=os.devnull, PIP_NO_INPUT="1",
                  PIP_DISABLE_PIP_VERSION_CHECK="1", CHECKWASH_TODAY=DATE, GREENWASH_TODAY=DATE,
                  GITHUB_RUN_ID=os.environ["GITHUB_RUN_ID"], GITHUB_RUN_ATTEMPT=os.environ["GITHUB_RUN_ATTEMPT"])
    return result


def facts():
    return dict(python=sys.version, interpreter=sys.executable, resolved_interpreter=str(Path(sys.executable).resolve()),
                platform=platform.platform(), os_name=os.name, runner=os.environ.get("RUNNER_NAME"),
                image=os.environ.get("ImageOS"), image_version=os.environ.get("ImageVersion"),
                locale_policy="LC_ALL=C.UTF-8", utc=cap.facts()["utc"])


class Commands:
    """Raw evidence for every Git/build/install/tool subprocess, including failures."""
    def __init__(self, output, cwd, env, deadline=None):
        self.output, self.cwd, self.env, self.deadline = Path(output), Path(cwd), env, deadline
        self.output.mkdir(parents=True, exist_ok=True)
        self.rows = []

    def run(self, argv, *, timeout=GIT_TIMEOUT, extra_env=None):
        prefix = self.output / f"command-{len(self.rows):04d}"
        row = dict(argv=list(map(str, argv)), cwd=str(self.cwd), raw_prefix=prefix.name, observation=None)
        self.rows.append(row)
        write(self.output / "commands.json", self.rows)
        observation = cap.capture(row["argv"], self.cwd, dict(self.env, **(extra_env or {})), prefix,
                                  timeout, STREAM_LIMIT, self.deadline)
        row["observation"] = observation
        write(self.output / "commands.json", self.rows)
        require(observation["status"] == "EXITED" and observation["capture_complete"] and observation["exit_code"] == 0,
                f"tool failed: {prefix.name}; original streams retained")
        return prefix.with_suffix(".stdout").read_bytes()

    def git(self, root, *args):
        git = shutil.which("git", path=self.env["PATH"])
        require(git is not None, "trusted Git absent")
        return self.run([git, "-c", "core.hooksPath=/dev/null", "-c", "core.autocrlf=false", "-C", root, *args])


def source(commands, root, expected):
    require(commands.git(root, "rev-parse", "HEAD").decode().strip() == expected, "source HEAD mismatch")
    require(not commands.git(root, "status", "--porcelain").strip(), "dirty source checkout")
    return dict(commit=expected, tree=commands.git(root, "rev-parse", "HEAD^{tree}").decode().strip(),
                package_tree=commands.git(root, "rev-parse", "HEAD:src/checkwash").decode().strip())


def validate_plan(plan):
    identity = event_identity()
    require(plan["schema_version"] == 1 and plan["purpose"] == "R1_SEEN_FIXED_COHORT_COST"
            and plan["classification"] == "ALREADY_SEEN_NONBLIND"
            and plan["cost_qualification"] == "NOT_ADJUDICATED", "plan purpose/qualification differs")
    require(plan["identity"] == identity and plan["harness_hashes"] == tool_hashes(), "plan event/source/harness differs")
    require(plan["members_sha256"] == MEMBERS_HASH and plan["partitions_sha256"] == PARTITIONS_HASH,
            "plan fixed data differs")
    require(plan["today"] == DATE and plan["primary_distribution"] == "pyz", "plan CLI contract differs")
    require(plan["limits"] == LIMITS and plan["arm_order"] == "alternate_by_original_ordinal", "plan bounds/order differs")
    members, shards, groups = cohort()
    require(plan["groups"] == groups and plan["shards"] == shards and plan["expected_arm_rows"] == 8542,
            "plan scheduling or denominator differs")
    require(plan["build_complete"] is True and set(plan["engines"]) == set(ARMS), "both qualified arms required")
    for arm in ARMS:
        engine = plan["engines"][arm]
        require(engine["source"]["commit"] == identity["baseline" if arm == "base" else "candidate"], "arm source differs")
        require(all(SHA.fullmatch(engine["source"][key]) for key in ("commit", "tree", "package_tree")), "arm source object identity invalid")
        require(engine["artifact_path"] == "arms/" + arm + "/artifacts/checkwash.pyz"
                and cap.HASH.fullmatch(engine["artifact_sha256"])
                and type(engine["artifact_bytes"]) is int and engine["artifact_bytes"] > 0
                and isinstance(engine["version"], str) and engine["version"]
                and type(engine["findings_version"]) is int and engine["findings_version"] > 0,
                "arm distribution identity invalid")
        require(engine["input_trust"] == "UNMODIFIED_EXACT_SOURCE_NO_READER_SUBSTITUTION", "arm reader contract differs")
    return members, shards, groups


def main():
    mode = sys.argv[1]
    output = Path(os.environ["R1_OUTPUT"]).resolve()
    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
    require(not output.is_relative_to(workspace), "receipts must be outside source/corpus workspace")
    output.mkdir(parents=True, exist_ok=True)
    try:
        if mode == "build":
            from r1_cost_build import build
            return build(output)
        if mode == "worker":
            from r1_cost_worker import worker
            return worker(output, Path(os.environ["R1_PREPARED"]), os.environ["R1_GROUP"])
        if mode == "aggregate":
            from r1_cost_aggregate import aggregate
            return aggregate(output, Path(os.environ["R1_INPUTS"]))
        raise ValueError("unknown fixed R1 cost mode")
    except Exception as error:
        write(output / "fatal.json", dict(error=repr(error), mode=mode, facts=facts(),
                                         cost_qualification="NOT_ADJUDICATED"))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
