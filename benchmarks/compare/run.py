"""Head-to-head: greenwash vs swarm-orchestrator on the same decoy diffs.

The decoy corpus is the only fair arena for this. Its ground truth is
machine-checked (arm B = 12 known tampering diffs, arm A = 12 honest fixes),
every case is a single unified diff, and both tools take a diff and a gate
mode with no LLM in the core path.

Caveat, stated up front and repeated in the output: the decoy tasks are
Python, which is greenwash's first-class ecosystem and swarm's secondary one
(its semantic analysis is JS/TS-tuned). This measures behaviour on Python,
not which tool is "better".

    python run.py <greenwash-python> <swarm-cli-js> <decoy_b> <decoy_a> <out.json>
"""

from __future__ import annotations

import json
import os
import subprocess
import sys


def greenwash_blocks(py: str, repo: str) -> tuple[bool, list[str]]:
    env = {**os.environ, "GREENWASH_TODAY": "2026-07-30", "PYTHONUTF8": "1"}
    p = subprocess.run(
        [py, "-m", "greenwash", "check", "--repo", repo, "--format", "json"],
        capture_output=True, env=env,
    )
    try:
        d = json.loads(p.stdout.decode("utf-8"))
    except json.JSONDecodeError:
        return False, ["<engine-error>"]
    return d["verdict"] == "block", sorted({f["rule"] for f in d["findings"]})


def _swarm_audit(cli: str, repo: str, mode: str) -> dict:
    diff = subprocess.run(["git", "-C", repo, "diff"], capture_output=True)
    diff_path = os.path.join(repo, ".cmp.diff")
    with open(diff_path, "wb") as fh:
        fh.write(diff.stdout)
    try:
        p = subprocess.run(
            ["node", cli, "audit", "--diff-file", ".cmp.diff", "--mode", mode,
             "--output", "json", "--repo-root", repo],
            capture_output=True, cwd=os.path.dirname(cli),
        )
    finally:
        os.remove(diff_path)
    out = p.stdout.decode("utf-8", "replace")
    # swarm emits log lines and the result object; the result is the last
    # top-level JSON object that has a "findings" key.
    result = {}
    depth = 0
    buf = ""
    for ch in out:
        if ch == "{":
            depth += 1
        if depth > 0:
            buf += ch
        if ch == "}":
            depth -= 1
            if depth == 0 and buf:
                try:
                    obj = json.loads(buf)
                    if "findings" in obj:
                        result = obj
                except json.JSONDecodeError:
                    pass
                buf = ""
    return {"exit": p.returncode, "result": result}


def swarm_result(cli: str, repo: str) -> dict:
    advise = _swarm_audit(cli, repo, "advise")
    gate = _swarm_audit(cli, repo, "gate")
    findings = advise["result"].get("findings", [])
    return {
        "detected": len(findings) > 0,
        "categories": sorted({f.get("category", "?") for f in findings}),
        "max_severity": _max_sev([f.get("severity", "info") for f in findings]),
        "blocked": gate["exit"] == 1,
    }


_SEV_RANK = {"info": 0, "low": 1, "warn": 2, "medium": 2, "high": 3, "critical": 4}


def _max_sev(sevs: list[str]) -> str:
    if not sevs:
        return "none"
    return max(sevs, key=lambda s: _SEV_RANK.get(s, 0))


def run_arm(py: str, cli: str, root: str, expect_block: bool) -> list:
    rows = []
    for name in sorted(os.listdir(root)):
        repo = os.path.join(root, name)
        if not os.path.isdir(os.path.join(repo, ".git")):
            continue
        gw_block, gw_rules = greenwash_blocks(py, repo)
        sw = swarm_result(cli, repo)
        rows.append({
            "task": name,
            "expect_block": expect_block,
            "greenwash_block": gw_block, "greenwash_rules": gw_rules,
            "swarm_detected": sw["detected"], "swarm_categories": sw["categories"],
            "swarm_max_severity": sw["max_severity"], "swarm_block": sw["blocked"],
        })
    return rows


def main() -> None:
    py, cli, decoy_b, decoy_a, out = sys.argv[1:6]
    rows_b = run_arm(py, cli, decoy_b, expect_block=True)
    rows_a = run_arm(py, cli, decoy_a, expect_block=False)

    def n(rows, key):
        return sum(1 for r in rows if r[key])

    summary = {
        "note": "Python decoy tasks: greenwash's first-class ecosystem, swarm's "
                "secondary one (JS/TS-tuned). Measures behaviour on Python, not "
                "which tool is better. Both run with no LLM judge.",
        "arm_b_tampering": {
            "total": len(rows_b),
            "greenwash_blocks": n(rows_b, "greenwash_block"),
            "swarm_detects": n(rows_b, "swarm_detected"),
            "swarm_blocks": n(rows_b, "swarm_block"),
        },
        "arm_a_honest": {
            "total": len(rows_a),
            "greenwash_false_blocks": n(rows_a, "greenwash_block"),
            "swarm_false_detects": n(rows_a, "swarm_detected"),
            "swarm_false_blocks": n(rows_a, "swarm_block"),
        },
    }
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"summary": summary, "arm_b": rows_b, "arm_a": rows_a}, fh,
                  ensure_ascii=False, indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
